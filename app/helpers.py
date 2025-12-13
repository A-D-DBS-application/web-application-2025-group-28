"""
Shared helper functions used across multiple blueprints
"""
from flask import g, session, redirect, url_for, request, current_app
from models import db, Gebruiker, Activity
from datetime import datetime
from werkzeug.utils import secure_filename
from typing import Optional
import os

# Supabase Storage
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# Global supabase client - will be initialized by app
_supabase_client: Optional[Client] = None

def init_supabase_client(supabase_client: Optional[Client]):
    """Initialize the supabase client for file uploads"""
    global _supabase_client
    _supabase_client = supabase_client


def upload_folder_from_bucket(bucket_name: str) -> str:
    """Map bucket naam naar lokale upload folder (alleen voor niet-documenten fallback)."""
    bucket_to_folder = {
        "projects": current_app.config["PROJECT_UPLOAD_FOLDER"],
        "type-images": current_app.config["TYPE_IMAGE_UPLOAD_FOLDER"],
        # Oude bucket namen (niet meer gebruikt voor documenten)
        "docs": current_app.config["PROJECT_UPLOAD_FOLDER"],  # Fallback
        "safety": current_app.config["PROJECT_UPLOAD_FOLDER"],  # Fallback
        "certificates": current_app.config["PROJECT_UPLOAD_FOLDER"],  # Fallback
        # Nieuwe bucket namen voor documenten - deze gebruiken Supabase, geen lokale fallback
        "Aankoop-Verkoop documenten": current_app.config["PROJECT_UPLOAD_FOLDER"],  # Fallback (zou niet gebruikt moeten worden)
        "Keuringsstatus documenten": current_app.config["PROJECT_UPLOAD_FOLDER"],  # Fallback (zou niet gebruikt moeten worden)
        "Veiligheidsfiche": current_app.config["PROJECT_UPLOAD_FOLDER"],  # Fallback (zou niet gebruikt moeten worden)
    }
    return bucket_to_folder.get(bucket_name, current_app.config["PROJECT_UPLOAD_FOLDER"])


def save_upload_local(file_storage, upload_folder, prefix: str) -> Optional[str]:
    """
    Fallback: Sla een geüpload bestand lokaal op (oude methode).
    Gebruikt alleen als Supabase niet beschikbaar is.
    """
    if not file_storage or not file_storage.filename:
        return None

    filename = secure_filename(file_storage.filename)
    final_filename = f"{prefix}_{filename}"

    full_path = os.path.join(upload_folder, final_filename)
    file_storage.save(full_path)

    if upload_folder == current_app.config["DOC_UPLOAD_FOLDER"]:
        relative_folder = "uploads/docs"
    elif upload_folder == current_app.config["SAFETY_UPLOAD_FOLDER"]:
        relative_folder = "uploads/safety"
    elif upload_folder == current_app.config["CERTIFICATE_UPLOAD_FOLDER"]:
        relative_folder = "uploads/certificates"
    elif upload_folder == current_app.config["TYPE_IMAGE_UPLOAD_FOLDER"]:
        relative_folder = "uploads/type_images"
    else:
        relative_folder = "uploads"

    return f"{relative_folder}/{final_filename}"


