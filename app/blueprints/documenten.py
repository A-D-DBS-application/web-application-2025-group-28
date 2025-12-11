from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for, g, current_app
from werkzeug.utils import secure_filename
from datetime import datetime
from sqlalchemy import or_, func

from helpers import login_required, save_upload_to_supabase, get_file_url_from_path, get_supabase_file_url, log_activity_db, delete_file_from_supabase
from constants import DOCUMENT_TYPES
from models import db, Document, Material, MaterialType, KeuringHistoriek


documenten_bp = Blueprint("documenten", __name__, url_prefix="/documenten")


def get_bucket_for_document_type(document_type: str) -> str:
    """Bepaal de juiste Supabase bucket op basis van document type."""
    bucket_mapping = {
        "Aankoopfactuur": "Aankoop-Verkoop documenten",
        "Verkoopfactuur": "Aankoop-Verkoop documenten",
        "Keuringstatus": "Keuringsstatus documenten",
        "Veiligheidsfiche": "Veiligheidsfiche"
    }
    return bucket_mapping.get(document_type, "Aankoop-Verkoop documenten")


@documenten_bp.route("/", methods=["GET"])
@login_required
def documenten():
    """Render het documentenoverzicht."""
    search_query = request.args.get("q", "")
    selected_type = request.args.get("type", "alle")

    # Haal alle documenten op uit de database
    query = Document.query
    
    # Filter op document type
    if selected_type and selected_type != "alle":
        query = query.filter(Document.document_type == selected_type)
    
    # Zoek functionaliteit - zoek op basis van materiaal naam en serienummer
    if search_query:
        search_like = f"%{search_query}%"
        # Zoek via joins met materialen en materiaal_types tabellen
        query = query.join(
            Material, 
            Document.material_id == Material.id,
            isouter=True  # LEFT JOIN voor documenten gekoppeld aan specifiek materiaal
        ).join(
            MaterialType,
            Document.material_type_id == MaterialType.id,
            isouter=True  # LEFT JOIN voor documenten gekoppeld aan materiaal type (veiligheidsfiches)
        ).filter(
            or_(
                Material.name.ilike(search_like),  # Zoek op materiaal naam
                Material.serial.ilike(search_like),  # Zoek op serienummer
                MaterialType.name.ilike(search_like),  # Zoek op materiaal type naam (voor veiligheidsfiches)
                Document.material_type.ilike(search_like),  # Zoek op legacy materiaal_type string
                Document.note.ilike(search_like)  # Ook zoeken in opmerkingen
            )
        )
    
    # Sorteer op datum (nieuwste eerst)
    query = query.order_by(Document.aangemaakt_op.desc())
    
    documents_db = query.all()
    
    # Converteer naar template formaat
    documents = []
    for doc in documents_db:
        # Bepaal materiaal naam
        material_name = None
        material_serial = None
        if doc.material_id and doc.material:
            material_name = doc.material.name
            material_serial = doc.material.serial
        elif doc.material_type_id and doc.material_type_ref:
            material_name = f"Type: {doc.material_type_ref.name}"
        
        # Bepaal bucket en haal URL op
        bucket = get_bucket_for_document_type(doc.document_type)
        # Gebruik de juiste bucket voor het ophalen van de URL
        # Het file_path bevat alleen de bestandsnaam, niet de bucket naam
        # We moeten de bucket expliciet doorgeven
        file_url = get_supabase_file_url(bucket, doc.file_path)
        
        # Format file size
        file_size_str = ""
        if doc.file_size:
            if doc.file_size < 1024:
                file_size_str = f"{doc.file_size} B"
            elif doc.file_size < 1024 * 1024:
                file_size_str = f"{doc.file_size / 1024:.1f} KB"
            else:
                file_size_str = f"{doc.file_size / (1024 * 1024):.1f} MB"
        
        documents.append({
            "id": doc.id,
            "name": doc.file_name,
            "type": doc.document_type,
            "material": material_name or "Onbekend",
            "material_serial": material_serial,
            "material_id": doc.material_id,
            "material_type": doc.material_type,
            "date": doc.aangemaakt_op.strftime("%d-%m-%Y") if doc.aangemaakt_op else "",
            "size": file_size_str,
            "uploaded_by": doc.uploaded_by or "Onbekend",
            "url": file_url,
            "path": doc.file_path,
            "note": doc.note
        })
    
    # Haal alle materialen op voor de dropdown (dynamisch - exclusief verwijderde materialen)
    # Deze lijst wordt automatisch bijgewerkt wanneer materialen worden toegevoegd of verwijderd
    all_materials = Material.query.filter(
        or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
    ).order_by(Material.name.asc()).all()
    
    # Haal alle materiaal types op voor de dropdown (dynamisch)
    # Combineer types uit materialen en uit bestaande veiligheidsfiches
    material_types_set = set()
    
    # Haal types uit MaterialType tabel
    material_types_from_db = MaterialType.query.all()
    for mt in material_types_from_db:
        if mt.name:
            material_types_set.add(mt.name)
    
    # Haal ook types uit documenten tabel (uit bestaande veiligheidsfiches)
    material_types_from_docs = db.session.query(Document.material_type).filter(
        Document.material_type.isnot(None),
        Document.material_type != "",
        Document.document_type == "Veiligheidsfiche"
    ).distinct().all()
    for (name,) in material_types_from_docs:
        if name:
            material_types_set.add(name)
    
    material_types_list = sorted(list(material_types_set))

    return render_template(
        "documenten.html",
        search_query=search_query,
        selected_type=selected_type,
        document_types=DOCUMENT_TYPES,
        documents=documents,
        all_materials=all_materials,
        material_types_list=material_types_list,
    )


