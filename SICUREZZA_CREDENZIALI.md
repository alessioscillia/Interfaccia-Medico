# 🔒 Guida Sicurezza Credenziali - Quick Reference

## ✅ STATO ATTUALE: SICURO ✓

Il tuo setup è configurato correttamente! Le credenziali sono protette.

---

## 📋 Verifiche Eseguite

✅ **`.gitignore` configurato** - I file sensibili sono esclusi da Git  
✅ **Credenziali NON tracciate** - Git non tiene traccia dei file sensibili  
✅ **File esistono e sono validi** - service-account.json è presente e corretto  
✅ **Service Account attivo**: `streamlit-access@streamlit-sheets-460712.iam.gserviceaccount.com`

---

## 🚨 CONTROLLI DA FARE PRIMA DI OGNI PUSH

Prima di fare `git push`, **SEMPRE** esegui:

```powershell
# 1. Verifica lo status
git status

# 2. Verifica cosa stai per committare
git diff --cached

# 3. Esegui lo script di sicurezza
python verifica_sicurezza.py
```

### ⚠️ NON fare push se vedi:
- `service-account.json` in rosso o verde
- `secrets.toml` in rosso o verde
- File `.json` che non conosci

---

## 🔍 Comandi Utili di Verifica

### Verificare file tracciati
```powershell
git ls-files | Select-String "json|secret|credential"
```

### Verificare staged files
```powershell
git diff --cached --name-only
```

### Verificare storia completa (cerca "leak")
```powershell
git log --all --full-history -- service-account.json
```

### Se hai committato per errore le credenziali:
```powershell
# 1. Rimuovi dal tracking (NON cancella il file locale)
git rm --cached service-account.json

# 2. Commit della rimozione
git commit -m "Remove sensitive file from tracking"

# 3. IMPORTANTE: Rigenera le credenziali su Google Cloud!
# Perché? La storia di Git potrebbe ancora contenere le vecchie credenziali
```

---

## 🛡️ Best Practices

### ✅ DA FARE:
- ✓ Esegui `python verifica_sicurezza.py` regolarmente
- ✓ Controlla `git status` prima di ogni commit
- ✓ Mantieni `.gitignore` aggiornato
- ✓ Usa Streamlit Secrets per il deploy su Cloud
- ✓ Rigenera le credenziali se sospetti una compromissione

### ❌ NON FARE:
- ✗ Non copiare service-account.json in altre cartelle sincronizzate
- ✗ Non inviare il file via email/chat non criptate
- ✗ Non committare file con nomi diversi ma stesso contenuto
- ✗ Non condividere screenshot del file JSON
- ✗ Non caricare il file su servizi di storage pubblici

---

## 🚨 COSA FARE SE HAI ESPOSTO LE CREDENZIALI

### Se hai fatto push delle credenziali su GitHub:

1. **RIGENERA IMMEDIATAMENTE le credenziali**:
   - Vai su [Google Cloud Console](https://console.cloud.google.com/)
   - Vai a **IAM & Admin** → **Service Accounts**
   - Trova il tuo service account
   - Vai su **Keys** → Elimina la chiave compromessa
   - Crea una nuova chiave JSON

2. **Rimuovi il file dalla storia di Git**:
   ```powershell
   # Installa BFG Repo Cleaner
   # Scarica da: https://rtyley.github.io/bfg-repo-cleaner/
   
   # Usa BFG per rimuovere il file
   java -jar bfg.jar --delete-files service-account.json
   git reflog expire --expire=now --all
   git gc --prune=now --aggressive
   
   # Force push (ATTENZIONE: coordina con il team)
   git push --force
   ```

3. **Notifica il team** (se applicabile)

4. **Aggiorna le credenziali**:
   - Sostituisci il file locale con quello nuovo
   - Aggiorna Streamlit Secrets se usi Streamlit Cloud
   - Testa che l'app funzioni con le nuove credenziali

---

## 🌐 Sicurezza su OneDrive

⚠️ **ATTENZIONE**: Il tuo progetto è in una cartella OneDrive sincronizzata!

**Verifica**:
1. La cartella OneDrive è **privata** (non condivisa con nessuno)
2. Il file `service-account.json` **NON è in una sottocartella condivisa**
3. OneDrive Backup non sta facendo backup del file in cloud pubblico

**Per verificare**:
- Tasto destro su `service-account.json` → Proprietà
- Controlla che NON ci sia l'icona "Condiviso" di OneDrive
- Se è condiviso, interrompi la condivisione IMMEDIATAMENTE

---

## 📞 Contatti Utili

- **Google Cloud Support**: https://cloud.google.com/support
- **GitHub Security**: https://docs.github.com/en/code-security
- **Streamlit Secrets**: https://docs.streamlit.io/streamlit-community-cloud/get-started/deploy-an-app/connect-to-data-sources/secrets-management

---

## 🎯 Script Rapido di Verifica

Esegui questo prima di ogni sessione di lavoro:

```powershell
# Vai nella directory del progetto
cd C:\Users\gianc\OneDrive\Desktop\Interfaccia-Medico

# Esegui verifica sicurezza
python verifica_sicurezza.py

# Controlla Git status
git status

# Se tutto OK, procedi con il tuo lavoro
```

---

## 📝 Checklist Settimanale

- [ ] Eseguito `python verifica_sicurezza.py`
- [ ] Verificato che service-account.json non sia condiviso
- [ ] Controllato accessi al Service Account su Google Cloud
- [ ] Verificato log di accesso su Google Drive (se disponibili)
- [ ] Confermato che .gitignore sia committato e pushato

---

**Data ultimo controllo**: 12 Novembre 2025  
**Service Account**: streamlit-access@streamlit-sheets-460712.iam.gserviceaccount.com  
**Stato**: ✅ SICURO
