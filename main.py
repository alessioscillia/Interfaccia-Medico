import streamlit as st
from PIL import Image
import threading
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import io

st.set_page_config(layout="wide")
st.markdown("<h2 style='margin-bottom:0;'>Valutazione qualità immagini colonscopiche</h2>", unsafe_allow_html=True)

user_id = st.text_input("👨‍⚕️ Id utente:", key="user_id")
if not user_id:
    st.warning("Inserisci il tuo nome per proseguire.")
    st.stop()


# Autenticazione Google Drive (OAuth)
@st.cache_resource(show_spinner=False)
def get_drive():
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
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

# Recupera tutte le sottocartelle ('Dataset 1', 'Dataset 2', 'Dataset 3')
folder_list = drive.ListFile(
    {'q': f"'{ARTICOLO_POLYPS_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"}
).GetList()

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

all_images_by_dataset = {}
for folder in folder_list:
    images = drive.ListFile(
        {'q': f"'{folder['id']}' in parents and trashed=false and mimeType contains 'image/'"}
    ).GetList()
    all_images_by_dataset[folder['title']] = [
        {
            "img_obj": img,
            "folder_name": folder['title']
        }
        for img in images
    ]

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
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        dati = conn.read(worksheet="Foglio1").fillna("")
        if not dati.empty and "id_utente" in dati.columns:
            unique_users = dati["id_utente"].unique().tolist()
        else:
            unique_users = []
    except Exception:
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
            # Seleziona IMAGES_PER_DATASET immagini da questo dataset (con wrapping se necessario)
            selected = [
                dataset_images[(dataset_offset + i) % len(dataset_images)]
                for i in range(IMAGES_PER_DATASET)
            ]
            user_images.extend(selected)
    
    return user_images


# Selezione basata su gruppo di utenti
if "immagini" not in st.session_state:
    st.session_state.immagini = get_user_images(user_id)
    st.session_state.indice = 0
    st.session_state.valutazioni = []

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
    with col1:
        if image is not None:
            st.image(image, width='stretch')
        st.markdown(f"<b>Dataset:</b> {folder_name}", unsafe_allow_html=True)  # Mostra il nome del dataset
        score = st.slider("Score di qualità (1 = pessima, 10 = ottima)", 1, 10, 5, key=f"score_{indice}")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("⬅️ Indietro"):
                if indice > 0:
                    # Rimuovi l'ultima valutazione per poter ricominciare da quella precedente
                    if st.session_state.valutazioni:
                        st.session_state.valutazioni.pop()
                    st.session_state.indice -= 1
                    st.rerun()
        
        with col_btn2:
            if st.button("Salva voto per questa immagine ➜"):
                st.session_state.valutazioni.append({
                    "id_utente": user_id,
                    "nome_immagine": img_file['title'],
                    "score": score,
                    "dataset": folder_name     # aggiunge anche il nome del dataset al record
                })
                st.session_state.indice += 1
                st.rerun()
    
    with col2:
        st.markdown("### Linee guida qualità")
        st.markdown(linee_guida)
    
    st.markdown(f"<center><small>{indice + 1} / {len(imgs)} immagini valutate</small></center>", unsafe_allow_html=True)
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
    conn = st.connection("gsheets", type=GSheetsConnection)
    dati = conn.read(worksheet="Foglio1").fillna("")
    df_tot = pd.concat([dati, df], ignore_index=True)
    conn.update(worksheet="Foglio1", data=df_tot)
    st.success("Risultati salvati su Google Sheets!")