@documenten_bp.route("/upload", methods=["POST"])
@login_required
def documenten_upload():
    """Handle document upload."""
    try:
        # Haal form data op
        document_file = request.files.get("document_file")
        document_type = request.form.get("document_type", "").strip()
        material_id = request.form.get("material_id", "").strip()
        material_type_name = request.form.get("material_type", "").strip()
        note = request.form.get("note", "").strip()
        
        # Validatie
        if not document_file or not document_file.filename:
            flash("Geen bestand geselecteerd.", "error")
            return redirect(url_for("documenten.documenten"))
        
        if not document_type:
            flash("Document type is verplicht.", "error")
            return redirect(url_for("documenten.documenten"))
        
        # Bepaal of we materiaal of materiaal type nodig hebben
        is_veiligheidsfiche = document_type == "Veiligheidsfiche"
        
        if is_veiligheidsfiche:
            # Voor veiligheidsfiche: materiaal type is verplicht
            if not material_type_name:
                flash("Materiaal type is verplicht voor veiligheidsfiche.", "error")
                return redirect(url_for("documenten.documenten"))
            
            # Zoek of maak materiaal type
            material_type = MaterialType.query.filter_by(name=material_type_name).first()
            if not material_type:
                # Maak nieuw materiaal type aan
                material_type = MaterialType(
                    name=material_type_name,
                    aangemaakt_op=datetime.utcnow()
                )
                db.session.add(material_type)
                db.session.flush()  # Flush om ID te krijgen
            
            material_id = None
            material_type_id = material_type.id
        else:
            # Voor andere document types: materiaal is verplicht
            if not material_id:
                flash("Materieel is verplicht voor dit document type.", "error")
                return redirect(url_for("documenten.documenten"))
            
            # Valideer dat materiaal bestaat en niet verwijderd is
            material = Material.query.filter(
                Material.id == int(material_id),
                or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
            ).first()
            if not material:
                flash("Geselecteerd materieel bestaat niet of is verwijderd.", "error")
                return redirect(url_for("documenten.documenten"))
            
            material_type_id = None
        
        # Bepaal bucket op basis van document type
        bucket = get_bucket_for_document_type(document_type)
        
        # Genereer prefix voor bestandsnaam
        if material_id:
            # Material is al gevalideerd hierboven, maar haal opnieuw op voor prefix
            material = Material.query.filter(
                Material.id == int(material_id),
                or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
            ).first()
            if not material:
                flash("Geselecteerd materieel bestaat niet of is verwijderd.", "error")
                return redirect(url_for("documenten.documenten"))
            prefix = f"{material.serial}_{document_type.lower().replace(' ', '_')}"
        else:
            prefix = f"{material_type_name.lower().replace(' ', '_')}_{document_type.lower().replace(' ', '_')}"
        
        # Upload naar Supabase Storage
        file_path = save_upload_to_supabase(
            document_file,
            bucket_name=bucket,
            folder="",  # Geen subfolder, direct in bucket
            prefix=prefix
        )
        
        if not file_path:
            flash("Fout bij uploaden van bestand.", "error")
            return redirect(url_for("documenten.documenten"))
        
        # Bereken bestandsgrootte
        document_file.seek(0, 2)  # Ga naar einde
        file_size = document_file.tell()
        document_file.seek(0)  # Reset
        
        # Maak document record aan
        user_name = g.user.naam if g.user else "Onbekend"
        document = Document(
            document_type=document_type,
            file_path=file_path,
            file_name=secure_filename(document_file.filename),
            file_size=file_size,
            material_id=int(material_id) if material_id else None,
            material_type_id=material_type_id,
            material_type=material_type_name if is_veiligheidsfiche else None,
            uploaded_by=user_name,
            user_id=g.user.gebruiker_id if g.user else None,
            note=note if note else None,
            aangemaakt_op=datetime.utcnow()
        )
        
        db.session.add(document)
        
        # Als het een keuringstatus is, update de keuringsstatus
        if document_type == "Keuringstatus" and material_id:
            material = Material.query.filter(
                Material.id == int(material_id),
                or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
            ).first()
            if material:
                # Update inspection status naar "goedgekeurd"
                material.inspection_status = "goedgekeurd"
                material.laatste_keuring = datetime.utcnow().date()
                
                # Maak keuring historiek record aan
                keuring_historiek = KeuringHistoriek(
                    material_id=material.id,
                    serienummer=material.serial,
                    keuring_datum=datetime.utcnow().date(),
                    resultaat="goedgekeurd",
                    uitgevoerd_door=user_name,
                    certificaat_path=file_path,
                    volgende_keuring_datum=None,  # Kan later worden ingevuld
                    aangemaakt_op=datetime.utcnow()
                )
                db.session.add(keuring_historiek)
                
                # Log activiteit
                log_activity_db(
                    action="Keuringstatus geüpload",
                    name=material.name or "",
                    serial=material.serial or ""
                )
        
        db.session.commit()
        
        flash(f"Document '{document_file.filename}' succesvol geüpload.", "success")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error uploading document: {e}", exc_info=True)
        flash(f"Fout bij uploaden: {str(e)}", "error")
    
    return redirect(url_for("documenten.documenten"))


