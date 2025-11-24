# Interfaccia-Medico

Applicazione Streamlit per la valutazione della qualità di immagini endoscopiche.

## Descrizione dei File Principali

### `main.py` 
Interfaccia web Streamlit per la valutazione di immagini mediche. Permette agli utenti di visualizzare immagini endoscopiche provenienti da Google Drive, assegnare punteggi di qualità secondo linee guida predefinite (luminosità, nitidezza, colori, artefatti) e salvare i risultati su Google Sheets. Include autenticazione tramite service account e gestione di batch di immagini organizzati per dataset.

### `txt_generation.py`
Script per la generazione automatica di batch di immagini. Scansiona le cartelle Google Drive contenenti i dataset, seleziona casualmente un numero configurabile di immagini per dataset e genera file `.txt` con gli ID delle immagini da valutare. Utile per preparare sessioni di valutazione bilanciate tra diversi dataset.

## Installazione Locale

### Prerequisiti
- Python 3.8+
- pip
