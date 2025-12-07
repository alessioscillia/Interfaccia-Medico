import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from PIL import Image
import io
import os
import json
import base64
import logging
import threading
import uuid
from datetime import datetime

# Timezone Management
try:
    from zoneinfo import ZoneInfo
    _HAS_ZONEINFO = True
except Exception:
    ZoneInfo = None
    _HAS_ZONEINFO = False
    try:
        import pytz
    except Exception:
        pytz = None

# ==============================================================================
# 1. CONFIGURATION AND CONSTANTS
# ==============================================================================

st.set_page_config(layout="wide", page_title="Medical Image Assessment")

# --- USER CONFIGURATION ---
ARTICOLO_POLYPS_FOLDER_ID = '1He7eQCE2xI5X8n00A-B-eKEBZjNIw9cJ'
DATA_DEVELOPMENT_FOLDER_ID = "1gZc6y9Q0DDHyNLbQoEOJVCdMwH_UIYut"
SCORING_FOLDER_ID = "1Joi3sCLkq2GQ1MG4LH2veq0cYftbb9XQ"
USERS_PER_GROUP = 3 

# Translated Guidelines
LINEE_GUIDA = """
- **Brightness:** The image must be well-lit without excessively dark or overexposed areas.
- **Sharpness:** Mucosal details must be clearly visible, avoiding blurriness due to motion blur.
- **Natural Colors:** Absence of unnatural color casts.
- **Absence of Artifacts:** Avoid images disturbed by digital artifacts or sudden movements.
- **Composition:** The region of interest must be centered and clearly visible.
"""

# ==============================================================================
# 2. UTILITY FUNCTIONS
# ==============================================================================

def _now_rome_str():
    """Returns current time in Rome timezone (or UTC fallback)."""
    fmt = '%Y-%m-%d %H:%M:%S'
    try:
        if _HAS_ZONEINFO and ZoneInfo is not None:
            return datetime.now(ZoneInfo("Europe/Rome")).strftime(fmt)
        if 'pytz' in globals() and pytz is not None:
            return datetime.now(pytz.timezone("Europe/Rome")).strftime(fmt)
    except Exception:
        pass
    return datetime.utcnow().strftime(fmt)

def bytes_to_base64_url(img_bytes):
    try:
        b64_encoded = base64.b64encode(img_bytes).decode()
        return f"data:image/png;base64,{b64_encoded}"
    except Exception:
         return None

# ==============================================================================
# 3. GOOGLE DRIVE AND DATA MANAGEMENT
# ==============================================================================

@st.cache_resource(show_spinner=False)
def get_drive():
    gauth = GoogleAuth()
    if "gcp_service_account" in st.secrets:
        service_account_info = dict(st.secrets["gcp_service_account"])
        temp_cred_file = "temp_service_account.json"
        with open(temp_cred_file, "w") as f:
            json.dump(service_account_info, f)
        service_account_file = temp_cred_file
        client_email = service_account_info.get('client_email')
    else:
        service_account_file = "service-account.json"
        if not os.path.exists(service_account_file):
            st.error("Credentials file 'service-account.json' not found!")
            st.stop()
        with open(service_account_file, 'r') as f:
            service_account_info = json.load(f)
            client_email = service_account_info.get('client_email')
    
    gauth.settings['client_config_backend'] = 'service'
    gauth.settings['service_config'] = {
        'client_json_file_path': service_account_file,
        'client_user_email': client_email,
    }
    gauth.ServiceAuth()
    drive = GoogleDrive(gauth)
    return drive

drive = get_drive()

@st.cache_data(show_spinner=False)
def get_image_bytes_by_id(file_id: str):
    f = drive.CreateFile({'id': file_id})
    buf = f.GetContentIOBuffer()
    return buf.read()

