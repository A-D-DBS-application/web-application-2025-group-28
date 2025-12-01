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
)
from datetime import datetime
from functools import wraps
import os
from dateutil.relativedelta import relativedelta

from config import Config
from models import db, Gebruiker, Material, Activity, MaterialUsage, Project, Keuringstatus
from sqlalchemy import or_, func
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
        if session.get("user_email") is None:
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
    total_items = Material.query.count()

    # Tel items die keuring vereisen (te keuren)
    # Dit zijn alleen items met status "keuring verlopen" of "keuring gepland"
    # Voor items "in gebruik": check inspection_status
    today = datetime.utcnow().date()
    
    # Items met status "keuring verlopen" (direct of via inspection_status)
    keuring_verlopen_direct = Material.query.filter_by(status="keuring verlopen").count()
    keuring_verlopen_in_use = db.session.query(Material).filter(
        Material.status == "in gebruik",
        Material.inspection_status == "keuring verlopen"
    ).count()
    
    # Items met status "keuring gepland" (direct of via inspection_status)
    keuring_gepland_direct = Material.query.filter_by(status="keuring gepland").count()
    keuring_gepland_in_use = db.session.query(Material).filter(
        Material.status == "in gebruik",
        Material.inspection_status == "keuring gepland"
    ).count()
    
    to_inspect = keuring_verlopen_direct + keuring_verlopen_in_use + keuring_gepland_direct + keuring_gepland_in_use

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

os.makedirs(DOC_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SAFETY_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROJECT_UPLOAD_FOLDER, exist_ok=True)

app.config["DOC_UPLOAD_FOLDER"] = DOC_UPLOAD_FOLDER
app.config["SAFETY_UPLOAD_FOLDER"] = SAFETY_UPLOAD_FOLDER
app.config["PROJECT_UPLOAD_FOLDER"] = PROJECT_UPLOAD_FOLDER


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
        }

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
    f = request.form

    # Beheerwachtwoord controleren
    admin_pw = (f.get("admin_password") or "").strip()
    if admin_pw != "Sunset":
        flash("Onjuist wachtwoord voor het toevoegen van nieuw materieel.", "danger")
        return redirect(url_for("materiaal"))

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
    
    # Check if material has active usages - if so, keep status as "in gebruik"
    active_usages_count = MaterialUsage.query.filter_by(
        material_id=item.id, 
        is_active=True
    ).count()
    
    if active_usages_count > 0:
        # Material is in use, keep status as "in gebruik"
        item.status = "in gebruik"
        # Store the keuring status in inspection_status so we can preserve it
        if hasattr(item, "inspection_status"):
            item.inspection_status = keuring_status
    else:
        # No active usages, use keuring status from form as the main status
        item.status = keuring_status
        # Also store in inspection_status for consistency
        if hasattr(item, "inspection_status"):
            item.inspection_status = keuring_status
    
    item.nummer_op_materieel = (f.get("nummer_op_materieel") or "").strip()

    # Handle "Volgende keuring" field (separate from keuring status)
    next_inspection = (f.get("inspection_status") or "").strip()
    # Only update if it's different from keuring status (to preserve "Volgende keuring" info)
    # For now, we'll use inspection_status for keuring status, so we skip this
    # If you need a separate "Volgende keuring" field, we'd need to add a new column

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
    serial = (request.form.get("serial") or "").strip()
    admin_pw = (request.form.get("admin_password") or "").strip()

    if admin_pw != "Sunset":
        flash("Onjuist wachtwoord voor het verwijderen van materiaal.", "danger")
        return redirect(url_for("materiaal"))

    item = find_material_by_serial(serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

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
    user_id = g.user.gebruiker_id if getattr(g, "user", None) else None
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
        
        # If no other active usages, revert status to original keuring status
        if other_active_usages == 0:
            # Restore original keuring status from inspection_status if available
            if hasattr(mat, "inspection_status") and mat.inspection_status:
                mat.status = mat.inspection_status
            else:
                # Default to goedgekeurd if no inspection_status is stored
                mat.status = "goedgekeurd"

    db.session.commit()

    if mat:
        log_activity_db("Niet meer in gebruik", mat.name or "", mat.serial or "")

    flash("Materieel wordt niet langer als 'in gebruik' getoond.", "success")
    return redirect(url_for("materiaal"))


# -----------------------------------------------------
# WERVEN
# -----------------------------------------------------


@app.route("/werven")
@login_required
def werven():
    today = datetime.utcnow().date()
    projects = (
        Project.query.filter_by(is_deleted=False)
        .order_by(Project.start_date.asc())
        .all()
    )
    return render_template("werven.html", projects=projects, today=today)


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
    project_id = (request.form.get("project_id") or "").strip()
    admin_pw = (request.form.get("admin_password") or "").strip()

    if admin_pw != "Sunset":
        flash("Onjuist wachtwoord voor het verwijderen van een werf.", "danger")
        return redirect(url_for("werven"))

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

    return render_template(
        "werf_detail.html",
        project=project,
        today=today,
        all_materials=all_materials,
        active_usages=active_usages,
        materials=materials,
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

    user_id = g.user.gebruiker_id if getattr(g, "user", None) else None
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
        
        # If no other active usages, revert status to original keuring status
        if other_active_usages == 0:
            # Restore original keuring status from inspection_status if available
            if hasattr(mat, "inspection_status") and mat.inspection_status:
                mat.status = mat.inspection_status
            else:
                # Default to goedgekeurd if no inspection_status is stored
                mat.status = "goedgekeurd"

    db.session.commit()

    if mat:
        log_activity_db(
            "Niet meer in gebruik (werf)", mat.name or "", mat.serial or ""
        )

    flash("Materiaal is niet langer in gebruik op deze werf.", "success")
    return redirect(url_for("werf_detail", project_id=project_id))


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
    volgende_keuring = keuring_datum + relativedelta(months=6)
    
    # Maak nieuwe keuring aan
    nieuwe_keuring = Keuringstatus(
        serienummer=serial,
        laatste_controle=keuring_datum,
        volgende_controle=volgende_keuring,
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
    material.status = "goedgekeurd"  # Update status naar goedgekeurd
    
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


# KEURINGEN EN DOCUMENTEN
# -----------------------------------------------------


@app.route("/keuringen")
@login_required
def keuringen():
    """Keuringen overzicht pagina"""
    today = datetime.utcnow().date()
    
    # Haal uitgevoerde keuringen op (met laatste_controle in het verleden of vandaag)
    # Gebruik try/except om te werken met of zonder uitgevoerd_door kolom
    try:
        uitgevoerde_keuringen_raw = (
            Keuringstatus.query
            .filter(Keuringstatus.laatste_controle <= today)
            .order_by(Keuringstatus.laatste_controle.desc())
            .all()
        )
        
        # Voeg opmerking attribuut toe aan elke keuring als het niet bestaat
        uitgevoerde_keuringen = []
        for keuring in uitgevoerde_keuringen_raw:
            # opmerkingen kolom bestaat nu in de database
            uitgevoerde_keuringen.append(keuring)
        
        # Haal geplande keuringen op (volgende_controle in de toekomst)
        geplande_keuringen_raw = (
            Keuringstatus.query
            .filter(Keuringstatus.volgende_controle > today)
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
            if k.laatste_controle and k.laatste_controle <= today
        ]
        uitgevoerde_keuringen_raw.sort(key=lambda x: x.laatste_controle or datetime.min.date(), reverse=True)
        
        geplande_keuringen_raw = [
            k for k in all_keuringen 
            if k.volgende_controle and k.volgende_controle > today
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
    
    # Tel goedgekeurde items
    # Items met status "goedgekeurd" OF items "in gebruik" met inspection_status "goedgekeurd"
    goedgekeurd_direct = Material.query.filter_by(status="goedgekeurd").count()
    goedgekeurd_in_use = db.session.query(Material).filter(
        Material.status == "in gebruik",
        Material.inspection_status == "goedgekeurd"
    ).count()
    goedgekeurd_count = goedgekeurd_direct + goedgekeurd_in_use
    
    # Tel afgekeurde items
    # Items met status "afgekeurd" OF items "in gebruik" met inspection_status "afgekeurd"
    afgekeurd_direct = Material.query.filter_by(status="afgekeurd").count()
    afgekeurd_in_use = db.session.query(Material).filter(
        Material.status == "in gebruik",
        Material.inspection_status == "afgekeurd"
    ).count()
    afgekeurd_count = afgekeurd_direct + afgekeurd_in_use
    
    # Tel items die keuring vereisen (te keuren)
    # Dit zijn alleen items met status "keuring verlopen" of "keuring gepland"
    # Voor items "in gebruik": check inspection_status
    
    # Items met status "keuring verlopen" (direct of via inspection_status)
    keuring_verlopen_direct = Material.query.filter_by(status="keuring verlopen").count()
    keuring_verlopen_in_use = db.session.query(Material).filter(
        Material.status == "in gebruik",
        Material.inspection_status == "keuring verlopen"
    ).count()
    
    # Items met status "keuring gepland" (direct of via inspection_status)
    keuring_gepland_direct = Material.query.filter_by(status="keuring gepland").count()
    keuring_gepland_in_use = db.session.query(Material).filter(
        Material.status == "in gebruik",
        Material.inspection_status == "keuring gepland"
    ).count()
    
    te_keuren = keuring_verlopen_direct + keuring_verlopen_in_use + keuring_gepland_direct + keuring_gepland_in_use
    
    # Haal items op met status "keuring verlopen" voor de "Items die Keuring Vereisen" box
    # Dit zijn items met status "keuring verlopen" OF items "in gebruik" met inspection_status "keuring verlopen"
    keuring_verlopen_items_direct = Material.query.filter_by(status="keuring verlopen").all()
    keuring_verlopen_items_in_use = Material.query.filter(
        Material.status == "in gebruik",
        Material.inspection_status == "keuring verlopen"
    ).all()
    # Combineer beide lijsten en sorteer op naam
    afgekeurde_items = sorted(
        keuring_verlopen_items_direct + keuring_verlopen_items_in_use,
        key=lambda x: (x.name or "").lower()
    )
    
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
