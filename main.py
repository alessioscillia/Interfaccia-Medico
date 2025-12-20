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
import gspread
from google.oauth2.service_account import Credentials

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
DATA_DEVELOPMENT_FOLDER_ID = "1XHP5ZEq-RmJnXlQN8G_LdUHhv2dbVE62"
USERS_PER_GROUP = 3 
IMAGES_PER_BATCH = 30 
TARGET_PER_DATASET = 6 

# Filenames for Guideline Reference Images
HIGH_QUALITY_FILENAME = "EndoCV2021_001164.jpg"
LOW_QUALITY_FILENAME = "C3_EndoCV2021_00153.jpg"

# Guidelines
LINEE_GUIDA = """

 **Sharpness & Focus**
  - Clear visualization of mucosal texture, pit patterns, vascular structures and lesion margins
  - Minimal motion blur during endoscope movement

 **Lighting & Exposure**
  - Image is neither too dark nor overexposed, with good visibility even in deeper lumen sections
  - No harsh shadows and limited glare/reflection artifacts from mucosal surfaces

 **Color and Contrast**
  - Realistic representation of tissue color with preserved microvascular contrast
  - Sufficient differentiation between structures of similar morphology

 **Resolution**
  - High detail visibility and fine visualization of small or flat polyps
  - Minimal pixelation or loss of information

 **Field of View and Depth of Field**
  - Broad angle without significant vignetting, showing a large portion of the lumen
  - Multiple planes in focus simultaneously, maintaining clarity for both near and distant surfaces

 **Stability and Artifacts**
  - Stable image with reduced vibration or jitter
  - Low noise, controlled optical distortion, and limited interference from fluids, debris or bubbles

 **Recognition & Diagnostic Adequacy**
  - Reliable visualization of haustral folds, appendiceal orifice, vascular trees and different polyp morphologies
  - Image quality sufficient for lesion characterization and to support clinical decisions and therapeutic actions
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


def get_gspread_client():
    """Autenticazione sicura per gspread usando st.secrets"""
    # Definiamo gli scope necessari per scrivere su Sheets e Drive
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Carichiamo le credenziali direttamente dai secrets di Streamlit
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    
    # Creiamo il client
    client = gspread.authorize(creds)
    return client

def safe_append_data(data_list, worksheet_name="Results"):
    """
    Salva i dati in modalità APPEND (sicura per multi-utente).
    data_list: lista di dizionari (le tue valutazioni)
    """
    try:
        client = get_gspread_client()
        # Apri il foglio di calcolo (usa l'URL o il nome del file se è unico)
        # Nota: Assicurati che il nome del file Google Sheet sia corretto. 
        # Qui assumo che il foglio si chiami come il titolo dell'app o sia definito nell'URL connection, 
        # ma con gspread devi aprire il file per Nome esatto o Key.
        # ESEMPIO: Se il tuo file su Drive si chiama "ValutazioniEndoscopia"
        # sh = client.open("ValutazioniEndoscopia") 
        
        # Se usi l'URL del foglio (più sicuro):
        sh = client.open_by_url(st.secrets["connections"]["gsheets"]["spreadsheet"]) 
        
        worksheet = sh.worksheet(worksheet_name)
        
        # 1. Definiamo l'ordine delle colonne ESATTO come le vuoi nel foglio
        # Questo è cruciale perché append_row vuole una lista, non un dizionario
        headers = [
            "id_utente", " esperienza", "nome_immagine", "dataset", 
            "score", "file_txt_assegnato", "timestamp", "feedback"
        ]
        
        # 2. Prepariamo le righe da inserire
        rows_to_append = []
        for item in data_list:
            row = [
                item.get("id_utente", ""),
                item.get("esperienza", ""),
                item.get("nome_immagine", ""),
                item.get("dataset", ""),
                item.get("score", ""),
                item.get("file_txt_assegnato", ""),
                item.get("timestamp", ""),
                item.get("feedback", "") # Il feedback è nel dataframe ma va passato riga per riga
            ]
            rows_to_append.append(row)
            
        # 3. Scrittura atomica (Thread-safe lato Google)
        if rows_to_append:
            worksheet.append_rows(rows_to_append)
            return True
            
    except Exception as e:
        logging.error(f"Errore salvataggio gspread: {e}")
        st.error(f"Errore tecnico nel salvataggio: {e}")
        return False

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

@st.cache_data(show_spinner=False)
def load_guideline_images():
    """Load and download the two reference images for the guidelines."""
    refs = {"high": None, "low": None}
    
    # Map: key -> filename
    files_to_find = {
        "high": HIGH_QUALITY_FILENAME,
        "low": LOW_QUALITY_FILENAME
    }

    try:
        for key, fname in files_to_find.items():
            # Cerchiamo il file per nome nel Drive (globale, ma escludendo il cestino)
            # Questo evita di dover sapere l'ID della cartella a priori
            q = f"title = '{fname}' and trashed=false"
            file_list = drive.ListFile({'q': q}).GetList()
            
            if file_list:
                # Prendiamo il primo match trovato
                f_obj = file_list[0]
                img_bytes = get_image_bytes_by_id(f_obj['id'])
                refs[key] = Image.open(io.BytesIO(img_bytes))
    except Exception as e:
        logging.warning(f"Warning: Could not load guideline images: {e}")
    
    return refs

@st.cache_data(show_spinner=False)
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
    conn = None
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df_batches = conn.read(worksheet="Batches", ttl=0).fillna("")
    except Exception:
        logging.getLogger(__name__).exception("Error accessing Batches worksheet")
        return [], set(), pd.DataFrame()

    # Ensure the worksheet has the expected columns; if not, create/reset it with headers
    required_cols = ["batch_name", "image_ids"]
    try:
        if df_batches.empty or any(col not in df_batches.columns for col in required_cols):
            df_batches = pd.DataFrame(columns=required_cols)
            conn.update(worksheet="Batches", data=df_batches)
    except Exception:
        logging.getLogger(__name__).exception("Error initializing Batches worksheet")
        return [], set(), pd.DataFrame()

    scoring_sets = []
    used_ids_global = set()
    
    if df_batches.empty or "batch_name" not in df_batches.columns:
        return [], used_ids_global, df_batches

    for index, row in df_batches.iterrows():
        b_name = str(row['batch_name']).strip()
        ids_str = str(row['image_ids']).strip()
        
        if b_name and ids_str:
            ids_list = [x.strip() for x in ids_str.split(',') if x.strip()]
            if ids_list:
                scoring_sets.append({
                    "filename": b_name,
                    "ids": ids_list
                })
                used_ids_global.update(ids_list)
    
    return scoring_sets, used_ids_global, df_batches

def create_new_batch_entry(existing_df, used_ids_global):
    """Crea un nuovo batch e lo salva nel foglio 'Batches'."""
    images_by_id, datasets = load_datasets_and_index()
    
    available_images = {} 
    all_available_pool = []
    
    for ds_name, entries in datasets.items():
        clean_entries = [e for e in entries if e['img_obj']['id'] not in used_ids_global]
        random.shuffle(clean_entries)
        available_images[ds_name] = clean_entries
        all_available_pool.extend(clean_entries)
    
    if not all_available_pool:
        all_available_pool = []
        for ds_name, entries in datasets.items():
            random.shuffle(entries)
            available_images[ds_name] = entries
            all_available_pool.extend(entries)

    selected_entries = []
    datasets_names = list(datasets.keys())
    
    for ds_name in datasets_names:
        pool = available_images.get(ds_name, [])
        take_n = min(len(pool), TARGET_PER_DATASET)
        selected_entries.extend(pool[:take_n])
        ids_taken = [x['img_obj']['id'] for x in pool[:take_n]]
        all_available_pool = [x for x in all_available_pool if x['img_obj']['id'] not in ids_taken]

    missing_count = IMAGES_PER_BATCH - len(selected_entries)
    if missing_count > 0:
        random.shuffle(all_available_pool)
        selected_entries.extend(all_available_pool[:missing_count])
    
    random.shuffle(selected_entries)
    new_ids = [entry['img_obj']['id'] for entry in selected_entries]
    
    next_num = 1
    if not existing_df.empty and "batch_name" in existing_df.columns:
        for name in existing_df["batch_name"]:
            try:
                num = int(str(name).replace("batch_", ""))
                if num >= next_num:
                    next_num = num + 1
            except:
                pass
    
    new_batch_name = f"batch_{next_num:02d}"
    ids_string = ",".join(new_ids)
    
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        new_row = pd.DataFrame([{"batch_name": new_batch_name, "image_ids": ids_string}])
        
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
    scoring_sets, used_ids_global, df_batches = get_batches_from_sheet()

    logger = logging.getLogger(__name__)
    
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        dati = conn.read(worksheet="Results", ttl=0).fillna("")
    except Exception:
        logger.exception("Error reading Google Sheets")
        dati = pd.DataFrame()

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

    assigned_set = None
    
    for s_set in scoring_sets:
        fname = s_set['filename']
        if fname in user_completed_batches:
            continue 
        
        if batch_counts.get(fname, 0) < USERS_PER_GROUP:
            assigned_set = s_set
            break 
    
    if assigned_set is None:
        with st.spinner("Generating new image batch..."):
            new_fname, new_ids = create_new_batch_entry(df_batches, used_ids_global)
            if not new_fname:
                return [], "ERROR"
            
            assigned_set = {
                "filename": new_fname,
                "ids": new_ids
            }

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

    # --- 3. IMAGE LOADING & MANAGEMENT ---
    images_by_id, _ = load_datasets_and_index()
    if not images_by_id:
        st.error(
            "⚠️ **Unable to load images** \n\n"
            "We encountered a problem accessing the image database. "
            "Please contact the administrator for assistance."
        )
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
        
    # --- LOAD REFERENCE IMAGES FOR GUIDELINES ---
    # Lo facciamo qui per averle pronte da mostrare in col1
    guideline_imgs = load_guideline_images()

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
            st.markdown("### **Criteria for Adequate Endoscopic Image Quality**")
            st.markdown(LINEE_GUIDA)
            
            # --- DISPLAY REFERENCE IMAGES ---
            st.divider()
            st.markdown("#### Reference Examples")
            
            c_good, c_bad = st.columns(2)
            with c_good:
                st.caption("✅ High Quality")
                if guideline_imgs.get("high"):
                    st.image(guideline_imgs["high"], width='stretch')
                else:
                    st.caption("(Image not found)")
            
            with c_bad:
                st.caption("❌ Low Quality")
                if guideline_imgs.get("low"):
                    st.image(guideline_imgs["low"], width='stretch')
                else:
                    st.caption("(Image not found)")

        with col2:
            st.markdown("### Image to Evaluate")
            if image:
                st.image(image, width='stretch')
            
            st.markdown(f"<b>Dataset:</b> {folder_name}", unsafe_allow_html=True)
            
            score = st.slider("Quality Score (1-10)", 1, 10, 5, key=f"score_{indice}")
            
            c_back, c_save, c_summ = st.columns([1, 1.5, 1])
            
            with c_back:
                if st.button("⬅️ Back", width='stretch'):
                    if indice > 0:
                        if st.session_state.valutazioni:
                            st.session_state.valutazioni.pop()
                        st.session_state.indice -= 1
                        st.rerun()
            
            with c_save:
                if st.button("Next ➜", width='stretch', type="primary"):
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
                if st.button("📋 Summary", width='stretch'):
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


            if st.button("💾 SAVE AND SUBMIT RESULTS", type="primary", width='stretch'):
                with st.spinner("Saving Results..."):
                    
                    # 1. Prepariamo i dati aggiungendo il feedback a ogni riga
                    dati_da_salvare = []
                    for val in st.session_state.valutazioni:
                        # Creiamo una copia per non sporcare la session state
                        entry = val.copy()
                        # Aggiungiamo il feedback (è uguale per tutte le immagini di questa sessione)
                        entry['feedback'] = feedback_text 
                        # Rimuoviamo colonne inutili per il sheet se presenti
                        entry.pop('file_id', None)
                        entry.pop('anteprima', None)
                        dati_da_salvare.append(entry)

                    # 2. Usiamo la NUOVA funzione di salvataggio sicuro
                    success = safe_append_data(dati_da_salvare, worksheet_name="Results")

                    if success:
                        st.session_state.salvato = True
                        st.rerun()
                    else:
                        # Fallback: se fallisce gspread, offri il CSV
                        st.error("⚠️ Errore di connessione a Google Sheets.")
                        df = pd.DataFrame(st.session_state.valutazioni)
                        csv = df.to_csv(index=False)
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