@st.cache_data(show_spinner="Loading images...", ttl=3600)
def load_datasets_and_index():
    try:
        folder_list = drive.ListFile(
            {'q': f"'{DATA_DEVELOPMENT_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"}
        ).GetList()
    except Exception:
        logging.getLogger(__name__).exception("Error accessing Data-Development")
        return {}, {}

    images_by_id = {}
    datasets = {}
    for folder in folder_list:
        try:
            images = drive.ListFile(
                {'q': f"'{folder['id']}' in parents and trashed=false and mimeType contains 'image/'"}
            ).GetList()
        except Exception:
            images = []
        dataset_entries = []
        for img in images:
            entry = {
                "img_obj": {'id': img['id'], 'title': img['title']},
                "folder_name": folder['title']
            }
            dataset_entries.append(entry)
            images_by_id[img['id']] = {
                'title': img['title'],
                'folder_name': folder['title']
            }
        datasets[folder['title']] = dataset_entries
    return images_by_id, datasets

@st.cache_data(show_spinner="Preparing evaluation lists...", ttl=3600)
def load_scoring_sets():
    try:
        scoring_files = drive.ListFile(
            {'q': f"'{SCORING_FOLDER_ID}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'"}
        ).GetList()
    except Exception:
        logging.getLogger(__name__).exception("Error accessing Scoring")
        return []

    txt_files = [f for f in scoring_files if f['title'].lower().endswith('.txt')]
    txt_files.sort(key=lambda f: f['title'].lower())

    scoring_sets = []
    for f in txt_files:
        try:
            content = f.GetContentString()
            ids = [line.strip() for line in content.splitlines() if line.strip()]
            if ids:
                scoring_sets.append({
                    "filename": f['title'],
                    "ids": ids
                })
        except Exception:
            pass
    return scoring_sets

