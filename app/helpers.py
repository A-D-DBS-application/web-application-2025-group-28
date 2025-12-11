"""
Shared helper functions used across multiple blueprints
"""
from flask import g, session, redirect, url_for, request, current_app
from models import db, Gebruiker, Activity
from datetime import datetime
from werkzeug.utils import secure_filename
import os

# Supabase Storage
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# Global supabase client - will be initialized by app
_supabase_client: Client | None = None

def init_supabase_client(supabase_client: Client | None):
    """Initialize the supabase client for file uploads"""
    global _supabase_client
    _supabase_client = supabase_client


def upload_folder_from_bucket(bucket_name: str) -> str:
    """
    Map bucket naam naar lokale upload folder (alleen voor backward compatibility).
    Deze functie wordt niet meer gebruikt voor documenten - alles gaat naar Supabase.
    """
    # Deze functie wordt alleen nog gebruikt voor type-images en projects
    # Documenten gaan altijd naar Supabase
    bucket_to_folder = {
        "projects": current_app.config.get("PROJECT_UPLOAD_FOLDER", ""),
        "type-images": current_app.config.get("TYPE_IMAGE_UPLOAD_FOLDER", ""),
    }
    return bucket_to_folder.get(bucket_name, "")


def save_upload_local(file_storage, upload_folder, prefix: str) -> str | None:
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


def save_upload_to_supabase(file_storage, bucket_name: str, folder: str, prefix: str) -> str | None:
    """
    Upload een bestand naar Supabase Storage.
    Retourneert het pad in de bucket (bijv. 'BOOR123_doc_20250101_120000_foto.pdf').
    Alle documenten worden opgeslagen in Supabase Storage - geen lokale fallback meer.
    """
    if not file_storage or not file_storage.filename:
        return None
    
    if not _supabase_client:
        # Geen fallback meer - Supabase is vereist
        print("Error: Supabase client not available. Cannot upload file.")
        raise RuntimeError("Supabase client not initialized. Cannot upload files.")
    
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
        print(f"Error uploading to Supabase Storage: {e}")
        # Geen fallback meer - gooi error
        raise RuntimeError(f"Failed to upload file to Supabase Storage: {e}")


def save_upload(file_storage, upload_folder, prefix: str) -> str | None:
    """
    Upload een bestand naar Supabase Storage.
    Bepaalt automatisch de juiste bucket op basis van upload_folder.
    Gebruikt de juiste Nederlandse bucket namen voor documenten.
    Retourneert pad (bijv. "filename.jpg").
    """
    # Bepaal bucket op basis van upload_folder
    upload_folder_str = str(upload_folder) if upload_folder else ""
    
    # Check op speciale SUPABASE_ markers in configuratie
    if upload_folder == current_app.config.get("SAFETY_UPLOAD_FOLDER") or "SUPABASE_Veiligheidsfiche" in upload_folder_str:
        bucket = "Veiligheidsfiche"
        folder = ""
    elif upload_folder == current_app.config.get("CERTIFICATE_UPLOAD_FOLDER") or "SUPABASE_Keuringsstatus" in upload_folder_str:
        bucket = "Keuringsstatus documenten"
        folder = ""
    elif upload_folder == current_app.config.get("DOC_UPLOAD_FOLDER") or "SUPABASE_Aankoop-Verkoop" in upload_folder_str:
        bucket = "Aankoop-Verkoop documenten"
        folder = ""
    elif upload_folder == current_app.config.get("TYPE_IMAGE_UPLOAD_FOLDER"):
        bucket = "type-images"
        folder = ""
    elif upload_folder == current_app.config.get("PROJECT_UPLOAD_FOLDER"):
        bucket = "projects"
        folder = ""
    # Fallback: check op pad string (voor backward compatibility)
    elif "safety" in upload_folder_str.lower():
        bucket = "Veiligheidsfiche"
        folder = ""
    elif "certificate" in upload_folder_str.lower():
        bucket = "Keuringsstatus documenten"
        folder = ""
    elif "docs" in upload_folder_str.lower():
        bucket = "Aankoop-Verkoop documenten"
        folder = ""
    elif "type_image" in upload_folder_str.lower():
        bucket = "type-images"
        folder = ""
    else:
        # Default: Aankoop-Verkoop documenten voor documenten
        bucket = "Aankoop-Verkoop documenten"
        folder = ""
    
    result = save_upload_to_supabase(file_storage, bucket, folder, prefix)
    
    # Voor type-images: voeg bucket prefix toe aan het pad voor consistentie
    if bucket == "type-images" and result:
        if not result.startswith("type-images/"):
            return f"type-images/{result}"
    
    return result


def save_project_image(file_storage, prefix: str) -> str | None:
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


def get_supabase_file_url(bucket_name: str, file_path: str) -> str | None:
    """
    Haal publieke URL op voor een bestand in Supabase Storage.
    Retourneert None als Supabase niet beschikbaar is of bestand niet bestaat.
    Geen lokale fallback meer - alles moet in Supabase staan.
    """
    if not _supabase_client:
        # Geen fallback meer - Supabase is vereist
        print(f"Warning: Supabase client not available. Cannot get URL for {bucket_name}/{file_path}")
        return None
    
    try:
        # Als file_path al een volledige URL is, retourneer die
        if file_path.startswith("http://") or file_path.startswith("https://"):
            return file_path
        
        # Verwijder bucket prefix als die er al in zit (bijv. "type-images/filename.jpg" -> "filename.jpg")
        # Supabase get_public_url verwacht alleen het pad binnen de bucket
        clean_path = file_path
        if file_path.startswith(f"{bucket_name}/"):
            clean_path = file_path[len(f"{bucket_name}/"):]
        
        # Haal publieke URL op van Supabase
        response = _supabase_client.storage.from_(bucket_name).get_public_url(clean_path)
        print(f"DEBUG: Generated Supabase URL for bucket={bucket_name}, path={clean_path}, full_path={file_path}, URL={response}")
        return response
    except Exception as e:
        print(f"Error getting Supabase file URL for {bucket_name}/{file_path}: {e}")
        # Geen fallback meer - retourneer None
        return None


def get_file_url_from_path(file_path: str) -> str | None:
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

