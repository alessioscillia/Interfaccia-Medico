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
from datetime import datetime

# Gestione Timezone
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
# 1. CONFIGURAZIONE E COSTANTI
# ==============================================================================

st.set_page_config(layout="wide", page_title="Valutazione Immagini Mediche")

# --- CONFIGURAZIONE UTENTE ---
ARTICOLO_POLYPS_FOLDER_ID = '1He7eQCE2xI5X8n00A-B-eKEBZjNIw9cJ'
DATA_DEVELOPMENT_FOLDER_ID = "1gZc6y9Q0DDHyNLbQoEOJVCdMwH_UIYut"
SCORING_FOLDER_ID = "1Joi3sCLkq2GQ1MG4LH2veq0cYftbb9XQ"
USERS_PER_GROUP = 3 

LINEE_GUIDA = """
- **Luminosità:** l'immagine deve essere ben illuminata senza aree eccessivamente scure o sovraesposte.
- **Nitidezza:** i dettagli della mucosa devono essere ben visibili, senza sfocatura dovuta a motion blur.
- **Colori naturali:** assenza di dominanti cromatiche innaturali.
- **Assenza di artefatti:** evitare immagini disturbate da artefatti digitali o movimenti improvvisi.
- **Composizione:** la porzione di interesse deve essere centrata e visibile.
"""

# ==============================================================================
# 2. FUNZIONI DI UTILITÀ
# ==============================================================================

def _now_rome_str():
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
# 3. GESTIONE GOOGLE DRIVE E DATI
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
            st.error("File delle credenziali 'service-account.json' non trovato!")
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

@st.cache_data(show_spinner="Caricamento immagini...", ttl=3600)
def load_datasets_and_index():
    try:
        folder_list = drive.ListFile(
            {'q': f"'{DATA_DEVELOPMENT_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"}
        ).GetList()
    except Exception:
        logging.getLogger(__name__).exception("Errore accesso Data-Development")
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

@st.cache_data(show_spinner="Preparazione liste di valutazione...", ttl=3600)
def load_scoring_sets():
    """
    Legge i file .txt. Restituisce una lista di dizionari:
    [{'filename': 'batch1.txt', 'ids': [...]}, ...]
    """
    try:
        scoring_files = drive.ListFile(
            {'q': f"'{SCORING_FOLDER_ID}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'"}
        ).GetList()
    except Exception:
        logging.getLogger(__name__).exception("Errore accesso Scoring")
        return []

    txt_files = [f for f in scoring_files if f['title'].lower().endswith('.txt')]
    # Ordiniamo per nome file per coerenza
    txt_files.sort(key=lambda f: f['title'].lower())

    scoring_sets = []
    for f in txt_files:
        try:
            content = f.GetContentString()
            ids = [line.strip() for line in content.splitlines() if line.strip()]
            if ids:
                # Modifica: Salvo anche il nome del file
                scoring_sets.append({
                    "filename": f['title'],
                    "ids": ids
                })
        except Exception:
            pass
    return scoring_sets

def get_user_images(user_id: str):
    """
    Determina immagini e nome del file txt assegnato.
    Returns: (list_of_images, assigned_txt_filename)
    """
    images_by_id, _ = load_datasets_and_index()
    scoring_sets = load_scoring_sets() # Ora è una lista di dict {'filename':..., 'ids':...}

    if not scoring_sets:
        st.error("Nessun file di scoring trovato.")
        return [], None

    logger = logging.getLogger(__name__)
    
    # Lettura storico da Google Sheets
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        dati = conn.read(worksheet="Foglio1").fillna("")
    except Exception:
        logger.exception("Errore lettura Google Sheets")
        dati = pd.DataFrame()

    # Logica di assegnazione
    assigned_set_index = 0
    
    # 1. Controlliamo se l'utente esiste già nello storico
    user_exists = False
    last_assigned_file = None
    
    if not dati.empty and "id_utente" in dati.columns:
        # Filtriamo le righe di questo utente
        user_rows = dati[dati["id_utente"] == user_id]
        if not user_rows.empty:
            user_exists = True
            # Cerchiamo se c'è la colonna del file assegnato
            if "file_txt_assegnato" in user_rows.columns:
                # Prendiamo l'ultimo file assegnato a questo utente
                last_val = user_rows.iloc[-1]["file_txt_assegnato"]
                if last_val and str(last_val).strip() != "":
                    last_assigned_file = str(last_val).strip()

    if user_exists and last_assigned_file:
        # CASO: UTENTE DI RITORNO
        # Troviamo l'indice del file usato l'ultima volta
        last_idx = -1
        for i, s_set in enumerate(scoring_sets):
            if s_set['filename'] == last_assigned_file:
                last_idx = i
                break
        
        if last_idx != -1:
            # Assegna il prossimo file (rotazione circolare)
            assigned_set_index = (last_idx + 1) % len(scoring_sets)
        else:
            # Se il file vecchio non esiste più, riparte da 0 o logica default
            assigned_set_index = 0
            
    else:
        # CASO: NUOVO UTENTE (o utente vecchio senza colonna 'file_txt_assegnato')
        # Calcoliamo la posizione in base al numero di utenti unici globali
        if not dati.empty and "id_utente" in dati.columns:
            unique_users = dati["id_utente"].unique().tolist()
            # Se l'utente è nuovo, la sua posizione è alla fine
            if user_id not in unique_users:
                user_position = len(unique_users)
            else:
                user_position = unique_users.index(user_id)
        else:
            user_position = 0
            
        group_index = user_position // USERS_PER_GROUP
        assigned_set_index = group_index % len(scoring_sets)

    # Recupero i dati del set scelto
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
# 4. COMPONENTI UI
# ==============================================================================

