"""
Documenten blueprint - handles all document-related routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app
from models import db, Material, Document, MaterialType
from helpers import login_required, log_activity_db, save_upload, get_file_url_from_path
from sqlalchemy import text
import os

documenten_bp = Blueprint('documenten', __name__)


# Document types functionality removed - using simple string field in Document model


@documenten_bp.route("/documenten")
@login_required
def documenten():
    """Documenten overzicht met zoeken en filteren"""
    import os as _os
    
    q = (request.args.get("q") or "").strip().lower()
    doc_type = (request.args.get("type") or "").strip().lower()
    
    # Define available document types as a static list
    available_document_types = [
        "Aankoopfactuur",
        "Keuringstatus",
        "Verkoopfactuur",
        "Veiligheidsfiche",
        "Handleiding",
        "Overige"
    ]
    
    # Query materials with proper error handling
    try:
        all_materials = Material.query.all()
    except Exception as e:
        print(f"Error querying materials: {e}")
        # Rollback and retry
        try:
            db.session.rollback()
            all_materials = Material.query.all()
        except Exception as e2:
            print(f"Error retrying materials query: {e2}")
            all_materials = []
    documents = []
    
    # Haal Document records uit database op
    all_documents = []
    try:
        all_documents = Document.query.order_by(Document.created_at.desc()).all()
    except Exception as e:
        print(f"Error querying documents (material_type column missing): {e}")
        print("Using raw SQL query without material_type column...")
        try:
            result = db.session.execute(
                text("""
                    SELECT id, created_at, document_type, file_path, file_name, file_size, 
                           material_id, uploaded_by, user_id, note
                    FROM documenten
                    ORDER BY created_at DESC
                """)
            )
            for row in result:
                doc_obj = type('DocumentObj', (), {
                    'id': row.id,
                    'created_at': row.created_at,
                    'document_type': row.document_type,
                    'file_path': row.file_path,
                    'file_name': row.file_name,
                    'file_size': row.file_size,
                    'material_id': row.material_id,
                    'uploaded_by': row.uploaded_by,
                    'user_id': row.user_id,
                    'note': row.note,
                    'material': Material.query.get(row.material_id) if row.material_id else None,
                    'material_type': None
                })()
                all_documents.append(doc_obj)
        except Exception as e2:
            print(f"Error with raw SQL query: {e2}")
            all_documents = []
    
    for doc in all_documents:
        material = doc.material if hasattr(doc, 'material') else None
        file_url = get_file_url_from_path(doc.file_path) if doc.file_path else None
        
        # Use the new linked_entity_name property if available, otherwise fallback
        if hasattr(doc, 'linked_entity_name'):
            linked_name = doc.linked_entity_name or "Onbekend"
        else:
            # Fallback for legacy or raw SQL results
            if material:
                linked_name = material.name
            elif hasattr(doc, 'material_type') and doc.material_type:
                linked_name = doc.material_type
            else:
                linked_name = "Onbekend"
        
        documents.append({
            "type": doc.document_type or "Overige",
            "name": doc.file_name or "Onbekend",
            "material": linked_name,
            "material_serial": material.serial if material else "",
            "date": doc.created_at.strftime("%Y-%m-%d") if doc.created_at else "",
            "size": f"{doc.file_size / 1024:.1f} KB" if doc.file_size else "Onbekend",
            "uploaded_by": doc.uploaded_by or "Onbekend",
            "path": doc.file_path,
            "url": file_url,
            "status": doc.document_type or "Overige",
        })
    
    # Oude documenten van Material records (voor backward compatibility)
    for material in all_materials:
        if material.documentation_path:
            doc_name = _os.path.basename(material.documentation_path)
            doc_type_from_name = (
                "Handleiding"
                if "handleiding" in doc_name.lower()
                or "manual" in doc_name.lower()
                else "Overige"
            )
            
            file_url = get_file_url_from_path(material.documentation_path)

            documents.append({
                "type": doc_type_from_name,
                "name": doc_name,
                "material": material.name or "Onbekend",
                "material_serial": material.serial,
                "date": material.created_at.strftime("%Y-%m-%d")
                    if getattr(material, "created_at", None)
                    else "",
                "size": "2.3 MB",
                "uploaded_by": material.assigned_to or "Systeem",
                "path": material.documentation_path,
                "url": file_url,
                "status": doc_type_from_name,
            })
        
        if material.safety_sheet_path:
            doc_name = _os.path.basename(material.safety_sheet_path)
            file_url = get_file_url_from_path(material.safety_sheet_path)
            
            documents.append({
                "type": "Veiligheidscertificaat",
                "name": doc_name,
                "material": material.name or "Onbekend",
                "material_serial": material.serial,
                "date": material.created_at.strftime("%Y-%m-%d")
                    if getattr(material, "created_at", None)
                    else "",
                "size": "456 KB",
                "uploaded_by": material.assigned_to or "Systeem",
                "path": material.safety_sheet_path,
                "url": file_url,
                "status": "Veiligheidscertificaat",
            })

    if q:
        documents = [
            d
            for d in documents
            if q in d["name"].lower() or q in d["material"].lower()
        ]

    if doc_type and doc_type != "alle":
        documents = [
            d for d in documents if d["type"].lower() == doc_type.lower()
        ]
    
    total_docs = len(documents)
    safety_certs = len(
        [d for d in documents if d["type"] == "Veiligheidscertificaat"]
    )
    
    # Get unique material types for the datalist
    material_types_list = []
    
    # From MaterialType table
    material_types_from_table = MaterialType.query.with_entities(MaterialType.name).distinct().all()
    material_types_list.extend([mt[0] for mt in material_types_from_table if mt[0]])
    
    # From Material table (existing materials)
    material_types_from_materials = db.session.query(Material.type).filter(
        Material.type.isnot(None),
        Material.type != ""
    ).distinct().all()
    material_types_list.extend([mt[0] for mt in material_types_from_materials if mt[0] and mt[0] not in material_types_list])
    
    # Remove duplicates and sort
    material_types_list = sorted(list(set(material_types_list)))
    
    return render_template(
        "documenten.html",
        documents=documents,
        total_docs=total_docs,
        safety_certs=safety_certs,
        search_query=q,
        selected_type=doc_type,
        all_materials=all_materials,
        material_types_list=material_types_list,
        document_types=available_document_types,
    )


@documenten_bp.route("/documenten/upload", methods=["POST"])
@login_required
def documenten_upload():
    """Handle document upload"""
    document_file = request.files.get("document_file")
    document_type = (request.form.get("document_type") or "").strip()
    material_id = request.form.get("material_id")
    material_type = (request.form.get("material_type") or "").strip()
    note = (request.form.get("note") or "").strip()
    
    if not document_file or not document_file.filename:
        flash("Geen bestand geselecteerd.", "danger")
        return redirect(url_for("documenten.documenten"))
    
    if not document_type:
        flash("Document type is verplicht.", "danger")
        return redirect(url_for("documenten.documenten"))
    
    # Get user info
    user_id = g.user.gebruiker_id if getattr(g, "user", None) else None
    uploaded_by = g.user.Naam if getattr(g, "user", None) else "Onbekend"
    
    # Determine upload folder based on document type
    if document_type == "Veiligheidsfiche":
        upload_folder = current_app.config["SAFETY_UPLOAD_FOLDER"]
        prefix = f"safety_{material_type or 'generic'}"
    else:
        upload_folder = current_app.config["DOC_UPLOAD_FOLDER"]
        if material_id:
            material = Material.query.get(material_id)
            prefix = f"{material.serial}_doc" if material else "doc"
        else:
            prefix = "doc"
    
    # Save the file
    file_path = save_upload(document_file, upload_folder, prefix)
    if not file_path:
        flash("Fout bij het uploaden van het bestand.", "danger")
        return redirect(url_for("documenten.documenten"))
    
    # Get file size
    file_size = None
    if document_file.content_length:
        file_size = document_file.content_length
    
    # Determine material_type_id if material_type (string) is provided
    material_type_id = None
    if material_type and not material_id:
        # Look up MaterialType by name
        material_type_obj = MaterialType.query.filter_by(name=material_type).first()
        if material_type_obj:
            material_type_id = material_type_obj.id
    
    # Create Document record
    new_document = Document(
        document_type=document_type,
        file_path=file_path,
        file_name=document_file.filename,
        file_size=file_size,
        material_id=int(material_id) if material_id else None,
        material_type_id=material_type_id,  # Use FK instead of string
        material_type=material_type if material_type and not material_type_id else None,  # Keep for backward compatibility
        uploaded_by=uploaded_by,
        user_id=user_id,
        note=note if note else None,
    )
    
    db.session.add(new_document)
    db.session.commit()
    
    flash(f"Document '{document_file.filename}' is succesvol geüpload.", "success")
    log_activity_db("Document toegevoegd", document_file.filename, "")
    return redirect(url_for("documenten.documenten"))

