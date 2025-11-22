import streamlit as st
from PIL import Image
import threading
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import io
import logging
from datetime import datetime
import os
import json


# Prefer zoneinfo (Python 3.9+); se non disponibile usa pytz se presente, altrimenti fallback a UTC
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


def _now_rome_str():
    """Return current time in Europe/Rome as formatted string. Falls back to UTC if tz libs missing."""
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

st.set_page_config(layout="wide")
st.markdown("<h2 style='margin-bottom:0;'>Valutazione qualità immagini colonscopiche</h2>", unsafe_allow_html=True)

user_id = st.text_input("👨‍⚕️ Id utente:", key="user_id")
if not user_id:
    st.warning("Inserisci il tuo nome per proseguire.")
    st.stop()


# Autenticazione Google Drive tramite Service Account (nessuna autenticazione utente richiesta)
@st.cache_resource(show_spinner=False)
def get_drive():
    gauth = GoogleAuth()
    
    # Determina quale file di credenziali usare
    if "gcp_service_account" in st.secrets:
        # Usa Streamlit secrets (per deployment su Streamlit Cloud)
        service_account_info = dict(st.secrets["gcp_service_account"])
        
        # Salva temporaneamente le credenziali in un file
        temp_cred_file = "temp_service_account.json"
        with open(temp_cred_file, "w") as f:
            json.dump(service_account_info, f)
        
        service_account_file = temp_cred_file
        client_email = service_account_info.get('client_email')
    else:
        # Usa il file locale service-account.json
        service_account_file = "service-account.json"
        if not os.path.exists(service_account_file):
            st.error(f"""
            ⚠️ **File delle credenziali non trovato!**
            
            Per usare questa applicazione, devi:
            1. Creare un Service Account su Google Cloud Console
            2. Scaricare il file JSON delle credenziali
            3. Salvarlo come `{service_account_file}` nella stessa directory di questo script
            
            Oppure configura le credenziali in `.streamlit/secrets.toml` per il deployment.
            
            Consulta il file SETUP_SERVICE_ACCOUNT.md per istruzioni dettagliate.
            """)
            st.stop()
        
        # Leggi l'email del client dal file
        with open(service_account_file, 'r') as f:
            service_account_info = json.load(f)
            client_email = service_account_info.get('client_email')
    
    # Configura PyDrive2 per usare il service account
    gauth.settings['client_config_backend'] = 'service'
    gauth.settings['service_config'] = {
        'client_json_file_path': service_account_file,
        'client_user_email': client_email,  # Questo campo è richiesto da PyDrive2
    }
    
    # Autentica usando il service account
    gauth.ServiceAuth()
    
    drive = GoogleDrive(gauth)
    return drive

drive = get_drive()


# Cache per download immagine: usa l'id del file per evitare di serializzare l'oggetto PyDrive
@st.cache_data(show_spinner=False)
def get_image_bytes_by_id(file_id: str):
    """Scarica i bytes dell'immagine da Google Drive usando l'id del file.

    Viene memorizzato in cache da Streamlit per evitare ripetuti download durante la stessa sessione.
    """
    f = drive.CreateFile({'id': file_id})
    buf = f.GetContentIOBuffer()
    return buf.read()

# ID della cartella principale 'Articolo Polyps'
ARTICOLO_POLYPS_FOLDER_ID = '1He7eQCE2xI5X8n00A-B-eKEBZjNIw9cJ'

# Linee guida
linee_guida = """
- **Luminosità:** l'immagine deve essere ben illuminata senza aree eccessivamente scure o sovraesposte.
- **Nitidezza:** i dettagli della mucosa devono essere ben visibili, senza sfocatura dovuta a motion blur.
- **Colori naturali:** assenza di dominanti cromatiche innaturali.
- **Assenza di artefatti:** evitare immagini disturbate da artefatti digitali o movimenti improvvisi.
- **Composizione:** la porzione di interesse deve essere centrata e visibile.
"""

# MODIFICA QUI NUMERO DI IMMAGINI PER DATASET DA MOSTRARE
IMAGES_PER_DATASET = 3

