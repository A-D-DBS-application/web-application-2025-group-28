# Supabase Storage Setup Instructies

## Stap 1: Buckets aanmaken in Supabase

1. Ga naar je Supabase Dashboard: https://supabase.com/dashboard
2. Selecteer je project
3. Ga naar **Storage** in het linker menu
4. Klik op **"New bucket"** en maak de volgende buckets aan:

### Buckets die je moet aanmaken:

1. **`docs`** 
   - Public: ✅ Ja (of Nee, afhankelijk van je security requirements)
   - Beschrijving: Documenten zoals handleidingen, facturen, etc.

2. **`safety`**
   - Public: ✅ Ja (veiligheidsfiches moeten toegankelijk zijn)
   - Beschrijving: Veiligheidsfiches en veiligheidscertificaten

3. **`projects`**
   - Public: ✅ Ja (werf afbeeldingen moeten zichtbaar zijn)
   - Beschrijving: Afbeeldingen van werven/projecten

4. **`certificates`**
   - Public: ❌ Nee (keuring certificaten zijn privé)
   - Beschrijving: Keuring certificaten

5. **`type-images`**
   - Public: ✅ Ja (materiaal type afbeeldingen)
   - Beschrijving: Afbeeldingen voor materiaal types

### Bucket Policies (RLS - Row Level Security)

Voor **publieke buckets** (docs, safety, projects, type-images):
- Maak een policy aan die **SELECT** toestaat voor **anon** gebruikers
- Dit zorgt ervoor dat bestanden publiek toegankelijk zijn via URLs

Voor **privé buckets** (certificates):
- Maak een policy aan die alleen **authenticated** gebruikers toestaat
- Of gebruik service role key voor server-side toegang

## Stap 2: Supabase Credentials configureren

1. Ga naar **Settings** > **API** in je Supabase Dashboard
2. Kopieer de volgende waarden:

### In `app/config.py`:

```python
SUPABASE_URL = 'https://[jouw-project-ref].supabase.co'  # Project URL
SUPABASE_SERVICE_KEY = 'eyJ...'  # service_role key (NIET de anon key!)
```

**Belangrijk:** 
- Gebruik de **service_role** key, niet de **anon** key
- De service_role key heeft volledige toegang en mag alleen server-side gebruikt worden
- Deel deze key NOOIT in client-side code!

## Stap 3: Dependencies installeren

```bash
pip install supabase
```

Of als je requirements.txt gebruikt:
```bash
pip install -r requirements.txt
```

## Stap 4: Testen

1. Start je Flask applicatie
2. Probeer een bestand te uploaden (bijv. een document of werf afbeelding)
3. Controleer in Supabase Storage of het bestand is geüpload
4. Controleer of het bestand zichtbaar is in de applicatie

## Stap 5: Bestaande bestanden migreren (optioneel)

Als je bestaande bestanden hebt in `static/uploads/`, kun je deze migreren naar Supabase Storage met het volgende script:

```python
# migrate_files.py (maak dit bestand aan)
from app import app, supabase_client
import os
from pathlib import Path

def migrate_existing_files():
    with app.app_context():
        base_folder = os.path.join(app.root_path, "static", "uploads")
        
        folder_mapping = {
            "docs": "docs",
            "safety": "safety",
            "projects": "projects",
            "certificates": "certificates",
            "type_images": "type-images"
        }
        
        for local_folder, bucket_name in folder_mapping.items():
            local_path = os.path.join(base_folder, local_folder)
            if not os.path.exists(local_path):
                continue
                
            for filename in os.listdir(local_path):
                file_path = os.path.join(local_path, filename)
                if os.path.isfile(file_path):
                    try:
                        with open(file_path, 'rb') as f:
                            supabase_client.storage.from_(bucket_name).upload(
                                path=filename,
                                file=f.read(),
                                file_options={"upsert": "true"}
                            )
                        print(f"✓ Migrated: {filename} to {bucket_name}")
                    except Exception as e:
                        print(f"✗ Error migrating {filename}: {e}")

if __name__ == "__main__":
    migrate_existing_files()
```

## Troubleshooting

### Fout: "Bucket not found"
- Controleer of alle buckets correct zijn aangemaakt in Supabase Dashboard
- Controleer of de bucket namen exact overeenkomen (case-sensitive!)

### Fout: "Invalid API key"
- Controleer of je de **service_role** key gebruikt, niet de anon key
- Controleer of de key correct is gekopieerd (geen extra spaties)

### Bestanden zijn niet zichtbaar
- Controleer of de bucket **public** is ingesteld (voor publieke bestanden)
- Controleer of de RLS policies correct zijn ingesteld
- Controleer of het bestandspad correct is opgeslagen in de database

### Fallback naar lokale storage
- Als Supabase niet beschikbaar is, valt de applicatie automatisch terug naar lokale storage
- Controleer de console logs voor error berichten

## Belangrijke opmerkingen

1. **Security**: De service_role key heeft volledige toegang. Bewaar deze veilig en deel deze nooit publiekelijk.

2. **File paths**: Bestanden worden opgeslagen met het pad zoals: `docs/BOOR123_doc_20250101_120000_foto.pdf`
   - Dit pad wordt opgeslagen in de database
   - De URL wordt automatisch gegenereerd wanneer nodig

3. **Backward compatibility**: Oude bestanden die lokaal zijn opgeslagen blijven werken via fallback mechanisme.

4. **Bucket naming**: De bucket namen zijn case-sensitive. Gebruik exact:
   - `docs`
   - `safety`
   - `projects`
   - `certificates`
   - `type-images` (met streepje, niet underscore!)

