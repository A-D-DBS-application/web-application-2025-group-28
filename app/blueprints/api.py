"""
API blueprint - handles API endpoints
"""
from flask import Blueprint, request, jsonify, g
from models import db, Material, MaterialUsage, Keuringstatus, Document
from helpers import login_required, get_file_url_from_path
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route("/search", methods=["GET"])
@login_required
def api_search():
    """
    API endpoint for searching materials - returns JSON.
    Optimized with eager loading and subqueries to avoid N+1 query problems.
    """
    try:
        q = (request.args.get("q") or "").strip().lower()
        
        if not q:
            return jsonify({"items": []}), 200
        
        like = f"%{q}%"
        
        # Optimized query - eager load material_type to get inspection_validity_days
        items = (
            Material.query
            .options(joinedload(Material.material_type))
            .filter(or_(Material.name.ilike(like), Material.serial.ilike(like)))
            .limit(10)
            .all()
        )
        
        if not items:
            return jsonify({"items": []}), 200
        
        # Get all material IDs for batch querying
        material_ids = [item.id for item in items]
        
        # Single query to get active usage counts for all materials at once
        # This avoids N+1 queries by using a subquery/aggregation
        usage_count_map = {}
        if material_ids:
            try:
                active_usage_counts = (
                    db.session.query(
                        MaterialUsage.material_id,
                        func.count(MaterialUsage.id).label('count')
                    )
                    .filter(
                        MaterialUsage.material_id.in_(material_ids),
                        MaterialUsage.is_active.is_(True)
                    )
                    .group_by(MaterialUsage.material_id)
                    .all()
                )
                
                # Convert to dictionary for O(1) lookup
                usage_count_map = {row[0]: row[1] for row in active_usage_counts if row and row[0]}
            except Exception as usage_query_error:
                print(f"Warning: Could not query material usage: {usage_query_error}")
                usage_count_map = {}
        
        # Query all documents for these materials in one query
        documents_by_material = {}
        if material_ids:
            try:
                material_documents = (
                    Document.query
                    .filter(Document.material_id.in_(material_ids))
                    .all()
                )
                
                # Group documents by material_id
                for doc in material_documents:
                    if doc and doc.material_id:
                        if doc.material_id not in documents_by_material:
                            documents_by_material[doc.material_id] = []
                        documents_by_material[doc.material_id].append(doc)
            except Exception as doc_query_error:
                print(f"Warning: Could not query documents: {doc_query_error}")
                documents_by_material = {}
        
        # Also query keuring by serienummer for materials that don't have keuring_id
        # This handles the fallback case more efficiently
        serials = [item.serial for item in items if item.serial]
        keuring_by_serial = {}
        if serials:
            try:
                keuring_records = Keuringstatus.query.filter(
                    Keuringstatus.serienummer.in_(serials)
                ).all()
                keuring_by_serial = {
                    k.serienummer: k 
                    for k in keuring_records
                    if k and k.serienummer
                }
            except Exception as keuring_query_error:
                print(f"Warning: Could not query keuring by serial: {keuring_query_error}")
                keuring_by_serial = {}
        
        results = []
        for item in items:
            try:
                # Get active usage count from pre-loaded map
                active_usages_count = usage_count_map.get(item.id, 0)
                
                # Determine actual status: if has active usages, status is "in gebruik"
                actual_status = "in gebruik" if active_usages_count > 0 else (item.status or "")
                
                # Get keuring info - try relationship first, then fallback to serial lookup
                keuring_info = None
                try:
                    # Try to access keuring relationship (may be None if no keuring_id)
                    if item.keuring_id and item.keuring:
                        keuring_info = item.keuring
                    elif item.serial and item.serial in keuring_by_serial:
                        keuring_info = keuring_by_serial[item.serial]
                except Exception as keuring_error:
                    # If accessing relationship fails, fallback to serial lookup
                    print(f"Warning: Could not access keuring relationship for {item.serial}: {keuring_error}")
                    if item.serial and item.serial in keuring_by_serial:
                        keuring_info = keuring_by_serial[item.serial]
                
                # Safe date formatting for keuring dates
                keuring_gepland = None
                laatste_keuring = None
                if keuring_info:
                    if keuring_info.volgende_controle:
                        try:
                            keuring_gepland = keuring_info.volgende_controle.strftime("%Y-%m-%d")
                        except (AttributeError, ValueError):
                            keuring_gepland = None
                    if keuring_info.laatste_controle:
                        try:
                            laatste_keuring = keuring_info.laatste_controle.strftime("%Y-%m-%d")
                        except (AttributeError, ValueError):
                            laatste_keuring = None
                
                # Build URLs for documentation using storage helper
                documentation_url = ""
                try:
                    if item.documentation_path:
                        documentation_url = get_file_url_from_path(item.documentation_path) or ""
                except Exception as doc_url_error:
                    print(f"Warning: Could not generate documentation URL for {item.serial}: {doc_url_error}")
                    documentation_url = ""
                
                # Haal veiligheidsfiche op op basis van material_type_id
                # Zoek naar een Document met type "Veiligheidsfiche" gekoppeld aan het materiaal type
                safety_sheet_path = None
                safety_sheet_url = None
                try:
                    from models import Document
                    if item.material_type_id:
                        # Zoek het meest recente veiligheidsfiche document voor dit materiaal type
                        safety_doc = Document.query.filter(
                            Document.document_type == "Veiligheidsfiche",
                            Document.material_type_id == item.material_type_id
                        ).order_by(Document.aangemaakt_op.desc()).first()
                        
                        if safety_doc and safety_doc.file_path:
                            safety_sheet_path = safety_doc.file_path
                            # Genereer URL voor veiligheidsfiche
                            # Gebruik direct de bucket naam om circulaire import te voorkomen
                            from helpers import get_supabase_file_url
                            bucket = "Veiligheidsfiche"  # Direct bucket naam
                            safety_sheet_url = get_supabase_file_url(bucket, safety_doc.file_path) or ""
                except (ImportError, AttributeError, ProgrammingError) as safety_error:
                    # Document tabel bestaat niet of is niet beschikbaar
                    print(f"Warning: Could not get safety sheet for {item.serial}: {safety_error}")
                    safety_sheet_path = None
                    safety_sheet_url = None
                
                # Get documents for this material
                material_docs = documents_by_material.get(item.id, [])
                documents_list = []
                for doc in material_docs:
                    doc_url = ""
                    try:
                        if doc.file_path:
                            doc_url = get_file_url_from_path(doc.file_path) or ""
                    except Exception as doc_url_error:
                        print(f"Warning: Could not generate document URL: {doc_url_error}")
                        doc_url = ""
                    
                    documents_list.append({
                        "id": doc.id if doc.id else None,
                        "file_name": str(doc.file_name) if doc.file_name else "",
                        "file_path": str(doc.file_path) if doc.file_path else "",
                        "file_url": str(doc_url) if doc_url else "",
                        "document_type": str(doc.document_type) if doc.document_type else "",
                        "file_size": int(doc.file_size) if doc.file_size else 0,
                    })
                
                # Safely format purchase_date
                purchase_date_str = ""
                try:
                    if item.purchase_date:
                        purchase_date_str = item.purchase_date.strftime("%Y-%m-%d")
                except (AttributeError, ValueError, TypeError) as date_error:
                    print(f"Warning: Could not format purchase_date for {item.serial}: {date_error}")
                    purchase_date_str = ""
                
                # Format laatste_keuring from material (not from keuring_info)
                # Use purchase_date as fallback if laatste_keuring is not set (for display purposes)
                laatste_keuring_material_str = None
                try:
                    inspection_date = item.laatste_keuring or item.purchase_date
                    if inspection_date:
                        laatste_keuring_material_str = inspection_date.strftime("%Y-%m-%d")
                except (AttributeError, ValueError, TypeError) as date_error:
                    print(f"Warning: Could not format laatste_keuring for {item.serial}: {date_error}")
                    laatste_keuring_material_str = None
                
                # Format raw laatste_keuring value (without fallback) for editing purposes
                laatste_keuring_raw_str = None
                try:
                    if item.laatste_keuring:
                        laatste_keuring_raw_str = item.laatste_keuring.strftime("%Y-%m-%d")
                except (AttributeError, ValueError, TypeError) as date_error:
                    print(f"Warning: Could not format raw laatste_keuring for {item.serial}: {date_error}")
                    laatste_keuring_raw_str = None
                
                # Get inspection_validity_days from material_type
                inspection_validity_days = None
                try:
                    if item.material_type_id and item.material_type:
                        inspection_validity_days = item.material_type.inspection_validity_days
                except Exception as type_error:
                    print(f"Warning: Could not get inspection_validity_days for {item.serial}: {type_error}")
                    inspection_validity_days = None
                
                results.append(
                    {
                    "serial": str(item.serial) if item.serial else "",
                    "name": str(item.name) if item.name else "",
                    "type": str(item.type) if item.type else "",
                    "status": str(actual_status) if actual_status else "",
                    "is_in_use": bool(active_usages_count > 0),
                    "assigned_to": str(item.assigned_to) if item.assigned_to else "",
                    "site": str(item.site) if item.site else "",
                    "purchase_date": purchase_date_str,
                    "note": str(item.note) if item.note else "",
                    "nummer_op_materieel": str(item.nummer_op_materieel) if item.nummer_op_materieel else "",
                    "documentation_path": str(item.documentation_path) if item.documentation_path else "",
                    "documentation_url": str(documentation_url) if documentation_url else "",
                    "safety_sheet_path": str(safety_sheet_path) if safety_sheet_path else None,
                    "safety_sheet_url": str(safety_sheet_url) if safety_sheet_url else None,
                    "inspection_status": str(item.inspection_status).strip() if item.inspection_status and str(item.inspection_status).strip() else None,
                    "keuring_gepland": str(keuring_gepland) if keuring_gepland else None,
                    "laatste_keuring": str(laatste_keuring) if laatste_keuring else None,  # From keuring_info
                    "laatste_keuring_material": laatste_keuring_material_str,  # From material.laatste_keuring (with purchase_date fallback for display)
                    "laatste_keuring_raw": laatste_keuring_raw_str,  # Raw laatste_keuring value (no fallback) for editing
                    "inspection_validity_days": int(inspection_validity_days) if inspection_validity_days else None,
                    "documents": documents_list,
                    }
                )
            except Exception as e:
                # Log error for this item but continue with other items
                print(f"Error processing material {item.serial if item else 'unknown'}: {e}")
                continue
        
        return jsonify({"items": results}), 200
    except Exception as e:
        # Log the error and return a proper error response
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in api_search: {e}")
        print(f"Traceback: {error_details}")
        
        # Return a user-friendly error message
        error_message = f"Er is een fout opgetreden bij het zoeken: {str(e)}"
        return jsonify({
            "error": error_message,
            "error_type": type(e).__name__,
            "items": []
        }), 500