# ✅ OTTIMIZZAZIONE 1: Cache del listing cartelle/immagini (evita chiamate API ad ogni rerun)
@st.cache_data(show_spinner="Caricamento immagini...", ttl=3600)
def load_all_images_from_drive():
    """Carica tutte le cartelle e immagini da Google Drive. Cachato per 1 ora."""
    # Recupera tutte le sottocartelle ('Dataset 1', 'Dataset 2', 'Dataset 3')
    folder_list = drive.ListFile(
        {'q': f"'{ARTICOLO_POLYPS_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"}
    ).GetList()
    
    all_images_by_dataset = {}
    for folder in folder_list:
        images = drive.ListFile(
            {'q': f"'{folder['id']}' in parents and trashed=false and mimeType contains 'image/'"}
        ).GetList()
        # Salviamo solo i metadati essenziali (non l'intero oggetto PyDrive)
        all_images_by_dataset[folder['title']] = [
            {
                "img_obj": {'id': img['id'], 'title': img['title']},
                "folder_name": folder['title']
            }
            for img in images
        ]
    return all_images_by_dataset

all_images_by_dataset = load_all_images_from_drive()

if not all_images_by_dataset or all(len(v) == 0 for v in all_images_by_dataset.values()):
    st.warning("Nessuna immagine trovata nelle sottocartelle.")
    st.stop()


# Funzione per ottenere le immagini assegnate all'utente attuale
def get_user_images(user_id: str):
    """Determina il gruppo di assegnazione dell'utente e restituisce le immagini da valutare.
    
    Ogni 3 utenti consecutivi riceve lo stesso set di immagini.
    Es: utenti 1,2,3 -> set A; utenti 4,5,6 -> set B; utenti 7,8,9 -> set C; utenti 10,11,12 -> set A (ricomincia)
    """
    # Leggi gli utenti unici già presenti su Google Sheets
    logger = logging.getLogger(__name__)
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        dati = conn.read(worksheet="Foglio1").fillna("")
        if not dati.empty and "id_utente" in dati.columns:
            unique_users = dati["id_utente"].unique().tolist()
        else:
            unique_users = []
    except Exception as e:
        # Log the error for diagnosis and show a lightweight warning to the user.
        logger.exception("Errore lettura Google Sheets")
        st.warning("Impossibile leggere gli utenti da Google Sheets; verrà usata una lista vuota (fallback).")
        unique_users = []
    
    # Se l'utente è già in lista, la sua posizione è quella
    if user_id in unique_users:
        user_position = unique_users.index(user_id)
    else:
        # Se non è in lista, sarà il prossimo utente dopo gli ultimi
        user_position = len(unique_users)
    
    # Determina il gruppo di assegnazione (ogni 3 utenti)
    group_number = user_position // 3
    
    # Raccogli tutte le immagini organizzate per dataset
    total_datasets = len(all_images_by_dataset)
    images_per_group = IMAGES_PER_DATASET * total_datasets
    total_possible_images = sum(len(imgs) for imgs in all_images_by_dataset.values())

    # Protezione: se per qualche motivo non ci sono immagini totali, evita divisione/modulo per zero
    if total_possible_images == 0:
        logging.getLogger(__name__).warning("Nessuna immagine disponibile")
        return []
    
    # Calcola l'indice di inizio per questo gruppo
    group_start_idx = (group_number * images_per_group) % total_possible_images
    
    # Costruisci la lista di immagini per questo utente (IMAGES_PER_DATASET per ogni dataset)
    user_images = []
    sorted_datasets = sorted(all_images_by_dataset.keys())
    
    for dataset_idx, dataset_name in enumerate(sorted_datasets):
        dataset_images = all_images_by_dataset[dataset_name]
        if len(dataset_images) > 0:
            # Calcola l'offset per questo dataset e gruppo
            dataset_offset = (group_start_idx + (dataset_idx * IMAGES_PER_DATASET)) % len(dataset_images)
            # Seleziona fino a IMAGES_PER_DATASET immagini da questo dataset (se il dataset è più piccolo,
            # prendiamo solo quanto è disponibile per evitare duplicati nell'elenco risultante)
            take_count = min(IMAGES_PER_DATASET, len(dataset_images))
            selected = [
                dataset_images[(dataset_offset + i) % len(dataset_images)]
                for i in range(take_count)
            ]
            user_images.extend(selected)
    
    return user_images