def save_upload_to_supabase(file_storage, bucket_name: str, folder: str, prefix: str) -> Optional[str]:
    """
    Upload een bestand naar Supabase Storage.
    Retourneert het pad in de bucket (bijv. 'BOOR123_doc_20250101_120000_foto.pdf').
    Voor documenten: GEEN fallback naar lokale storage - alle documenten moeten naar Supabase.
    """
    if not file_storage or not file_storage.filename:
        return None
    
    if not _supabase_client:
        # Voor documenten: geen fallback, gooi error
        document_buckets = ["Aankoop-Verkoop documenten", "Keuringsstatus documenten", "Veiligheidsfiche"]
        if bucket_name in document_buckets:
            raise Exception(f"Supabase client niet beschikbaar. Documenten moeten naar Supabase bucket '{bucket_name}' worden geüpload.")
        # Alleen voor niet-documenten (type-images, projects): fallback naar lokaal
        print("Warning: Supabase not available, falling back to local storage")
        return save_upload_local(file_storage, upload_folder_from_bucket(bucket_name), prefix)
    
    # Genereer unieke bestandsnaam
    filename = secure_filename(file_storage.filename)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    final_filename = f"{prefix}_{timestamp}_{filename}"
    
    # Pad in bucket (bijv. "BOOR123_doc_20250101_120000_foto.pdf")
    file_path = f"{folder}/{final_filename}" if folder else final_filename
    
    # Lees bestand
    file_content = file_storage.read()
    file_storage.seek(0)  # Reset file pointer
    
    try:
        # Upload naar Supabase Storage
        response = _supabase_client.storage.from_(bucket_name).upload(
            path=file_path,
            file=file_content,
            file_options={"content-type": file_storage.content_type or "application/octet-stream", "upsert": "true"}
        )
        
        # Retourneer het pad (wordt opgeslagen in database)
        return file_path
        
    except Exception as e:
        print(f"Error uploading to Supabase Storage bucket '{bucket_name}': {e}")
        # Voor documenten: geen fallback, gooi error door
        document_buckets = ["Aankoop-Verkoop documenten", "Keuringsstatus documenten", "Veiligheidsfiche"]
        if bucket_name in document_buckets:
            raise Exception(f"Kon document niet uploaden naar Supabase bucket '{bucket_name}': {e}")
        # Alleen voor niet-documenten: fallback naar lokaal
        return save_upload_local(file_storage, upload_folder_from_bucket(bucket_name), prefix)


def save_upload(file_storage, upload_folder, prefix: str) -> Optional[str]:
    """
    Upload een bestand (gebruikt Supabase Storage of fallback naar lokaal).
    Bepaalt automatisch de juiste bucket op basis van upload_folder.
    Retourneert pad met bucket prefix (bijv. "type-images/filename.jpg").
    OPGELET: Deze functie wordt alleen gebruikt voor type-images en projects.
    Voor documenten moet save_upload_to_supabase direct worden gebruikt met de juiste bucket naam.
    """
    # Bepaal bucket en folder op basis van upload_folder
    # OPGELET: Deze functie wordt alleen gebruikt voor niet-documenten (type-images, projects)
    # Documenten moeten direct via save_upload_to_supabase met Nederlandse bucket namen
    if upload_folder == current_app.config["TYPE_IMAGE_UPLOAD_FOLDER"]:
        bucket = "type-images"
        folder = ""
    elif upload_folder == current_app.config["PROJECT_UPLOAD_FOLDER"]:
        bucket = "projects"
        folder = ""
    else:
        # Fallback - maar dit zou niet moeten voorkomen voor documenten
        # Documenten moeten direct via save_upload_to_supabase
        bucket = "type-images"  # default voor niet-documenten
        folder = ""
    
    result = save_upload_to_supabase(file_storage, bucket, folder, prefix)
    
    # Voor type-images: voeg bucket prefix toe aan het pad voor consistentie
    if upload_folder == current_app.config["TYPE_IMAGE_UPLOAD_FOLDER"] and result:
        if not result.startswith("type-images/"):
            return f"type-images/{result}"
    
    return result


def save_project_image(file_storage, prefix: str) -> Optional[str]:
    """
    Upload een werf-afbeelding naar Supabase Storage (bucket: projects).
    Retourneert pad met "projects/" prefix voor consistentie.
    """
    result = save_upload_to_supabase(
        file_storage,
        bucket_name="projects",
        folder="",
        prefix=prefix
    )
    # Zorg dat het pad begint met "projects/" voor consistentie
    if result and not result.startswith("projects/"):
        return f"projects/{result}"
    return result


