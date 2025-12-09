class Config: 
    SECRET_KEY = 'your_secret_key'
    SQLALCHEMY_DATABASE_URI = 'postgresql://postgres.erxupmhvgazjnwubthwj:Fleet360Ugent@aws-1-eu-west-3.pooler.supabase.com:5432/postgres'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Supabase Storage configuratie
    # Vervang deze met jouw Supabase project URL en keys
    # Je vindt deze in Supabase Dashboard > Settings > API
    SUPABASE_URL = 'https://erxupmhvgazjnwubthwj.supabase.co'  # Vervang met jouw Supabase URL
    SUPABASE_SERVICE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVyeHVwbWh2Z2F6am53dWJ0aHdqIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MDg3MDcxNSwiZXhwIjoyMDc2NDQ2NzE1fQ.uTuFxr1W8Vu4krenq3JrqpH8wl6zh4eCUorFN-iV4rU'  # Service key voor server-side uploads (Settings > API > service_role key)