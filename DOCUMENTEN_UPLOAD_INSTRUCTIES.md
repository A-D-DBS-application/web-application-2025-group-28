# Documenten Upload Functie - Implementatie Instructies

Dit document beschrijft de stappen die nodig zijn om de nieuwe documenten upload functie te activeren.

## 📋 Overzicht

De nieuwe functie maakt het mogelijk om documenten te uploaden via de documenten pagina met de volgende types (alle met hoofdletter):
- **Aankoopfactuur** (moet gekoppeld worden aan materiaal)
- **Keuringstatus** (moet gekoppeld worden aan materiaal)
- **Verkoopfactuur** (moet gekoppeld worden aan materiaal)
- **Veiligheidsfiche** (NIET gekoppeld aan materiaal)

## 🔧 Stappen voor Supabase

### Stap 1: Nieuwe tabel aanmaken

1. Ga naar je Supabase project dashboard
2. Navigeer naar **SQL Editor** (in het linker menu)
3. Open het bestand `supabase_documenten.sql` uit deze repository
4. Kopieer de volledige SQL code
5. Plak de code in de SQL Editor
6. Klik op **Run** om de tabel aan te maken

De tabel `documenten` wordt nu aangemaakt met de volgende kolommen:
- `id` (bigint, primary key)
- `created_at` (timestamp)
- `document_type` (text) - type document ('Aankoopfactuur', 'Keuringstatus', 'Verkoopfactuur', 'Veiligheidsfiche')
- `file_path` (text) - pad naar bestand
- `file_name` (text) - originele bestandsnaam
- `file_size` (bigint) - bestandsgrootte in bytes
- `material_id` (bigint, nullable) - link naar materiaal
- `uploaded_by` (text) - naam van gebruiker
- `user_id` (bigint, nullable) - ID van gebruiker
- `note` (text, nullable) - optionele opmerkingen

### Stap 2: Verificatie

Controleer of de tabel correct is aangemaakt:
1. Ga naar **Table Editor** in Supabase
2. Je zou de nieuwe tabel `documenten` moeten zien
3. Controleer of alle kolommen aanwezig zijn

## 💻 Stappen voor VSCode (Code)

### Stap 1: Code is al aangepast

De volgende bestanden zijn al aangepast:
- ✅ `app/models.py` - Document model toegevoegd
- ✅ `app/app.py` - Upload route en documenten route aangepast
- ✅ `app/templates/documenten.html` - Upload formulier toegevoegd

### Stap 2: Dependencies controleren

Zorg ervoor dat alle dependencies geïnstalleerd zijn:
```bash
pip install -r requirements.txt
```

### Stap 3: Applicatie starten

Start de Flask applicatie:
```bash
python app/app.py
```

## 🎯 Functionaliteit

### Document uploaden

1. Ga naar de **Documenten** pagina
2. Klik op de knop **➕ Document toevoegen**
3. Selecteer een bestand (PDF, JPG, PNG, DOC, DOCX)
4. Kies het document type:
   - **Aankoopfactuur** → Selecteer materiaal (verplicht)
   - **Keuringstatus** → Selecteer materiaal (verplicht)
   - **Verkoopfactuur** → Selecteer materiaal (verplicht)
   - **Veiligheidsfiche** → Geen materiaal selectie nodig
5. Optioneel: voeg een opmerking toe
6. Klik op **Uploaden**

### Documenten bekijken

- Alle geüploade documenten worden getoond in de documenten tabel
- Je kunt filteren op document type
- Je kunt zoeken op document naam of materiaal naam
- Documenten kunnen worden gedownload via de download knop

## 📁 Bestandsopslag

Documenten worden opgeslagen in:
```
app/static/uploads/docs/
```

De bestandsnamen worden automatisch gegenereerd met:
- Document type
- Timestamp
- Originele bestandsnaam

Voorbeeld: `aankoopfactuur_20251207_163045_factuur.pdf`

## 🔗 Database relaties

- **Document → Material**: Als document type niet "veiligheidsfiche" is, wordt het gekoppeld aan een materiaal
- **Document → Gebruiker**: Elke upload wordt gekoppeld aan de ingelogde gebruiker
- **Material → Document**: Een materiaal kan meerdere documenten hebben

## ⚠️ Belangrijke opmerkingen

1. **Veiligheidsfiche**: Documenten van type "Veiligheidsfiche" worden NIET gekoppeld aan materiaal (material_id = NULL)
2. **Andere types**: Alle andere document types MOETEN gekoppeld worden aan een materiaal
3. **Bestandsgrootte**: De bestandsgrootte wordt automatisch berekend en opgeslagen
4. **Backward compatibility**: Oude documenten (van materials.documentation_path en materials.safety_sheet_path) worden nog steeds getoond

## 🐛 Troubleshooting

### Tabel bestaat niet
- Controleer of de SQL query correct is uitgevoerd in Supabase
- Controleer of je in de juiste database/schema werkt

### Upload werkt niet
- Controleer of de folder `app/static/uploads/docs/` bestaat
- Controleer of de applicatie schrijfrechten heeft op deze folder
- Controleer de Flask logs voor error berichten

### Documenten worden niet getoond
- Controleer of de documenten correct zijn opgeslagen in de database
- Controleer of de file_path correct is (relatief pad vanaf static folder)

## 📝 Code wijzigingen samenvatting

### Nieuwe bestanden:
- `supabase_documenten.sql` - SQL script voor nieuwe tabel

### Aangepaste bestanden:
- `app/models.py` - Document model toegevoegd
- `app/app.py` - Document import, upload route, documenten route aangepast
- `app/templates/documenten.html` - Upload modal en formulier toegevoegd

### Nieuwe routes:
- `POST /documenten/upload` - Upload een nieuw document

### Nieuwe model:
- `Document` - Model voor documenten tabel

