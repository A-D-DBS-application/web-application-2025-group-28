"""
Materiaal blueprint - handles all material-related routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g, current_app
from models import db, Material, MaterialUsage, Project, MaterialType, Activity, Keuringstatus, Document
from helpers import login_required, log_activity_db, save_upload, save_upload_to_supabase
from services import MaterialService, MaterialUsageService
from constants import DEFAULT_INSPECTION_STATUS, DOCUMENT_TYPES
from datetime import datetime
from sqlalchemy import or_, func, case, text
from werkzeug.utils import secure_filename
import os

materiaal_bp = Blueprint('materiaal', __name__, url_prefix='/materiaal')

# Import helper functions from app.py (will be moved later)
# For now, we'll import them or define them here
def update_verlopen_keuringen():
    """Update expired inspections automatically"""
    from models import Keuringstatus
    today = datetime.utcnow().date()
    
    keuringen_met_verlopen_datum = Keuringstatus.query.filter(
        Keuringstatus.volgende_controle.isnot(None),
        Keuringstatus.volgende_controle < today,
        Keuringstatus.laatste_controle.is_(None)
    ).all()
    
    updated_count = 0
    for keuring in keuringen_met_verlopen_datum:
        if not keuring.serienummer:
            continue
        material = Material.query.filter_by(serial=keuring.serienummer).first()
        if material:
            material.inspection_status = "keuring verlopen"
            updated_count += 1
    
    if updated_count > 0:
        db.session.commit()
    
    return updated_count


@materiaal_bp.route("", methods=["GET"])
@login_required
def materiaal():
    """Materiaal overzicht"""
    update_verlopen_keuringen()
    
    q = (request.args.get("q") or "").strip().lower()
    type_filter = (request.args.get("type") or "").strip().lower()
    status = (request.args.get("status") or "").strip().lower()

    query = Material.query.filter(
        or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
    )

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Material.name.ilike(like), Material.serial.ilike(like))
        )

    if type_filter:
        query = query.filter(Material.type.ilike(f"%{type_filter}%"))

    if status:
        if status == "in gebruik":
            query = query.filter(Material.status == "in gebruik")
        elif status == "niet in gebruik":
            query = query.filter(Material.status != "in gebruik")

    total_items = Material.query.filter(
        or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
    ).count()
    in_use = (
        db.session.query(func.count(MaterialUsage.id))
        .join(Material, MaterialUsage.material_id == Material.id)
        .filter(MaterialUsage.is_active.is_(True))
        .filter(or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None)))
        .scalar()
    ) or 0

    all_materials = Material.query.filter(
        or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
    ).all()
    
    active_usages = (
        db.session.query(MaterialUsage, Material)
        .join(Material, MaterialUsage.material_id == Material.id)
        .filter(MaterialUsage.is_active.is_(True))
        .filter(or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None)))
        .order_by(MaterialUsage.start_time.desc())
        .all()
    )

    my_usages = []
    other_usages = []
    usages_without_project = []
    
    current_user_name = g.user.Naam if getattr(g, "user", None) else None

    for usage, material in active_usages:
        row = {
            "id": usage.id,
            "material_id": material.id,
            "name": material.name,
            "serial": material.serial,
            "site": usage.site or "",
            "used_by": usage.used_by or "",
            "start_time": usage.start_time,
            "project_id": usage.project_id,
            "material": material,  # Voor backward compatibility
            "project": usage.project,
        }
        
        # Check if usage has no project
        if usage.project_id is None:
            usages_without_project.append(row)
        
        # Check if the "used_by" name matches the logged-in user's name
        usage_name = (usage.used_by or "").strip()
        if current_user_name and usage_name.lower() == current_user_name.lower():
            my_usages.append(row)
        else:
            other_usages.append(row)

    # Items ophalen en sorteren: eerst materiaal dat in gebruik is, daarna de rest
    active_material_ids = set()
    for usage_dict in my_usages + other_usages:
        if 'material' in usage_dict and usage_dict['material']:
            active_material_ids.add(usage_dict['material'].id)
    
    # Use SQL ORDER BY instead of Python sorting for better performance
    if active_material_ids:
        query = query.order_by(
            case((Material.id.in_(active_material_ids), 0), else_=1),
            Material.name.asc()
        )
    else:
        query = query.order_by(Material.name.asc())
    
    items = query.all()
    
    # Get all unique types from materials for the filter dropdown
    unique_types = (
        db.session.query(Material.type)
        .filter(Material.type.isnot(None))
        .filter(Material.type != "")
        .distinct()
        .order_by(Material.type)
        .all()
    )
    types_list = [t[0] for t in unique_types if t[0]]
    
    # Get all Material Types for the dropdown in modals
    all_material_types = MaterialType.query.order_by(MaterialType.name.asc()).all()
    
    # Werven voor de dropdown in "Gebruik Materieel"
    from models import Project
    from datetime import datetime
    today = datetime.utcnow().date()
    projects = (
        Project.query.filter_by(is_deleted=False)
        .order_by(Project.start_date.asc())
        .all()
    )

    return render_template(
        "materiaal.html",
        items=items,  # Template verwacht 'items', niet 'materials'
        total_items=total_items,
        in_use=in_use,
        my_usages=my_usages,
        other_usages=other_usages,
        usages_without_project=usages_without_project,
        all_materials=all_materials,
        all_material_types=all_material_types,
        active_material_ids=active_material_ids,
        types_list=types_list,
        projects=projects,
        today=today,
        search_q=q,
    )


@materiaal_bp.route("/types", methods=["GET"])
@login_required
def materiaal_types():
    """Materiaal types overzicht"""
    search_q = (request.args.get("q") or "").strip().lower()
    
    query = MaterialType.query
    
    if search_q:
        query = query.filter(
            or_(
                MaterialType.name.ilike(f"%{search_q}%"),
                MaterialType.description.ilike(f"%{search_q}%")
            )
        )
    
    types = query.order_by(MaterialType.name).all()
    
    # Tel aantal materialen per type
    for type_item in types:
        type_item.material_count = Material.query.filter(
            Material.type == type_item.name,
            or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
        ).count()
    
    return render_template(
        "materiaal_types.html",
        types=types,
        search_q=search_q,
    )


@materiaal_bp.route("/types/new", methods=["POST"])
@login_required
def materiaal_type_toevoegen():
    """Voeg een nieuw materiaal type toe."""
    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    inspection_validity_days = request.form.get("inspection_validity_days")
    type_image_file = request.files.get("type_image")
    safety_sheet_file = request.files.get("safety_sheet")
    
    if not name:
        flash("Type naam is verplicht.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    if not inspection_validity_days:
        flash("Geldigheid keuring (dagen) is verplicht.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    try:
        inspection_validity_days = int(inspection_validity_days)
        if inspection_validity_days < 1:
            flash("Geldigheid keuring moet minimaal 1 dag zijn.", "danger")
            return redirect(url_for("materiaal.materiaal_types"))
    except (ValueError, TypeError):
        flash("Geldigheid keuring moet een geldig nummer zijn.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    existing = MaterialType.query.filter_by(name=name).first()
    if existing:
        flash(f"Type '{name}' bestaat al.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    type_image_path = None
    if type_image_file and type_image_file.filename:
        filename = secure_filename(type_image_file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png']:
            flash("Foto moet een .jpg, .jpeg of .png bestand zijn.", "danger")
            return redirect(url_for("materiaal.materiaal_types"))
        
        prefix = secure_filename(name)
        type_image_path = save_upload(type_image_file, current_app.config["TYPE_IMAGE_UPLOAD_FOLDER"], prefix)
    
    safety_sheet_path = None
    if safety_sheet_file and safety_sheet_file.filename:
        filename = secure_filename(safety_sheet_file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext != '.pdf':
            flash("Veiligheidsfiche moet een PDF bestand zijn.", "danger")
            return redirect(url_for("materiaal.materiaal_types"))
        
        prefix = secure_filename(name)
        safety_sheet_path = save_upload(safety_sheet_file, current_app.config["SAFETY_UPLOAD_FOLDER"], prefix)
    
    new_type = MaterialType(
        name=name,
        description=description if description else None,
        inspection_validity_days=inspection_validity_days,
        type_image=type_image_path,
        safety_sheet=safety_sheet_path,
    )
    
    db.session.add(new_type)
    db.session.flush()  # Flush om ID te krijgen voor Document record
    
    # Maak Document record aan voor veiligheidsfiche in documenten tabel
    if safety_sheet_path:
        # Upload naar Supabase Storage bucket "Veiligheidsfiche"
        safety_sheet_file.seek(0)  # Reset file pointer
        bucket = "Veiligheidsfiche"
        file_path = save_upload_to_supabase(
            safety_sheet_file,
            bucket_name=bucket,
            folder="",
            prefix=f"{name.lower().replace(' ', '_')}_veiligheidsfiche"
        )
        
        if file_path:
            # Bereken bestandsgrootte
            safety_sheet_file.seek(0, 2)  # Ga naar einde
            file_size = safety_sheet_file.tell()
            safety_sheet_file.seek(0)  # Reset
            
            user_name = g.user.naam if g.user else "Onbekend"
            document = Document(
                document_type="Veiligheidsfiche",
                file_path=file_path,
                file_name=filename,
                file_size=file_size,
                material_id=None,
                material_type_id=new_type.id,
                material_type=name,
                uploaded_by=user_name,
                user_id=g.user.gebruiker_id if g.user else None,
                note=None,
                aangemaakt_op=datetime.utcnow()
            )
            db.session.add(document)
    
    db.session.commit()
    
    log_activity_db("materiaal type toegevoegd", name, "")
    flash(f"Type '{name}' is toegevoegd.", "success")
    return redirect(url_for("materiaal.materiaal_types"))


@materiaal_bp.route("/types/edit", methods=["POST"])
@login_required
def materiaal_type_bewerken():
    """Bewerk een bestaand materiaal type."""
    type_id = request.form.get("type_id")
    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    inspection_validity_days = request.form.get("inspection_validity_days")
    type_image_file = request.files.get("type_image")
    safety_sheet_file = request.files.get("safety_sheet")
    
    if not type_id:
        flash("Type ID ontbreekt.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    type_item = MaterialType.query.get(type_id)
    if not type_item:
        flash("Type niet gevonden.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    if not name:
        flash("Type naam is verplicht.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    if not inspection_validity_days:
        flash("Geldigheid keuring (dagen) is verplicht.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    try:
        inspection_validity_days = int(inspection_validity_days)
        if inspection_validity_days < 1:
            flash("Geldigheid keuring moet minimaal 1 dag zijn.", "danger")
            return redirect(url_for("materiaal.materiaal_types"))
    except (ValueError, TypeError):
        flash("Geldigheid keuring moet een geldig nummer zijn.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    existing = MaterialType.query.filter_by(name=name).first()
    if existing and existing.id != type_item.id:
        flash(f"Type '{name}' bestaat al.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    old_name = type_item.name
    
    if type_image_file and type_image_file.filename:
        filename = secure_filename(type_image_file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png']:
            flash("Foto moet een .jpg, .jpeg of .png bestand zijn.", "danger")
            return redirect(url_for("materiaal.materiaal_types"))
        
        if type_item.type_image:
            old_path = os.path.join(current_app.root_path, "static", type_item.type_image)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except:
                    pass
        
        prefix = secure_filename(name)
        type_item.type_image = save_upload(type_image_file, current_app.config["TYPE_IMAGE_UPLOAD_FOLDER"], prefix)
    
    if safety_sheet_file and safety_sheet_file.filename:
        filename = secure_filename(safety_sheet_file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext != '.pdf':
            flash("Veiligheidsfiche moet een PDF bestand zijn.", "danger")
            return redirect(url_for("materiaal.materiaal_types"))
        
        if type_item.safety_sheet:
            old_path = os.path.join(current_app.root_path, "static", type_item.safety_sheet)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except:
                    pass
        
        prefix = secure_filename(name)
        type_item.safety_sheet = save_upload(safety_sheet_file, current_app.config["SAFETY_UPLOAD_FOLDER"], prefix)
        
        # Maak/update Document record aan voor veiligheidsfiche in documenten tabel
        if type_item.safety_sheet:
            # Verwijder oude Document record als die bestaat
            old_doc = Document.query.filter_by(
                material_type_id=type_item.id,
                document_type="Veiligheidsfiche"
            ).first()
            if old_doc:
                db.session.delete(old_doc)
            
            # Upload naar Supabase Storage bucket "Veiligheidsfiche"
            safety_sheet_file.seek(0)  # Reset file pointer
            bucket = "Veiligheidsfiche"
            file_path = save_upload_to_supabase(
                safety_sheet_file,
                bucket_name=bucket,
                folder="",
                prefix=f"{name.lower().replace(' ', '_')}_veiligheidsfiche"
            )
            
            if file_path:
                # Bereken bestandsgrootte
                safety_sheet_file.seek(0, 2)  # Ga naar einde
                file_size = safety_sheet_file.tell()
                safety_sheet_file.seek(0)  # Reset
                
                filename = secure_filename(safety_sheet_file.filename)
                user_name = g.user.naam if g.user else "Onbekend"
                document = Document(
                    document_type="Veiligheidsfiche",
                    file_path=file_path,
                    file_name=filename,
                    file_size=file_size,
                    material_id=None,
                    material_type_id=type_item.id,
                    material_type=name,
                    uploaded_by=user_name,
                    user_id=g.user.gebruiker_id if g.user else None,
                    note=None,
                    aangemaakt_op=datetime.utcnow()
                )
                db.session.add(document)
    
    type_item.name = name
    type_item.description = description if description else None
    type_item.inspection_validity_days = inspection_validity_days
    
    db.session.commit()
    
    log_activity_db("materiaal type bewerkt", f"{old_name} -> {name}", "")
    flash(f"Type '{name}' is bijgewerkt.", "success")
    return redirect(url_for("materiaal.materiaal_types"))


@materiaal_bp.route("/types/delete", methods=["POST"])
@login_required
def materiaal_type_verwijderen():
    """Verwijder een materiaal type."""
    type_id = request.form.get("type_id")
    
    if not type_id:
        flash("Type ID ontbreekt.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    type_item = MaterialType.query.get(type_id)
    if not type_item:
        flash("Type niet gevonden.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    # Check if any materials use this type
    materials_using_type = Material.query.filter(
        Material.type == type_item.name,
        or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
    ).count()
    if materials_using_type > 0:
        flash(f"Kan type '{type_item.name}' niet verwijderen: {materials_using_type} materiaal(en) gebruiken dit type.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    # Delete associated files
    if type_item.type_image:
        old_path = os.path.join(current_app.root_path, "static", type_item.type_image)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except:
                pass
    
    if type_item.safety_sheet:
        old_path = os.path.join(current_app.root_path, "static", type_item.safety_sheet)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except:
                pass
    
    type_name = type_item.name
    
    # Use no_autoflush to prevent SQLAlchemy from querying related tables (like documenten)
    # that might not exist in the database
    try:
        with db.session.no_autoflush:
            db.session.delete(type_item)
        db.session.commit()
    except Exception as e:
        # If there's an error (e.g., documenten table doesn't exist), 
        # try a direct SQL delete to bypass relationship loading
        db.session.rollback()
        try:
            # Use raw SQL delete to bypass relationship loading
            db.session.execute(
                text("DELETE FROM materiaal_types WHERE id = :id"),
                {"id": int(type_id)}
            )
            db.session.commit()
        except Exception as e2:
            db.session.rollback()
            flash(f"Fout bij verwijderen type: {str(e2)}", "danger")
            return redirect(url_for("materiaal.materiaal_types"))
    
    log_activity_db("materiaal type verwijderd", type_name, "")
    flash(f"Type '{type_name}' is verwijderd.", "success")
    return redirect(url_for("materiaal.materiaal_types"))


# -----------------------------------------------------
# MATERIAAL CRUD ROUTES
# -----------------------------------------------------


@materiaal_bp.route("/new", methods=["POST"])
@login_required
def materiaal_toevoegen():
    """
    Nieuw materiaal AANMAKEN.
    Dit is wat gebeurt via het plus-icoon.
    """
    # Admin check
    if not getattr(g.user, 'is_admin', False):
        flash("Geen toegang tot deze functie. Alleen admins kunnen materiaal toevoegen.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    f = request.form
    name = (f.get("name") or "").strip()
    serial = (f.get("serial") or "").strip()
    nummer = (f.get("nummer_op_materieel") or "").strip()
    type_ = (f.get("type") or "").strip()
    purchase_date_str = (f.get("purchase_date") or "").strip()
    project_id_str = (f.get("project_id") or "").strip()
    assigned_to = (f.get("assigned_to") or "").strip()
    note = (f.get("note") or "").strip()
    keuring_status = (f.get("keuring_status") or DEFAULT_INSPECTION_STATUS).strip()
    laatste_keuring_str = (f.get("laatste_keuring") or "").strip()
    datum_geplande_keuring_str = (f.get("datum_geplande_keuring") or "").strip()
    document_type = (f.get("document_type") or "Aankoopfactuur").strip()  # Default naar Aankoopfactuur
    documentation_file = request.files.get("documentation")

    # Validate: if keuring_status is "keuring gepland", datum_geplande_keuring is required
    if keuring_status == "keuring gepland" and not datum_geplande_keuring_str:
        flash("Datum geplande keuring is verplicht wanneer 'Keuring gepland' is geselecteerd.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    # Get project if project_id is provided
    project_id = int(project_id_str) if project_id_str else None
    project = None
    site = None
    if project_id:
        project = Project.query.filter_by(id=project_id, is_deleted=False).first()
        if project:
            site = project.name

    documentation_file = request.files.get("documentation")

    if not name or not serial:
        flash("Naam en serienummer zijn verplicht.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    # Use service to check if serial exists
    bestaand = MaterialService.find_by_serial(serial)
    if bestaand:
        flash("Serienummer bestaat al in het systeem.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    documentation_path = None
    if documentation_file and documentation_file.filename:
        documentation_path = save_upload(
            documentation_file, current_app.config["DOC_UPLOAD_FOLDER"], f"{serial}_doc"
        )

    item = Material(
        name=name,
        serial=serial,
        type=type_,
        assigned_to=assigned_to if assigned_to else None,
        site=site if site else None,
        project_id=project_id,
        note=note if note else None,
        status=DEFAULT_INSPECTION_STATUS,  # Keep status for backward compatibility
        nummer_op_materieel=nummer if nummer else None,
        documentation_path=documentation_path,
    )

    if purchase_date_str:
        try:
            item.purchase_date = datetime.strptime(purchase_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    # Set material_type_id if type is provided
    if type_:
        material_type = MaterialType.query.filter_by(name=type_).first()
        if material_type:
            item.material_type_id = material_type.id
    
    # Set inspection_status (keuring_status) and laatste_keuring
    if hasattr(item, "inspection_status"):
        item.inspection_status = keuring_status
    
    if laatste_keuring_str:
        try:
            item.laatste_keuring = datetime.strptime(laatste_keuring_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    # Note: No fallback to purchase_date - expiry calculation only uses laatste_keuring

    db.session.add(item)
    db.session.flush()  # Flush to get the item.id before creating related records
    
    # Maak Document record aan voor documentatie in documenten tabel
    if documentation_path and documentation_file and documentation_file.filename:
        # Upload naar Supabase Storage bucket op basis van document type
        bucket_mapping = {
            "Aankoopfactuur": "Aankoop-Verkoop documenten",
            "Verkoopfactuur": "Aankoop-Verkoop documenten",
            "Keuringstatus": "Keuringsstatus documenten",
            "Veiligheidsfiche": "Veiligheidsfiche"
        }
        bucket = bucket_mapping.get(document_type, "Aankoop-Verkoop documenten")
        
        documentation_file.seek(0)  # Reset file pointer
        file_path = save_upload_to_supabase(
            documentation_file,
            bucket_name=bucket,
            folder="",
            prefix=f"{serial}_{document_type.lower().replace(' ', '_')}"
        )
        
        if file_path:
            # Bereken bestandsgrootte
            documentation_file.seek(0, 2)  # Ga naar einde
            file_size = documentation_file.tell()
            documentation_file.seek(0)  # Reset
            
            filename = secure_filename(documentation_file.filename)
            user_name = g.user.naam if g.user else "Onbekend"
            document = Document(
                document_type=document_type,
                file_path=file_path,
                file_name=filename,
                file_size=file_size,
                material_id=item.id,
                material_type_id=None,
                material_type=None,
                uploaded_by=user_name,
                user_id=g.user.gebruiker_id if g.user else None,
                note=None,
                aangemaakt_op=datetime.utcnow()
            )
            db.session.add(document)
    
    # Check if inspection is expired based on laatste_keuring + keuring_geldigheid_dagen
    # This MUST override user-selected status
    if item.laatste_keuring and MaterialService.check_inspection_expiry(item):
        item.inspection_status = "keuring verlopen"
        keuring_status = "keuring verlopen"  # Update for Keuringstatus record creation

    # If keuring_status is "keuring gepland" and datum_geplande_keuring is provided, create Keuringstatus record
    if keuring_status == "keuring gepland" and datum_geplande_keuring_str:
        try:
            volgende_controle_date = datetime.strptime(datum_geplande_keuring_str, "%Y-%m-%d").date()
            user_id = g.user.gebruiker_id if getattr(g, "user", None) and hasattr(g.user, "gebruiker_id") else None
            
            keuring_record = Keuringstatus(
                serienummer=serial,
                laatste_controle=None,
                volgende_controle=volgende_controle_date,
                uitgevoerd_door=None,
                opmerkingen=None,
                updated_by=user_id,
            )
            db.session.add(keuring_record)
        except ValueError:
            # Invalid date format, skip creating keuring record
            pass

    db.session.commit()

    log_activity_db("Toegevoegd", item.name or "", item.serial or "")
    flash("Nieuw materiaal is succesvol toegevoegd", "success")
    return redirect(url_for("materiaal.materiaal"))


@materiaal_bp.route("/edit", methods=["POST"])
@login_required
def materiaal_bewerken():
    f = request.form
    original_serial = (f.get("original_serial") or "").strip()
    item = MaterialService.find_by_serial(original_serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    new_serial = (f.get("serial") or "").strip()
    if not new_serial:
        flash("Serienummer is verplicht.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    if new_serial != original_serial and MaterialService.find_by_serial(new_serial):
        flash("Nieuw serienummer bestaat al.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    item.serial = new_serial
    item.name = (f.get("name") or "").strip()
    type_ = (f.get("type") or "").strip()
    item.type = type_

    # Update material_type_id if type is provided
    if type_:
        material_type = MaterialType.query.filter_by(name=type_).first()
        if material_type:
            item.material_type_id = material_type.id

    purchase_date = (f.get("purchase_date") or "").strip()
    if purchase_date:
        try:
            item.purchase_date = datetime.strptime(purchase_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    # Update laatste_keuring if provided
    laatste_keuring_str = (f.get("laatste_keuring") or "").strip()
    if laatste_keuring_str:
        try:
            item.laatste_keuring = datetime.strptime(laatste_keuring_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    # Note: No fallback to purchase_date - expiry calculation only uses laatste_keuring

    item.assigned_to = (f.get("assigned_to") or "").strip()
    item.site = (f.get("site") or "").strip()
    item.note = (f.get("note") or "").strip()
    
    # Get keuring status from form
    keuring_status = (f.get("status") or DEFAULT_INSPECTION_STATUS).strip()
    
    # Use service to update material status based on active usages
    MaterialService.update_material_status(item)
    
    # inspection_status kolom: de keuringstatus
    item.inspection_status = keuring_status
    
    # Check if inspection is expired based on laatste_keuring + keuring_geldigheid_dagen
    # This MUST override user-selected status
    if item.laatste_keuring and MaterialService.check_inspection_expiry(item):
        item.inspection_status = "keuring verlopen"
    
    item.nummer_op_materieel = (f.get("nummer_op_materieel") or "").strip()

    documentation_file = request.files.get("documentation")
    document_type = (f.get("document_type") or "Aankoopfactuur").strip()  # Default naar Aankoopfactuur

    if documentation_file and documentation_file.filename:
        # Upload naar Supabase Storage bucket op basis van document type
        bucket_mapping = {
            "Aankoopfactuur": "Aankoop-Verkoop documenten",
            "Verkoopfactuur": "Aankoop-Verkoop documenten",
            "Keuringstatus": "Keuringsstatus documenten",
            "Veiligheidsfiche": "Veiligheidsfiche"
        }
        bucket = bucket_mapping.get(document_type, "Aankoop-Verkoop documenten")
        
        # Upload naar Supabase
        documentation_file.seek(0)  # Reset file pointer
        file_path = save_upload_to_supabase(
            documentation_file,
            bucket_name=bucket,
            folder="",
            prefix=f"{item.serial}_{document_type.lower().replace(' ', '_')}"
        )
        
        if file_path:
            # Update documentation_path voor backward compatibility
            item.documentation_path = file_path
            
            # Bereken bestandsgrootte
            documentation_file.seek(0, 2)  # Ga naar einde
            file_size = documentation_file.tell()
            documentation_file.seek(0)  # Reset
            
            filename = secure_filename(documentation_file.filename)
            user_name = g.user.naam if g.user else "Onbekend"
            
            # Verwijder oude Document record als die bestaat
            old_doc = Document.query.filter_by(
                material_id=item.id,
                document_type=document_type
            ).first()
            if old_doc:
                db.session.delete(old_doc)
            
            # Maak nieuw Document record aan
            document = Document(
                document_type=document_type,
                file_path=file_path,
                file_name=filename,
                file_size=file_size,
                material_id=item.id,
                material_type_id=None,
                material_type=None,
                uploaded_by=user_name,
                user_id=g.user.gebruiker_id if g.user else None,
                note=None,
                aangemaakt_op=datetime.utcnow()
            )
            db.session.add(document)

    db.session.commit()

    log_activity_db("Bewerkt", item.name or "", item.serial or "")
    flash("Materieel bewerkt.", "success")
    return redirect(url_for("materiaal.materiaal"))


@materiaal_bp.route("/delete", methods=["POST"])
@login_required
def materiaal_verwijderen():
    # Admin check
    if not getattr(g.user, 'is_admin', False):
        flash("Geen toegang tot deze functie. Alleen admins kunnen materiaal verwijderen.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    serial = (request.form.get("serial") or "").strip()
    
    # Use session.no_autoflush to prevent SQLAlchemy from querying related tables (like documenten)
    # that might not exist
    with db.session.no_autoflush:
        item = MaterialService.find_by_serial(serial)
        if not item:
            flash("Item niet gevonden.", "danger")
            return redirect(url_for("materiaal.materiaal"))

        # Soft delete: mark as deleted instead of actually deleting
        item.is_deleted = True
        
        # Stop all active usages for this material
        MaterialUsage.query.filter_by(material_id=item.id, is_active=True).update(
            {'is_active': False, 'end_time': datetime.utcnow()},
            synchronize_session=False
        )

    db.session.commit()

    log_activity_db("Verwijderd", item.name or "", serial)
    flash("Materieel verwijderd.", "success")
    return redirect(url_for("materiaal.materiaal"))


@materiaal_bp.route("/document/delete", methods=["POST"])
@login_required
def materiaal_document_verwijderen():
    """Verwijder een document (documentatie of veiligheidsfiche) van een materiaal item"""
    serial = (request.form.get("serial") or "").strip()
    doc_type = (request.form.get("doc_type") or "").strip()  # "documentation" of "safety"
    
    if not serial or not doc_type:
        flash("Ongeldige aanvraag.", "danger")
        return redirect(url_for("materiaal.materiaal"))
    
    item = MaterialService.find_by_serial(serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal.materiaal"))
    
    # Bepaal welk pad moet worden verwijderd
    file_path = None
    field_name = None
    
    if doc_type == "documentation":
        file_path = item.documentation_path
        field_name = "documentation_path"
    else:
        flash("Ongeldig document type.", "danger")
        return redirect(url_for("materiaal.materiaal"))
    
    # Verwijder fysiek bestand als het bestaat
    if file_path:
        full_path = os.path.join(current_app.root_path, "static", file_path)
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except OSError as e:
                # Log error maar ga door met database update
                print(f"Fout bij verwijderen bestand {full_path}: {e}")
    
    # Verwijder pad uit database
    setattr(item, field_name, None)
    db.session.commit()
    
    doc_name = "Documentatie"
    log_activity_db(f"{doc_name} verwijderd", item.name or "", item.serial or "")
    flash(f"{doc_name} verwijderd.", "success")
    return redirect(url_for("materiaal.materiaal"))


@materiaal_bp.route("/use", methods=["POST"])
@login_required
def materiaal_gebruiken():
    """
    Materieel in gebruik nemen – schrijft naar material_usage + activity_log.
    """
    f = request.form

    name = (f.get("name") or "").strip()
    nummer = (f.get("nummer_op_materieel") or "").strip()
    assigned_to = (f.get("assigned_to") or "").strip()
    site = (f.get("site") or "").strip()
    project_id_str = (f.get("project_id") or "").strip()

    project_id = int(project_id_str) if project_id_str else None
    project = None
    if project_id:
        project = Project.query.filter_by(id=project_id, is_deleted=False).first()

    if not name and not nummer:
        flash("Naam of nummer op materieel is verplicht.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    item = MaterialService.find_by_name_or_number(name, nummer)
    if not item:
        flash("Materiaal niet gevonden in het datasysteem.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    if not assigned_to and getattr(g, "user", None):
        assigned_to = g.user.Naam or ""

    # Use service to start usage
    try:
        user_id = g.user.gebruiker_id
        # Get project if project_id provided
        project_obj = None
        if project_id:
            project_obj = Project.query.filter_by(id=project_id, is_deleted=False).first()
        site_value = site or (project_obj.name if project_obj else None)
        MaterialUsageService.start_usage(
            material=item,
            user_id=user_id,
            used_by=assigned_to or (g.user.Naam if getattr(g, "user", None) else ""),
            project_id=project_id,
            site=site_value
        )
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("materiaal.materiaal"))

    log_activity_db("In gebruik", item.name or "", item.serial or "")
    flash("Materieel staat nu als 'in gebruik'.", "success")
    return redirect(url_for("materiaal.materiaal"))


@materiaal_bp.route("/stop", methods=["POST"])
@login_required
def materiaal_stop_gebruik():
    usage_id = request.form.get("usage_id", "").strip()
    if not usage_id:
        flash("Geen gebruiksessie gevonden.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    current_user_name = g.user.Naam if getattr(g, "user", None) else ""
    is_admin = getattr(g.user, 'is_admin', False) if getattr(g, "user", None) else False

    # Use service to stop usage
    try:
        usage = MaterialUsageService.stop_usage(
            usage_id=int(usage_id),
            user_name=current_user_name,
            is_admin=is_admin
        )
        mat = Material.query.filter_by(id=usage.material_id).first()
        if mat:
            log_activity_db("Niet meer in gebruik", mat.name or "", mat.serial or "")
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("materiaal.materiaal"))
    except PermissionError as e:
        flash(str(e), "danger")
        return redirect(url_for("materiaal.materiaal"))

    flash("Materieel wordt niet langer als 'in gebruik' getoond.", "success")
    return redirect(url_for("materiaal.materiaal"))


@materiaal_bp.route("/assign_to_project", methods=["POST"])
@login_required
def materiaal_assign_to_project():
    """
    Koppel een actief materiaal gebruik aan een werf.
    """
    usage_id = (request.form.get("usage_id") or "").strip()
    project_id = (request.form.get("project_id") or "").strip()

    if not usage_id or not project_id:
        flash("Selecteer een werf om het materiaal aan te koppelen.", "danger")
        return redirect(url_for("materiaal.materiaal"))

    # Use service to assign to project
    try:
        usage = MaterialUsageService.assign_to_project(
            usage_id=int(usage_id),
            project_id=int(project_id)
        )
        mat = Material.query.filter_by(id=usage.material_id).first()
        project = Project.query.filter_by(id=int(project_id), is_deleted=False).first()
        if project and mat:
            log_activity_db(
                f"Gekoppeld aan werf {project.name}", mat.name or "", mat.serial or ""
            )
            flash(f"Materiaal is gekoppeld aan werf '{project.name}'.", "success")
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("materiaal.materiaal"))

    return redirect(url_for("materiaal.materiaal"))

