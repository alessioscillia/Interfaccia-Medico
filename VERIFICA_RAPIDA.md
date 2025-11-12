# 🔒 VERIFICA SICUREZZA - COMANDI RAPIDI

## ✅ Prima di lavorare
```powershell
python verifica_sicurezza.py
```

## ✅ Prima di fare commit
```powershell
git status
git diff --cached
```

## ✅ Prima di fare push
```powershell
python verifica_sicurezza.py
git log --oneline -5
```

## 🚨 SE TROVI PROBLEMI
Consulta: `SICUREZZA_CREDENZIALI.md`

---

**Ricorda**: NON committare MAI `service-account.json`!
