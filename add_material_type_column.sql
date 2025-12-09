-- SQL script om material_type kolom toe te voegen aan documenten tabel
-- Voer dit uit in Supabase SQL Editor

ALTER TABLE documenten 
ADD COLUMN IF NOT EXISTS material_type TEXT;

-- Optioneel: voeg comment toe
COMMENT ON COLUMN documenten.material_type IS 'Materiaal type voor Veiligheidsfiche documenten (wanneer material_id NULL is)';

