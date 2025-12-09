"""
Materiaal blueprint - handles all material-related routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g
from models import db, Material, MaterialUsage, Project, MaterialType, Activity, Keuringstatus
from helpers import login_required, log_activity_db
from datetime import datetime
from sqlalchemy import or_, func
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

    query = Material.query

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

    total_items = Material.query.count()
    in_use = (
        db.session.query(func.count(MaterialUsage.id))
        .filter(MaterialUsage.is_active.is_(True))
        .scalar()
    ) or 0

    all_materials = Material.query.all()
    
    active_usages = (
        db.session.query(MaterialUsage, Material)
        .join(Material, MaterialUsage.material_id == Material.id)
        .filter(MaterialUsage.is_active.is_(True))
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
    
    items = query.all()
    items.sort(
        key=lambda it: (
            it.id not in active_material_ids,  # in gebruik (False) komt eerst
            (it.name or "").lower(),
        )
    )
    
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
        type_item.material_count = Material.query.filter_by(type=type_item.name).count()
    
    return render_template(
        "materiaal_types.html",
        types=types,
        search_q=search_q,
    )


@materiaal_bp.route("/types/new", methods=["POST"])
@login_required
def materiaal_type_toevoegen():
    """Voeg een nieuw materiaal type toe."""
    from app import app, save_upload
    
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
        type_image_path = save_upload(type_image_file, app.config["TYPE_IMAGE_UPLOAD_FOLDER"], prefix)
    
    safety_sheet_path = None
    if safety_sheet_file and safety_sheet_file.filename:
        filename = secure_filename(safety_sheet_file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext != '.pdf':
            flash("Veiligheidsfiche moet een PDF bestand zijn.", "danger")
            return redirect(url_for("materiaal.materiaal_types"))
        
        prefix = secure_filename(name)
        safety_sheet_path = save_upload(safety_sheet_file, app.config["SAFETY_UPLOAD_FOLDER"], prefix)
    
    new_type = MaterialType(
        name=name,
        description=description if description else None,
        inspection_validity_days=inspection_validity_days,
        type_image=type_image_path,
        safety_sheet=safety_sheet_path,
    )
    
    db.session.add(new_type)
    db.session.commit()
    
    log_activity_db("materiaal type toegevoegd", name, "")
    flash(f"Type '{name}' is toegevoegd.", "success")
    return redirect(url_for("materiaal.materiaal_types"))


@materiaal_bp.route("/types/edit", methods=["POST"])
@login_required
def materiaal_type_bewerken():
    """Bewerk een bestaand materiaal type."""
    from app import app, save_upload
    
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
            old_path = os.path.join(app.root_path, "static", type_item.type_image)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except:
                    pass
        
        prefix = secure_filename(name)
        type_item.type_image = save_upload(type_image_file, app.config["TYPE_IMAGE_UPLOAD_FOLDER"], prefix)
    
    if safety_sheet_file and safety_sheet_file.filename:
        filename = secure_filename(safety_sheet_file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext != '.pdf':
            flash("Veiligheidsfiche moet een PDF bestand zijn.", "danger")
            return redirect(url_for("materiaal.materiaal_types"))
        
        if type_item.safety_sheet:
            old_path = os.path.join(app.root_path, "static", type_item.safety_sheet)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except:
                    pass
        
        prefix = secure_filename(name)
        type_item.safety_sheet = save_upload(safety_sheet_file, app.config["SAFETY_UPLOAD_FOLDER"], prefix)
    
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
    from app import app
    
    type_id = request.form.get("type_id")
    
    if not type_id:
        flash("Type ID ontbreekt.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    type_item = MaterialType.query.get(type_id)
    if not type_item:
        flash("Type niet gevonden.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    # Check if any materials use this type
    materials_using_type = Material.query.filter_by(type=type_item.name).count()
    if materials_using_type > 0:
        flash(f"Kan type '{type_item.name}' niet verwijderen: {materials_using_type} materiaal(en) gebruiken dit type.", "danger")
        return redirect(url_for("materiaal.materiaal_types"))
    
    # Delete associated files
    if type_item.type_image:
        old_path = os.path.join(app.root_path, "static", type_item.type_image)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except:
                pass
    
    if type_item.safety_sheet:
        old_path = os.path.join(app.root_path, "static", type_item.safety_sheet)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except:
                pass
    
    type_name = type_item.name
    db.session.delete(type_item)
    db.session.commit()
    
    log_activity_db("materiaal type verwijderd", type_name, "")
    flash(f"Type '{type_name}' is verwijderd.", "success")
    return redirect(url_for("materiaal.materiaal_types"))

