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
import random
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
# Nota: SCORING_FOLDER_ID non serve più per scrivere i file TXT, 
# ma teniamo le costanti delle immagini.
DATA_DEVELOPMENT_FOLDER_ID = "1gZc6y9Q0DDHyNLbQoEOJVCdMwH_UIYut"
USERS_PER_GROUP = 3 
IMAGES_PER_BATCH = 9 
TARGET_PER_DATASET = 3 

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
    # Gestione credenziali (uguale a prima)
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
    """Carica la struttura delle cartelle e tutte le immagini disponibili."""
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

def get_batches_from_sheet():
    """Legge i batch dal foglio 'Batches' di Google Sheets."""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        # Leggiamo il foglio 'Batches'. ttl=0 per avere dati freschi.
        df_batches = conn.read(worksheet="Batches", ttl=0).fillna("")
    except Exception:
        logging.getLogger(__name__).exception("Error accessing Batches worksheet")
        return [], set(), pd.DataFrame()

    scoring_sets = []
    used_ids_global = set()
    
    # Se il foglio è vuoto o non ha colonne, ritorniamo vuoto
    if df_batches.empty or "batch_name" not in df_batches.columns:
        return [], used_ids_global, df_batches

    # Iteriamo sulle righe per ricostruire la struttura
    for index, row in df_batches.iterrows():
        b_name = str(row['batch_name']).strip()
        ids_str = str(row['image_ids']).strip()
        
        if b_name and ids_str:
            # Gli ID sono salvati come stringa separata da virgole "id1,id2,id3"
            ids_list = [x.strip() for x in ids_str.split(',') if x.strip()]
            if ids_list:
                scoring_sets.append({
                    "filename": b_name, # Usiamo 'filename' per compatibilità col resto del codice
                    "ids": ids_list
                })
                used_ids_global.update(ids_list)
    
    return scoring_sets, used_ids_global, df_batches

def create_new_batch_entry(existing_df, used_ids_global):
    """Crea un nuovo batch e lo salva nel foglio 'Batches'."""
    images_by_id, datasets = load_datasets_and_index()
    
    # 1. Identifica le immagini disponibili
    available_images = {} 
    all_available_pool = []
    
    for ds_name, entries in datasets.items():
        clean_entries = [e for e in entries if e['img_obj']['id'] not in used_ids_global]
        random.shuffle(clean_entries)
        available_images[ds_name] = clean_entries
        all_available_pool.extend(clean_entries)
    
    # Soft reset se finiamo le immagini
    if not all_available_pool:
        st.warning("⚠️ Recycling images for this session.")
        all_available_pool = []
        for ds_name, entries in datasets.items():
            random.shuffle(entries)
            available_images[ds_name] = entries
            all_available_pool.extend(entries)

    # 2. Selezione Immagini
    selected_entries = []
    datasets_names = list(datasets.keys())
    
    # Primo giro: target per dataset
    for ds_name in datasets_names:
        pool = available_images.get(ds_name, [])
        take_n = min(len(pool), TARGET_PER_DATASET)
        selected_entries.extend(pool[:take_n])
        ids_taken = [x['img_obj']['id'] for x in pool[:take_n]]
        all_available_pool = [x for x in all_available_pool if x['img_obj']['id'] not in ids_taken]

    # Riempimento
    missing_count = IMAGES_PER_BATCH - len(selected_entries)
    if missing_count > 0:
        random.shuffle(all_available_pool)
        selected_entries.extend(all_available_pool[:missing_count])
    
    random.shuffle(selected_entries)
    
    new_ids = [entry['img_obj']['id'] for entry in selected_entries]
    
    # 3. Preparazione dati per salvataggio
    # Calcoliamo il prossimo numero di batch
    next_num = 1
    if not existing_df.empty and "batch_name" in existing_df.columns:
        # Cerchiamo di parsare "batch_XX"
        for name in existing_df["batch_name"]:
            try:
                num = int(str(name).replace("batch_", ""))
                if num >= next_num:
                    next_num = num + 1
            except:
                pass
    
    new_batch_name = f"batch_{next_num:02d}"
    ids_string = ",".join(new_ids)
    
    # 4. Salvataggio su Sheet
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        # Creiamo il DataFrame della nuova riga
        new_row = pd.DataFrame([{"batch_name": new_batch_name, "image_ids": ids_string}])
        
        # Uniamo al vecchio e aggiorniamo
        # Nota: gsheets connection update sovrascrive tutto, quindi dobbiamo concatenare
        if existing_df.empty:
            updated_df = new_row
        else:
            updated_df = pd.concat([existing_df, new_row], ignore_index=True)
            
        conn.update(worksheet="Batches", data=updated_df)
        
        return new_batch_name, new_ids
        
    except Exception as e:
        st.error(f"Error saving batch to Sheet: {e}")
        return None, []

