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

# Gestione Timezone (opzionale, fallback a UTC se mancano librerie)
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

# Configurazione della pagina Streamlit (deve essere la prima istruzione Streamlit)
st.set_page_config(layout="wide", page_title="Valutazione Immagini Mediche")

# --- CONFIGURAZIONE UTENTE ---
# ID della cartella su Google Drive contenente i dataset di immagini.
# Modificare questo ID con quello della propria cartella condivisa.
ARTICOLO_POLYPS_FOLDER_ID = '1He7eQCE2xI5X8n00A-B-eKEBZjNIw9cJ'

# Numero di immagini da mostrare per ogni dataset (sottocartella).
IMAGES_PER_DATASET = 3

# Linee guida mostrate all'utente durante la valutazione.
LINEE_GUIDA = """
- **Luminosità:** l'immagine deve essere ben illuminata senza aree eccessivamente scure o sovraesposte.
- **Nitidezza:** i dettagli della mucosa devono essere ben visibili, senza sfocatura dovuta a motion blur.
- **Colori naturali:** assenza di dominanti cromatiche innaturali.
- **Assenza di artefatti:** evitare immagini disturbate da artefatti digitali o movimenti improvvisi.
- **Composizione:** la porzione di interesse deve essere centrata e visibile.
"""

# ==============================================================================
# 2. FUNZIONI DI UTILITÀ (HELPER FUNCTIONS)
# ==============================================================================

def _now_rome_str():
    """
    Restituisce l'orario corrente formattato (Europe/Rome).
    Effettua un fallback a UTC se le librerie di timezone non sono disponibili.
    """
    fmt = '%Y-%m-%d %H:%M:%S'
    try:
        if _HAS_ZONEINFO and ZoneInfo is not None:
            return datetime.now(ZoneInfo("Europe/Rome")).strftime(fmt)
        if 'pytz' in globals() and pytz is not None:
            return datetime.now(pytz.timezone("Europe/Rome")).strftime(fmt)
    except Exception:
        pass
    # Fallback
    return datetime.utcnow().strftime(fmt)

def bytes_to_base64_url(img_bytes):
    """
    Converte i bytes di un'immagine in una stringa Data URL base64.
    Necessario per visualizzare le immagini all'interno di st.dataframe.
    """
    try:
        b64_encoded = base64.b64encode(img_bytes).decode()
        # Assumiamo PNG per semplicità, i browser moderni gestiscono bene anche se è JPEG
        return f"data:image/png;base64,{b64_encoded}"
    except Exception:
         return None

# ==============================================================================
# 3. GESTIONE GOOGLE DRIVE E DATI
# ==============================================================================

@st.cache_resource(show_spinner=False)
def get_drive():
    """
    Autentica e restituisce l'oggetto GoogleDrive.
    Gestisce sia l'autenticazione tramite st.secrets (Cloud) che file locale (Locale).
    """
    gauth = GoogleAuth()
    
    # Verifica se siamo in ambiente Cloud (Streamlit Secrets) o Locale
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

# Inizializza l'oggetto drive globale
drive = get_drive()

@st.cache_data(show_spinner=False)
def get_image_bytes_by_id(file_id: str):
    """
    Scarica i bytes grezzi di un file da Google Drive dato il suo ID.
    Cachato per evitare download ripetuti della stessa immagine.
    """
    f = drive.CreateFile({'id': file_id})
    buf = f.GetContentIOBuffer()
    return buf.read()

@st.cache_data(show_spinner="Caricamento lista immagini...", ttl=3600)
def load_all_images_from_drive():
    """
    Scansiona la cartella principale su Drive e indicizza tutte le immagini
    divise per sottocartella (dataset).
    """
    # 1. Trova le sottocartelle
    folder_list = drive.ListFile(
        {'q': f"'{ARTICOLO_POLYPS_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"}
    ).GetList()
    
    all_images_by_dataset = {}
    
    # 2. Per ogni sottocartella, trova le immagini
    for folder in folder_list:
        images = drive.ListFile(
            {'q': f"'{folder['id']}' in parents and trashed=false and mimeType contains 'image/'"}
        ).GetList()
        
        all_images_by_dataset[folder['title']] = [
            {
                "img_obj": {'id': img['id'], 'title': img['title']},
                "folder_name": folder['title']
            }
            for img in images
        ]
    return all_images_by_dataset