def get_user_images(user_id: str):
    images_by_id, _ = load_datasets_and_index()
    scoring_sets = load_scoring_sets()

    if not scoring_sets:
        st.error("No scoring files found.")
        return [], None

    logger = logging.getLogger(__name__)
    
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        # IMPORTANT: ttl=0 forces fresh read to see recent saves
        dati = conn.read(worksheet="Foglio1", ttl=0).fillna("")
    except Exception:
        logger.exception("Error reading Google Sheets")
        dati = pd.DataFrame()

    completed_files = set()
    user_position = 0 

    if not dati.empty and "id_utente" in dati.columns:
        user_rows = dati[dati["id_utente"] == user_id]
        
        if not user_rows.empty and "file_txt_assegnato" in user_rows.columns:
            completed_list = user_rows["file_txt_assegnato"].unique().tolist()
            completed_files = set([str(x).strip() for x in completed_list if str(x).strip() != ""])

        unique_users = dati["id_utente"].unique().tolist()
        if user_id not in unique_users:
            user_position = len(unique_users)
        else:
            user_position = unique_users.index(user_id)

    assigned_set_index = -1

    if not completed_files:
        group_index = user_position // USERS_PER_GROUP
        assigned_set_index = group_index % len(scoring_sets)
    else:
        group_idx = (user_position // USERS_PER_GROUP) % len(scoring_sets)
        if scoring_sets[group_idx]['filename'] not in completed_files:
            assigned_set_index = group_idx
        else:
            for i, s_set in enumerate(scoring_sets):
                if s_set['filename'] not in completed_files:
                    assigned_set_index = i
                    break
    
    if assigned_set_index != -1 and scoring_sets[assigned_set_index]['filename'] in completed_files:
         assigned_set_index = -1 
         for i, s_set in enumerate(scoring_sets):
                if s_set['filename'] not in completed_files:
                    assigned_set_index = i
                    break

    if assigned_set_index == -1:
        return [], "COMPLETED"

    chosen_set = scoring_sets[assigned_set_index]
    target_ids = chosen_set['ids']
    assigned_filename = chosen_set['filename']

    user_images = []
    for img_id in target_ids:
        meta = images_by_id.get(img_id)
        if not meta:
            continue
        user_images.append({
            "img_obj": {'id': img_id, 'title': meta['title']},
            "folder_name": meta['folder_name']
        })
        
    return user_images, assigned_filename

# ==============================================================================
# 4. UI COMPONENTS
# ==============================================================================

@st.dialog("Summary of your choices", width="large")
def visualizza_riepilogo():
    if "valutazioni" in st.session_state and st.session_state.valutazioni:
        data_for_display = []
        for item in st.session_state.valutazioni:
            display_item = item.copy()
            img_bytes = get_image_bytes_by_id(display_item["file_id"])
            display_item["anteprima"] = bytes_to_base64_url(img_bytes)
            data_for_display.append(display_item)

        df_temp = pd.DataFrame(data_for_display)
        st.dataframe(
            df_temp,
            width='stretch',
            hide_index=True,
            row_height=100,
            column_order=("anteprima", "score"), 
            column_config={
                "anteprima": st.column_config.ImageColumn("Preview", width="medium"), 
                "score": st.column_config.NumberColumn("Score", format="%d ⭐"),
            }
        )
        st.caption(f"Total images assessed: {len(df_temp)}")
    else:
        st.info("No assessments yet.")

# ==============================================================================
# 5. MAIN APPLICATION FLOW
# ==============================================================================

def main():
    st.markdown("<h2 style='margin-bottom:0;'>Colonoscopic Image Quality Assessment</h2>", unsafe_allow_html=True)
    
    # --- 1. USER & ID MANAGEMENT ---
    if "user_id" not in st.session_state:
        st.session_state.user_id = str(uuid.uuid4())[:8].upper()
    
    user_id = st.session_state.user_id
    st.caption(f"User ID: **{user_id}**")

    # State to confirm session start
    if "session_confirmed" not in st.session_state:
        st.session_state.session_confirmed = False

    # --- 2. PARTICIPANT INFORMATION ---
    # Show this section only if not confirmed yet
    
    if not st.session_state.session_confirmed:
        st.markdown("### Participant Information")
        st.write("Please select your experience level to start:")
        
        # Clean options in English
        options_exp = [
            "0", 
            "less than 220", 
            "more than 220"
        ]
        
        # index=None makes it empty at start
        esperienza_selezione = st.radio(
            "How many colonoscopies have you performed?",
            options=options_exp,
            index=None,  # <--- No default selection
            key="radio_esperienza"
        )
        
        st.write("") # Spacing
        
        # Confirmation Button
        if st.button("Confirm and Start", type="primary"):
            if esperienza_selezione is None:
                st.error("⚠️ Please select an experience level to proceed.")
            else:
                st.session_state.input_esperienza = esperienza_selezione
                st.session_state.session_confirmed = True
                st.rerun()
        
        # STOP HERE: If not confirmed, do not load images yet
        st.stop()

    # --- IF WE ARE HERE, SESSION IS CONFIRMED ---
    
    # Retrieve saved experience
    esperienza = st.session_state.input_esperienza
    
    # Small info header
    st.info(f"Active Session | Experience: **{esperienza}**")

    # --- 3. IMAGE LOADING & MANAGEMENT ---
    images_by_id, _ = load_datasets_and_index()
    if not images_by_id:
        st.stop()

    # Initialize Session State for images
    if "immagini" not in st.session_state:
        with st.spinner("Assigning image batch..."):
            imgs, txt_filename = get_user_images(user_id)
        
        # --- COMPLETION CHECK ---
        if txt_filename == "COMPLETED":
            st.success(f"🎉 Congratulations! You have completed all available evaluation sets.")
            st.info("There are no further images to evaluate at this time.")
            st.session_state.immagini = []
            st.session_state.current_txt_file = None
            st.stop()

        st.session_state.immagini = imgs
        st.session_state.current_txt_file = txt_filename 
        st.session_state.indice = 0
        st.session_state.valutazioni = []
        st.rerun()

    indice = st.session_state.indice
    imgs = st.session_state.immagini
    
    if not imgs:
        st.error("Error: No images found in the assigned set.")
        st.stop()

    # --- ASSESSMENT LOOP ---
    if indice < len(imgs):
        curr_entry = imgs[indice]
        img_file = curr_entry["img_obj"]
        folder_name = curr_entry["folder_name"]
        file_id = img_file['id']

        try:
            img_bytes = get_image_bytes_by_id(file_id)
            image = Image.open(io.BytesIO(img_bytes))
        except Exception:
            image = None

        col1, col2 = st.columns([1, 2])

        with col1:
            st.markdown("### Quality Guidelines")
            st.markdown(LINEE_GUIDA)
        
        with col2:
            if image:
                st.image(image, use_container_width=True)
            
            st.markdown(f"<b>Dataset:</b> {folder_name}", unsafe_allow_html=True)
            
            score = st.slider("Quality Score (1-10)", 1, 10, 5, key=f"score_{indice}")
            
            c_back, c_save, c_summ = st.columns([1, 1.5, 1])
            
            with c_back:
                if st.button("⬅️ Back", use_container_width=True):
                    if indice > 0:
                        if st.session_state.valutazioni:
                            st.session_state.valutazioni.pop()
                        st.session_state.indice -= 1
                        st.rerun()
            
            with c_save:
                if st.button("Next ➜", use_container_width=True, type="primary"):
                    st.session_state.valutazioni.append({
                        "id_utente": user_id,
                        "esperienza": esperienza,
                        "nome_immagine": img_file['title'],
                        "file_id": img_file['id'], 
                        "score": score,
                        "dataset": folder_name,
                        "file_txt_assegnato": st.session_state.current_txt_file,
                        "timestamp": _now_rome_str()
                    })
                    st.session_state.indice += 1
                    st.rerun()

            with c_summ:
                if st.button("📋 Summary", use_container_width=True):
                    visualizza_riepilogo()
        
        st.markdown(f"<center><small>Image {indice + 1} of {len(imgs)}</small></center>", unsafe_allow_html=True)
        
        # Pre-loading next image
        if indice + 1 < len(imgs):
            next_id = imgs[indice + 1]['img_obj']['id']
            threading.Thread(target=get_image_bytes_by_id, args=(next_id,), daemon=True).start()

    # --- FINAL SCREEN ---
    else:
        if "salvato" not in st.session_state:
            st.session_state.salvato = False

        if not st.session_state.salvato:
            st.markdown("## 🎉 Evaluation Completed!")
            st.info("Thank you! You have evaluated all assigned images.")
            
            st.markdown("#### 💬 Feedback (optional)")
            feedback_text = st.text_area("Report any issues or suggestions:", height=100)

            st.write("") 

            if st.button("💾 SAVE AND SUBMIT RESULTS", type="primary", use_container_width=True):
                with st.spinner("Saving in progress..."):
                    try:
                        df = pd.DataFrame(st.session_state.valutazioni)
                        df['feedback'] = feedback_text
                        
                        conn = st.connection("gsheets", type=GSheetsConnection)
                        existing_data = conn.read(worksheet="Foglio1")
                        
                        df_to_save = df.drop(columns=['file_id'], errors='ignore')

                        if existing_data.empty:
                            conn.update(worksheet="Foglio1", data=df_to_save)
                        else:
                            new_data = pd.concat([existing_data, df_to_save], ignore_index=True)
                            conn.update(worksheet="Foglio1", data=new_data)
                        
                        st.session_state.salvato = True
                        st.rerun() 
                    except Exception as e:
                        st.error(f"⚠️ Error saving data: {e}")
                        csv = df.drop(columns=['file_id'], errors='ignore').to_csv(index=False)
                        st.download_button("📥 Download CSV Backup", csv, "backup_valutazioni.csv", "text/csv")
        
        else:
            st.success("✅ Results successfully submitted!")
            st.balloons()
            
            if st.button("🔄 Start a new session (with new images)"):
                # Maintain ID and Experience, reset the rest
                current_id = st.session_state.user_id
                current_exp = st.session_state.input_esperienza
                
                # Save confirmation state before clearing
                temp_confirmed = True 
                
                st.session_state.clear()
                
                # Restore
                st.session_state.user_id = current_id
                st.session_state.input_esperienza = current_exp
                st.session_state.session_confirmed = temp_confirmed
                
                st.rerun()

if __name__ == "__main__":
    main()