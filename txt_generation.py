import os
import json
import random
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

# --- CONFIGURAZIONE ---
# ID della cartella su Google Drive contenente i dataset di immagini.
ARTICOLO_POLYPS_FOLDER_ID = '1He7eQCE2xI5X8n00A-B-eKEBZjNIw9cJ'
IMAGES_PER_DATASET_PER_BATCH = 3
OUTPUT_DIR = "generated_batches"

def get_drive():
    """
    Autentica e restituisce l'oggetto GoogleDrive.
    Gestisce l'autenticazione tramite file locale (Locale).
    """
    gauth = GoogleAuth()
    service_account_file = "service-account.json"
    if not os.path.exists(service_account_file):
        print("File delle credenziali 'service-account.json' non trovato!")
        exit()
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

def main():
    drive = get_drive()
    
    print(f"Scansione cartella principale: {ARTICOLO_POLYPS_FOLDER_ID}")
    
    # 1. Trova le sottocartelle (Dataset)
    folder_list = drive.ListFile(
        {'q': f"'{ARTICOLO_POLYPS_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"}
    ).GetList()
    
    all_images_by_dataset = {}
    
    # 2. Scarica le liste di immagini per ogni dataset
    for folder in folder_list:
        print(f"Scansione dataset: {folder['title']}...")
        images = drive.ListFile(
            {'q': f"'{folder['id']}' in parents and trashed=false and mimeType contains 'image/'"}
        ).GetList()
        
        # Salviamo solo ID e Titolo
        image_data = [{'id': img['id'], 'title': img['title']} for img in images]
        
        # (Opzionale) Mescola le immagini per casualità, o commenta per ordine alfabetico/temporale
        random.shuffle(image_data)
        
        all_images_by_dataset[folder['title']] = image_data
        print(f"  -> Trovate {len(image_data)} immagini.")

    # 3. Generazione Batch
    # Calcola quanti batch servono (basato sul dataset più numeroso)
    max_images = max(len(imgs) for imgs in all_images_by_dataset.values()) if all_images_by_dataset else 0
    num_batches = (max_images + IMAGES_PER_DATASET_PER_BATCH - 1) // IMAGES_PER_DATASET_PER_BATCH
    
    print(f"\nGenerazione di {num_batches} file batch (da {IMAGES_PER_DATASET_PER_BATCH} immagini per dataset)...")
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    for batch_idx in range(num_batches):
        batch_images = []
        
        start_idx = batch_idx * IMAGES_PER_DATASET_PER_BATCH
        end_idx = start_idx + IMAGES_PER_DATASET_PER_BATCH
        
        for dataset_name, images in all_images_by_dataset.items():
            if not images:
                continue
            
            # Opzione B: Wrap around (ricomincia da capo se finiscono le immagini)
            # Usiamo l'operatore modulo per garantire la ciclicità degli indici
            for i in range(IMAGES_PER_DATASET_PER_BATCH):
                current_img_idx = (start_idx + i) % len(images)
                batch_images.append(images[current_img_idx]['id'])
        
        # Salva su file
        filename = f"batch_{batch_idx + 1:02d}.txt"
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        with open(filepath, "w") as f:
            for img_id in batch_images:
                f.write(f"{img_id}\n")
        
        print(f"  -> Creato {filename} con {len(batch_images)} immagini.")

    print(f"\nFatto! I file sono nella cartella '{OUTPUT_DIR}'.")
    print("Ora devi caricare questi file nella cartella 'Scoring' su Google Drive.")

if __name__ == "__main__":
    main()
