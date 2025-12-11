from flask import Flask, session, g
from datetime import datetime
import os

from config import Config
from models import db, Gebruiker
from helpers import get_file_url_from_path

# Supabase Storage
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    print("Warning: supabase package not installed. Run: pip install supabase")

app = Flask(__name__)
app.secret_key = "dev"  # voor flash() + sessies
app.config.from_object(Config)

# SQLAlchemy koppelen aan app (Supabase/Postgres)
db.init_app(app)

# Supabase Storage client initialiseren
supabase_client: Client | None = None
if SUPABASE_AVAILABLE and app.config.get("SUPABASE_URL") and app.config.get("SUPABASE_SERVICE_KEY"):
    try:
        supabase_client = create_client(
            app.config["SUPABASE_URL"],
            app.config["SUPABASE_SERVICE_KEY"]
        )
        print("✓ Supabase Storage client initialized")
    except Exception as e:
        print(f"Warning: Could not initialize Supabase client: {e}")
        supabase_client = None
else:
    print("Warning: Supabase credentials not configured. Check config.py")

# Initialize supabase client in helpers module
from helpers import init_supabase_client
init_supabase_client(supabase_client)

# -----------------------------------------------------
# BLUEPRINTS
# -----------------------------------------------------

# Register blueprints
from blueprints.auth import auth_bp
app.register_blueprint(auth_bp)

from blueprints.materiaal import materiaal_bp
app.register_blueprint(materiaal_bp)

from blueprints.keuringen import keuringen_bp
app.register_blueprint(keuringen_bp)

from blueprints.documenten import documenten_bp
app.register_blueprint(documenten_bp)

from blueprints.werven import werven_bp
app.register_blueprint(werven_bp)

from blueprints.dashboard import dashboard_bp
app.register_blueprint(dashboard_bp)

from blueprints.geschiedenis import geschiedenis_bp
app.register_blueprint(geschiedenis_bp)

from blueprints.api import api_bp
app.register_blueprint(api_bp)

# -----------------------------------------------------
# HELPERS
# -----------------------------------------------------


# login_required is now imported from helpers
from helpers import login_required


@app.before_request
def load_current_user():
    g.user = None
    email = session.get("user_email")
    if not email:
        return
    g.user = Gebruiker.query.filter_by(email=email).first()


# Document types initialization removed - document_type is now stored as string in Document model


@app.context_processor
def inject_user():
    # in templates beschikbaar als {{ current_user }}
    from constants import INSPECTION_STATUSES, USAGE_STATUSES, KEURING_RESULTATEN, KEURING_STATUS_FILTERS, PERIOD_FILTERS, DOCUMENT_TYPES, KEURING_STATUS_OPTIONS
    return {
        "current_user": g.user,
        "get_file_url": get_file_url_from_path,  # Helper functie voor file URLs
        "inspection_statuses": INSPECTION_STATUSES,  # Make constants available in templates
        "usage_statuses": USAGE_STATUSES,
        "keuring_resultaten": KEURING_RESULTATEN,
        "keuring_status_filters": KEURING_STATUS_FILTERS,  # For keuringen page filter dropdown
        "period_filters": PERIOD_FILTERS,  # For geschiedenis page period filter dropdown
        "document_types": DOCUMENT_TYPES,  # For documenten page document types
        "keuring_status_options": KEURING_STATUS_OPTIONS,  # For "Nieuw Materiaal" modal keuring status dropdown
    }


# Helper functions moved to helpers.py or services.py
# log_activity_db is in helpers.py
# Material lookup functions use MaterialService directly
# update_verlopen_keuringen is MaterialService.update_expired_inspections()


# -----------------------------------------------------
# ROUTES - All routes moved to blueprints
# -----------------------------------------------------
# Dashboard routes moved to blueprints/dashboard.py
# Geschiedenis routes moved to blueprints/geschiedenis.py
# API routes moved to blueprints/api.py


# -----------------------------------------------------
# UPLOAD CONFIGURATIE – documentatie
# -----------------------------------------------------

BASE_UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
DOC_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "docs")
SAFETY_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "safety")
PROJECT_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "projects")
CERTIFICATE_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "certificates")
TYPE_IMAGE_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "type_images")

os.makedirs(DOC_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SAFETY_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROJECT_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CERTIFICATE_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TYPE_IMAGE_UPLOAD_FOLDER, exist_ok=True)

app.config["DOC_UPLOAD_FOLDER"] = DOC_UPLOAD_FOLDER
app.config["SAFETY_UPLOAD_FOLDER"] = SAFETY_UPLOAD_FOLDER
app.config["PROJECT_UPLOAD_FOLDER"] = PROJECT_UPLOAD_FOLDER
app.config["CERTIFICATE_UPLOAD_FOLDER"] = CERTIFICATE_UPLOAD_FOLDER
app.config["TYPE_IMAGE_UPLOAD_FOLDER"] = TYPE_IMAGE_UPLOAD_FOLDER

# Upload helper functions are in helpers.py




if __name__ == "__main__":
    with app.app_context():
        # geen db.create_all(); Supabase beheert de tabellen
        pass

    app.run(debug=True, port=5000)
