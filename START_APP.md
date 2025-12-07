# App Starten - Stap voor Stap

## ⚠️ Belangrijk: Eerst Supabase tabel aanmaken!

**VOOR** je de app start, moet je eerst de tabel in Supabase aanmaken:

1. Ga naar je Supabase dashboard
2. Klik op **SQL Editor**
3. Open het bestand `supabase_documenten.sql`
4. Kopieer alle code
5. Plak in SQL Editor en klik **Run**

## 🚀 App Starten in VSCode

### Optie 1: Via Terminal in VSCode

1. **Open Terminal in VSCode:**
   - Druk op `` Ctrl + ` `` (backtick) of
   - Ga naar menu: **Terminal** → **New Terminal**

2. **Zorg dat je in de juiste directory bent:**
   ```bash
   cd /Users/luisbauer/Documents/GitHub/web-application-2025-group-28
   ```

3. **Activeer virtual environment (als je die gebruikt):**
   ```bash
   source .venv/bin/activate
   ```

4. **Start de app:**
   ```bash
   python app/app.py
   ```

### Optie 2: Via Run Button in VSCode

1. Open het bestand `app/app.py`
2. Klik op de **▶️ Run** knop rechtsboven
3. Of druk op `F5` en selecteer "Python: Current File"

## ✅ Controleer of het werkt

Als de app succesvol start, zie je in de terminal:
```
 * Running on http://127.0.0.1:5000
 * Debugger is active!
```

Open dan je browser en ga naar: **http://localhost:5000**

## 🐛 Problemen oplossen

### Error: "relation 'documenten' does not exist"
**Oplossing:** Je moet eerst het SQL script uitvoeren in Supabase (zie boven)

### Error: "Module not found"
**Oplossing:** Installeer dependencies:
```bash
pip install -r requirements.txt
```

### Error: "Port already in use"
**Oplossing:** Stop andere Flask processen of gebruik een andere poort:
```python
app.run(debug=True, port=5001)
```

### App start wel maar geeft errors op documenten pagina
**Oplossing:** Dit is normaal als de tabel nog niet bestaat. Voer het SQL script uit in Supabase.

## 📝 Na het starten

1. Log in op de applicatie
2. Ga naar de **Documenten** pagina
3. Je zou de knop **➕ Document toevoegen** moeten zien
4. Als je een error ziet over de tabel, voer dan eerst het SQL script uit in Supabase

