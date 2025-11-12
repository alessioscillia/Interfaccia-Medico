# 🔐 Guida Setup Service Account per Google Drive

Questa guida ti aiuterà a configurare l'applicazione per usare un Service Account di Google, eliminando la necessità di autenticazione per ogni utente.

## 📝 Passo 1: Crea il Service Account

1. Vai su [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un nuovo progetto o seleziona uno esistente
3. Nel menu laterale, vai su **APIs & Services** → **Credentials**
4. Clicca **Create Credentials** → **Service Account**
5. Inserisci un nome (es: "streamlit-app-viewer")
6. Clicca **Create and Continue**
7. Salta i permessi opzionali (clicca **Continue** e poi **Done**)

## 🔑 Passo 2: Scarica le Credenziali

1. Nella pagina **Credentials**, clicca sul service account appena creato
2. Vai sulla tab **Keys**
3. Clicca **Add Key** → **Create new key**
4. Seleziona **JSON** e clicca **Create**
5. Il file JSON verrà scaricato automaticamente
6. **IMPORTANTE**: Rinomina il file in `service-account.json` e mettilo nella stessa cartella di `main.py`

## 🔌 Passo 3: Abilita le API

1. Nella Google Cloud Console, vai su **APIs & Services** → **Library**
2. Cerca **"Google Drive API"** e cliccala
3. Clicca **Enable**
4. Torna alla **Library** e cerca **"Google Sheets API"**
5. Clicca **Enable**

## 🤝 Passo 4: Condividi le Risorse

### A. Condividi la cartella Google Drive

1. Apri il file `service-account.json` che hai scaricato
2. Copia l'indirizzo email nel campo `client_email` (sarà qualcosa come `nome@progetto.iam.gserviceaccount.com`)
3. Vai su Google Drive e trova la cartella **"Articolo Polyps"** (ID: `1He7eQCE2xI5X8n00A-B-eKEBZjNIw9cJ`)
4. Tasto destro sulla cartella → **Condividi**
5. Incolla l'email del service account
6. Imposta i permessi su **Visualizzatore** (lettura)
7. **IMPORTANTE**: Deseleziona "Invia notifica" se presente
8. Clicca **Condividi**

### B. Condividi il Google Sheet

1. Apri il tuo Google Sheet con i risultati
2. Clicca **Condividi** in alto a destra
3. Incolla la stessa email del service account
4. Imposta i permessi su **Editor** (scrittura necessaria per salvare i risultati)
5. **IMPORTANTE**: Deseleziona "Invia notifica" se presente
6. Clicca **Condividi**

## 🚀 Passo 5: Testa l'Applicazione

1. Assicurati che il file `service-account.json` sia nella stessa cartella di `main.py`
2. Esegui l'applicazione:
   ```bash
   streamlit run main.py
   ```
3. L'app dovrebbe caricarsi senza richiedere autenticazione!

## ☁️ Deploy su Streamlit Cloud

Per il deployment su Streamlit Cloud, NON caricare `service-account.json` su GitHub!

### Configurazione Secrets su Streamlit Cloud:

1. Vai su [share.streamlit.io](https://share.streamlit.io)
2. Apri la tua app deployata
3. Vai su **Settings** → **Secrets**
4. Apri il file `service-account.json` locale con un editor di testo
5. Copia tutto il contenuto JSON
6. Nel campo Secrets, incolla nel seguente formato:

```toml
[gcp_service_account]
type = "service_account"
project_id = "TUO_PROJECT_ID"
private_key_id = "TUA_PRIVATE_KEY_ID"
private_key = "-----BEGIN PRIVATE KEY-----\nTUA_CHIAVE_PRIVATA_QUI\n-----END PRIVATE KEY-----\n"
client_email = "tua-email@progetto.iam.gserviceaccount.com"
client_id = "TUO_CLIENT_ID"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/tua-email%40progetto.iam.gserviceaccount.com"
universe_domain = "googleapis.com"
```

**IMPORTANTE**: 
- Sostituisci tutti i valori con quelli dal tuo `service-account.json`
- La `private_key` deve includere `\n` per le interruzioni di riga
- Salva i secrets e riavvia l'app

## 🔒 Sicurezza

⚠️ **NON condividere mai il file `service-account.json` pubblicamente!**

- Non caricarlo su GitHub
- Non inviarlo via email non criptata
- Non condividerlo in chat pubbliche

Se il file viene compromesso:
1. Vai su Google Cloud Console → Service Accounts
2. Elimina la chiave compromessa
3. Crea una nuova chiave
4. Aggiorna il file e i secrets

## ✅ Checklist Finale

- [ ] Service Account creato
- [ ] File `service-account.json` scaricato e rinominato
- [ ] Google Drive API abilitata
- [ ] Google Sheets API abilitata
- [ ] Cartella Drive condivisa con il service account (permessi Visualizzatore)
- [ ] Google Sheet condiviso con il service account (permessi Editor)
- [ ] App testata localmente senza errori
- [ ] (Opzionale) Secrets configurati su Streamlit Cloud

## 🆘 Risoluzione Problemi

### Errore: "File delle credenziali non trovato"
- Verifica che `service-account.json` sia nella stessa cartella di `main.py`
- Verifica che il nome del file sia esattamente `service-account.json`

### Errore: "Access denied" o "Permission denied"
- Verifica di aver condiviso sia la cartella Drive che il Google Sheet
- Verifica che l'email del service account sia corretta
- Verifica che le API siano abilitate

### L'app non carica le immagini
- Verifica che l'ID della cartella nel codice sia corretto: `1He7eQCE2xI5X8n00A-B-eKEBZjNIw9cJ`
- Verifica che il service account abbia accesso a quella cartella

### Errore su Streamlit Cloud
- Verifica che i secrets siano formattati correttamente
- Verifica che la `private_key` contenga `\n` per le interruzioni di riga
- Riavvia l'app dopo aver salvato i secrets
