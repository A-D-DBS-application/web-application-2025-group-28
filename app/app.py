from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    g,
    jsonify,
    Response,
)
from datetime import datetime
from functools import wraps
import os
from dateutil.relativedelta import relativedelta

from config import Config
from models import db, Gebruiker, Material, Activity, MaterialUsage, Project, Keuringstatus, KeuringHistoriek
from sqlalchemy import or_, func, and_
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "dev"  # voor flash() + sessies
app.config.from_object(Config)

# SQLAlchemy koppelen aan app (Supabase/Postgres)
db.init_app(app)

# -----------------------------------------------------
# HELPERS
# -----------------------------------------------------


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        # Alleen doorgaan als er een ingelogde én bestaande gebruiker is
        if session.get("user_email") is None:
            return redirect(url_for("login", next=request.path))

        # `load_current_user` zet g.user; als die om welke reden dan ook None is,
        # beschouwen we de sessie als ongeldig en sturen we terug naar login.
        if getattr(g, "user", None) is None:
            session.clear()
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.before_request
def load_current_user():
    g.user = None
    email = session.get("user_email")
    if not email:
        return
    g.user = Gebruiker.query.filter_by(Email=email).first()


@app.context_processor
def inject_user():
    # in templates beschikbaar als {{ current_user }}
    return {"current_user": g.user}


def log_activity_db(action: str, name: str, serial: str):
    """Schrijf een activiteit weg naar de activity_log tabel in Supabase."""
    user_name = None
    if getattr(g, "user", None) and g.user.Naam:
        user_name = g.user.Naam

    act = Activity(
        action=action,
        name=name or "",
        serial=serial or "",
        user_name=user_name or "Onbekend",
        created_at=datetime.utcnow(),
    )
    db.session.add(act)
    db.session.commit()


def find_material_by_serial(serial: str):
    if not serial:
        return None
    return Material.query.filter_by(serial=serial).first()


def find_material_by_name_or_number(name: str, nummer: str | None):
    """Zoek materiaal: eerst op nummer_op_materieel, dan op naam."""
    item = None
    if nummer:
        item = Material.query.filter_by(nummer_op_materieel=nummer).first()
    if not item and name:
        item = Material.query.filter_by(name=name).first()
    return item


def update_verlopen_keuringen():
    """
    AUTOMATISCH ALGORITME: Check of items automatisch op "keuring verlopen" moeten
    Dit gebeurt wanneer volgende_controle verstreken is EN keuring nog niet uitgevoerd is
    Deze functie kan overal worden aangeroepen om de status up-to-date te houden
    """
    today = datetime.utcnow().date()
    
    keuringen_met_verlopen_datum = Keuringstatus.query.filter(
        Keuringstatus.volgende_controle.isnot(None),
        Keuringstatus.volgende_controle < today,
        Keuringstatus.laatste_controle.is_(None)  # Alleen voor nog niet uitgevoerde keuringen
    ).all()
    
    updated_count = 0
    for keuring in keuringen_met_verlopen_datum:
        if not keuring.serienummer:
            continue
        
        # Zoek materiaal op serienummer
        material = find_material_by_serial(keuring.serienummer)
        if not material:
            continue
        
        # Update inspection_status naar "keuring verlopen" als het nog niet zo is
        # Status kolom blijft "in gebruik" of "niet in gebruik"
        if material.inspection_status not in ["keuring verlopen", "keuring gepland"]:
            material.inspection_status = "keuring verlopen"
            updated_count += 1
    
    # Commit de status updates als er updates zijn
    if updated_count > 0:
        db.session.commit()
    
    return updated_count


