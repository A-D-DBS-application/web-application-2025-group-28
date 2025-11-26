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
from models import db, Gebruiker, Material, Activity, MaterialUsage
from sqlalchemy import or_, func
from werkzeug.utils import secure_filename

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
from werkzeug.security import generate_password_hash, check_password_hash


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

    # voorbeeld: aantal items met status 'afgekeurd' als "te keuren"
    to_inspect = Material.query.filter_by(status="afgekeurd").count()

    # recente activiteit uit activity_log tabel
    recent = Activity.query.order_by(Activity.created_at.desc()).limit(8).all()

    return render_template(
        "dashboard.html",
        total_items=total_items,
        to_inspect=to_inspect,
        recent_activity=recent,
    )


# -----------------------------------------------------
# API SEARCH VOOR DASHBOARD
# -----------------------------------------------------


@app.route("/api/search", methods=["GET"])
@login_required
def api_search():
    """API endpoint for searching materials - returns JSON"""
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
# UPLOAD CONFIGURATIE – documentatie & veiligheidsfiches
# -----------------------------------------------------

BASE_UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
DOC_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "docs")
SAFETY_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "safety")

os.makedirs(DOC_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SAFETY_UPLOAD_FOLDER, exist_ok=True)

app.config["DOC_UPLOAD_FOLDER"] = DOC_UPLOAD_FOLDER
app.config["SAFETY_UPLOAD_FOLDER"] = SAFETY_UPLOAD_FOLDER


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

    items = query.all()

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

    current_user_id = g.user.gebruiker_id if getattr(g, "user", None) else None

    for usage, mat in active_usages:
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

    return render_template(
        "materiaal.html",
        items=items,
        total_items=total_items,
        in_use=in_use,
        all_materials=all_materials,
        my_usages=my_usages,
        other_usages=other_usages,
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

    inspection_status = (f.get("inspection_status") or "").strip()
    if hasattr(item, "inspection_status"):
        setattr(
            item,
            "inspection_status",
            inspection_status if inspection_status else None,
        )

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

    if not name and not nummer:
        flash("Naam of nummer op materieel is verplicht.", "danger")
        return redirect(url_for("materiaal"))

    item = find_material_by_name_or_number(name, nummer)
    if not item:
        flash("Materiaal niet gevonden in het datasysteem.", "danger")
        return redirect(url_for("materiaal"))

    if not assigned_to and getattr(g, "user", None):
        assigned_to = g.user.Naam or ""

    # update materiaal zelf (optioneel)
    item.assigned_to = assigned_to
    item.site = site or item.site

    # Nieuwe gebruik-sessie
    user_id = g.user.gebruiker_id if getattr(g, "user", None) else None
    usage = MaterialUsage(
        material_id=item.id,
        user_id=user_id,
        site=site or None,
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
    if mat and mat.assigned_to == usage.used_by:
        mat.assigned_to = None
        mat.site = None

    db.session.commit()

    if mat:
        log_activity_db("Niet meer in gebruik", mat.name or "", mat.serial or "")

    flash("Materieel wordt niet langer als 'in gebruik' getoond.", "success")
    return redirect(url_for("materiaal"))


# -----------------------------------------------------
# KEURINGEN EN DOCUMENTEN
# -----------------------------------------------------


@app.route("/keuringen")
@login_required
def keuringen():
    return render_template("keuringen.html")


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