def get_user_images(user_id: str, all_images_by_dataset: dict):
    """
    Determina quali immagini mostrare all'utente corrente.
    Usa una logica deterministica basata sull'ordine degli utenti nel Google Sheet
    per mostrare set diversi.
    """
    logger = logging.getLogger(__name__)
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        dati = conn.read(worksheet="Foglio1").fillna("")
        if not dati.empty and "id_utente" in dati.columns:
            unique_users = dati["id_utente"].unique().tolist()
        else:
            unique_users = []
    except Exception:
        logger.exception("Errore lettura Google Sheets")
        st.warning("Impossibile leggere gli utenti da Google Sheets; verrà usata una lista vuota (fallback).")
        unique_users = []
    
    # Trova la posizione dell'utente
    if user_id in unique_users:
        user_position = unique_users.index(user_id)
    else:
        user_position = len(unique_users)
    
    # Logica di assegnazione (Round Robin semplificato)
    group_number = user_position // 3
    total_datasets = len(all_images_by_dataset)
    images_per_group = IMAGES_PER_DATASET * total_datasets
    total_possible_images = sum(len(imgs) for imgs in all_images_by_dataset.values())

    if total_possible_images == 0:
        return []
    
    group_start_idx = (group_number * images_per_group) % total_possible_images
    
    user_images = []
    sorted_datasets = sorted(all_images_by_dataset.keys())
    
    for dataset_idx, dataset_name in enumerate(sorted_datasets):
        dataset_images = all_images_by_dataset[dataset_name]
        if len(dataset_images) > 0:
            dataset_offset = (group_start_idx + (dataset_idx * IMAGES_PER_DATASET)) % len(dataset_images)
            take_count = min(IMAGES_PER_DATASET, len(dataset_images))
            selected = [
                dataset_images[(dataset_offset + i) % len(dataset_images)]
                for i in range(take_count)
            ]
            user_images.extend(selected)
    
    return user_images

# ==============================================================================
# 4. COMPONENTI UI
# ==============================================================================

@st.dialog("Riepilogo delle tue scelte", width="large")
def visualizza_riepilogo():
    """
    Mostra un pop-up modale con il riepilogo delle votazioni effettuate.
    Include le anteprime delle immagini.
    """
    if "valutazioni" in st.session_state and st.session_state.valutazioni:
        
        data_for_display = []
        
        # Prepara i dati per la visualizzazione
        for item in st.session_state.valutazioni:
            display_item = item.copy()
            # Recupera i bytes e converte in base64 per l'anteprima
            img_bytes = get_image_bytes_by_id(display_item["file_id"])
            display_item["anteprima"] = bytes_to_base64_url(img_bytes)
            data_for_display.append(display_item)

        df_temp = pd.DataFrame(data_for_display)

        # Configurazione Dataframe: MOSTRA SOLO ANTEPRIMA E SCORE
        st.dataframe(
            df_temp,
            use_container_width=True,
            hide_index=True,
            row_height=100, # Altezza aumentata per vedere meglio l'immagine
            column_order=("anteprima", "score"), 
            column_config={
                "anteprima": st.column_config.ImageColumn("Anteprima Immagine", width="medium"), 
                "score": st.column_config.NumberColumn("Voto Assegnato", format="%d ⭐"),
            }
        )
        st.caption(f"Totale immagini valutate: {len(df_temp)}")
    else:
        st.info("Non hai ancora effettuato nessuna valutazione in questa sessione.")

# ==============================================================================
# 5. MAIN APPLICATION FLOW
# ==============================================================================

