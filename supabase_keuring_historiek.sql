-- ============================================
-- KEURING HISTORIEK TABEL
-- ============================================
-- Deze tabel slaat alle uitgevoerde keuringen op voor historiek
-- Elke keer dat een keuring wordt uitgevoerd, wordt hier een record aangemaakt

CREATE TABLE IF NOT EXISTS public.keuring_historiek (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  
  -- Link naar materiaal
  material_id bigint NOT NULL,
  serienummer text NOT NULL,
  
  -- Keuring details
  keuring_datum date NOT NULL,              -- Wanneer keuring is uitgevoerd
  resultaat text NOT NULL,                  -- 'goedgekeurd', 'afgekeurd', 'voorwaardelijk'
  uitgevoerd_door text NOT NULL,            -- Wie heeft de keuring gedaan
  opmerkingen text,                         -- Extra notities
  
  -- Volgende keuring info (op moment van deze keuring)
  volgende_keuring_datum date,              -- Wanneer moet volgende keuring
  
  -- Documenten (optioneel)
  certificaat_path text,                    -- Pad naar certificaat PDF/foto
  
  CONSTRAINT keuring_historiek_pkey PRIMARY KEY (id),
  CONSTRAINT keuring_historiek_material_id_fkey FOREIGN KEY (material_id) 
    REFERENCES public.materials(id) ON DELETE CASCADE
);

-- Index voor snelle queries op serienummer
CREATE INDEX IF NOT EXISTS idx_keuring_historiek_serienummer 
  ON public.keuring_historiek(serienummer);

-- Index voor snelle queries op materiaal
CREATE INDEX IF NOT EXISTS idx_keuring_historiek_material_id 
  ON public.keuring_historiek(material_id);

-- Index voor snelle queries op datum
CREATE INDEX IF NOT EXISTS idx_keuring_historiek_keuring_datum 
  ON public.keuring_historiek(keuring_datum DESC);