@st.dialog("Riepilogo delle tue scelte", width="large")
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
                "anteprima": st.column_config.ImageColumn("Anteprima", width="medium"), 
                "score": st.column_config.NumberColumn("Voto", format="%d ⭐"),
            }
        )
        st.caption(f"Totale immagini valutate: {len(df_temp)}")
    else:
        st.info("Nessuna valutazione.")

# ==============================================================================
# 5. MAIN
# ==============================================================================

def main():
    st.markdown("<h2 style='margin-bottom:0;'>Valutazione qualità immagini colonscopiche</h2>", unsafe_allow_html=True)

    user_id = st.text_input("👨‍⚕️ Id utente:", key="user_id")
    if not user_id:
        st.warning("Inserisci il tuo nome per proseguire.")
        st.stop()

    # Caricamento
    images_by_id, _ = load_datasets_and_index()
    if not images_by_id:
        st.stop()

    # Inizializzazione Session State
    if "immagini" not in st.session_state:
        # Recupera immagini E nome del file assegnato
        imgs, txt_filename = get_user_images(user_id)
        st.session_state.immagini = imgs
        st.session_state.current_txt_file = txt_filename # Salviamo il nome del file in sessione
        st.session_state.indice = 0
        st.session_state.valutazioni = []

    indice = st.session_state.indice
    imgs = st.session_state.immagini
    
    if not imgs:
        st.error("Nessuna immagine trovata per questo set di valutazione.")
        st.stop()

    # Loop Valutazione
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
            st.markdown("### Linee guida qualità")
            st.markdown(LINEE_GUIDA)
        
        with col2:
            if image:
                st.image(image, width='stretch')
            
            st.markdown(f"<b>Dataset:</b> {folder_name}", unsafe_allow_html=True)
            # (Debug opzionale: mostra quale file txt stiamo usando)
            # st.caption(f"File assegnato: {st.session_state.current_txt_file}")
            
            score = st.slider("Score qualità (1-10)", 1, 10, 5, key=f"score_{indice}")
            
            c_back, c_save, c_summ = st.columns([1, 1.5, 1])
            
            with c_back:
                if st.button("⬅️ Indietro", width='stretch'):
                    if indice > 0:
                        if st.session_state.valutazioni:
                            st.session_state.valutazioni.pop()
                        st.session_state.indice -= 1
                        st.rerun()
            
            with c_save:
                if st.button("Salva e prosegui ➜", width='stretch', type="primary"):
                    st.session_state.valutazioni.append({
                        "id_utente": user_id,
                        "nome_immagine": img_file['title'],
                        "file_id": img_file['id'], 
                        "score": score,
                        "dataset": folder_name,
                        # SALVIAMO IL NOME DEL FILE TXT ASSEGNATO
                        "file_txt_assegnato": st.session_state.current_txt_file,
                        "timestamp": _now_rome_str()
                    })
                    st.session_state.indice += 1
                    st.rerun()

            with c_summ:
                if st.button("📋 Riepilogo", width='stretch'):
                    visualizza_riepilogo()
        
        st.markdown(f"<center><small>{indice} / {len(imgs)} immagini valutate</small></center>", unsafe_allow_html=True)
        
        # Prefetch
        if indice + 1 < len(imgs):
            next_id = imgs[indice + 1]['img_obj']['id']
            threading.Thread(target=get_image_bytes_by_id, args=(next_id,), daemon=True).start()

    else:
        st.success("Hai completato tutte le valutazioni!")
        df = pd.DataFrame(st.session_state.valutazioni)
        
        # Mostra tabella pulita
        cols_to_show = [c for c in df.columns if c not in ['file_id']]
        st.dataframe(df[cols_to_show], hide_index=True)
        
        if "salvato" not in st.session_state:
            st.session_state.salvato = False
        
        if not st.session_state.salvato:
            with st.spinner("Salvataggio risultati..."):
                try:
                    conn = st.connection("gsheets", type=GSheetsConnection)
                    existing_data = conn.read(worksheet="Foglio1")
                    
                    # Rimuoviamo file_id ma MANTENIAMO file_txt_assegnato
                    df_to_save = df.drop(columns=['file_id'], errors='ignore')

                    if existing_data.empty:
                        conn.update(worksheet="Foglio1", data=df_to_save)
                    else:
                        new_data = pd.concat([existing_data, df_to_save], ignore_index=True)
                        conn.update(worksheet="Foglio1", data=new_data)
                    
                    st.session_state.salvato = True
                    st.success("✅ Salvato con successo!")
                except Exception as e:
                    st.error(f"⚠️ Errore salvataggio: {e}")
                    csv = df.drop(columns=['file_id'], errors='ignore').to_csv(index=False)
                    st.download_button("📥 Scarica CSV", csv, "risultati.csv", "text/csv")
        else:
            st.success("✅ Risultati già salvati!")

if __name__ == "__main__":
    main()