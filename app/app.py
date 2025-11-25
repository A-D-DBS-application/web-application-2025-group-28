from flask import Flask, render_template, request, redirect, url_for, flash, session, g, jsonify
from datetime import datetime
from functools import wraps


from config import Config
from models import db, Gebruiker, Material
from sqlalchemy import or_, func


app = Flask(__name__)
app.secret_key = "dev"  # voor flash() + sessies
app.config.from_object(Config)

# SQLAlchemy koppelen aan app (Supabase/Postgres)
db.init_app(app)


# ---------------- Recente activiteit (in-memory) ----------------
ACTIVITY_LOG: list[dict] = []


def log_activity(action: str, name: str, serial: str):
    """Sla een activiteit op, inclusief welke gebruiker het deed."""
    ACTIVITY_LOG.insert(0, {
        "ts": datetime.now(),
        "action": action,
        "name": name,
        "serial": serial,
        "user": g.user.Naam if getattr(g, "user", None) and g.user.Naam else "Onbekend"
    })
    if len(ACTIVITY_LOG) > 50:
        ACTIVITY_LOG.pop()


# ---------------- Helper: materiaal zoeken ----------------
def find_material(serial: str):
    if not serial:
        return None
    return Material.query.filter_by(serial=serial).first()


# ---------------- Auth helpers ----------------
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


# ---------------- Auth routes (wachtwoordloos) ----------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        naam = (request.form.get("naam") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        functie = (request.form.get("functie") or "").strip()

        if not email:
            flash("E-mail is verplicht.", "danger")
            return render_template("auth_signup.html")

        # bestaat al in Supabase?
        if Gebruiker.query.filter_by(Email=email).first():
            flash("E-mail bestaat al. Log in a.u.b.", "warning")
            return redirect(url_for("login", email=email))

        new_user = Gebruiker(Naam=naam, Email=email, Functie=functie)
        db.session.add(new_user)
        db.session.commit()

        session["user_email"] = email
        flash("Account aangemaakt en ingelogd.", "success")
        return redirect(url_for("dashboard"))

    # GET
    return render_template("auth_signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if not email:
            flash("E-mail is verplicht.", "danger")
            return render_template("auth_login.html")

        user = Gebruiker.query.filter_by(Email=email).first()
        if not user:
            flash("Geen account gevonden. Registreer je even.", "info")
            return redirect(url_for("signup", email=email))

        session["user_email"] = email
        flash("Je bent ingelogd.", "success")
        next_url = request.args.get("next")
        return redirect(next_url or url_for("dashboard"))

    # GET
    return render_template("auth_login.html", prefill_email=request.args.get("email", ""))


@app.route("/logout")
def logout():
    session.clear()
    flash("Je bent uitgelogd.", "info")
    return redirect(url_for("login"))


# ---------------- Beschermde pagina’s ----------------
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

    recent = ACTIVITY_LOG[:8]
    return render_template(
        "dashboard.html",
        total_items=total_items,
        to_inspect=to_inspect,
        recent_activity=recent
    )


@app.route("/api/search", methods=["GET"])
@login_required
def api_search():
    """API endpoint for searching materials - returns JSON"""
    q = (request.args.get("q") or "").strip().lower()
    
    if not q:
        return {"items": []}, 200
    
    like = f"%{q}%"
    items = Material.query.filter(
        or_(Material.name.ilike(like), Material.serial.ilike(like))
    ).limit(10).all()
    
    results = []
    for item in items:
        results.append({
            "serial": item.serial,
            "name": item.name,
            "category": item.category or "",
            "type": item.type or "",
            "status": item.status or "",
            "assigned_to": item.assigned_to or "",
            "site": item.site or "",
            "purchase_date": item.purchase_date.strftime("%Y-%m-%d") if item.purchase_date else "",
            "note": item.note or "",
            "nummer_op_materieel": item.nummer_op_materieel or "",
            "documentation_path": item.documentation_path or "",
            "safety_sheet_path": item.safety_sheet_path or "",
        })
    
    return jsonify({"items": results}), 200


# ---------------- Materiaal-overzicht ----------------
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
            or_(Material.name.ilike(like),
                Material.serial.ilike(like))
        )

    if category:
        query = query.filter(Material.category.ilike(category))

    if status:
        query = query.filter(Material.status.ilike(status))

    items = query.all()

    total_items = Material.query.count()

    # "in gebruik" = assigned_to OF site niet leeg
    in_use = db.session.query(func.count(Material.id)).filter(
        (func.coalesce(Material.assigned_to, "") != "") |
        (func.coalesce(Material.site, "") != "")
    ).scalar()

    # alle materialen voor datalist in "Gebruik Materieel"
    all_materials = Material.query.all()

    return render_template(
        "materiaal.html",
        items=items,
        total_items=total_items,
        in_use=in_use,
        all_materials=all_materials,
    )

# -----------------------------------------------------
# UPLOAD CONFIGURATIE – documentatie & veiligheidsfiches
# -----------------------------------------------------
import os
from werkzeug.utils import secure_filename