# -----------------------------------------------------
# AUTH – met wachtwoord-hash in Gebruiker.password_hash
# -----------------------------------------------------


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        naam = (request.form.get("naam") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        functie = (request.form.get("functie") or "").strip()
        password = (request.form.get("password") or "").strip()

        if not email or not password:
            flash("E-mail en wachtwoord zijn verplicht.", "danger")
            return render_template("auth_signup.html")

        # bestaat al in Supabase?
        if Gebruiker.query.filter_by(Email=email).first():
            flash("E-mail bestaat al. Log in a.u.b.", "warning")
            return redirect(url_for("login", email=email))

        pw_hash = generate_password_hash(password)

        new_user = Gebruiker(
            Naam=naam or None,
            Email=email,
            Functie=functie or None,
            password_hash=pw_hash,
        )
        db.session.add(new_user)
        db.session.commit()

        session["user_email"] = email
        flash("Account aangemaakt en ingelogd.", "success")
        return redirect(url_for("dashboard"))

    # GET
    return render_template("auth_signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    prefill_email = request.args.get("email", "")
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()

        if not email or not password:
            flash("E-mail en wachtwoord zijn verplicht.", "danger")
            return render_template("auth_login.html", prefill_email=prefill_email)

        user = Gebruiker.query.filter_by(Email=email).first()
        if not user or not user.password_hash:
            flash("Geen account gevonden. Registreer je even.", "info")
            return redirect(url_for("signup", email=email))

        if not check_password_hash(user.password_hash, password):
            flash("Onjuist wachtwoord.", "danger")
            return render_template("auth_login.html", prefill_email=email)

        session["user_email"] = email
        flash("Je bent ingelogd.", "success")
        next_url = request.args.get("next")
        return redirect(next_url or url_for("dashboard"))

    # GET
    return render_template("auth_login.html", prefill_email=prefill_email)


@app.route("/logout")
def logout():
    session.clear()
    flash("Je bent uitgelogd.", "info")
    return redirect(url_for("login"))


# -----------------------------------------------------
# DASHBOARD
# -----------------------------------------------------


@app.route("/")
@login_required
def root_redirect():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    # Update automatisch verlopen keuringen
    update_verlopen_keuringen()
    
    total_items = Material.query.count()

    # Tel items die keuring vereisen (te keuren)
    # Dit zijn items met inspection_status "keuring verlopen" of "keuring gepland"
    today = datetime.utcnow().date()
    
    keuring_verlopen_count = Material.query.filter_by(inspection_status="keuring verlopen").count()
    keuring_gepland_count = Material.query.filter_by(inspection_status="keuring gepland").count()
    
    to_inspect = keuring_verlopen_count + keuring_gepland_count

    # recente activiteit uit activity_log tabel
    recent = Activity.query.order_by(Activity.created_at.desc()).limit(8).all()

    # Haal geplande keuringen op (volgende_controle in de toekomst)
    geplande_keuringen = (
        Keuringstatus.query
        .filter(Keuringstatus.volgende_controle > today)
        .order_by(Keuringstatus.volgende_controle.asc())
        .limit(10)  # Toon maximaal 10 komende keuringen
        .all()
    )

    # Data voor "Materiaal in gebruik nemen" modal
    all_materials = Material.query.all()
    today = datetime.utcnow().date()
    projects = (
        Project.query.filter_by(is_deleted=False)
        .order_by(Project.start_date.asc())
        .all()
    )

    return render_template(
        "dashboard.html",
        total_items=total_items,
        to_inspect=to_inspect,
        recent_activity=recent,
        all_materials=all_materials,
        projects=projects,
        today=today,
        geplande_keuringen=geplande_keuringen,
    )


# -----------------------------------------------------
# GESCHIEDENIS
# -----------------------------------------------------


@app.route("/geschiedenis")
@login_required
def geschiedenis():
    """Geschiedenis overzicht met categorieën en filters"""
    from datetime import timedelta
    
    # Haal filter parameters op
    filter_type = request.args.get("type", "all")
    filter_user = request.args.get("user", "")
    filter_period = request.args.get("period", "all")
    search_q = request.args.get("q", "").strip().lower()
    
    # Base query
    query = Activity.query
    
    # Filter op periode
    today = datetime.utcnow().date()
    if filter_period == "today":
        start_date = datetime.combine(today, datetime.min.time())
        query = query.filter(Activity.created_at >= start_date)
    elif filter_period == "week":
        start_date = datetime.combine(today - timedelta(days=7), datetime.min.time())
        query = query.filter(Activity.created_at >= start_date)
    elif filter_period == "month":
        start_date = datetime.combine(today - timedelta(days=30), datetime.min.time())
        query = query.filter(Activity.created_at >= start_date)
    
    # Filter op gebruiker
    if filter_user:
        query = query.filter(Activity.user_name.ilike(f"%{filter_user}%"))
    
    # Filter op zoekterm
    if search_q:
        query = query.filter(
            or_(
                Activity.name.ilike(f"%{search_q}%"),
                Activity.serial.ilike(f"%{search_q}%"),
                Activity.action.ilike(f"%{search_q}%"),
            )
        )
    
    # Haal activiteiten op
    all_activities = query.order_by(Activity.created_at.desc()).limit(500).all()
    
    # Categoriseer activiteiten op basis van action
    materiaal_acties = []
    gebruik_acties = []
    keuring_acties = []
    
    for act in all_activities:
        action_lower = (act.action or "").lower()
        
        if action_lower in ["toegevoegd", "bewerkt", "verwijderd"] or "verwijderd" in action_lower:
            materiaal_acties.append(act)
        if "in gebruik" in action_lower or "verplaatst" in action_lower or "gekoppeld" in action_lower:
            gebruik_acties.append(act)
        if "keuring" in action_lower:
            keuring_acties.append(act)
    
    # Filter op type als geselecteerd
    if filter_type == "materiaal":
        display_activities = materiaal_acties
    elif filter_type == "gebruik":
        display_activities = gebruik_acties
    elif filter_type == "keuring":
        display_activities = keuring_acties
    else:
        display_activities = all_activities
    
    # Haal unieke gebruikers op voor filter dropdown
    unique_users = db.session.query(Activity.user_name).filter(
        Activity.user_name.isnot(None),
        Activity.user_name != ""
    ).distinct().all()
    users_list = sorted([u[0] for u in unique_users if u[0]])
    
    return render_template(
        "geschiedenis.html",
        activities=display_activities,
        all_count=len(all_activities),
        materiaal_count=len(materiaal_acties),
        gebruik_count=len(gebruik_acties),
        keuring_count=len(keuring_acties),
        filter_type=filter_type,
        filter_user=filter_user,
        filter_period=filter_period,
        search_q=search_q,
        users_list=users_list,
    )


@app.route("/geschiedenis/export")
@login_required
def geschiedenis_export():
    """Export geschiedenis naar CSV"""
    import csv
    from io import StringIO
    from datetime import timedelta
    
    # Haal filter parameters op (zelfde als geschiedenis route)
    filter_type = request.args.get("type", "all")
    filter_user = request.args.get("user", "")
    filter_period = request.args.get("period", "all")
    search_q = request.args.get("q", "").strip().lower()
    
    # Base query
    query = Activity.query
    
    # Filter op periode
    today = datetime.utcnow().date()
    if filter_period == "today":
        start_date = datetime.combine(today, datetime.min.time())
        query = query.filter(Activity.created_at >= start_date)
    elif filter_period == "week":
        start_date = datetime.combine(today - timedelta(days=7), datetime.min.time())
        query = query.filter(Activity.created_at >= start_date)
    elif filter_period == "month":
        start_date = datetime.combine(today - timedelta(days=30), datetime.min.time())
        query = query.filter(Activity.created_at >= start_date)
    
    # Filter op gebruiker
    if filter_user:
        query = query.filter(Activity.user_name.ilike(f"%{filter_user}%"))
    
    # Filter op zoekterm
    if search_q:
        query = query.filter(
            or_(
                Activity.name.ilike(f"%{search_q}%"),
                Activity.serial.ilike(f"%{search_q}%"),
                Activity.action.ilike(f"%{search_q}%"),
            )
        )
    
    # Haal activiteiten op
    activities = query.order_by(Activity.created_at.desc()).all()
    
    # Filter op type
    if filter_type != "all":
        filtered = []
        for act in activities:
            action_lower = (act.action or "").lower()
            if filter_type == "materiaal" and (action_lower in ["toegevoegd", "bewerkt", "verwijderd"] or "verwijderd" in action_lower):
                filtered.append(act)
            elif filter_type == "gebruik" and ("in gebruik" in action_lower or "verplaatst" in action_lower or "gekoppeld" in action_lower):
                filtered.append(act)
            elif filter_type == "keuring" and "keuring" in action_lower:
                filtered.append(act)
        activities = filtered
    
    # Maak CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow(['Datum', 'Tijd', 'Actie', 'Materiaal', 'Serienummer', 'Gebruiker'])
    
    # Data
    for act in activities:
        writer.writerow([
            act.created_at.strftime('%Y-%m-%d') if act.created_at else '',
            act.created_at.strftime('%H:%M:%S') if act.created_at else '',
            act.action or '',
            act.name or '',
            act.serial or '',
            act.user_name or '',
        ])
    
    # Maak response
    output.seek(0)
    filename = f"geschiedenis_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# -----------------------------------------------------
# API SEARCH VOOR DASHBOARD
# -----------------------------------------------------


@app.route("/api/search", methods=["GET"])
@login_required
def api_search():
    """API endpoint for searching materials - returns JSON"""
    try:
        q = (request.args.get("q") or "").strip().lower()
        
        if not q:
            return jsonify({"items": []}), 200
        
        like = f"%{q}%"
        items = (
            Material.query.filter(
            or_(Material.name.ilike(like), Material.serial.ilike(like))
            )
            .limit(10)
            .all()
        )
        
        results = []
        for item in items:
            try:
                # Check if material has active usages
                active_usages_count = MaterialUsage.query.filter_by(
                    material_id=item.id, 
                    is_active=True
                ).count()
                
                # Determine actual status: if has active usages, status is "in gebruik"
                actual_status = "in gebruik" if active_usages_count > 0 else (item.status or "")
                
                # Haal keuring informatie op
                keuring_info = None
                if item.keuring_id:
                    keuring_info = Keuringstatus.query.filter_by(id=item.keuring_id).first()
                
                # Als er geen keuring_id is, probeer via serienummer
                if not keuring_info:
                    keuring_info = Keuringstatus.query.filter_by(serienummer=item.serial).first()
                
                # Safe date formatting for keuring dates
                keuring_gepland = None
                laatste_keuring = None
                if keuring_info:
                    if hasattr(keuring_info, 'volgende_controle') and keuring_info.volgende_controle:
                        try:
                            keuring_gepland = keuring_info.volgende_controle.strftime("%Y-%m-%d")
                        except (AttributeError, ValueError):
                            keuring_gepland = None
                    if hasattr(keuring_info, 'laatste_controle') and keuring_info.laatste_controle:
                        try:
                            laatste_keuring = keuring_info.laatste_controle.strftime("%Y-%m-%d")
                        except (AttributeError, ValueError):
                            laatste_keuring = None
                
                results.append(
                    {
                    "serial": item.serial or "",
                    "name": item.name or "",
                    "type": item.type or "",
                    "status": actual_status,
                    "is_in_use": active_usages_count > 0,
                    "assigned_to": item.assigned_to or "",
                    "site": item.site or "",
                    "purchase_date": item.purchase_date.strftime("%Y-%m-%d")
                        if item.purchase_date
                        else "",
                    "note": item.note or "",
                    "nummer_op_materieel": item.nummer_op_materieel or "",
                    "documentation_path": item.documentation_path or "",
                    "safety_sheet_path": item.safety_sheet_path or "",
                    "inspection_status": item.inspection_status or "",
                    "keuring_gepland": keuring_gepland,
                    "laatste_keuring": laatste_keuring,
                    }
                )
            except Exception as e:
                # Log error for this item but continue with other items
                print(f"Error processing material {item.serial if item else 'unknown'}: {e}")
                continue
        
        return jsonify({"items": results}), 200
    except Exception as e:
        # Log the error and return a proper error response
        print(f"Error in api_search: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "items": []}), 500


# -----------------------------------------------------
# UPLOAD CONFIGURATIE – documentatie & veiligheidsfiches
# -----------------------------------------------------

BASE_UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
DOC_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "docs")
SAFETY_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "safety")
PROJECT_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "projects")
CERTIFICATE_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "certificates")

os.makedirs(DOC_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SAFETY_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROJECT_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CERTIFICATE_UPLOAD_FOLDER, exist_ok=True)

app.config["DOC_UPLOAD_FOLDER"] = DOC_UPLOAD_FOLDER
app.config["SAFETY_UPLOAD_FOLDER"] = SAFETY_UPLOAD_FOLDER
app.config["PROJECT_UPLOAD_FOLDER"] = PROJECT_UPLOAD_FOLDER
app.config["CERTIFICATE_UPLOAD_FOLDER"] = CERTIFICATE_UPLOAD_FOLDER


def save_upload(file_storage, upload_folder, prefix: str) -> str | None:
    """
    Sla een geüpload bestand op en geef het relatieve pad terug.
    (bv. 'uploads/docs/BOOR123_foto.pdf')
    Retourneert None wanneer er geen geldig bestand werd meegegeven.
    """

    # Geen bestand → niets opslaan
    if not file_storage or not file_storage.filename:
        return None

    filename = secure_filename(file_storage.filename)
    final_filename = f"{prefix}_{filename}"

    full_path = os.path.join(upload_folder, final_filename)
    file_storage.save(full_path)

    if upload_folder == app.config["DOC_UPLOAD_FOLDER"]:
        relative_folder = "uploads/docs"
    elif upload_folder == app.config["SAFETY_UPLOAD_FOLDER"]:
        relative_folder = "uploads/safety"
    elif upload_folder == app.config["CERTIFICATE_UPLOAD_FOLDER"]:
        relative_folder = "uploads/certificates"
    else:
        relative_folder = "uploads"

    return f"{relative_folder}/{final_filename}"


def save_project_image(file_storage, prefix: str) -> str | None:
    """
    Sla een werf-afbeelding op in static/uploads/projects
    en geef het relatieve pad terug (bv. 'uploads/projects/werf1_foto.jpg').
    """
    if not file_storage or not file_storage.filename:
        return None

    filename = secure_filename(file_storage.filename)
    final_filename = f"{prefix}_{filename}"

    full_path = os.path.join(app.config["PROJECT_UPLOAD_FOLDER"], final_filename)
    file_storage.save(full_path)

    return f"uploads/projects/{final_filename}"


# -----------------------------------------------------
# MATERIAAL – OVERZICHT
# -----------------------------------------------------