# Selezione basata su gruppo di utenti
if "immagini" not in st.session_state:
    st.session_state.immagini = get_user_images(user_id)
    st.session_state.indice = 0
    st.session_state.valutazioni = []
    st.session_state.mostra_riepilogo = False

indice = st.session_state.indice
imgs = st.session_state.immagini

if indice < len(imgs):
    curr_entry = imgs[indice]
    img_file = curr_entry["img_obj"]
    folder_name = curr_entry["folder_name"]

    # Usa la funzione cache per scaricare i bytes (solo la prima volta per id)
    file_id = img_file['id']
    try:
        img_bytes = get_image_bytes_by_id(file_id)
        image = Image.open(io.BytesIO(img_bytes))
    except Exception as e:
        st.error(f"Errore nel download dell'immagine: {e}")
        image = None

    col1, col2 = st.columns([2, 1])
    with col2:
        st.markdown("### Linee guida qualità")
        st.markdown(linee_guida)
    
    with col1:
        if image is not None:
            st.image(image, width='stretch')
        st.markdown(f"<b>Dataset:</b> {folder_name}", unsafe_allow_html=True)  # Mostra il nome del dataset
        score = st.slider("Score di qualità (1 = pessima, 10 = ottima)", 1, 10, 5, key=f"score_{indice}")
        
        col_btn1, col_btn2, col_btn3 = st.columns(3)
        with col_btn1:
            if st.button("⬅️ Indietro"):
                if indice > 0:
                    # Rimuovi l'ultima valutazione per poter ricominciare da quella precedente
                    if st.session_state.valutazioni:
                        st.session_state.valutazioni.pop()
                    st.session_state.indice -= 1
                    st.rerun()
        
        with col_btn2:
            if st.button("Salva voto per questa immagine"):
                st.session_state.valutazioni.append({
                    "id_utente": user_id,
                    "nome_immagine": img_file['title'],
                    "score": score,
                    "dataset": folder_name,    # aggiunge anche il nome del dataset al record
                    "timestamp": _now_rome_str()
                })
                st.session_state.indice += 1
                st.rerun()  # Necessario per passare subito all'immagine successiva
        
        with col_btn3:
            if st.button("📋 Vedere Riepilogo"):
                st.session_state.mostra_riepilogo = not st.session_state.mostra_riepilogo
                st.rerun()
    
    st.markdown(f"<center><small>{indice} / {len(imgs)} immagini valutate</small></center>", unsafe_allow_html=True)
    
    # ✅ SEZIONE MODALE RIEPILOGO: mostra come popup elegante con st.container
    if st.session_state.mostra_riepilogo and len(st.session_state.valutazioni) > 0:
        # Contenitore modale con stile CSS
        modal_container = st.container()
        
        with modal_container:
            # Stile modale con bordo e sfondo + nascondere controlli immagine
            st.markdown("""
            <style>
            .riepilogo-modal-box {
                border: 2px solid #1f77b4;
                border-radius: 10px;
                padding: 20px;
                background-color: #f8f9fa;
                margin-top: 20px;
            }
            .riepilogo-modal-header-box {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                border-bottom: 2px solid #1f77b4;
                padding-bottom: 15px;
            }
            .riepilogo-modal-title {
                color: #1f77b4;
                font-size: 24px;
                font-weight: bold;
                margin: 0;
            }
            /* Nascondi i controlli di Streamlit sulle immagini */
            button[title="View fullscreen"] {
                display: none !important;
            }
            </style>
            """, unsafe_allow_html=True)
            
            # Intestazione con titolo e bottone chiudi
            col_title, col_close_btn = st.columns([10, 1])
            with col_title:
                st.markdown("<h3 style='color: #1f77b4; margin: 0;'>📸 Riepilogo Valutazioni</h3>", unsafe_allow_html=True)
            with col_close_btn:
                if st.button("✕", key="close_riepilogo", help="Chiudi riepilogo"):
                    st.session_state.mostra_riepilogo = False
                    st.rerun()
            
            st.divider()
            
            # Contenuto: griglia di immagini
            valutazioni = st.session_state.valutazioni
            cols_per_row = 3  # quante immagini per riga
            
            for i in range(0, len(valutazioni), cols_per_row):
                row_cols = st.columns(cols_per_row)
                for j, col in enumerate(row_cols):
                    if i + j < len(valutazioni):
                        val = valutazioni[i + j]
                        img_file_id = None
                        
                        # Trova l'id dell'immagine dalla lista imgs
                        for img_entry in imgs:
                            if img_entry["img_obj"]["title"] == val["nome_immagine"]:
                                img_file_id = img_entry["img_obj"]["id"]
                                break
                        
                        with col:
                            # Contenitore per ogni card immagine
                            st.markdown("<div style='border: 1px solid #e0e0e0; border-radius: 8px; padding: 10px;'>", unsafe_allow_html=True)
                            
                            # Scarica e mostra l'anteprima
                            if img_file_id:
                                try:
                                    img_bytes = get_image_bytes_by_id(img_file_id)
                                    preview_img = Image.open(io.BytesIO(img_bytes))
                                    st.image(preview_img, use_container_width=True)
                                except Exception as e:
                                    st.warning(f"Impossibile caricare")
                            
                            # Mostra il nome e lo score
                            st.markdown(f"<small><b>{val['nome_immagine']}</b></small>", unsafe_allow_html=True)
                            st.markdown(f"<div style='text-align:center; font-size:20px; font-weight:bold; color:#4CAF50; margin: 10px 0;'>Score: {val['score']}/10</div>", unsafe_allow_html=True)
                            st.caption(f"Dataset: {val['dataset']}")
                            
                            st.markdown("</div>", unsafe_allow_html=True)
    
    # Prefetch della prossima immagine in background (non blocca la UI)
    next_idx = indice + 1
    if next_idx < len(imgs):
        try:
            next_id = imgs[next_idx]['img_obj']['id']
            # l'invocazione a get_image_bytes_by_id salverà in cache i bytes
            threading.Thread(target=get_image_bytes_by_id, args=(next_id,), daemon=True).start()
        except Exception:
            pass