BASE_UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
DOC_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "docs")
SAFETY_UPLOAD_FOLDER = os.path.join(BASE_UPLOAD_FOLDER, "safety")

os.makedirs(DOC_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SAFETY_UPLOAD_FOLDER, exist_ok=True)

app.config["DOC_UPLOAD_FOLDER"] = DOC_UPLOAD_FOLDER
app.config["SAFETY_UPLOAD_FOLDER"] = SAFETY_UPLOAD_FOLDER

# -----------------------------------------------------
# BESTAND UPLOAD HELPER – documentatie & veiligheidsfiches
# -----------------------------------------------------
def save_upload(file_storage, upload_folder, prefix: str) -> str | None:
    """
    Sla een geüpload bestand op en geef het relatieve pad terug.
    (bv. 'uploads/docs/BOOR123_foto.pdf')
    Retourneert None wanneer er geen geldig bestand werd meegegeven.
    """

    # Geen bestand → niets opslaan
    if not file_storage or not file_storage.filename:
        return None

    # Veilige bestandsnaam genereren
    filename = secure_filename(file_storage.filename)
    final_filename = f"{prefix}_{filename}"

    # Volledig pad op schijf
    full_path = os.path.join(upload_folder, final_filename)
    file_storage.save(full_path)

    # Relatieve map binnen /static bepalen
    if upload_folder == app.config["DOC_UPLOAD_FOLDER"]:
        relative_folder = "uploads/docs"
    else:
        relative_folder = "uploads/safety"

    # Relatief pad teruggeven (voor opslag in DB)
    return f"{relative_folder}/{final_filename}"

