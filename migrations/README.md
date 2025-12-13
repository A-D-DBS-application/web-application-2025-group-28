# Database Migrations

## Migration: 001_create_materialen_met_huidige_locatie_view.sql

### Purpose
This migration creates a SQL view that joins `materialen` with `materiaal_gebruik` to get the current active usage location for each material.

### What it does
- Creates a view `materialen_met_huidige_locatie` that:
  - Includes all columns from `materialen`
  - Adds `in_gebruik` boolean indicating if material has active usage
  - Adds `current_werf_id` and `current_locatie` from the most recent active usage
  - Adds `current_werf_naam` by joining with `werven` table
  - Uses `LEFT JOIN LATERAL` to get the most recent active usage per material

### How to apply
1. Connect to your Supabase database (via Supabase Dashboard > SQL Editor, or using psql)
2. Run the SQL script: `migrations/001_create_materialen_met_huidige_locatie_view.sql`

### Note
The view is currently not directly used by the application code, but serves as a reference implementation.
The actual logic is implemented in Python in `app/services.py` to avoid N+1 queries and for better performance.