def get_user_images(user_id: str):
    images_by_id, _ = load_datasets_and_index()
    # Carichiamo i batch dallo Sheet invece che dai file TXT
    scoring_sets, used_ids_global, df_batches = get_batches_from_sheet()

    logger = logging.getLogger(__name__)
    
    # Leggi storico valutazioni (Sheet Foglio1)
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        dati = conn.read(worksheet="Foglio1", ttl=0).fillna("")
    except Exception:
        logger.exception("Error reading Google Sheets")
        dati = pd.DataFrame()

    # 1. Analizza lo stato dei batch esistenti
    batch_counts = {s['filename']: 0 for s in scoring_sets} 
    user_completed_batches = set()
    
    if not dati.empty and "file_txt_assegnato" in dati.columns:
        valid_rows = dati[dati["file_txt_assegnato"].astype(str).str.strip() != ""]
        usage_stats = valid_rows.groupby("file_txt_assegnato")["id_utente"].nunique()
        for fname, count in usage_stats.items():
            if fname in batch_counts:
                batch_counts[fname] = count
        
        user_rows = dati[dati["id_utente"] == user_id]
        if not user_rows.empty:
            user_completed_batches = set(user_rows["file_txt_assegnato"].unique())

    # 2. Cerca un batch esistente assegnabile
    assigned_set = None
    
    for s_set in scoring_sets:
        fname = s_set['filename']
        if fname in user_completed_batches:
            continue 
        
        if batch_counts.get(fname, 0) < USERS_PER_GROUP:
            assigned_set = s_set
            break 
    
    # 3. Se non c'è batch esistente valido, creane uno nuovo
    if assigned_set is None:
        with st.spinner("Generating new image batch..."):
            # Passiamo df_batches così può calcolare il numero progressivo corretto
            new_fname, new_ids = create_new_batch_entry(df_batches, used_ids_global)
            if not new_fname:
                return [], "ERROR"
            
            assigned_set = {
                "filename": new_fname,
                "ids": new_ids
            }

    # 4. Prepara output
    target_ids = assigned_set['ids']
    assigned_filename = assigned_set['filename']

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
    if not st.session_state.session_confirmed:
        st.markdown("### Please select your experience level to start:")
        
        options_exp = [
            "0", 
            "less than 220", 
            "more than 220"
        ]
        
        esperienza_selezione = st.radio(
            "How many colonoscopies have you performed?",
            options=options_exp,
            index=None,
            key="radio_esperienza"
        )
        
        st.write("") 
        
        if st.button("Confirm and Start", type="primary"):
            if esperienza_selezione is None:
                st.error("⚠️ Please select an experience level to proceed.")
            else:
                st.session_state.input_esperienza = esperienza_selezione
                st.session_state.session_confirmed = True
                st.rerun()
        
        st.stop()

    # --- IF WE ARE HERE, SESSION IS CONFIRMED ---
    esperienza = st.session_state.input_esperienza
    st.info(f"Active Session | Experience: **{esperienza}**")

    # --- 3. IMAGE LOADING & MANAGEMENT ---
    images_by_id, _ = load_datasets_and_index()
    if not images_by_id:
        st.stop()

    # Initialize Session State for images
    if "immagini" not in st.session_state:
        with st.spinner("Assigning image batch..."):
            imgs, txt_filename = get_user_images(user_id)
        
        if txt_filename == "ERROR":
            st.error("Critical Error: Could not generate assignment. Please check 'Batches' sheet exists.")
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
                st.image(image, width="stretch")
            
            st.markdown(f"<b>Dataset:</b> {folder_name}", unsafe_allow_html=True)
            
            score = st.slider("Quality Score (1-10)", 1, 10, 5, key=f"score_{indice}")
            
            c_back, c_save, c_summ = st.columns([1, 1.5, 1])
            
            with c_back:
                if st.button("⬅️ Back",width="stretch"):
                    if indice > 0:
                        if st.session_state.valutazioni:
                            st.session_state.valutazioni.pop()
                        st.session_state.indice -= 1
                        st.rerun()
            
            with c_save:
                if st.button("Next ➜", width="stretch", type="primary"):
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
                if st.button("📋 Summary", width="stretch"):
                    visualizza_riepilogo()
        
        st.markdown(f"<center><small>Image {indice + 1} of {len(imgs)}</small></center>", unsafe_allow_html=True)
        
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

            if st.button("💾 SAVE AND SUBMIT RESULTS", type="primary", width="stretch"):
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
                current_id = st.session_state.user_id
                current_exp = st.session_state.input_esperienza
                temp_confirmed = True 
                
                st.session_state.clear()
                
                st.session_state.user_id = current_id
                st.session_state.input_esperienza = current_exp
                st.session_state.session_confirmed = temp_confirmed
                
                st.rerun()

if __name__ == "__main__":
    main()