# ---------------- Materiaal: toevoegen (via + in KPI) ----------------
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

    # bestanden zoals documentatie & veiligheidsfiche ophalen
    documentation_file = request.files.get("documentation")
    safety_file = request.files.get("safety_sheet")

    if not name or not serial:
        flash("Naam en serienummer zijn verplicht.", "danger")
        return redirect(url_for("materiaal"))

    # check op dubbele serial
    bestaand = find_material(serial)
    if bestaand:
        flash("Serienummer bestaat al in het systeem.", "danger")
        return redirect(url_for("materiaal"))

    # uploads opslaan (relatieve paden)
    documentation_path = save_upload(
        documentation_file, app.config["DOC_UPLOAD_FOLDER"], f"{serial}_doc"
    )
    safety_sheet_path = save_upload(
        safety_file, app.config["SAFETY_UPLOAD_FOLDER"], f"{serial}_safety"
    )

    # nieuw Material-object (rij in Supabase)
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

    # aankoopdatum (optioneel) parsen
    if purchase_date_str:
        from datetime import datetime as _dt
        try:
            item.purchase_date = _dt.strptime(purchase_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    # als je een kolom hebt voor keuring/inspection_status in je model, zet die hier:
    if hasattr(item, "inspection_status"):
        setattr(item, "inspection_status", inspection_status if inspection_status else None)

    db.session.add(item)
    db.session.commit()

    log_activity("Toegevoegd", item.name or "", item.serial or "")
    flash("Nieuw materieel is toegevoegd aan Supabase.", "success")
    return redirect(url_for("materiaal"))


# ---------------- Materiaal: bewerken ----------------
@app.route("/materiaal/edit", methods=["POST"])
@login_required
def materiaal_bewerken():
    f = request.form
    original_serial = (f.get("original_serial") or "").strip()
    item = find_material(original_serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

    new_serial = (f.get("serial") or "").strip()
    if not new_serial:
        flash("Serienummer is verplicht.", "danger")
        return redirect(url_for("materiaal"))

    if new_serial != original_serial and find_material(new_serial):
        flash("Nieuw serienummer bestaat al.", "danger")
        return redirect(url_for("materiaal"))

    item.serial = new_serial
    item.name = (f.get("name") or "").strip()
    item.category = (f.get("category") or "").strip()
    item.type = (f.get("type") or "").strip()

    purchase_date = (f.get("purchase_date") or "").strip()
    if purchase_date:
        from datetime import datetime as _dt
        try:
            item.purchase_date = _dt.strptime(purchase_date, "%Y-%m-%d").date()
        except ValueError:
            pass

    item.assigned_to = (f.get("assigned_to") or "").strip()
    item.site = (f.get("site") or "").strip()
    item.note = (f.get("note") or "").strip()
    item.status = (f.get("status") or "goedgekeurd").strip()
    item.nummer_op_materieel = (f.get("nummer_op_materieel") or "").strip()

    # optioneel keuringstatus
    inspection_status = (f.get("inspection_status") or "").strip()
    if hasattr(item, "inspection_status"):
        setattr(item, "inspection_status", inspection_status if inspection_status else None)

    # NIEUW: bestanden (overschrijven als je er nieuwe uploadt)
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

    log_activity("Bewerkt", item.name or "", item.serial or "")
    flash("Materieel bewerkt.", "success")
    return redirect(url_for("materiaal"))


# ---------------- Materiaal: verwijderen ----------------
@app.route("/materiaal/delete", methods=["POST"])
@login_required
def materiaal_verwijderen():
    serial = (request.form.get("serial") or "").strip()
    item = find_material(serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

    db.session.delete(item)
    db.session.commit()

    log_activity("Verwijderd", item.name or "", serial)
    flash("Materieel verwijderd.", "success")
    return redirect(url_for("materiaal"))


# ---------------- Materiaal: in gebruik nemen ----------------
@app.route("/materiaal/use", methods=["POST"])
@login_required
def materiaal_gebruiken():
    """
    Materieel in gebruik nemen.
    HIER hoort de foutmelding “Materiaal niet gevonden in het datasysteem”.
    """
    f = request.form

    name = (f.get("name") or "").strip()
    nummer = (f.get("nummer_op_materieel") or "").strip()
    assigned_to = (f.get("assigned_to") or "").strip()
    site = (f.get("site") or "").strip()

    if not name:
        flash("Naam van het materieel is verplicht.", "danger")
        return redirect(url_for("materiaal"))

    # zoek eerst op nummer, dan op naam
    item = None
    if nummer:
        item = Material.query.filter_by(nummer_op_materieel=nummer).first()
    if not item and name:
        item = Material.query.filter_by(name=name).first()

    if not item:
        flash("Materiaal niet gevonden in het datasysteem.", "danger")
        return redirect(url_for("materiaal"))

    # markeer als in gebruik
    if not assigned_to and getattr(g, "user", None):
        assigned_to = g.user.Naam or ""

    item.assigned_to = assigned_to
    item.site = site

    db.session.commit()

    log_activity("In gebruik", item.name or "", item.serial or "")
    flash("Materieel staat nu als 'in gebruik'.", "success")
    return redirect(url_for("materiaal"))


# ---------------- Keuringen ----------------
@app.route("/keuringen")
@login_required
def keuringen():
    return render_template("keuringen.html")


# ---------------- Documenten ----------------
@app.route("/documenten")
@login_required
def documenten():
    """Documenten overzicht met zoeken en filteren"""
    import os
    
    q = (request.args.get("q") or "").strip().lower()
    doc_type = (request.args.get("type") or "").strip().lower()
    
    # Verzamel alle documenten uit Material records
    all_materials = Material.query.all()
    documents = []
    
    for material in all_materials:
        # Documentatie toevoegen
        if material.documentation_path:
            doc_name = os.path.basename(material.documentation_path)
            # Bepaal type op basis van bestandsnaam
            doc_type_from_name = "Handleiding" if "handleiding" in doc_name.lower() or "manual" in doc_name.lower() else "Overige"
            
            documents.append({
                "type": doc_type_from_name,
                "name": doc_name,
                "material": material.name or "Onbekend",
                "material_serial": material.serial,
                "date": material.created_at.strftime("%Y-%m-%d") if material.created_at else "",
                "size": "2.3 MB",  # Dummy size
                "uploaded_by": material.assigned_to or "Systeem",
                "path": material.documentation_path,
                "status": doc_type_from_name
            })
        
        # Veiligheidsfiche toevoegen
        if material.safety_sheet_path:
            doc_name = os.path.basename(material.safety_sheet_path)
            documents.append({
                "type": "Veiligheidscertificaat",
                "name": doc_name,
                "material": material.name or "Onbekend",
                "material_serial": material.serial,
                "date": material.created_at.strftime("%Y-%m-%d") if material.created_at else "",
                "size": "456 KB",  # Dummy size
                "uploaded_by": material.assigned_to or "Systeem",
                "path": material.safety_sheet_path,
                "status": "Veiligheidscertificaat"
            })
    
    # Voeg dummy documenten toe voor voorbeelden
    documents.append({
        "type": "Servicerapport",
        "name": "Service-Rapport-Augustus-2024.pdf",
        "material": "Compressor Atlas Copco",
        "material_serial": "CP-2022-112",
        "date": "2024-08-01",
        "size": "1.1 MB",
        "uploaded_by": "Atlas Copco",
        "path": None,
        "status": "Servicerapport"
    })
    
    # Filter op zoekterm
    if q:
        documents = [d for d in documents if q in d["name"].lower() or q in d["material"].lower()]
    
    # Filter op type
    if doc_type and doc_type != "alle":
        documents = [d for d in documents if d["type"].lower() == doc_type.lower()]
    
    total_docs = len(documents)
    safety_certs = len([d for d in documents if d["type"] == "Veiligheidscertificaat"])
    
    return render_template(
        "documenten.html",
        documents=documents,
        total_docs=total_docs,
        safety_certs=safety_certs,
        search_query=q,
        selected_type=doc_type
    )


if __name__ == "__main__":
    with app.app_context():
        # geen db.create_all(); Supabase beheert de tabellen
        pass

    app.run(debug=True)
