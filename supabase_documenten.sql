-- ============================================
-- DOCUMENTEN TABEL
-- ============================================
-- Deze tabel slaat alle documenten op die geüpload worden via de documenten pagina
-- Document types: Aankoopfactuur, Keuringstatus, Verkoopfactuur, Veiligheidsfiche
-- Als type = 'Veiligheidsfiche', dan is material_id NULL (niet gelinked aan materiaal)
-- Als type != 'Veiligheidsfiche', dan is material_id verplicht (gelinked aan materiaal)

CREATE TABLE IF NOT EXISTS public.documenten (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  
  -- Document type: 'Aankoopfactuur', 'Keuringstatus', 'Verkoopfactuur', 'Veiligheidsfiche'
  document_type text NOT NULL,
  
  -- Bestand informatie
  file_path text NOT NULL,                    -- Pad naar het geüploade bestand
  file_name text NOT NULL,                    -- Originele bestandsnaam
  file_size bigint,                           -- Bestandsgrootte in bytes (optioneel)
  
  -- Link naar materiaal (NULL als type = 'Veiligheidsfiche')
  material_id bigint,
  
  -- Wie heeft het geüpload
  uploaded_by text,                           -- Naam van de gebruiker
  user_id bigint,                             -- ID van de gebruiker (optioneel)
  
  -- Extra informatie
  note text,                                  -- Optionele opmerkingen
  
  CONSTRAINT documenten_pkey PRIMARY KEY (id),
  CONSTRAINT documenten_material_id_fkey FOREIGN KEY (material_id) 
    REFERENCES public.materials(id) ON DELETE SET NULL,
  CONSTRAINT documenten_user_id_fkey FOREIGN KEY (user_id) 
    REFERENCES public."Gebruiker"(gebruiker_id) ON DELETE SET NULL,
  CONSTRAINT documenten_type_check CHECK (document_type IN ('Aankoopfactuur', 'Keuringstatus', 'Verkoopfactuur', 'Veiligheidsfiche'))
);

-- Index voor snelle queries op document type
CREATE INDEX IF NOT EXISTS idx_documenten_document_type 
  ON public.documenten(document_type);

-- Index voor snelle queries op materiaal
CREATE INDEX IF NOT EXISTS idx_documenten_material_id 
  ON public.documenten(material_id);

-- Index voor snelle queries op upload datum
CREATE INDEX IF NOT EXISTS idx_documenten_created_at 
  ON public.documenten(created_at DESC);

-- Index voor snelle queries op gebruiker
CREATE INDEX IF NOT EXISTS idx_documenten_user_id 
  ON public.documenten(user_id);