def main():
    st.markdown("<h2 style='margin-bottom:0;'>Valutazione qualità immagini colonscopiche</h2>", unsafe_allow_html=True)

    # 1. Input Utente
    user_id = st.text_input("👨‍⚕️ Id utente:", key="user_id")
    if not user_id:
        st.warning("Inserisci il tuo nome per proseguire.")
        st.stop()

    # 2. Caricamento Dati (Immagini)
    all_images_by_dataset = load_all_images_from_drive()
    
    if not all_images_by_dataset or all(len(v) == 0 for v in all_images_by_dataset.values()):
        st.warning("Nessuna immagine trovata nelle sottocartelle.")
        st.stop()

    # 3. Inizializzazione Session State
    if "immagini" not in st.session_state:
        st.session_state.immagini = get_user_images(user_id, all_images_by_dataset)
        st.session_state.indice = 0
        st.session_state.valutazioni = []

    indice = st.session_state.indice
    imgs = st.session_state.immagini

    # 4. Loop di Valutazione
    if indice < len(imgs):
        curr_entry = imgs[indice]
        img_file = curr_entry["img_obj"]
        folder_name = curr_entry["folder_name"]
        file_id = img_file['id']

        # Download Immagine Corrente
        try:
            img_bytes = get_image_bytes_by_id(file_id)
            image = Image.open(io.BytesIO(img_bytes))
        except Exception as e:
            st.error(f"Errore nel download dell'immagine: {e}")
            image = None

        # Layout a due colonne: Guida | Immagine + Controlli
        col1, col2 = st.columns([1, 2])

        with col1:
            st.markdown("### Linee guida qualità")
            st.markdown(LINEE_GUIDA)
        
        with col2:
            if image is not None:
                st.image(image, width='stretch')
            
            st.markdown(f"<b>Dataset:</b> {folder_name}", unsafe_allow_html=True)
            
            # Slider per il voto
            score = st.slider("Score di qualità (1 = pessima, 10 = ottima)", 1, 10, 5, key=f"score_{indice}")
            
            # Pulsanti di navigazione
            col_btn_back, col_btn_save, col_btn_summary = st.columns([1, 1.5, 1])
            
            with col_btn_back:
                if st.button("⬅️ Indietro", use_container_width=True):
                    if indice > 0:
                        if st.session_state.valutazioni:
                            st.session_state.valutazioni.pop()
                        st.session_state.indice -= 1
                        st.rerun()
            
            with col_btn_save:
                if st.button("Salva voto e prosegui ➜", use_container_width=True, type="primary"):
                    st.session_state.valutazioni.append({
                        "id_utente": user_id,
                        "nome_immagine": img_file['title'],
                        "file_id": img_file['id'], 
                        "score": score,
                        "dataset": folder_name,
                        "timestamp": _now_rome_str()
                    })
                    st.session_state.indice += 1
                    st.rerun()

            with col_btn_summary:
                if st.button("📋 Riepilogo", use_container_width=True):
                    visualizza_riepilogo()
        
        st.markdown(f"<center><small>{indice} / {len(imgs)} immagini valutate</small></center>", unsafe_allow_html=True)
        
        # Prefetch immagine successiva in background per fluidità
        next_idx = indice + 1
        if next_idx < len(imgs):
            try:
                next_id = imgs[next_idx]['img_obj']['id']
                threading.Thread(target=get_image_bytes_by_id, args=(next_id,), daemon=True).start()
            except Exception:
                pass

    # 5. Schermata Finale e Salvataggio
    else:
        st.success("Hai completato tutte le valutazioni!")
        df = pd.DataFrame(st.session_state.valutazioni)
        
        # Mostra tabella finale pulita (senza ID tecnici)
        cols_to_show = [c for c in df.columns if c != 'file_id']
        st.dataframe(df[cols_to_show], hide_index=True)
        
        if "salvato" not in st.session_state:
            st.session_state.salvato = False
        
        if not st.session_state.salvato:
            with st.spinner("Salvataggio risultati..."):
                try:
                    conn = st.connection("gsheets", type=GSheetsConnection)
                    existing_data = conn.read(worksheet="Foglio1")
                    
                    # Rimuovi file_id prima di salvare su sheets
                    df_to_save = df.drop(columns=['file_id'], errors='ignore')

                    if existing_data.empty:
                        conn.update(worksheet="Foglio1", data=df_to_save)
                    else:
                        new_data = pd.concat([existing_data, df_to_save], ignore_index=True)
                        conn.update(worksheet="Foglio1", data=new_data)
                    
                    st.session_state.salvato = True
                    st.success("✅ Risultati salvati con successo!")
                except Exception as e:
                    st.error(f"⚠️ Errore durante il salvataggio: {e}")
                    st.info("Puoi scaricare i risultati localmente usando il bottone qui sotto.")
                    csv = df.drop(columns=['file_id'], errors='ignore').to_csv(index=False)
                    st.download_button(
                        label="📥 Scarica risultati (CSV)",
                        data=csv,
                        file_name=f"valutazioni_{user_id}_{_now_rome_str().replace(' ', '_').replace(':', '-')}.csv",
                        mime="text/csv"
                    )
        else:
            st.success("✅ Risultati già salvati!")

if __name__ == "__main__":
    main()