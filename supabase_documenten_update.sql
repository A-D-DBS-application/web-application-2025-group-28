-- ============================================
-- UPDATE: Voeg index toe voor material_type kolom
-- ============================================
-- LET OP: De material_type kolom bestaat al in de database (aangemaakt door iemand anders)
-- Dit script voegt alleen de index toe voor betere performance

-- Voeg index toe voor snelle queries op materiaal type
CREATE INDEX IF NOT EXISTS idx_documenten_material_type 
ON public.documenten(material_type);

-- Optioneel: Update bestaande Veiligheidsfiche documenten
-- (Als je al documenten hebt, kun je deze query aanpassen)
-- UPDATE public.documenten 
-- SET material_type = 'Onbekend' 
-- WHERE document_type = 'Veiligheidsfiche' AND material_type IS NULL;