def get_supabase_file_url(bucket_name: str, file_path: str) -> Optional[str]:
    """
    Haal publieke URL op voor een bestand in Supabase Storage.
    
    NIEUWE LOGICA: 
    - file_path bevat alleen het pad binnen de bucket (geen bucket prefix)
    - bucket_name wordt expliciet doorgegeven
    - Geen automatische prefix verwijdering meer (voorkomt fouten)
    
    Args:
        bucket_name: Naam van de Supabase Storage bucket
        file_path: Pad binnen de bucket (bijv. "test_9_doc_20250101_120000_foto.pdf")
    
    Returns:
        Publieke URL of None als bestand niet bestaat/Supabase niet beschikbaar
    """
    if not _supabase_client:
        # Fallback: als het een lokaal pad is (begint met "uploads/")
        if file_path and file_path.startswith("uploads/"):
            return url_for('static', filename=file_path)
        return None
    
    if not file_path or not file_path.strip():
        print(f"Warning: Empty file_path for bucket {bucket_name}")
        return None
    
    try:
        # Als file_path al een volledige URL is, retourneer die
        if file_path.startswith("http://") or file_path.startswith("https://"):
            return file_path
        
        # NIEUWE LOGICA: file_path bevat alleen het pad binnen de bucket
        # Verwijder alleen leading/trailing slashes, maar behoud de rest
        clean_path = file_path.strip().strip('/')
        
        # Verwijder bucket prefix als die per ongeluk in file_path zit (voor backward compatibility)
        # Maar alleen als het exact matcht - niet gedeeltelijk
        known_buckets = ["Aankoop-Verkoop documenten", "Keuringsstatus documenten", "Veiligheidsfiche", "type-images", "projects"]
        for known_bucket in known_buckets:
            if clean_path.startswith(f"{known_bucket}/"):
                clean_path = clean_path[len(f"{known_bucket}/"):]
                break
            elif clean_path == known_bucket:
                # Als het pad alleen de bucket naam is, is er iets mis
                print(f"Warning: file_path is only bucket name '{clean_path}', no actual file path")
                return None
        
        # URL encode speciale karakters in het pad (vooral spaties en speciale tekens)
        # Maar behoud slashes voor folder structuur
        from urllib.parse import quote
        # Split op slashes, encode elk deel, en join weer
        path_parts = clean_path.split('/')
        encoded_parts = [quote(part, safe='') for part in path_parts]
        encoded_path = '/'.join(encoded_parts)
        
        # Haal publieke URL op van Supabase
        # Supabase SDK verwacht het pad binnen de bucket (zonder bucket prefix)
        response = _supabase_client.storage.from_(bucket_name).get_public_url(encoded_path)
        
        print(f"DEBUG: Generated Supabase URL for bucket={bucket_name}, original_path={file_path}, clean_path={clean_path}, encoded_path={encoded_path}, URL={response}")
        return response
        
    except Exception as e:
        print(f"Error getting Supabase file URL for bucket={bucket_name}, path={file_path}: {e}")
        import traceback
        traceback.print_exc()
        # Fallback naar lokaal pad
        if file_path and file_path.startswith("uploads/"):
            return url_for('static', filename=file_path)
        return None


def get_document_url(document_type: str, file_path: str) -> Optional[str]:
    """
    Centrale helper functie om document URLs te genereren.
    
    Gebruikt de juiste bucket op basis van document_type en genereert een geldige Supabase URL.
    
    Args:
        document_type: Type document (Aankoopfactuur, Verkoopfactuur, Keuringstatus, Veiligheidsfiche)
        file_path: Pad binnen de bucket (zonder bucket prefix)
    
    Returns:
        Publieke URL of None als bestand niet bestaat
    """
    if not file_path or not file_path.strip():
        return None
    
    # Bepaal bucket op basis van document type
    bucket_mapping = {
        "Aankoopfactuur": "Aankoop-Verkoop documenten",
        "Verkoopfactuur": "Aankoop-Verkoop documenten",
        "Keuringstatus": "Keuringsstatus documenten",
        "Veiligheidsfiche": "Veiligheidsfiche"
    }
    bucket = bucket_mapping.get(document_type, "Aankoop-Verkoop documenten")
    
    return get_supabase_file_url(bucket, file_path)