else:
    st.success("Hai completato tutte le valutazioni!")
    df = pd.DataFrame(st.session_state.valutazioni)
    st.dataframe(df)
    
    # ✅ OTTIMIZZAZIONE 3: Salvataggio con retry e gestione errori graceful
    if "salvato" not in st.session_state:
        st.session_state.salvato = False
    
    if not st.session_state.salvato:
        with st.spinner("Salvataggio risultati..."):
            try:
                conn = st.connection("gsheets", type=GSheetsConnection)
                # ✅ FIX: Usa append invece di update per aggiungere righe senza sovrascrivere
                # Questo preserva i dati degli utenti precedenti
                existing_data = conn.read(worksheet="Foglio1")
                
                # Se il foglio è vuoto, scrivi anche l'header
                if existing_data.empty:
                    conn.update(worksheet="Foglio1", data=df)
                else:
                    # Altrimenti aggiungi solo le nuove righe
                    new_data = pd.concat([existing_data, df], ignore_index=True)
                    conn.update(worksheet="Foglio1", data=new_data)
                
                st.session_state.salvato = True
                st.success("✅ Risultati salvati con successo!")
            except Exception as e:
                st.error(f"⚠️ Errore durante il salvataggio: {e}")
                st.info("Puoi scaricare i risultati localmente usando il bottone qui sotto.")
                # Offri download CSV come fallback
                csv = df.to_csv(index=False)
                st.download_button(
                    label="📥 Scarica risultati (CSV)",
                    data=csv,
                    file_name=f"valutazioni_{user_id}_{_now_rome_str().replace(' ', '_').replace(':', '-')}.csv",
                    mime="text/csv"
                )
    else:
        st.success("✅ Risultati già salvati!")