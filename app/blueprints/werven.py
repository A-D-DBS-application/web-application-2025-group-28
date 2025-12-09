"""
Werven blueprint - handles all project/werf-related routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, g, current_app
from models import db, Material, MaterialUsage, Project
from helpers import login_required, log_activity_db, save_project_image, get_file_url_from_path
from services import MaterialService
from datetime import datetime
from sqlalchemy import or_
import csv
from io import StringIO

werven_bp = Blueprint('werven', __name__)


def find_material_by_name_or_number(name: str, nummer: str | None):
    """Find material by name or number"""
    return MaterialService.find_by_name_or_number(name, nummer)


@werven_bp.route("/werven")
@login_required
def werven():
    today = datetime.utcnow().date()
    search_q = (request.args.get("q") or "").strip().lower()
    
    # Alle werven voor autocomplete suggesties
    all_projects = Project.query.filter_by(is_deleted=False).order_by(Project.name).all()
    
    query = Project.query.filter_by(is_deleted=False)
    
    # Filter op zoekterm
    if search_q:
        query = query.filter(
            or_(
                Project.name.ilike(f"%{search_q}%"),
                Project.address.ilike(f"%{search_q}%"),
                Project.type.ilike(f"%{search_q}%"),
            )
        )
    
    projects = query.order_by(Project.start_date.asc()).all()
    return render_template("werven.html", projects=projects, all_projects=all_projects, today=today, search_q=search_q)


@werven_bp.route("/werven/new", methods=["POST"])
@login_required
def werf_toevoegen():
    f = request.form

    name = (f.get("name") or "").strip()
    type_ = (f.get("type") or "").strip()
    address = (f.get("address") or "").strip()
    start_date_str = (f.get("start_date") or "").strip()
    end_date_str = (f.get("end_date") or "").strip()
    note = (f.get("note") or "").strip()

    image_file = request.files.get("image_file")

    if not name or not start_date_str:
        flash("Naam en startdatum zijn verplicht voor een werf.", "danger")
        return redirect(url_for("werven.werven"))

    start_date = None
    end_date = None
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige startdatum.", "danger")
        return redirect(url_for("werven.werven"))

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Ongeldige einddatum.", "danger")
            return redirect(url_for("werven.werven"))

    image_path = save_project_image(image_file, name.replace(" ", "_")) if image_file else None

    project = Project(
        name=name,
        address=address or None,
        start_date=start_date,
        end_date=end_date,
        type=type_ or None,
        image_url=image_path,
        note=note or None,
        is_deleted=False,
        created_at=datetime.utcnow(),
    )

    db.session.add(project)
    db.session.commit()

    flash("Nieuwe werf toegevoegd.", "success")
    return redirect(url_for("werven.werven"))


@werven_bp.route("/werven/delete", methods=["POST"])
@login_required
def werf_verwijderen():
    # Admin check
    if not getattr(g.user, 'is_admin', False):
        flash("Geen toegang tot deze functie. Alleen admins kunnen werven verwijderen.", "danger")
        return redirect(url_for("werven.werven"))

    project_id = (request.form.get("project_id") or "").strip()
    if not project_id:
        flash("Geen werf geselecteerd.", "danger")
        return redirect(url_for("werven.werven"))

    project = Project.query.filter_by(id=project_id, is_deleted=False).first()
    if not project:
        flash("Werf niet gevonden.", "danger")
        return redirect(url_for("werven.werven"))

    project_id_int = int(project_id)
    project_name = project.name or f"Werf {project_id_int}"

    # 1. Stop alle actieve MaterialUsage records die aan deze werf gekoppeld zijn
    active_usages = MaterialUsage.query.filter_by(
        project_id=project_id_int,
        is_active=True
    ).all()
    
    materials_to_update = set()
    
    for usage in active_usages:
        usage.is_active = False
        usage.end_time = datetime.utcnow()
        usage.project_id = None
        materials_to_update.add(usage.material_id)
        
        # Log activiteit
        mat = Material.query.get(usage.material_id)
        if mat:
            log_activity_db(
                f"Gebruik gestopt (werf verwijderd: {project_name})",
                mat.name or "",
                mat.serial or ""
            )

    # 2. Update alle Material records die aan deze werf gekoppeld zijn
    materials = Material.query.filter_by(project_id=project_id_int).all()
    
    for mat in materials:
        mat.project_id = None
        mat.site = None
        
        # Als het materiaal "in gebruik" was, zet status op "niet in gebruik"
        # Maar controleer eerst of er nog andere actieve usages zijn
        other_active_usages = MaterialUsage.query.filter_by(
            material_id=mat.id,
            is_active=True
        ).count()
        
        if mat.status == "in gebruik" and other_active_usages == 0:
            mat.status = "niet in gebruik"
        
        materials_to_update.add(mat.id)
        
        # Log activiteit
        log_activity_db(
            f"Ontkoppeld van werf: {project_name}",
            mat.name or "",
            mat.serial or ""
        )

    # 3. Soft delete de werf
    project.is_deleted = True
    
    db.session.commit()

    # Tel hoeveel materialen zijn geüpdatet
    materials_count = len(materials_to_update)
    if materials_count > 0:
        flash(
            f"Werf '{project_name}' werd verwijderd. {materials_count} materiaal(en) zijn niet meer in gebruik.",
            "success"
        )
    else:
        flash(f"Werf '{project_name}' werd verwijderd.", "success")
    
    return redirect(url_for("werven.werven"))


@werven_bp.route("/werven/<int:project_id>")
@login_required
def werf_detail(project_id):
    project = Project.query.filter_by(id=project_id, is_deleted=False).first_or_404()
    today = datetime.utcnow().date()

    # Debug: print image_url info
    if project.image_url:
        image_url_result = get_file_url_from_path(project.image_url)
        print(f"DEBUG: Project {project_id} - image_url in DB: {project.image_url}")
        print(f"DEBUG: Generated URL: {image_url_result}")

    # alle materialen
    all_materials = Material.query.all()

    # actieve usages op deze werf
    active_usages = (
        db.session.query(MaterialUsage, Material)
        .join(Material, MaterialUsage.material_id == Material.id)
        .filter(
            MaterialUsage.is_active.is_(True),
            MaterialUsage.project_id == project_id,
        )
        .order_by(MaterialUsage.start_time.desc())
        .all()
    )

    # alle materialen die aan deze werf gekoppeld zijn
    materials = Material.query.filter(Material.project_id == project_id).all()

    # alle andere werven voor de "wissel naar werf" dropdown
    other_projects = Project.query.filter(
        Project.is_deleted.is_(False),
        Project.id != project_id
    ).order_by(Project.name).all()

    return render_template(
        "werf_detail.html",
        project=project,
        today=today,
        all_materials=all_materials,
        active_usages=active_usages,
        materials=materials,
        other_projects=other_projects,
    )


@werven_bp.route("/werven/<int:project_id>/edit", methods=["POST"])
@login_required
def werf_bewerken(project_id):
    project = Project.query.filter_by(id=project_id, is_deleted=False).first_or_404()
    f = request.form

    name = (f.get("name") or "").strip()
    type_ = (f.get("type") or "").strip()
    address = (f.get("address") or "").strip()
    start_date_str = (f.get("start_date") or "").strip()
    end_date_str = (f.get("end_date") or "").strip()
    note = (f.get("note") or "").strip()

    image_file = request.files.get("image_file")

    if not name or not start_date_str:
        flash("Naam en startdatum zijn verplicht voor een werf.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    try:
        project.start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige startdatum.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    if end_date_str:
        try:
            project.end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Ongeldige einddatum.", "danger")
            return redirect(url_for("werven.werf_detail", project_id=project_id))
    else:
        project.end_date = None

    project.name = name
    project.type = type_ or None
    project.address = address or None
    project.note = note or None

    if image_file and image_file.filename:
        project.image_url = save_project_image(image_file, name.replace(" ", "_"))

    db.session.commit()
    flash("Werfgegevens bijgewerkt.", "success")
    return redirect(url_for("werven.werf_detail", project_id=project_id))


@werven_bp.route("/werven/<int:project_id>/use_material", methods=["POST"])
@login_required
def werf_materiaal_gebruiken(project_id):
    project = Project.query.filter_by(id=project_id, is_deleted=False).first_or_404()
    f = request.form

    name = (f.get("name") or "").strip()
    nummer = (f.get("nummer_op_materieel") or "").strip()
    assigned_to = (f.get("assigned_to") or "").strip()

    if not name and not nummer:
        flash("Naam of nummer op materieel is verplicht.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    item = find_material_by_name_or_number(name, nummer)
    if not item:
        flash("Materiaal niet gevonden in het datasysteem.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    # Check if material is already in use
    active_usage = MaterialUsage.query.filter_by(
        material_id=item.id,
        is_active=True
    ).first()
    
    if active_usage:
        flash("Materiaal is niet beschikbaar voor deze toewijzing.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    if not assigned_to and getattr(g, "user", None):
        assigned_to = g.user.Naam or ""

    # update materiaal zelf
    item.assigned_to = assigned_to
    item.site = project.name or item.site
    item.project_id = project_id
    
    # Set status to "in gebruik"
    item.status = "in gebruik"

    # In de database is user_id NOT NULL, dus we gebruiken altijd de ingelogde gebruiker
    user_id = g.user.gebruiker_id
    usage = MaterialUsage(
        material_id=item.id,
        user_id=user_id,
        site=item.site,
        note=None,
        start_time=datetime.utcnow(),
        end_time=None,
        is_active=True,
        used_by=assigned_to or (g.user.Naam if getattr(g, "user", None) else None),
        project_id=project_id,
    )

    db.session.add(usage)
    db.session.commit()

    log_activity_db("In gebruik (werf)", item.name or "", item.serial or "")
    flash("Materiaal staat nu als 'in gebruik' op deze werf.", "success")
    return redirect(url_for("werven.werf_detail", project_id=project_id))


@werven_bp.route("/werven/<int:project_id>/stop_usage", methods=["POST"])
@login_required
def werf_stop_gebruik(project_id):
    """Stop gebruik van materiaal vanuit de werf-detailpagina."""
    usage_id = (request.form.get("usage_id") or "").strip()
    if not usage_id:
        flash("Geen gebruiksessie gevonden.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    usage = MaterialUsage.query.filter_by(id=usage_id, project_id=project_id).first()
    if not usage or not usage.is_active:
        flash("Gebruiksregistratie niet gevonden.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    # Check of de gebruiker dit materiaal zelf in gebruik heeft OF admin is
    current_user_name = g.user.Naam if getattr(g, "user", None) else None
    is_admin = getattr(g.user, 'is_admin', False) if getattr(g, "user", None) else False
    usage_name = (usage.used_by or "").strip()
    
    is_own_usage = current_user_name and usage_name.lower() == current_user_name.lower()
    
    if not is_own_usage and not is_admin:
        flash("Je kunt alleen je eigen materiaal stoppen. Neem contact op met een admin.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    usage.is_active = False
    usage.end_time = datetime.utcnow()

    mat = Material.query.filter_by(id=usage.material_id).first()
    if mat:
        if mat.assigned_to == usage.used_by:
            mat.assigned_to = None
            mat.site = None
        
        # Check if there are any other active usages for this material
        other_active_usages = MaterialUsage.query.filter_by(
            material_id=mat.id, 
            is_active=True
        ).count()
        
        # If no other active usages, set status to "niet in gebruik"
        if other_active_usages == 0:
            mat.status = "niet in gebruik"

    db.session.commit()

    if mat:
        log_activity_db(
            "Niet meer in gebruik (werf)", mat.name or "", mat.serial or ""
        )

    flash("Materiaal is niet langer in gebruik op deze werf.", "success")
    return redirect(url_for("werven.werf_detail", project_id=project_id))


@werven_bp.route("/werven/<int:project_id>/switch_material", methods=["POST"])
@login_required
def werf_switch_material(project_id):
    """Wissel materiaal van huidige werf naar een andere werf."""
    usage_id = (request.form.get("usage_id") or "").strip()
    new_project_id = (request.form.get("new_project_id") or "").strip()

    if not usage_id or not new_project_id:
        flash("Selecteer een werf om het materiaal naar te verplaatsen.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    # Haal huidige usage op
    usage = MaterialUsage.query.filter_by(id=usage_id, project_id=project_id, is_active=True).first()
    if not usage:
        flash("Gebruiksregistratie niet gevonden of niet actief.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    # Controleer of nieuwe werf bestaat
    new_project = Project.query.filter_by(id=new_project_id, is_deleted=False).first()
    if not new_project:
        flash("Doelwerf niet gevonden.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    # Haal materiaal op
    mat = Material.query.filter_by(id=usage.material_id).first()
    if not mat:
        flash("Materiaal niet gevonden.", "danger")
        return redirect(url_for("werven.werf_detail", project_id=project_id))

    # Update usage en materiaal naar nieuwe werf
    usage.project_id = int(new_project_id)
    usage.site = new_project.name
    mat.project_id = int(new_project_id)
    mat.site = new_project.name

    db.session.commit()

    log_activity_db(
        f"Verplaatst naar werf {new_project.name}", mat.name or "", mat.serial or ""
    )

    flash(f"Materiaal is verplaatst naar werf '{new_project.name}'.", "success")
    return redirect(url_for("werven.werf_detail", project_id=project_id))


@werven_bp.route("/werven/<int:project_id>/export")
@login_required
def werf_export_materiaal(project_id):
    """Export materiaal in gebruik op deze werf naar CSV"""
    project = Project.query.filter_by(id=project_id, is_deleted=False).first_or_404()

    # Haal actieve usages op voor deze werf
    active_usages = (
        db.session.query(MaterialUsage, Material)
        .join(Material, MaterialUsage.material_id == Material.id)
        .filter(
            MaterialUsage.is_active.is_(True),
            MaterialUsage.project_id == project_id,
        )
        .order_by(MaterialUsage.start_time.desc())
        .all()
    )

    # Maak CSV
    output = StringIO()
    writer = csv.writer(output)

    # Headers
    writer.writerow([
        'Werf', 'Materieel', 'Serienummer', 'Nummer op materieel',
        'Gebruikt door', 'In gebruik sinds', 'Status'
    ])

    # Data
    for usage, mat in active_usages:
        writer.writerow([
            project.name or f'Werf {project.id}',
            mat.name or '',
            mat.serial or '',
            mat.nummer_op_materieel or '',
            usage.used_by or '',
            usage.start_time.strftime('%Y-%m-%d %H:%M') if usage.start_time else '',
            mat.status or '',
        ])

    # Maak response
    output.seek(0)
    filename = f"werf_{project.name or project.id}_materiaal_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    # Vervang ongeldige karakters in bestandsnaam
    filename = "".join(c if c.isalnum() or c in '._-' else '_' for c in filename)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )



