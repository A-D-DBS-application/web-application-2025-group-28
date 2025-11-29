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

from config import Config
from models import db, Gebruiker, Material, Activity, MaterialUsage, Project
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
# AUTH
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
    to_inspect = Material.query.filter_by(status="afgekeurd").count()
    recent = Activity.query.order_by(Activity.created_at.desc()).limit(8).all()

    return render_template(
        "dashboard.html",
        total_items=total_items,
        to_inspect=to_inspect,
        recent_activity=recent,
    )


# -----------------------------------------------------
# API SEARCH
# -----------------------------------------------------


@app.route("/api/search", methods=["GET"])
@login_required
def api_search():
    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return {"items": []}, 200

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
        results.append(
            {
                "serial": item.serial,
                "name": item.name,
                "category": item.category or "",
                "type": item.type or "",
                "status": item.status or "",
                "assigned_to": item.assigned_to or "",
                "site": item.site or "",
                "purchase_date": item.purchase_date.strftime("%Y-%m-%d")
                if item.purchase_date
                else "",
                "note": item.note or "",
                "nummer_op_materieel": item.nummer_op_materieel or "",
                "documentation_path": item.documentation_path or "",
                "safety_sheet_path": item.safety_sheet_path or "",
            }
        )

    return jsonify({"items": results}), 200


# -----------------------------------------------------
# UPLOADS
# -----------------------------------------------------

BASE_UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
DOC_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "docs")
SAFETY_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "safety")

os.makedirs(DOC_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SAFETY_UPLOAD_FOLDER, exist_ok=True)

app.config["DOC_UPLOAD_FOLDER"] = DOC_UPLOAD_FOLDER
app.config["SAFETY_UPLOAD_FOLDER"] = SAFETY_UPLOAD_FOLDER


def save_upload(file_storage, upload_folder, prefix: str) -> str | None:
    if not file_storage or not file_storage.filename:
        return None

    filename = secure_filename(file_storage.filename)
    final_filename = f"{prefix}_{filename}"

    full_path = os.path.join(upload_folder, final_filename)
    file_storage.save(full_path)

    if upload_folder == app.config["DOC_UPLOAD_FOLDER"]:
        relative_folder = "uploads/docs"
    else:
        relative_folder = "uploads/safety"

    return f"{relative_folder}/{final_filename}"


# -----------------------------------------------------
# MATERIAAL – OVERZICHT
# -----------------------------------------------------


@app.route("/materiaal", methods=["GET"])
@login_required
def materiaal():
    q = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "").strip().lower()
    status = (request.args.get("status") or "").strip().lower()

    query = Material.query

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Material.name.ilike(like), Material.serial.ilike(like))
        )

    if category:
        query = query.filter(Material.category.ilike(category))

    if status:
        query = query.filter(Material.status.ilike(status))

    total_items = Material.query.count()

    in_use = (
        db.session.query(func.count(MaterialUsage.id))
        .filter(MaterialUsage.is_active.is_(True))
        .scalar()
    ) or 0

    all_materials = Material.query.all()

    # wervenlijst voor dropdown in gebruik-modal
    today = datetime.utcnow().date()
    projects = (
        Project.query.filter(Project.is_deleted.is_(False))
        .order_by(Project.start_date.asc())
        .all()
    )

    # actieve usages
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

        if current_user_id and usage.user_id == current_user_id:
            my_usages.append(row)
        else:
            other_usages.append(row)

    items = query.all()
    items.sort(
        key=lambda it: (
            it.id not in active_material_ids,
            (it.name or "").lower(),
        )
    )

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
    )


# -----------------------------------------------------
# MATERIAAL – TOEVOEGEN / BEWERKEN / VERWIJDEREN
# -----------------------------------------------------


@app.route("/materiaal/new", methods=["POST"])
@login_required
def materiaal_toevoegen():
    f = request.form

    admin_pw = (f.get("admin_password") or "").strip()
    if admin_pw != "Sunset":
        flash("Onjuist wachtwoord voor het toevoegen van nieuw materieel.", "danger")
        return redirect(url_for("materiaal"))

    name = (f.get("name") or "").strip()
    serial = (f.get("serial") or "").strip()
    nummer = (f.get("nummer_op_materieel") or "").strip()
    category = (f.get("category") or "").strip()
    type_ = (f.get("type") or "").strip()
    purchase_date_str = (f.get("purchase_date") or "").strip()
    site = (f.get("site") or "").strip()
    assigned_to = (f.get("assigned_to") or "").strip()
    note = (f.get("note") or "").strip()
    status = (f.get("status") or "goedgekeurd").strip()
    inspection_status = (f.get("inspection_status") or "").strip()

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
        category=category,
        type=type_,
        assigned_to=assigned_to if assigned_to else None,
        site=site if site else None,
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

    item.inspection_status = inspection_status or None

    db.session.add(item)
    db.session.commit()

    log_activity_db("Toegevoegd", item.name or "", item.serial or "")
    flash("Nieuw materieel is toegevoegd aan Supabase.", "success")
    return redirect(url_for("materiaal"))


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
    item.category = (f.get("category") or "").strip()
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
    item.status = (f.get("status") or "goedgekeurd").strip()
    item.nummer_op_materieel = (f.get("nummer_op_materieel") or "").strip()
    item.inspection_status = (f.get("inspection_status") or "").strip() or None

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


@app.route("/materiaal/delete", methods=["POST"])
@login_required
def materiaal_verwijderen():
    serial = (request.form.get("serial") or "").strip()
    item = find_material_by_serial(serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

    db.session.delete(item)
    db.session.commit()

    log_activity_db("Verwijderd", item.name or "", serial)
    flash("Materieel verwijderd.", "success")
    return redirect(url_for("materiaal"))


# -----------------------------------------------------
# MATERIAAL – IN GEBRUIK / STOP
# -----------------------------------------------------


@app.route("/materiaal/use", methods=["POST"])
@login_required
def materiaal_gebruiken():
    f = request.form

    name = (f.get("name") or "").strip()
    nummer = (f.get("nummer_op_materieel") or "").strip()
    assigned_to = (f.get("assigned_to") or "").strip()
    site = (f.get("site") or "").strip()
    project_id_str = (f.get("project_id") or "").strip()

    project = None
    if project_id_str:
        try:
            pid = int(project_id_str)
            project = Project.query.filter(
                Project.id == pid, Project.is_deleted.is_(False)
            ).first()
        except ValueError:
            project = None

    if not name and not nummer:
        flash("Naam of nummer op materieel is verplicht.", "danger")
        return redirect(url_for("materiaal"))

    item = find_material_by_name_or_number(name, nummer)
    if not item:
        flash("Materiaal niet gevonden in het datasysteem.", "danger")
        return redirect(url_for("materiaal"))

    if not assigned_to and getattr(g, "user", None):
        assigned_to = g.user.Naam or ""

    item.assigned_to = assigned_to

    if project:
        item.project_id = project.id
        item.site = project.name or project.type
        site_value = item.site
    else:
        item.site = site or item.site
        site_value = item.site

    user_id = g.user.gebruiker_id if getattr(g, "user", None) else None
    usage = MaterialUsage(
        material_id=item.id,
        user_id=user_id,
        project_id=project.id if project else None,
        site=site_value or None,
        note=None,
        start_time=datetime.utcnow(),
        end_time=None,
        is_active=True,
        used_by=assigned_to or (g.user.Naam if getattr(g, "user", None) else None),
    )

    db.session.add(usage)
    db.session.commit()

    log_activity_db("In gebruik", item.name or "", item.serial or "")
    flash("Materieel staat nu als 'in gebruik'.", "success")
    return redirect(url_for("materiaal"))


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

    mat = Material.query.filter_by(id=usage.material_id).first()
    if mat and mat.assigned_to == usage.used_by:
        mat.assigned_to = None
        mat.site = None
        mat.project_id = None

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
        Project.query.filter(Project.is_deleted.is_(False))
        .order_by(Project.start_date.asc())
        .all()
    )
    return render_template("werven.html", projects=projects, today=today)


@app.route("/werven/<int:project_id>")
@login_required
def werf_detail(project_id: int):
    project = (
        Project.query.filter(Project.id == project_id, Project.is_deleted.is_(False))
        .first_or_404()
    )

    materials = Material.query.filter(Material.project_id == project.id).all()

    active_usages = (
        db.session.query(MaterialUsage, Material)
        .join(Material, MaterialUsage.material_id == Material.id)
        .filter(
            MaterialUsage.is_active.is_(True),
            MaterialUsage.project_id == project.id,
        )
        .order_by(MaterialUsage.start_time.desc())
        .all()
    )

    all_materials = Material.query.all()
    today = datetime.utcnow().date()

    return render_template(
        "werf_detail.html",
        project=project,
        materials=materials,
        active_usages=active_usages,
        all_materials=all_materials,
        today=today,
    )


@app.route("/werven/new", methods=["POST"])
@login_required
def werf_toevoegen():
    f = request.form

    name = (f.get("name") or "").strip()
    address = (f.get("address") or "").strip()
    start_date_str = (f.get("start_date") or "").strip()
    end_date_str = (f.get("end_date") or "").strip()
    image_url = (f.get("image_url") or "").strip()
    note = (f.get("note") or "").strip()
    type_ = (f.get("type") or "").strip()

    if not name or not start_date_str:
        flash("Naam en startdatum zijn verplicht voor een werf.", "danger")
        return redirect(url_for("werven"))

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige startdatum.", "danger")
        return redirect(url_for("werven"))

    end_date = None
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Ongeldige einddatum, die wordt genegeerd.", "warning")

    project = Project(
        name=name,
        address=address or None,
        start_date=start_date,
        end_date=end_date,
        type=type_ or None,
        image_url=image_url or None,
        note=note or None,
        is_deleted=False,
    )
    db.session.add(project)
    db.session.commit()

    flash("Werf toegevoegd.", "success")
    return redirect(url_for("werven"))


@app.route("/werven/<int:project_id>/edit", methods=["POST"])
@login_required
def werf_bewerken(project_id: int):
    project = (
        Project.query.filter(Project.id == project_id, Project.is_deleted.is_(False))
        .first()
    )
    if not project:
        flash("Werf niet gevonden.", "danger")
        return redirect(url_for("werven"))

    f = request.form

    name = (f.get("name") or "").strip()
    address = (f.get("address") or "").strip()
    start_date_str = (f.get("start_date") or "").strip()
    end_date_str = (f.get("end_date") or "").strip()
    image_url = (f.get("image_url") or "").strip()
    note = (f.get("note") or "").strip()
    type_ = (f.get("type") or "").strip()

    if not name or not start_date_str:
        flash("Naam en startdatum zijn verplicht.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige startdatum.", "danger")
        return redirect(url_for("werf_detail", project_id=project_id))

    end_date = None
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Ongeldige einddatum, die wordt genegeerd.", "warning")

    project.name = name
    project.address = address or None
    project.start_date = start_date
    project.end_date = end_date
    project.image_url = image_url or None
    project.note = note or None
    project.type = type_ or None

    db.session.commit()
    flash("Werf bijgewerkt.", "success")
    return redirect(url_for("werf_detail", project_id=project_id))


@app.route("/werven/delete", methods=["POST"])
@login_required
def werf_verwijderen():
    project_id_str = (request.form.get("project_id") or "").strip()
    if not project_id_str:
        flash("Geen werf opgegeven.", "danger")
        return redirect(url_for("werven"))

    try:
        pid = int(project_id_str)
    except ValueError:
        flash("Ongeldige werf.", "danger")
        return redirect(url_for("werven"))

    project = (
        Project.query.filter(Project.id == pid, Project.is_deleted.is_(False))
        .first()
    )
    if not project:
        flash("Werf niet gevonden.", "danger")
        return redirect(url_for("werven"))

    project.is_deleted = True
    db.session.commit()

    flash("Werf verwijderd.", "success")
    return redirect(url_for("werven"))


@app.route("/werven/<int:project_id>/materiaal/use", methods=["POST"])
@login_required
def werf_materiaal_gebruiken(project_id: int):
    project = (
        Project.query.filter(Project.id == project_id, Project.is_deleted.is_(False))
        .first()
    )
    if not project:
        flash("Werf niet gevonden.", "danger")
        return redirect(url_for("werven"))

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

    if not assigned_to and getattr(g, "user", None):
        assigned_to = g.user.Naam or ""

    item.assigned_to = assigned_to
    item.project_id = project.id
    item.site = project.name or project.type

    user_id = g.user.gebruiker_id if getattr(g, "user", None) else None
    usage = MaterialUsage(
        material_id=item.id,
        user_id=user_id,
        project_id=project.id,
        site=item.site,
        note=None,
        start_time=datetime.utcnow(),
        end_time=None,
        is_active=True,
        used_by=assigned_to or (g.user.Naam if getattr(g, "user", None) else None),
    )

    db.session.add(usage)
    db.session.commit()

    log_activity_db("In gebruik", item.name or "", item.serial or "")
    flash("Materieel gekoppeld aan deze werf en staat nu als 'in gebruik'.", "success")
    return redirect(url_for("werf_detail", project_id=project_id))


# -----------------------------------------------------
# KEURINGEN / DOCUMENTEN (ongewijzigd)
# -----------------------------------------------------


@app.route("/keuringen")
@login_required
def keuringen():
    return render_template("keuringen.html")


@app.route("/documenten")
@login_required
def documenten():
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
        pass

    app.run(debug=True)