@app.route("/materiaal", methods=["GET"])
@login_required
def materiaal():
    # Update automatisch verlopen keuringen
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

    # totaal aantal in systeem
    total_items = Material.query.count()

    # Aantal in gebruik via material_usage (actieve sessies)
    in_use = (
        db.session.query(func.count(MaterialUsage.id))
        .filter(MaterialUsage.is_active.is_(True))
        .scalar()
    ) or 0

    # alle materialen voor datalist in "Gebruik Materieel"
    all_materials = Material.query.all()

    # Actief gebruik ophalen (join material_usage + materials)
    active_usages = (
        db.session.query(MaterialUsage, Material)
        .join(Material, MaterialUsage.material_id == Material.id)
        .filter(MaterialUsage.is_active.is_(True))
        .order_by(MaterialUsage.start_time.desc())
        .all()
    )

    my_usages = []
    other_usages = []
    active_material_ids = set()

    current_user_id = g.user.gebruiker_id if getattr(g, "user", None) else None
    current_user_name = g.user.Naam if getattr(g, "user", None) else None

    # Usages zonder werf (project_id IS NULL)
    usages_without_project = []

    for usage, mat in active_usages:
        active_material_ids.add(mat.id)

        row = {
            "id": usage.id,
            "material_id": mat.id,
            "name": mat.name,
            "serial": mat.serial,
            "site": usage.site or "",
            "used_by": usage.used_by or "",
            "start_time": usage.start_time,
            "project_id": usage.project_id,
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

    # Items ophalen en sorteren:
    #   - eerst materiaal dat in gebruik is (groen lichtje)
    #   - daarna de rest (alfabetisch op naam)
    items = query.all()
    items.sort(
        key=lambda it: (
            it.id not in active_material_ids,  # in gebruik (False) komt eerst
            (it.name or "").lower(),
        )
    )

    # Werven voor de dropdown in "Gebruik Materieel"
    today = datetime.utcnow().date()
    projects = (
        Project.query.filter_by(is_deleted=False)
        .order_by(Project.start_date.asc())
        .all()
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

    return render_template(
        "materiaal.html",
        items=items,
        total_items=total_items,
        in_use=in_use,
        all_materials=all_materials,
        my_usages=my_usages,
        other_usages=other_usages,
        active_material_ids=active_material_ids,
        projects=projects,
        today=today,
        types_list=types_list,
        usages_without_project=usages_without_project,
    )


# -----------------------------------------------------
# MATERIAAL – TOEVOEGEN
# -----------------------------------------------------


@app.route("/materiaal/new", methods=["POST"])
@login_required
def materiaal_toevoegen():
    """
    Nieuw materiaal AANMAKEN in Supabase (tabel 'materials').
    Dit is wat gebeurt via het plus-icoon.
    """
    # Admin check
    if not getattr(g.user, 'is_admin', False):
        flash("Geen toegang tot deze functie. Alleen admins kunnen materiaal toevoegen.", "danger")
        return redirect(url_for("materiaal"))

    f = request.form
    name = (f.get("name") or "").strip()
    serial = (f.get("serial") or "").strip()
    nummer = (f.get("nummer_op_materieel") or "").strip()
    type_ = (f.get("type") or "").strip()
    purchase_date_str = (f.get("purchase_date") or "").strip()
    project_id_str = (f.get("project_id") or "").strip()
    assigned_to = (f.get("assigned_to") or "").strip()
    note = (f.get("note") or "").strip()
    status = (f.get("status") or "goedgekeurd").strip()
    inspection_status = (f.get("inspection_status") or "").strip()

    # Get project if project_id is provided
    project_id = int(project_id_str) if project_id_str else None
    project = None
    site = None
    if project_id:
        project = Project.query.filter_by(id=project_id, is_deleted=False).first()
        if project:
            site = project.name

    documentation_file = request.files.get("documentation")
    safety_file = request.files.get("safety_sheet")

    if not name or not serial:
        flash("Naam en serienummer zijn verplicht.", "danger")
        return redirect(url_for("materiaal"))

    bestaand = find_material_by_serial(serial)
    if bestaand:
        flash("Serienummer bestaat al in het systeem.", "danger")
        return redirect(url_for("materiaal"))

    documentation_path = save_upload(
        documentation_file, app.config["DOC_UPLOAD_FOLDER"], f"{serial}_doc"
    )
    safety_sheet_path = save_upload(
        safety_file, app.config["SAFETY_UPLOAD_FOLDER"], f"{serial}_safety"
    )

    item = Material(
        name=name,
        serial=serial,
        type=type_,
        assigned_to=assigned_to if assigned_to else None,
        site=site if site else None,
        project_id=project_id,
        note=note if note else None,
        status=status,
        nummer_op_materieel=nummer if nummer else None,
        documentation_path=documentation_path,
        safety_sheet_path=safety_sheet_path,
    )

    if purchase_date_str:
        try:
            item.purchase_date = datetime.strptime(purchase_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    # optioneel inspection_status als kolom bestaat
    if hasattr(item, "inspection_status"):
        setattr(
            item,
            "inspection_status",
            inspection_status if inspection_status else None,
        )

    db.session.add(item)
    db.session.commit()

    log_activity_db("Toegevoegd", item.name or "", item.serial or "")
    flash("Nieuw materieel is toegevoegd aan Supabase.", "success")
    return redirect(url_for("materiaal"))


# -----------------------------------------------------
# MATERIAAL – BEWERKEN
# -----------------------------------------------------


@app.route("/materiaal/edit", methods=["POST"])
@login_required
def materiaal_bewerken():
    f = request.form
    original_serial = (f.get("original_serial") or "").strip()
    item = find_material_by_serial(original_serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

    new_serial = (f.get("serial") or "").strip()
    if not new_serial:
        flash("Serienummer is verplicht.", "danger")
        return redirect(url_for("materiaal"))

    if new_serial != original_serial and find_material_by_serial(new_serial):
        flash("Nieuw serienummer bestaat al.", "danger")
        return redirect(url_for("materiaal"))

    item.serial = new_serial
    item.name = (f.get("name") or "").strip()
    item.type = (f.get("type") or "").strip()

    purchase_date = (f.get("purchase_date") or "").strip()
    if purchase_date:
        try:
            item.purchase_date = datetime.strptime(purchase_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    item.assigned_to = (f.get("assigned_to") or "").strip()
    item.site = (f.get("site") or "").strip()
    item.note = (f.get("note") or "").strip()
    
    # Get keuring status from form (goedgekeurd, afgekeurd, keuring verlopen, or keuring gepland)
    keuring_status = (f.get("status") or "goedgekeurd").strip()
    
    # Check if material has active usages - determine status based on that
    active_usages_count = MaterialUsage.query.filter_by(
        material_id=item.id, 
        is_active=True
    ).count()
    
    # Status kolom: alleen "in gebruik" of "niet in gebruik"
    if active_usages_count > 0:
        item.status = "in gebruik"
    else:
        item.status = "niet in gebruik"
    
    # inspection_status kolom: de keuringstatus
    item.inspection_status = keuring_status
    
    item.nummer_op_materieel = (f.get("nummer_op_materieel") or "").strip()

    documentation_file = request.files.get("documentation")
    safety_file = request.files.get("safety_sheet")

    if documentation_file and documentation_file.filename:
        item.documentation_path = save_upload(
            documentation_file, app.config["DOC_UPLOAD_FOLDER"], f"{item.serial}_doc"
        )

    if safety_file and safety_file.filename:
        item.safety_sheet_path = save_upload(
            safety_file, app.config["SAFETY_UPLOAD_FOLDER"], f"{item.serial}_safety"
        )

    db.session.commit()

    log_activity_db("Bewerkt", item.name or "", item.serial or "")
    flash("Materieel bewerkt.", "success")
    return redirect(url_for("materiaal"))


# -----------------------------------------------------
# MATERIAAL – VERWIJDEREN
# -----------------------------------------------------


@app.route("/materiaal/delete", methods=["POST"])
@login_required
def materiaal_verwijderen():
    # Admin check
    if not getattr(g.user, 'is_admin', False):
        flash("Geen toegang tot deze functie. Alleen admins kunnen materiaal verwijderen.", "danger")
        return redirect(url_for("materiaal"))

    serial = (request.form.get("serial") or "").strip()
    item = find_material_by_serial(serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

    # -------------------------------------------------
    # 1) Alle gekoppelde gebruiksregistraties verwijderen
    #    (material_usage heeft een NOT NULL constraint op material_id)
    # -------------------------------------------------
    usages = MaterialUsage.query.filter_by(material_id=item.id).all()
    for usage in usages:
        db.session.delete(usage)

    # Sla keuring_id op voor later controle
    keuring_id_to_check = item.keuring_id
    
    # Controleer eerst of andere materialen dezelfde keuringstatus gebruiken
    # (exclusief het huidige materiaal dat we gaan verwijderen)
    should_delete_keuring = False
    if keuring_id_to_check:
        # Tel hoeveel materialen deze keuringstatus gebruiken, exclusief het huidige item
        other_materials_with_keuring = (
            Material.query
            .filter_by(keuring_id=keuring_id_to_check)
            .filter(Material.id != item.id)
            .count()
        )
        should_delete_keuring = (other_materials_with_keuring == 0)
    
    # Verwijder de referentie naar keuringstatus van dit materiaal
    item.keuring_id = None
    
    # Verwijder het materiaal
    db.session.delete(item)
    
    # Verwijder de keuringstatus alleen als geen andere materialen het meer gebruiken
    if should_delete_keuring and keuring_id_to_check:
        keuring = Keuringstatus.query.filter_by(id=keuring_id_to_check).first()
        if keuring:
            db.session.delete(keuring)

    db.session.commit()

    log_activity_db("Verwijderd", item.name or "", serial)
    flash("Materieel verwijderd.", "success")
    return redirect(url_for("materiaal"))


# -----------------------------------------------------
# MATERIAAL – DOCUMENT VERWIJDEREN
# -----------------------------------------------------


@app.route("/materiaal/document/delete", methods=["POST"])
@login_required
def materiaal_document_verwijderen():
    """Verwijder een document (documentatie of veiligheidsfiche) van een materiaal item"""
    serial = (request.form.get("serial") or "").strip()
    doc_type = (request.form.get("doc_type") or "").strip()  # "documentation" of "safety"
    
    if not serial or not doc_type:
        flash("Ongeldige aanvraag.", "danger")
        return redirect(url_for("materiaal"))
    
    item = find_material_by_serial(serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal"))
    
    # Bepaal welk pad moet worden verwijderd
    file_path = None
    field_name = None
    
    if doc_type == "documentation":
        file_path = item.documentation_path
        field_name = "documentation_path"
    elif doc_type == "safety":
        file_path = item.safety_sheet_path
        field_name = "safety_sheet_path"
    else:
        flash("Ongeldig document type.", "danger")
        return redirect(url_for("materiaal"))
    
    # Verwijder fysiek bestand als het bestaat
    if file_path:
        full_path = os.path.join(app.root_path, "static", file_path)
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except OSError as e:
                # Log error maar ga door met database update
                print(f"Fout bij verwijderen bestand {full_path}: {e}")
    
    # Verwijder pad uit database
    setattr(item, field_name, None)
    db.session.commit()
    
    doc_name = "Documentatie" if doc_type == "documentation" else "Veiligheidsfiche"
    log_activity_db(f"{doc_name} verwijderd", item.name or "", item.serial or "")
    flash(f"{doc_name} verwijderd.", "success")
    return redirect(url_for("materiaal"))


# -----------------------------------------------------
# MATERIAAL – IN GEBRUIK NEMEN
# -----------------------------------------------------


@app.route("/materiaal/use", methods=["POST"])
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
        return redirect(url_for("materiaal"))

    item = find_material_by_name_or_number(name, nummer)
    if not item:
        flash("Materiaal niet gevonden in het datasysteem.", "danger")
        return redirect(url_for("materiaal"))

    # Check if material is already in use
    active_usage = MaterialUsage.query.filter_by(
        material_id=item.id,
        is_active=True
    ).first()
    
    if active_usage:
        flash("Materiaal is niet beschikbaar voor deze toewijzing.", "danger")
        return redirect(url_for("materiaal"))

    if not assigned_to and getattr(g, "user", None):
        assigned_to = g.user.Naam or ""

    # update materiaal zelf
    item.assigned_to = assigned_to
    item.site = site or (project.name if project else item.site)
    if project_id:
        item.project_id = project_id
    
    # Set status to "in gebruik"
    item.status = "in gebruik"

    # Nieuwe gebruik-sessie
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

    log_activity_db("In gebruik", item.name or "", item.serial or "")
    flash("Materieel staat nu als 'in gebruik'.", "success")
    return redirect(url_for("materiaal"))


# -----------------------------------------------------
# MATERIAAL – GEBRUIK STOPPEN
# -----------------------------------------------------


@app.route("/materiaal/stop", methods=["POST"])
@login_required
def materiaal_stop_gebruik():
    usage_id = request.form.get("usage_id", "").strip()
    if not usage_id:
        flash("Geen gebruiksessie gevonden.", "danger")
        return redirect(url_for("materiaal"))

    usage = MaterialUsage.query.filter_by(id=usage_id).first()
    if not usage or not usage.is_active:
        flash("Gebruiksregistratie niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

    # Check of de gebruiker dit materiaal zelf in gebruik heeft OF admin is
    current_user_name = g.user.Naam if getattr(g, "user", None) else None
    is_admin = getattr(g.user, 'is_admin', False) if getattr(g, "user", None) else False
    usage_name = (usage.used_by or "").strip()
    
    is_own_usage = current_user_name and usage_name.lower() == current_user_name.lower()
    
    if not is_own_usage and not is_admin:
        flash("Je kunt alleen je eigen materiaal stoppen. Neem contact op met een admin.", "danger")
        return redirect(url_for("materiaal"))

    usage.is_active = False
    usage.end_time = datetime.utcnow()

    # optioneel ook materiaal resetten
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
        log_activity_db("Niet meer in gebruik", mat.name or "", mat.serial or "")

    flash("Materieel wordt niet langer als 'in gebruik' getoond.", "success")
    return redirect(url_for("materiaal"))


@app.route("/materiaal/assign_to_project", methods=["POST"])
@login_required
def materiaal_assign_to_project():
    """
    Koppel een actief materiaal gebruik aan een werf.
    """
    usage_id = (request.form.get("usage_id") or "").strip()
    project_id = (request.form.get("project_id") or "").strip()

    if not usage_id or not project_id:
        flash("Selecteer een werf om het materiaal aan te koppelen.", "danger")
        return redirect(url_for("materiaal"))

    # Haal usage op
    usage = MaterialUsage.query.filter_by(id=usage_id, is_active=True).first()
    if not usage:
        flash("Gebruiksregistratie niet gevonden of niet actief.", "danger")
        return redirect(url_for("materiaal"))

    # Controleer of werf bestaat
    project = Project.query.filter_by(id=project_id, is_deleted=False).first()
    if not project:
        flash("Werf niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

    # Haal materiaal op
    mat = Material.query.filter_by(id=usage.material_id).first()
    if not mat:
        flash("Materiaal niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

    # Update usage en materiaal met project
    usage.project_id = int(project_id)
    usage.site = project.name
    mat.project_id = int(project_id)
    mat.site = project.name

    db.session.commit()

    log_activity_db(
        f"Gekoppeld aan werf {project.name}", mat.name or "", mat.serial or ""
    )

    flash(f"Materiaal is gekoppeld aan werf '{project.name}'.", "success")
    return redirect(url_for("materiaal"))


# -----------------------------------------------------
# WERVEN
# -----------------------------------------------------


@app.route("/werven")
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


@app.route("/werven/new", methods=["POST"])
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
        return redirect(url_for("werven"))

    start_date = None
    end_date = None
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige startdatum.", "danger")
        return redirect(url_for("werven"))

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Ongeldige einddatum.", "danger")
            return redirect(url_for("werven"))

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
    return redirect(url_for("werven"))


@app.route("/werven/delete", methods=["POST"])
@login_required
def werf_verwijderen():
    # Admin check
    if not getattr(g.user, 'is_admin', False):
        flash("Geen toegang tot deze functie. Alleen admins kunnen werven verwijderen.", "danger")
        return redirect(url_for("werven"))

    project_id = (request.form.get("project_id") or "").strip()
    if not project_id:
        flash("Geen werf geselecteerd.", "danger")
        return redirect(url_for("werven"))

    project = Project.query.filter_by(id=project_id, is_deleted=False).first()
    if not project:
        flash("Werf niet gevonden.", "danger")
        return redirect(url_for("werven"))

    project.is_deleted = True
    db.session.commit()

    flash("Werf werd verwijderd (soft delete).", "success")
    return redirect(url_for("werven"))


@app.route("/werven/<int:project_id>")
@login_required
def werf_detail(project_id):
    project = Project.query.filter_by(id=project_id, is_deleted=False).first_or_404()
    today = datetime.utcnow().date()

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


@app.route("/werven/<int:project_id>/edit", methods=["POST"])
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
        return redirect(url_for("werf_detail", project_id=project_id))

    try:
        project.start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige startdatum.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

    if end_date_str:
        try:
            project.end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Ongeldige einddatum.", "danger")
            return redirect(url_for("werf_detail", project_id=project_id))
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
    return redirect(url_for("werf_detail", project_id=project_id))


@app.route("/werven/<int:project_id>/use_material", methods=["POST"])
@login_required
def werf_materiaal_gebruiken(project_id):
    project = Project.query.filter_by(id=project_id, is_deleted=False).first_or_404()
    f = request.form

    name = (f.get("name") or "").strip()
    nummer = (f.get("nummer_op_materieel") or "").strip()
    assigned_to = (f.get("assigned_to") or "").strip()

    if not name and not nummer:
        flash("Naam of nummer op materieel is verplicht.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

    item = find_material_by_name_or_number(name, nummer)
    if not item:
        flash("Materiaal niet gevonden in het datasysteem.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

    # Check if material is already in use
    active_usage = MaterialUsage.query.filter_by(
        material_id=item.id,
        is_active=True
    ).first()
    
    if active_usage:
        flash("Materiaal is niet beschikbaar voor deze toewijzing.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

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
    return redirect(url_for("werf_detail", project_id=project_id))


@app.route("/werven/<int:project_id>/stop_usage", methods=["POST"])
@login_required
def werf_stop_gebruik(project_id):
    """
    Stop gebruik van materiaal vanuit de werf-detailpagina.
    """
    usage_id = (request.form.get("usage_id") or "").strip()
    if not usage_id:
        flash("Geen gebruiksessie gevonden.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

    usage = MaterialUsage.query.filter_by(id=usage_id, project_id=project_id).first()
    if not usage or not usage.is_active:
        flash("Gebruiksregistratie niet gevonden.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

    # Check of de gebruiker dit materiaal zelf in gebruik heeft OF admin is
    current_user_name = g.user.Naam if getattr(g, "user", None) else None
    is_admin = getattr(g.user, 'is_admin', False) if getattr(g, "user", None) else False
    usage_name = (usage.used_by or "").strip()
    
    is_own_usage = current_user_name and usage_name.lower() == current_user_name.lower()
    
    if not is_own_usage and not is_admin:
        flash("Je kunt alleen je eigen materiaal stoppen. Neem contact op met een admin.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

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
    return redirect(url_for("werf_detail", project_id=project_id))


@app.route("/werven/<int:project_id>/switch_material", methods=["POST"])
@login_required
def werf_switch_material(project_id):
    """
    Wissel materiaal van huidige werf naar een andere werf.
    """
    usage_id = (request.form.get("usage_id") or "").strip()
    new_project_id = (request.form.get("new_project_id") or "").strip()

    if not usage_id or not new_project_id:
        flash("Selecteer een werf om het materiaal naar te verplaatsen.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

    # Haal huidige usage op
    usage = MaterialUsage.query.filter_by(id=usage_id, project_id=project_id, is_active=True).first()
    if not usage:
        flash("Gebruiksregistratie niet gevonden of niet actief.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

    # Controleer of nieuwe werf bestaat
    new_project = Project.query.filter_by(id=new_project_id, is_deleted=False).first()
    if not new_project:
        flash("Doelwerf niet gevonden.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

    # Haal materiaal op
    mat = Material.query.filter_by(id=usage.material_id).first()
    if not mat:
        flash("Materiaal niet gevonden.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

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
    return redirect(url_for("werf_detail", project_id=project_id))


@app.route("/werven/<int:project_id>/export")
@login_required
def werf_export_materiaal(project_id):
    """Export materiaal in gebruik op deze werf naar CSV"""
    import csv
    from io import StringIO

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


# -----------------------------------------------------
# -----------------------------------------------------
# KEURINGEN
# -----------------------------------------------------


@app.route("/keuringen/new", methods=["POST"])
@login_required
def keuring_toevoegen():
    """Nieuwe keuring aanmaken"""
    f = request.form
    
    serial = (f.get("serial") or "").strip()
    keuring_datum_str = (f.get("keuring_datum") or "").strip()
    uitgevoerd_door = (f.get("uitgevoerd_door") or "").strip()
    opmerking = (f.get("opmerking") or "").strip()  # Form field is "opmerking", maar database kolom is "opmerkingen"
    
    if not serial or not keuring_datum_str or not uitgevoerd_door:
        flash("Serienummer, keuring datum en uitgevoerd door zijn verplicht.", "danger")
        return redirect(url_for("keuringen"))
    
    # Zoek materiaal op serienummer
    material = find_material_by_serial(serial)
    if not material:
        flash("Materiaal niet gevonden.", "danger")
        return redirect(url_for("keuringen"))
    
    # Parse datum
    try:
        keuring_datum = datetime.strptime(keuring_datum_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige datum formaat.", "danger")
        return redirect(url_for("keuringen"))
    
    # Bereken volgende keuring (standaard 6 maanden later)
    # Bij nieuwe keuring planning: volgende_controle = keuring_datum (wanneer de keuring gepland is)
    volgende_keuring = keuring_datum
    
    # Maak nieuwe keuring aan
    # laatste_controle = None omdat de keuring nog niet is uitgevoerd
    # volgende_controle = keuring_datum (wanneer de keuring gepland is)
    nieuwe_keuring = Keuringstatus(
        serienummer=serial,
        laatste_controle=None,  # Nog niet uitgevoerd
        volgende_controle=volgende_keuring,  # Geplande datum
    )
    # Voeg uitgevoerd_door toe als de kolom bestaat
    if hasattr(Keuringstatus, 'uitgevoerd_door'):
        nieuwe_keuring.uitgevoerd_door = uitgevoerd_door
    # Voeg opmerkingen toe als de kolom bestaat
    if hasattr(Keuringstatus, 'opmerkingen'):
        nieuwe_keuring.opmerkingen = opmerking if opmerking else None
    
    db.session.add(nieuwe_keuring)
    db.session.flush()  # Om de ID te krijgen
    
    # Koppel keuring aan materiaal
    material.keuring_id = nieuwe_keuring.id
    
    # Update inspection_status naar "keuring gepland"
    # Status kolom blijft "in gebruik" of "niet in gebruik"
    material.inspection_status = "keuring gepland"
    
    db.session.commit()
    
    log_activity_db("Keuring toegevoegd", material.name or "", serial)
    flash("Keuring succesvol toegevoegd.", "success")
    return redirect(url_for("keuringen"))


@app.route("/keuringen/edit", methods=["POST"])
@login_required
def keuring_bewerken():
    """Bewerk een bestaande keuring"""
    f = request.form
    
    keuring_id_str = (f.get("keuring_id") or "").strip()
    volgende_keuring_str = (f.get("volgende_keuring_datum") or "").strip()
    uitgevoerd_door = (f.get("uitgevoerd_door") or "").strip()
    opmerking = (f.get("opmerking") or "").strip()  # Form field is "opmerking", maar database kolom is "opmerkingen"
    
    if not keuring_id_str or not volgende_keuring_str or not uitgevoerd_door:
        flash("Keuring ID, volgende keuring datum en uitgevoerd door zijn verplicht.", "danger")
        return redirect(url_for("keuringen"))
    
    try:
        keuring_id = int(keuring_id_str)
    except ValueError:
        flash("Ongeldig keuring ID.", "danger")
        return redirect(url_for("keuringen"))
    
    # Zoek keuring op
    keuring = Keuringstatus.query.filter_by(id=keuring_id).first()
    if not keuring:
        flash("Keuring niet gevonden.", "danger")
        return redirect(url_for("keuringen"))
    
    # Parse datum
    try:
        volgende_keuring = datetime.strptime(volgende_keuring_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige datum formaat.", "danger")
        return redirect(url_for("keuringen"))
    
    # Update keuring
    keuring.volgende_controle = volgende_keuring
    if hasattr(keuring, 'uitgevoerd_door'):
        keuring.uitgevoerd_door = uitgevoerd_door
    if hasattr(keuring, 'opmerkingen'):
        keuring.opmerkingen = opmerking if opmerking else None
    
    db.session.commit()
    
    log_activity_db("Keuring bewerkt", keuring.serienummer or "", keuring.serienummer or "")
    flash("Keuring succesvol bijgewerkt.", "success")
    return redirect(url_for("keuringen"))


@app.route("/keuringen/resultaat", methods=["POST"])
@login_required
def keuring_resultaat():
    """
    Voer het resultaat van een keuring in en maak historiek record aan.
    Dit wordt gebruikt wanneer een geplande keuring is uitgevoerd.
    """
    f = request.form
    
    keuring_id_str = (f.get("keuring_id") or "").strip()
    resultaat = (f.get("resultaat") or "").strip()  # 'goedgekeurd', 'afgekeurd', 'voorwaardelijk'
    keuring_datum_str = (f.get("keuring_datum") or "").strip()
    volgende_keuring_str = (f.get("volgende_keuring_datum") or "").strip()
    uitgevoerd_door = (f.get("uitgevoerd_door") or "").strip()
    opmerking = (f.get("opmerking") or "").strip()
    
    # Handle certificaat upload
    certificaat_file = request.files.get("certificaat")
    
    if not keuring_id_str or not resultaat or not keuring_datum_str or not uitgevoerd_door:
        flash("Alle velden zijn verplicht.", "danger")
        return redirect(url_for("keuringen"))
    
    try:
        keuring_id = int(keuring_id_str)
    except ValueError:
        flash("Ongeldig keuring ID.", "danger")
        return redirect(url_for("keuringen"))
    
    # Zoek keuring op
    keuring = Keuringstatus.query.filter_by(id=keuring_id).first()
    if not keuring:
        flash("Keuring niet gevonden.", "danger")
        return redirect(url_for("keuringen"))
    
    # Zoek materiaal op serienummer
    material = find_material_by_serial(keuring.serienummer)
    if not material:
        flash("Materiaal niet gevonden.", "danger")
        return redirect(url_for("keuringen"))
    
    # Parse datum
    try:
        keuring_datum = datetime.strptime(keuring_datum_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige datum formaat.", "danger")
        return redirect(url_for("keuringen"))
    
    # Bereken volgende keuring: gebruik opgegeven datum of standaard 6 maanden later
    if volgende_keuring_str:
        try:
            volgende_keuring = datetime.strptime(volgende_keuring_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Ongeldige datum formaat voor volgende keuring. Gebruik standaard 6 maanden.", "warning")
            volgende_keuring = keuring_datum + relativedelta(months=6)
    else:
        # Geen datum opgegeven, gebruik standaard 6 maanden later
        volgende_keuring = keuring_datum + relativedelta(months=6)
    
    # Upload certificaat als aanwezig
    certificaat_path = None
    if certificaat_file and certificaat_file.filename:
        prefix = f"{keuring.serienummer or material.serial}_cert_{datetime.utcnow().strftime('%Y%m%d')}"
        certificaat_path = save_upload(
            certificaat_file, app.config["CERTIFICATE_UPLOAD_FOLDER"], prefix
        )
    
    # Maak historiek record aan
    historiek_record = KeuringHistoriek(
        material_id=material.id,
        serienummer=keuring.serienummer or material.serial,
        keuring_datum=keuring_datum,
        resultaat=resultaat,
        uitgevoerd_door=uitgevoerd_door,
        opmerkingen=opmerking if opmerking else None,
        volgende_keuring_datum=volgende_keuring,
        certificaat_path=certificaat_path,
    )
    db.session.add(historiek_record)
    
    # Update Keuringstatus met laatste controle en volgende controle
    keuring.laatste_controle = keuring_datum
    keuring.volgende_controle = volgende_keuring
    if hasattr(keuring, 'uitgevoerd_door'):
        keuring.uitgevoerd_door = uitgevoerd_door
    if hasattr(keuring, 'opmerkingen'):
        keuring.opmerkingen = opmerking if opmerking else None
    
    # Update materiaal inspection_status op basis van resultaat
    # Status kolom blijft "in gebruik" of "niet in gebruik"
    # inspection_status kolom bevat de keuringstatus
    material.inspection_status = resultaat
    
    db.session.commit()
    
    log_activity_db(f"Keuring uitgevoerd: {resultaat}", material.name or "", material.serial or "")
    flash(f"Keuring resultaat succesvol opgeslagen: {resultaat}.", "success")
    return redirect(url_for("keuringen"))


@app.route("/keuringen/delete", methods=["POST"])
@login_required
def keuring_verwijderen():
    """Verwijder een geplande keuring"""
    f = request.form
    
    keuring_id_str = (f.get("keuring_id") or "").strip()
    
    if not keuring_id_str:
        flash("Keuring ID is verplicht.", "danger")
        return redirect(url_for("keuringen"))
    
    try:
        keuring_id = int(keuring_id_str)
    except ValueError:
        flash("Ongeldig keuring ID.", "danger")
        return redirect(url_for("keuringen"))
    
    # Zoek keuring op
    keuring = Keuringstatus.query.filter_by(id=keuring_id).first()
    if not keuring:
        flash("Keuring niet gevonden.", "danger")
        return redirect(url_for("keuringen"))
    
    serial = keuring.serienummer or ""
    
    # Zoek materiaal dat deze keuring gebruikt
    material = find_material_by_serial(serial)
    
    # Verwijder de referentie naar keuringstatus van het materiaal
    if material and material.keuring_id == keuring_id:
        material.keuring_id = None
        # Als inspection_status "keuring gepland" was, zet terug naar "keuring verlopen"
        if material.inspection_status == "keuring gepland":
            material.inspection_status = "keuring verlopen"
    
    # Verwijder de keuring
    db.session.delete(keuring)
    db.session.commit()
    
    log_activity_db("Keuring verwijderd", serial, serial)
    flash("Keuring succesvol verwijderd.", "success")
    return redirect(url_for("keuringen"))


@app.route("/keuringen/dupliceer/<int:historiek_id>")
@login_required
def keuring_dupliceer(historiek_id):
    """Dupliceer een bestaande keuring"""
    historiek = KeuringHistoriek.query.filter_by(id=historiek_id).first()
    
    if not historiek:
        flash("Keuring niet gevonden.", "danger")
        return redirect(url_for("keuringen"))
    
    # Zoek materiaal
    material = Material.query.filter_by(id=historiek.material_id).first() if historiek.material_id else None
    if not material:
        flash("Materiaal niet gevonden.", "danger")
        return redirect(url_for("keuringen"))
    
    # Maak nieuwe keuring op basis van oude
    # Gebruik volgende_keuring_datum uit historiek, of 6 maanden vanaf vandaag als die niet bestaat
    volgende_keuring_datum = historiek.volgende_keuring_datum
    if not volgende_keuring_datum:
        volgende_keuring_datum = datetime.utcnow().date() + relativedelta(months=6)
    
    nieuwe_keuring = Keuringstatus(
        serienummer=historiek.serienummer,
        laatste_controle=None,  # Nieuwe keuring, nog niet uitgevoerd
        volgende_controle=volgende_keuring_datum,
        uitgevoerd_door=historiek.uitgevoerd_door,
        opmerkingen=f"Gedupliceerd van keuring {historiek.id}",
    )
    
    db.session.add(nieuwe_keuring)
    db.session.flush()
    
    # Koppel aan materiaal
    material.keuring_id = nieuwe_keuring.id
    # Update inspection_status naar "keuring gepland"
    material.inspection_status = "keuring gepland"
    
    db.session.commit()
    
    log_activity_db("Keuring gedupliceerd", material.name or "", material.serial or "")
    flash("Keuring succesvol gedupliceerd.", "success")
    return redirect(url_for("keuringen"))


@app.route("/keuringen/export")
@login_required
def keuringen_export():
    """Export keuringen naar CSV - respecteert dezelfde filters als de pagina"""
    import csv
    from io import StringIO
    
    today = datetime.utcnow().date()
    
    # Apply same filters as main page
    search_q = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "").strip()
    werf_filter = (request.args.get("werf") or "").strip()
    type_filter = (request.args.get("type") or "").strip()
    performer_filter = (request.args.get("performer") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    priority_filter = (request.args.get("priority") or "").strip()
    
    # Build query same as main page
    query = db.session.query(Keuringstatus, Material).join(
        Material, Material.keuring_id == Keuringstatus.id
    )
    
    # Apply filters (same logic as main route)
    if priority_filter == "te_laat":
        query = query.filter(
            Keuringstatus.volgende_controle.isnot(None),
            Keuringstatus.volgende_controle < today,
            Keuringstatus.laatste_controle.is_(None)
        )
    elif priority_filter == "vandaag":
        query = query.filter(
            Keuringstatus.volgende_controle == today,
            Keuringstatus.laatste_controle.is_(None)
        )
    elif priority_filter == "binnen_30":
        query = query.filter(
            Keuringstatus.volgende_controle.isnot(None),
            Keuringstatus.volgende_controle > today,
            Keuringstatus.volgende_controle <= (today + relativedelta(days=30)),
            Keuringstatus.laatste_controle.is_(None)
        )
    
    if search_q:
        like = f"%{search_q}%"
        query = query.filter(
            or_(
                Material.name.ilike(like),
                Material.serial.ilike(like)
            )
        )
    
    if status_filter:
        if status_filter == "te_laat":
            query = query.filter(
                Keuringstatus.volgende_controle.isnot(None),
                Keuringstatus.volgende_controle < today,
                Keuringstatus.laatste_controle.is_(None)
            )
        elif status_filter == "gepland":
            query = query.filter(
                Keuringstatus.volgende_controle.isnot(None),
                Keuringstatus.volgende_controle > today,
                Keuringstatus.laatste_controle.is_(None)
            )
        elif status_filter == "goedgekeurd":
            query = query.filter(Material.inspection_status == "goedgekeurd")
        elif status_filter == "afgekeurd":
            query = query.filter(Material.inspection_status == "afgekeurd")
    
    if werf_filter:
        query = query.filter(
            or_(
                Material.site.ilike(f"%{werf_filter}%"),
                Material.project_id == int(werf_filter) if werf_filter.isdigit() else None
            )
        )
    
    if type_filter:
        query = query.filter(Material.type.ilike(f"%{type_filter}%"))
    
    if performer_filter:
        query = query.filter(Keuringstatus.uitgevoerd_door.ilike(f"%{performer_filter}%"))
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
            query = query.filter(Keuringstatus.volgende_controle >= date_from_obj)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
            query = query.filter(Keuringstatus.volgende_controle <= date_to_obj)
        except ValueError:
            pass
    
    # Get all results (no pagination for export)
    inspection_items = query.order_by(Keuringstatus.volgende_controle.asc().nulls_last()).all()
    
    # Maak CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([
        'Materieel', 'Serienummer', 'Werf/Locatie', 'Laatste Keuring', 
        'Volgende Keuring', 'Resultaat', 'Uitgevoerd door', 'Opmerkingen'
    ])
    
    # Data
    for keuring, material in inspection_items:
        # Get latest history for this material
        latest_history = KeuringHistoriek.query.filter_by(
            material_id=material.id
        ).order_by(KeuringHistoriek.keuring_datum.desc()).first()
        
        writer.writerow([
            material.name or 'Onbekend',
            material.serial or '',
            material.site or (material.project.name if material.project else ''),
            keuring.laatste_controle.strftime('%Y-%m-%d') if keuring.laatste_controle else 'Nog niet uitgevoerd',
            keuring.volgende_controle.strftime('%Y-%m-%d') if keuring.volgende_controle else '',
            material.inspection_status or 'Gepland',
            keuring.uitgevoerd_door or '',
            keuring.opmerkingen or (latest_history.opmerkingen if latest_history else ''),
        ])
    
    # Maak response
    output.seek(0)
    filename = f"keuringen_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route("/api/keuring/<int:historiek_id>")
@login_required
def api_keuring_details(historiek_id):
    """API endpoint om keuring details op te halen"""
    historiek = KeuringHistoriek.query.filter_by(id=historiek_id).first()
    
    if not historiek:
        return jsonify({"error": "Keuring niet gevonden"}), 404
    
    # Haal materiaal op
    material = Material.query.filter_by(id=historiek.material_id).first()
    
    # Bepaal resultaat badge styling
    resultaat_badge = ""
    if historiek.resultaat == "goedgekeurd":
        resultaat_badge = '<span class="badge bg-success">✓ Goedgekeurd</span>'
    elif historiek.resultaat == "afgekeurd":
        resultaat_badge = '<span class="badge bg-danger">✗ Afgekeurd</span>'
    elif historiek.resultaat == "voorwaardelijk":
        resultaat_badge = '<span class="badge bg-warning">⚠ Voorwaardelijk</span>'
    else:
        resultaat_badge = f'<span class="badge bg-secondary">{historiek.resultaat}</span>'
    
    return jsonify({
        "id": historiek.id,
        "material_name": material.name if material else "Onbekend",
        "serial": historiek.serienummer,
        "keuring_datum": historiek.keuring_datum.strftime("%Y-%m-%d") if historiek.keuring_datum else "-",
        "resultaat": historiek.resultaat,
        "resultaat_badge": resultaat_badge,
        "uitgevoerd_door": historiek.uitgevoerd_door or "-",
        "opmerkingen": historiek.opmerkingen or "-",
        "volgende_keuring_datum": historiek.volgende_keuring_datum.strftime("%Y-%m-%d") if historiek.volgende_keuring_datum else "-",
        "certificaat_path": historiek.certificaat_path or None,
        "created_at": historiek.created_at.strftime("%Y-%m-%d %H:%M") if historiek.created_at else "-",
    })


@app.route("/api/keuring/historiek/<int:material_id>")
@login_required
def api_keuring_historiek(material_id):
    """API endpoint om alle keuring historiek voor een materiaal op te halen"""
    from datetime import date
    today = date.today()
    
    material = Material.query.filter_by(id=material_id).first()
    
    if not material:
        return jsonify({"error": "Materiaal niet gevonden"}), 404
    
    # Haal huidige keuringstatus op
    keuring_status = None
    volgende_keuring_datum = None
    dagen_verschil = None
    if material.keuring_id:
        keuring = Keuringstatus.query.filter_by(id=material.keuring_id).first()
        if keuring:
            volgende_keuring_datum = keuring.volgende_controle.strftime("%Y-%m-%d") if keuring.volgende_controle else None
            if keuring.volgende_controle:
                dagen_verschil = (keuring.volgende_controle - today).days
    
    historiek = KeuringHistoriek.query.filter_by(material_id=material_id).order_by(
        KeuringHistoriek.keuring_datum.desc()
    ).all()
    
    historiek_list = []
    for hist in historiek:
        historiek_list.append({
            "id": hist.id,
            "keuring_datum": hist.keuring_datum.strftime("%Y-%m-%d") if hist.keuring_datum else "-",
            "resultaat": hist.resultaat or "-",
            "uitgevoerd_door": hist.uitgevoerd_door or "-",
            "opmerkingen": hist.opmerkingen or None,
            "volgende_keuring_datum": hist.volgende_keuring_datum.strftime("%Y-%m-%d") if hist.volgende_keuring_datum else None,
            "certificaat_path": hist.certificaat_path or None,
        })
    
    return jsonify({
        "material_id": material_id,
        "material_name": material.name or "Onbekend",
        "serial": material.serial or "-",
        "inspection_status": material.inspection_status or "Onbekend",
        "volgende_keuring_datum": volgende_keuring_datum,
        "dagen_verschil": dagen_verschil,
        "historiek": historiek_list
    })


# KEURINGEN EN DOCUMENTEN
# -----------------------------------------------------


@app.route("/keuringen")
@login_required
def keuringen():
    """Keuringen overzicht pagina - verbeterd met filters, paginatie en prioriteit"""
    today = datetime.utcnow().date()
    
    # AUTOMATISCH ALGORITME: Update verlopen keuringen
    update_verlopen_keuringen()
    
    # ============================================
    # A. PRIORITEIT CARDS: Te laat, Vandaag, Binnen 30 dagen
    # ============================================
    # Te laat: volgende_controle < today EN laatste_controle IS NULL (nog niet uitgevoerd)
    te_laat_count = db.session.query(Keuringstatus, Material).join(
        Material, Material.keuring_id == Keuringstatus.id
    ).filter(
        Keuringstatus.volgende_controle.isnot(None),
        Keuringstatus.volgende_controle < today,
        Keuringstatus.laatste_controle.is_(None)
    ).count()
    
    # Te keuren vandaag: volgende_controle == today EN laatste_controle IS NULL
    vandaag_count = db.session.query(Keuringstatus, Material).join(
        Material, Material.keuring_id == Keuringstatus.id
    ).filter(
        Keuringstatus.volgende_controle == today,
        Keuringstatus.laatste_controle.is_(None)
    ).count()
    
    # Binnen 30 dagen: volgende_controle > today AND <= today + 30 EN laatste_controle IS NULL
    binnen_30_dagen_count = db.session.query(Keuringstatus, Material).join(
        Material, Material.keuring_id == Keuringstatus.id
    ).filter(
        Keuringstatus.volgende_controle.isnot(None),
        Keuringstatus.volgende_controle > today,
        Keuringstatus.volgende_controle <= (today + relativedelta(days=30)),
        Keuringstatus.laatste_controle.is_(None)
    ).count()
    
    # ============================================
    # B. FILTERS (query parameters)
    # ============================================
    search_q = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "").strip()
    werf_filter = (request.args.get("werf") or "").strip()
    type_filter = (request.args.get("type") or "").strip()
    performer_filter = (request.args.get("performer") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    priority_filter = (request.args.get("priority") or "").strip()  # "te_laat", "vandaag", "binnen_30"
    
    # Paginatie
    page = request.args.get("page", 1, type=int)
    per_page = 25
    
    # Sortering
    sort_by = request.args.get("sort", "volgende_controle")  # default: sort by next inspection
    sort_order = request.args.get("order", "asc")
    
    # ============================================
    # C. BUILD QUERY: Combine Keuringstatus + Material
    # ============================================
    # Start met join van Keuringstatus en Material
    query = db.session.query(Keuringstatus, Material).join(
        Material, Material.keuring_id == Keuringstatus.id
    )
    
    # Apply priority filter (from cards)
    if priority_filter == "te_laat":
        query = query.filter(
            Keuringstatus.volgende_controle.isnot(None),
            Keuringstatus.volgende_controle < today,
            Keuringstatus.laatste_controle.is_(None)
        )
    elif priority_filter == "vandaag":
        query = query.filter(
            Keuringstatus.volgende_controle == today,
            Keuringstatus.laatste_controle.is_(None)
        )
    elif priority_filter == "binnen_30":
        query = query.filter(
            Keuringstatus.volgende_controle.isnot(None),
            Keuringstatus.volgende_controle > today,
            Keuringstatus.volgende_controle <= (today + relativedelta(days=30)),
            Keuringstatus.laatste_controle.is_(None)
        )
    
    # Text search (material name or serial)
    if search_q:
        like = f"%{search_q}%"
        query = query.filter(
            or_(
                Material.name.ilike(like),
                Material.serial.ilike(like)
            )
        )
    
    # Status filter (based on inspection_status or result)
    if status_filter:
        if status_filter == "te_laat":
            # Overdue: volgende_controle < today AND laatste_controle IS NULL
            query = query.filter(
                Keuringstatus.volgende_controle.isnot(None),
                Keuringstatus.volgende_controle < today,
                Keuringstatus.laatste_controle.is_(None)
            )
        elif status_filter == "gepland":
            # Planned: volgende_controle > today AND laatste_controle IS NULL
            query = query.filter(
                Keuringstatus.volgende_controle.isnot(None),
                Keuringstatus.volgende_controle > today,
                Keuringstatus.laatste_controle.is_(None)
            )
        elif status_filter == "goedgekeurd":
            # Approved: check latest history or inspection_status
            query = query.filter(Material.inspection_status == "goedgekeurd")
        elif status_filter == "afgekeurd":
            # Rejected: check latest history or inspection_status
            query = query.filter(Material.inspection_status == "afgekeurd")
    
    # Werf/Location filter
    if werf_filter:
        query = query.filter(
            or_(
                Material.site.ilike(f"%{werf_filter}%"),
                Material.project_id == int(werf_filter) if werf_filter.isdigit() else None
            )
        )
    
    # Type filter
    if type_filter:
        query = query.filter(Material.type.ilike(f"%{type_filter}%"))
    
    # Performer filter
    if performer_filter:
        query = query.filter(Keuringstatus.uitgevoerd_door.ilike(f"%{performer_filter}%"))
    
    # Date range filter (on volgende_controle)
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
            query = query.filter(Keuringstatus.volgende_controle >= date_from_obj)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
            query = query.filter(Keuringstatus.volgende_controle <= date_to_obj)
        except ValueError:
            pass
    
    # ============================================
    # D. SORTING
    # ============================================
    if sort_by == "materieel":
        if sort_order == "desc":
            query = query.order_by(Material.name.desc())
        else:
            query = query.order_by(Material.name.asc())
    elif sort_by == "laatste_keuring":
        if sort_order == "desc":
            query = query.order_by(Keuringstatus.laatste_controle.desc().nulls_last())
        else:
            query = query.order_by(Keuringstatus.laatste_controle.asc().nulls_last())
    elif sort_by == "volgende_keuring":
        if sort_order == "desc":
            query = query.order_by(Keuringstatus.volgende_controle.desc().nulls_last())
        else:
            query = query.order_by(Keuringstatus.volgende_controle.asc().nulls_last())
    elif sort_by == "resultaat":
        if sort_order == "desc":
            query = query.order_by(Material.inspection_status.desc().nulls_last())
        else:
            query = query.order_by(Material.inspection_status.asc().nulls_last())
    else:
        # Default: sort by volgende_controle (ascending - most urgent first)
        query = query.order_by(Keuringstatus.volgende_controle.asc().nulls_last())
    
    # ============================================
    # E. PAGINATION
    # ============================================
    total_items = query.count()
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    inspection_items = pagination.items
    
    # ============================================
    # F. PREPARE DATA FOR TEMPLATE
    # ============================================
    # Build list of inspection items with computed status
    inspection_list = []
    for keuring, material in inspection_items:
        # Compute status badge
        status_badge = "gepland"
        status_class = "secondary"
        dagen_verschil = None
        
        if keuring.laatste_controle:
            # Already inspected - check result
            if material.inspection_status == "goedgekeurd":
                status_badge = "goedgekeurd"
                status_class = "success"
            elif material.inspection_status == "afgekeurd":
                status_badge = "afgekeurd"
                status_class = "danger"
            else:
                status_badge = "gepland"
                status_class = "secondary"
        else:
            # Not yet inspected - check if overdue
            if keuring.volgende_controle:
                if keuring.volgende_controle < today:
                    status_badge = "te laat"
                    status_class = "danger"
                    dagen_verschil = (today - keuring.volgende_controle).days
                elif keuring.volgende_controle == today:
                    status_badge = "vandaag"
                    status_class = "warning"
                    dagen_verschil = 0
                elif keuring.volgende_controle <= (today + relativedelta(days=30)):
                    status_badge = "binnenkort"
                    status_class = "warning"
                    dagen_verschil = (keuring.volgende_controle - today).days
                else:
                    status_badge = "gepland"
                    status_class = "secondary"
                    dagen_verschil = (keuring.volgende_controle - today).days
        
        # Check if certificate exists (from latest history)
        has_certificate = False
        latest_history = KeuringHistoriek.query.filter_by(
            material_id=material.id
        ).order_by(KeuringHistoriek.keuring_datum.desc()).first()
        if latest_history and latest_history.certificaat_path:
            has_certificate = True
        
        inspection_list.append({
            'keuring': keuring,
            'material': material,
            'status_badge': status_badge,
            'status_class': status_class,
            'dagen_verschil': dagen_verschil,
            'has_certificate': has_certificate,
        })
    
    # ============================================
    # G. FILTER OPTIONS FOR DROPDOWNS
    # ============================================
    # Get unique values for filters
    all_projects = Project.query.filter_by(is_deleted=False).order_by(Project.name).all()
    unique_types = db.session.query(Material.type).filter(
        Material.type.isnot(None),
        Material.type != ""
    ).distinct().order_by(Material.type).all()
    types_list = [t[0] for t in unique_types if t[0]]
    
    unique_performers = db.session.query(Keuringstatus.uitgevoerd_door).filter(
        Keuringstatus.uitgevoerd_door.isnot(None),
        Keuringstatus.uitgevoerd_door != ""
    ).distinct().order_by(Keuringstatus.uitgevoerd_door).all()
    performers_list = [p[0] for p in unique_performers if p[0]]
    
    # All materials for dropdowns
    all_materials = Material.query.order_by(Material.name).all()
    
    return render_template(
        "keuringen.html",
        # Priority cards
        te_laat_count=te_laat_count,
        vandaag_count=vandaag_count,
        binnen_30_dagen_count=binnen_30_dagen_count,
        today=today,
        # Inspection list
        inspection_list=inspection_list,
        pagination=pagination,
        total_items=total_items,
        # Filters
        search_q=search_q,
        status_filter=status_filter,
        werf_filter=werf_filter,
        type_filter=type_filter,
        performer_filter=performer_filter,
        date_from=date_from,
        date_to=date_to,
        priority_filter=priority_filter,
        sort_by=sort_by,
        sort_order=sort_order,
        # Filter options
        all_projects=all_projects,
        types_list=types_list,
        performers_list=performers_list,
        all_materials=all_materials,
    )
    
    # Haal uitgevoerde keuringen op (met laatste_controle in het verleden of vandaag)
    # Gebruik try/except om te werken met of zonder uitgevoerd_door kolom
    try:
        # Haal uitgevoerde keuringen op (met laatste_controle in het verleden of vandaag EN niet NULL)
        uitgevoerde_keuringen_raw = (
            Keuringstatus.query
            .filter(
                Keuringstatus.laatste_controle.isnot(None),
                Keuringstatus.laatste_controle <= today
            )
            .order_by(Keuringstatus.laatste_controle.desc())
            .all()
        )
        
        # Voeg opmerking attribuut toe aan elke keuring als het niet bestaat
        uitgevoerde_keuringen = []
        for keuring in uitgevoerde_keuringen_raw:
            # opmerkingen kolom bestaat nu in de database
            uitgevoerde_keuringen.append(keuring)
        
        # Haal geplande keuringen op (volgende_controle in de toekomst EN nog niet uitgevoerd)
        # Een keuring is "gepland" als laatste_controle None is (nog niet uitgevoerd)
        geplande_keuringen_raw = (
            Keuringstatus.query
            .filter(
                Keuringstatus.volgende_controle > today,
                Keuringstatus.laatste_controle.is_(None)  # Nog niet uitgevoerd
            )
            .order_by(Keuringstatus.volgende_controle.asc())
            .all()
        )
        
        # Voeg opmerking attribuut toe aan elke keuring als het niet bestaat
        geplande_keuringen = []
        for keuring in geplande_keuringen_raw:
            # opmerkingen kolom bestaat nu in de database
            geplande_keuringen.append(keuring)
    except Exception as e:
        # Als de kolom nog niet bestaat, gebruik een workaround
        # Haal alle keuringen op en filter in Python
        all_keuringen = Keuringstatus.query.all()
        uitgevoerde_keuringen_raw = [
            k for k in all_keuringen 
            if k.laatste_controle is not None and k.laatste_controle <= today
        ]
        uitgevoerde_keuringen_raw.sort(key=lambda x: x.laatste_controle or datetime.min.date(), reverse=True)
        
        geplande_keuringen_raw = [
            k for k in all_keuringen 
            if k.volgende_controle and k.volgende_controle > today and k.laatste_controle is None
        ]
        geplande_keuringen_raw.sort(key=lambda x: x.volgende_controle or datetime.max.date())
        
        # Voeg opmerking attribuut toe aan elke keuring als het niet bestaat
        uitgevoerde_keuringen = []
        for keuring in uitgevoerde_keuringen_raw:
            # opmerkingen kolom bestaat nu in de database
            uitgevoerde_keuringen.append(keuring)
        
        geplande_keuringen = []
        for keuring in geplande_keuringen_raw:
            # opmerkingen kolom bestaat nu in de database
            geplande_keuringen.append(keuring)
    
    # Haal alle materialen op voor de dropdown
    all_materials = Material.query.order_by(Material.name).all()
    
    # Tel keuringen - alleen die gekoppeld zijn aan bestaande materialen
    # Dit is het aantal materialen met een keuring_id
    total_keuringen = Material.query.filter(Material.keuring_id.isnot(None)).count()
    
    # Tel goedgekeurde items (gebaseerd op inspection_status)
    goedgekeurd_count = Material.query.filter_by(inspection_status="goedgekeurd").count()
    
    # Tel afgekeurde items (gebaseerd op inspection_status)
    afgekeurd_count = Material.query.filter_by(inspection_status="afgekeurd").count()
    
    # Tel items die keuring vereisen (te keuren)
    # Dit zijn items met inspection_status "keuring verlopen" of "keuring gepland"
    keuring_verlopen_count = Material.query.filter_by(inspection_status="keuring verlopen").count()
    keuring_gepland_count = Material.query.filter_by(inspection_status="keuring gepland").count()
    te_keuren = keuring_verlopen_count + keuring_gepland_count
    
    # Haal items op die keuring vereisen voor de "Items die Keuring Vereisen" box
    keuring_verlopen_items = Material.query.filter_by(inspection_status="keuring verlopen").all()
    keuring_gepland_items = Material.query.filter_by(inspection_status="keuring gepland").all()
    # Combineer alle lijsten en sorteer op naam
    afgekeurde_items = sorted(
        keuring_verlopen_items + keuring_gepland_items,
        key=lambda x: (x.name or "").lower()
    )
    
    # Haal keuring historiek op voor het overzicht (alle uitgevoerde keuringen)
    # Filter op serienummer als opgegeven
    historiek_query = KeuringHistoriek.query
    if filter_serial:
        historiek_query = historiek_query.filter(KeuringHistoriek.serienummer == filter_serial)
    
    keuring_historiek = (
        historiek_query
        .order_by(KeuringHistoriek.keuring_datum.desc())
        .limit(100)  # Limiteer tot laatste 100 keuringen voor performance
        .all()
    )
    
    # Voeg materiaal informatie toe aan elke historiek record
    for hist in keuring_historiek:
        if hist.material_id:
            hist.material_obj = Material.query.filter_by(id=hist.material_id).first()
        else:
            hist.material_obj = None
    
    # Als gefilterd op serienummer, haal materiaal op voor display
    filtered_material = None
    if filter_serial:
        filtered_material = find_material_by_serial(filter_serial)
    
    # STATISTIEKEN: Bereken verschillende statistieken
    total_historiek = KeuringHistoriek.query.count()
    goedgekeurd_historiek = KeuringHistoriek.query.filter_by(resultaat="goedgekeurd").count()
    afgekeurd_historiek = KeuringHistoriek.query.filter_by(resultaat="afgekeurd").count()
    
    # Gemiddelde tijd tussen keuringen (in dagen)
    avg_days_between = None
    if total_historiek > 1:
        # Haal eerste en laatste keuring datum op
        first_keuring = KeuringHistoriek.query.order_by(KeuringHistoriek.keuring_datum.asc()).first()
        last_keuring = KeuringHistoriek.query.order_by(KeuringHistoriek.keuring_datum.desc()).first()
        if first_keuring and last_keuring and first_keuring.keuring_datum and last_keuring.keuring_datum:
            days_diff = (last_keuring.keuring_datum - first_keuring.keuring_datum).days
            if days_diff > 0:
                avg_days_between = days_diff / total_historiek
    
    # Keuringen deze maand
    from datetime import date
    first_day_month = date.today().replace(day=1)
    keuringen_deze_maand = KeuringHistoriek.query.filter(
        KeuringHistoriek.keuring_datum >= first_day_month
    ).count()
    
    return render_template(
        "keuringen.html",
        uitgevoerde_keuringen=uitgevoerde_keuringen,
        geplande_keuringen=geplande_keuringen,
        all_materials=all_materials,
        total_keuringen=total_keuringen,
        goedgekeurd_count=goedgekeurd_count,
        afgekeurd_count=afgekeurd_count,
        te_keuren=te_keuren,
        today=today,
        afgekeurde_items=afgekeurde_items,
        keuring_historiek=keuring_historiek,
        filter_serial=filter_serial,
        filtered_material=filtered_material,
        binnenkort_verlopen=binnenkort_verlopen,
        total_historiek=total_historiek,
        goedgekeurd_historiek=goedgekeurd_historiek,
        afgekeurd_historiek=afgekeurd_historiek,
        avg_days_between=avg_days_between,
        keuringen_deze_maand=keuringen_deze_maand,
    )


@app.route("/documenten")
@login_required
def documenten():
    """Documenten overzicht met zoeken en filteren"""
    import os as _os
    
    q = (request.args.get("q") or "").strip().lower()
    doc_type = (request.args.get("type") or "").strip().lower()
    
    all_materials = Material.query.all()
    documents = []
    
    for material in all_materials:
        if material.documentation_path:
            doc_name = _os.path.basename(material.documentation_path)
            doc_type_from_name = (
                "Handleiding"
                if "handleiding" in doc_name.lower()
                or "manual" in doc_name.lower()
                else "Overige"
            )

            documents.append(
                {
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
                    "status": doc_type_from_name,
                }
            )
        
        if material.safety_sheet_path:
            doc_name = _os.path.basename(material.safety_sheet_path)
            documents.append(
                {
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
                    "status": "Veiligheidscertificaat",
                }
            )
    
    documents.append(
        {
        "type": "Servicerapport",
        "name": "Service-Rapport-Augustus-2024.pdf",
        "material": "Compressor Atlas Copco",
        "material_serial": "CP-2022-112",
        "date": "2024-08-01",
        "size": "1.1 MB",
        "uploaded_by": "Atlas Copco",
        "path": None,
            "status": "Servicerapport",
        }
    )

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
    
    return render_template(
        "documenten.html",
        documents=documents,
        total_docs=total_docs,
        safety_certs=safety_certs,
        search_query=q,
        selected_type=doc_type,
    )


if __name__ == "__main__":
    with app.app_context():
        # geen db.create_all(); Supabase beheert de tabellen
        pass

    app.run(debug=True)
