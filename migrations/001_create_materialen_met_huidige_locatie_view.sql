-- Migration: Create view for materials with current active usage location
-- This view joins materialen with materiaal_gebruik to get the current active usage location
-- Used by the Keuringen page to display correct werf/location

CREATE OR REPLACE VIEW public.materialen_met_huidige_locatie AS
SELECT
  m.*,
  (mg.id IS NOT NULL) AS in_gebruik,
  mg.werf_id AS current_werf_id,
  mg.locatie AS current_locatie,
  mg.start_tijd AS current_start_tijd,
  w.naam AS current_werf_naam
FROM public.materialen m
LEFT JOIN LATERAL (
  SELECT *
  FROM public.materiaal_gebruik
  WHERE materiaal_id = m.id
    AND is_actief = true
    AND (eind_tijd IS NULL OR eind_tijd > NOW())
  ORDER BY start_tijd DESC NULLS LAST
  LIMIT 1
) mg ON true
LEFT JOIN public.werven w ON mg.werf_id = w.project_id
WHERE m.is_verwijderd IS NOT TRUE OR m.is_verwijderd IS NULL;

-- Grant permissions (adjust roles as needed for your Supabase setup)
-- The view inherits permissions from the underlying tables
-- If you need explicit grants, uncomment and adjust:
-- GRANT SELECT ON public.materialen_met_huidige_locatie TO authenticated;
-- GRANT SELECT ON public.materialen_met_huidige_locatie TO anon;