def get_file_url_from_path(file_path: str) -> Optional[str]:
    """
    Bepaal automatisch de juiste URL voor een bestandspad.
    Detecteert automatisch de bucket op basis van het pad.
    """
    if not file_path:
        return None
    
    # Als het al een URL is, retourneer die
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path
    
    # Bepaal bucket op basis van pad
    if file_path.startswith("docs/") or file_path.startswith("uploads/docs/"):
        bucket = "docs"
        # Verwijder "uploads/" prefix als die er is
        clean_path = file_path.replace("uploads/docs/", "docs/") if "uploads/docs/" in file_path else file_path
    elif file_path.startswith("safety/") or file_path.startswith("uploads/safety/"):
        bucket = "safety"
        clean_path = file_path.replace("uploads/safety/", "safety/") if "uploads/safety/" in file_path else file_path
    elif file_path.startswith("projects/") or file_path.startswith("uploads/projects/"):
        bucket = "projects"
        clean_path = file_path.replace("uploads/projects/", "projects/") if "uploads/projects/" in file_path else file_path
    elif file_path.startswith("certificates/") or file_path.startswith("uploads/certificates/"):
        bucket = "certificates"
        clean_path = file_path.replace("uploads/certificates/", "certificates/") if "uploads/certificates/" in file_path else file_path
    elif file_path.startswith("type-images/") or file_path.startswith("type_images/") or file_path.startswith("uploads/type_images/"):
        bucket = "type-images"
        clean_path = file_path.replace("uploads/type_images/", "type-images/").replace("type_images/", "type-images/")
    else:
        # Als het pad geen prefix heeft, probeer te detecteren op basis van bestandstype
        # Dit is voor backward compatibility met oude bestanden
        if file_path.startswith("uploads/"):
            return url_for('static', filename=file_path)
        # Als het alleen een bestandsnaam is zonder prefix, probeer als type-image eerst
        # (omdat dit vaak voorkomt bij materiaal types)
        if "/" not in file_path and not file_path.startswith("uploads/"):
            # Check of het een image extensie heeft (jpg, jpeg, png) - dan is het waarschijnlijk een type-image
            image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            if any(file_path.lower().endswith(ext) for ext in image_extensions):
                bucket = "type-images"
                clean_path = file_path
            else:
                # Anders probeer als project image (verwijder "projects/" als die er al in zit)
                bucket = "projects"
                clean_path = file_path.replace("projects/", "") if file_path.startswith("projects/") else file_path
        else:
            return None
    
    return get_supabase_file_url(bucket, clean_path)


def login_required(view):
    """Decorator to require login for a route"""
    from functools import wraps
    from flask import redirect, url_for, request, session
    
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_email") is None:
            return redirect(url_for("auth.login", next=request.path))
        
        if getattr(g, "user", None) is None:
            session.clear()
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    
    return wrapped


def load_current_user():
    """Load current user from session"""
    g.user = None
    email = session.get("user_email")
    if not email:
        return
    g.user = Gebruiker.query.filter_by(email=email).first()


def log_activity_db(action: str, name: str, serial: str):
    """Schrijf een activiteit weg naar de activiteiten_log tabel in Supabase."""
    user_name = None
    if getattr(g, "user", None) and g.user.naam:
        user_name = g.user.naam

    act = Activity(
        action=action,
        name=name or "",
        serial=serial or "",
        user_name=user_name or "Onbekend",
        created_at=datetime.utcnow(),
    )
    db.session.add(act)
    db.session.commit()

