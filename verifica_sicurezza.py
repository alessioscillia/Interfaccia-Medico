#!/usr/bin/env python3
"""
Script di verifica sicurezza credenziali Google Service Account

Questo script verifica che:
1. Il file .gitignore contenga le protezioni necessarie
2. Le credenziali non siano tracciate da Git
3. I file sensibili esistano ma non siano committabili
4. Le credenziali siano valide (opzionale)
"""

import os
import subprocess
import json
from pathlib import Path

# Colori per output console
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text:^60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")

def print_success(text):
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠ {text}{Colors.END}")

def print_error(text):
    print(f"{Colors.RED}✗ {text}{Colors.END}")

def check_gitignore():
    """Verifica che .gitignore contenga le protezioni necessarie"""
    print_header("VERIFICA .gitignore")
    
    gitignore_path = Path(".gitignore")
    
    if not gitignore_path.exists():
        print_error(".gitignore non trovato!")
        print_warning("Crea un file .gitignore nella root del progetto")
        return False
    
    with open(gitignore_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    required_patterns = [
        'service-account.json',
        'service_account.json',
        '.streamlit/secrets.toml',
        'temp_service_account.json'
    ]
    
    all_present = True
    for pattern in required_patterns:
        if pattern in content:
            print_success(f"Pattern '{pattern}' presente")
        else:
            print_error(f"Pattern '{pattern}' MANCANTE!")
            all_present = False
    
    return all_present

def check_git_status():
    """Verifica che i file sensibili non siano tracciati da Git"""
    print_header("VERIFICA GIT STATUS")
    
    sensitive_files = [
        'service-account.json',
        'service_account.json',
        'temp_service_account.json',
        '.streamlit/secrets.toml'
    ]
    
    try:
        # Controlla se siamo in un repository Git
        result = subprocess.run(
            ['git', 'rev-parse', '--git-dir'],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            print_warning("Non sei in un repository Git")
            print_warning("Se vuoi usare Git, esegui: git init")
            return True
        
        # Controlla i file tracciati
        result = subprocess.run(
            ['git', 'ls-files'],
            capture_output=True,
            text=True,
            check=True
        )
        
        tracked_files = result.stdout.strip().split('\n')
        
        issues_found = False
        for sensitive_file in sensitive_files:
            if sensitive_file in tracked_files:
                print_error(f"ATTENZIONE! '{sensitive_file}' è tracciato da Git!")
                print_warning(f"  Rimuovilo con: git rm --cached {sensitive_file}")
                issues_found = True
            else:
                if Path(sensitive_file).exists():
                    print_success(f"'{sensitive_file}' esiste ma NON è tracciato ✓")
        
        # Controlla staged files
        result = subprocess.run(
            ['git', 'diff', '--cached', '--name-only'],
            capture_output=True,
            text=True,
            check=True
        )
        
        staged_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
        
        for sensitive_file in sensitive_files:
            if sensitive_file in staged_files:
                print_error(f"ATTENZIONE! '{sensitive_file}' è in staging!")
                print_warning(f"  Rimuovilo con: git reset HEAD {sensitive_file}")
                issues_found = True
        
        return not issues_found
        
    except FileNotFoundError:
        print_warning("Git non installato o non nel PATH")
        return True
    except Exception as e:
        print_error(f"Errore durante verifica Git: {e}")
        return False

def check_credentials_exist():
    """Verifica che i file delle credenziali esistano"""
    print_header("VERIFICA ESISTENZA CREDENZIALI")
    
    service_account_file = Path("service-account.json")
    secrets_file = Path(".streamlit/secrets.toml")
    
    has_credentials = False
    
    if service_account_file.exists():
        print_success(f"File '{service_account_file}' trovato")
        has_credentials = True
        
        # Verifica che sia un JSON valido
        try:
            with open(service_account_file, 'r') as f:
                data = json.load(f)
                
            required_keys = ['type', 'project_id', 'private_key', 'client_email']
            missing_keys = [key for key in required_keys if key not in data]
            
            if missing_keys:
                print_error(f"Chiavi mancanti nel JSON: {', '.join(missing_keys)}")
            else:
                print_success("Struttura JSON valida ✓")
                print_success(f"Service Account Email: {data['client_email']}")
                
        except json.JSONDecodeError:
            print_error("Il file non è un JSON valido!")
        except Exception as e:
            print_error(f"Errore lettura file: {e}")
    else:
        print_warning(f"File '{service_account_file}' NON trovato")
    
    if secrets_file.exists():
        print_success(f"File '{secrets_file}' trovato")
        has_credentials = True
    else:
        print_warning(f"File '{secrets_file}' NON trovato")
    
    if not has_credentials:
        print_error("Nessun file di credenziali trovato!")
        print_warning("Crea service-account.json seguendo SETUP_SERVICE_ACCOUNT.md")
        return False
    
    return True

def check_file_permissions():
    """Verifica i permessi dei file sensibili (solo su Unix/Linux)"""
    print_header("VERIFICA PERMESSI FILE")
    
    if os.name == 'nt':  # Windows
        print_warning("Sistema Windows rilevato - verifica permessi non disponibile")
        print_warning("Assicurati che il file non sia in una cartella condivisa pubblicamente")
        return True
    
    service_account_file = Path("service-account.json")
    
    if not service_account_file.exists():
        print_warning("File service-account.json non trovato")
        return True
    
    # Su Unix/Linux, verifica che il file non sia leggibile da altri
    stat_info = os.stat(service_account_file)
    mode = stat_info.st_mode
    
    # Verifica che non sia world-readable (altri possono leggere)
    world_readable = bool(mode & 0o004)
    group_readable = bool(mode & 0o040)
    
    if world_readable:
        print_error("Il file è leggibile da TUTTI gli utenti!")
        print_warning(f"Esegui: chmod 600 {service_account_file}")
        return False
    elif group_readable:
        print_warning("Il file è leggibile dal gruppo")
        print_warning(f"Per maggiore sicurezza: chmod 600 {service_account_file}")
    else:
        print_success("Permessi file corretti (solo proprietario) ✓")
    
    return True

def check_github_remote():
    """Verifica se esiste un remote GitHub e avvisa l'utente"""
    print_header("VERIFICA REPOSITORY REMOTO")
    
    try:
        result = subprocess.run(
            ['git', 'remote', '-v'],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            print_warning("Non sei in un repository Git")
            return True
        
        remotes = result.stdout.strip()
        
        if not remotes:
            print_success("Nessun remote configurato")
            print_warning("Se carichi su GitHub, assicurati che .gitignore sia committato PRIMA!")
            return True
        
        print_success("Remote trovati:")
        for line in remotes.split('\n'):
            print(f"  {line}")
        
        print_warning("\n⚠ PROMEMORIA IMPORTANTE:")
        print_warning("  - NON pushare MAI le credenziali su GitHub")
        print_warning("  - Verifica che .gitignore sia committato")
        print_warning("  - Controlla 'git status' prima di ogni push")
        
        return True
        
    except FileNotFoundError:
        return True
    except Exception as e:
        print_error(f"Errore verifica remote: {e}")
        return False

def main():
    print_header("VERIFICA SICUREZZA CREDENZIALI GOOGLE")
    print("Questo script verifica che le tue credenziali siano protette\n")
    
    results = {
        'gitignore': check_gitignore(),
        'git_status': check_git_status(),
        'credentials': check_credentials_exist(),
        'permissions': check_file_permissions(),
        'github': check_github_remote()
    }
    
    print_header("RIEPILOGO")
    
    all_passed = all(results.values())
    
    if all_passed:
        print_success("✓ TUTTE LE VERIFICHE SUPERATE!")
        print_success("Le tue credenziali sono al sicuro 🔒")
    else:
        print_error("✗ ALCUNE VERIFICHE FALLITE")
        print_warning("Correggi i problemi evidenziati sopra")
        
        if not results['git_status']:
            print_warning("\n⚠ AZIONE URGENTE RICHIESTA:")
            print_warning("Le credenziali sono tracciate da Git!")
    
    print("\n" + "="*60 + "\n")
    
    # Checklist finale
    print_header("CHECKLIST SICUREZZA")
    print("□ File .gitignore configurato correttamente")
    print("□ Credenziali NON tracciate da Git")
    print("□ File service-account.json esiste e funziona")
    print("□ Cartella Drive condivisa con service account")
    print("□ Google Sheet condiviso con service account")
    print("□ Mai condiviso il file JSON pubblicamente")
    print("□ File JSON NON in cartelle sincronizzate pubblicamente")
    print("\n")

if __name__ == "__main__":
    main()