@documenten_bp.route("/edit", methods=["POST"])
@login_required
def documenten_bewerken():
    """Wijzig een document."""
    try:
        document_id = request.form.get("document_id")
        if not document_id:
            flash("Document ID ontbreekt.", "error")
            return redirect(url_for("documenten.documenten"))
        
        document = Document.query.get(document_id)
        if not document:
            flash("Document niet gevonden.", "error")
            return redirect(url_for("documenten.documenten"))
        
        # Haal form data op
        document_type = request.form.get("document_type", "").strip()
        material_id = request.form.get("material_id", "").strip()
        material_type_name = request.form.get("material_type", "").strip()
        note = request.form.get("note", "").strip()
        document_file = request.files.get("document_file")
        
        # Validatie
        if not document_type:
            flash("Document type is verplicht.", "error")
            return redirect(url_for("documenten.documenten"))
        
        # Bepaal of we materiaal of materiaal type nodig hebben
        is_veiligheidsfiche = document_type == "Veiligheidsfiche"
        
        if is_veiligheidsfiche:
            # Voor veiligheidsfiche: materiaal type is verplicht
            if not material_type_name:
                flash("Materiaal type is verplicht voor veiligheidsfiche.", "error")
                return redirect(url_for("documenten.documenten"))
            
            # Zoek of maak materiaal type
            material_type = MaterialType.query.filter_by(name=material_type_name).first()
            if not material_type:
                # Maak nieuw materiaal type aan
                material_type = MaterialType(
                    name=material_type_name,
                    aangemaakt_op=datetime.utcnow()
                )
                db.session.add(material_type)
                db.session.flush()
            
            material_id = None
            material_type_id = material_type.id
        else:
            # Voor andere document types: materiaal is verplicht
            if not material_id:
                flash("Materieel is verplicht voor dit document type.", "error")
                return redirect(url_for("documenten.documenten"))
            
            # Valideer dat materiaal bestaat
            material = Material.query.filter(
                Material.id == int(material_id),
                or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
            ).first()
            if not material:
                flash("Geselecteerd materieel bestaat niet of is verwijderd.", "error")
                return redirect(url_for("documenten.documenten"))
            
            material_type_id = None
        
        # Als er een nieuw bestand is geüpload, verwijder het oude en upload het nieuwe
        if document_file and document_file.filename:
            # Bepaal bucket
            bucket = get_bucket_for_document_type(document_type)
            
            # Verwijder oud bestand uit Supabase
            old_bucket = get_bucket_for_document_type(document.document_type)
            if document.file_path:
                delete_file_from_supabase(old_bucket, document.file_path)
            
            # Genereer prefix voor nieuw bestand
            if material_id:
                material = Material.query.filter(
                    Material.id == int(material_id),
                    or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
                ).first()
                prefix = f"{material.serial}_{document_type.lower().replace(' ', '_')}"
            else:
                prefix = f"{material_type_name.lower().replace(' ', '_')}_{document_type.lower().replace(' ', '_')}"
            
            # Upload nieuw bestand
            file_path = save_upload_to_supabase(
                document_file,
                bucket_name=bucket,
                folder="",
                prefix=prefix
            )
            
            if not file_path:
                flash("Fout bij uploaden van nieuw bestand.", "error")
                return redirect(url_for("documenten.documenten"))
            
            # Bereken bestandsgrootte
            document_file.seek(0, 2)
            file_size = document_file.tell()
            document_file.seek(0)
            
            document.file_path = file_path
            document.file_name = secure_filename(document_file.filename)
            document.file_size = file_size
        
        # Update document velden
        document.document_type = document_type
        document.material_id = int(material_id) if material_id else None
        document.material_type_id = material_type_id
        document.material_type = material_type_name if is_veiligheidsfiche else None
        document.note = note if note else None
        
        db.session.commit()
        
        flash(f"Document '{document.file_name}' is bijgewerkt.", "success")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error editing document: {e}", exc_info=True)
        flash(f"Fout bij wijzigen: {str(e)}", "error")
    
    return redirect(url_for("documenten.documenten"))


@documenten_bp.route("/delete", methods=["POST"])
@login_required
def documenten_verwijderen():
    """Verwijder een document."""
    try:
        document_id = request.form.get("document_id")
        if not document_id:
            flash("Document ID ontbreekt.", "error")
            return redirect(url_for("documenten.documenten"))
        
        document = Document.query.get(document_id)
        if not document:
            flash("Document niet gevonden.", "error")
            return redirect(url_for("documenten.documenten"))
        
        # Verwijder bestand uit Supabase Storage
        bucket = get_bucket_for_document_type(document.document_type)
        if document.file_path:
            delete_file_from_supabase(bucket, document.file_path)
        
        # Verwijder document uit database
        file_name = document.file_name
        db.session.delete(document)
        db.session.commit()
        
        flash(f"Document '{file_name}' is verwijderd.", "success")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting document: {e}", exc_info=True)
        flash(f"Fout bij verwijderen: {str(e)}", "error")
    
    return redirect(url_for("documenten.documenten"))


@documenten_bp.record_once
def _register_plain_endpoint(state):
    """Expose alias zodat url_for('documenten') blijft werken."""
    state.app.add_url_rule("/documenten", "documenten", documenten)
