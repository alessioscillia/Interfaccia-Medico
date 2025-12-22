# Interfaccia Medico

App Streamlit per la valutazione della qualita' di immagini colonscopiche.

## Funzionalita'
- Assegna a ogni utente un batch di immagini da Google Drive (folder `DATA_DEVELOPMENT_FOLDER_ID`).
- Mostra linee guida e immagini di riferimento high/low quality.
- Permette di dare uno score 1-10 e salva i risultati su Google Sheets (worksheet `Results`).
- Gestisce i batch di immagini tramite Google Sheets (worksheet `Batches`), creando nuovi batch se necessario.
- Usa cache Streamlit per Drive e immagini per ridurre le latenze.

## Prerequisiti
- Python 3.10+ (consigliato) e dipendenze in [requirements.txt](requirements.txt).
- Credenziali Google service account con accesso a Drive/Sheets.
- File `secrets.toml` in `.streamlit/` con:

## Avvio locale
1. Crea venv e installa dipendenze: `pip install -r requirements.txt`.
2. Posiziona il JSON del service account in locale oppure usa `st.secrets`.
3. Esegui: `streamlit run main.py`.

## Note utili
- I worksheet `Batches` e `Results` devono esistere; se vuoti, l'app li inizializza con le colonne richieste.
- Le immagini di riferimento vengono cercate in Drive per i file `EndoCV2021_001164.jpg` e `C3_EndoCV2021_00153.jpg`.
