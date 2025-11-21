# app.py
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, g
)
from datetime import datetime
from functools import wraps
import os

from config import Config
from models import db, Gebruiker, Material


app = Flask(__name__)
app.secret_key = "dev"  # voor flash() + sessies
app.config.from_object(Config)

# SQLAlchemy koppelen aan app (Supabase/Postgres)
db.init_app(app)


# ---------------- Recente activiteit (in-memory) ----------------
ACTIVITY_LOG: list[dict] = []


def log_activity(action: str, name: str, serial: str):
    ACTIVITY_LOG.insert(0, {
        "ts": datetime.now(),
        "action": action,
        "name": name,
        "serial": serial
    })
    if len(ACTIVITY_LOG) > 50:
        ACTIVITY_LOG.pop()


# ---------------- Helper: materiaal zoeken ----------------
def find_material(serial: str) -> Material | None:
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


# ---------------- Auth routes (nog steeds wachtwoordloos) ----------------
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

    # simpel voorbeeld: aantal afgekeurde items als “te keuren”
    to_inspect = Material.query.filter_by(status="afgekeurd").count()

    recent = ACTIVITY_LOG[:8]
    return render_template(
        "dashboard.html",
        total_items=total_items,
        to_inspect=to_inspect,
        recent_activity=recent
    )


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
        from sqlalchemy import or_
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
    from sqlalchemy import func
    in_use = db.session.query(func.count(Material.id)) \
        .filter(func.coalesce(Material.site, "") != "") \
        .scalar()

    return render_template(
        "materiaal.html",
        items=items,
        total_items=total_items,
        in_use=in_use,
    )


# ---------------- Materiaal: toevoegen ----------------
@app.route("/materiaal/new", methods=["POST"])
@login_required
def materiaal_toevoegen():
    f = request.form
    serial = (f.get("serial") or "").strip()

    # 1) check: bestaat dit serienummer al in Supabase?
    item = find_material(serial)

    if not item:
        # DIT is de gevraagde foutmelding:
        flash("Materiaal bestaat niet in het datasysteem (Supabase).", "danger")
        return redirect(url_for("materiaal"))

    # 2) Bestaat: we updaten de gegevens op basis van het formulier
    item.name = (f.get("name") or "").strip() or item.name
    item.category = (f.get("category") or "").strip() or item.category
    item.type = (f.get("type") or "").strip() or item.type

    purchase_date = (f.get("purchase_date") or "").strip()
    if purchase_date:
        from datetime import datetime as _dt
        try:
            item.purchase_date = _dt.strptime(purchase_date, "%Y-%m-%d").date()
        except ValueError:
            pass  # laat oude datum staan als parsing faalt

    item.assigned_to = (f.get("assigned_to") or "").strip()
    item.site = (f.get("site") or "").strip()
    item.note = (f.get("note") or "").strip()
    item.status = (f.get("status") or "goedgekeurd").strip()

    db.session.commit()

    log_activity("Toegevoegd / bijgewerkt", item.name or "", item.serial)
    flash("Materieel bijgewerkt in Supabase.", "success")
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

    db.session.commit()

    log_activity("Bewerkt", item.name or "", item.serial)
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


# ---------------- Keuringen dummy ----------------
@app.route("/keuringen")
@login_required
def keuringen():
    return redirect(url_for("materiaal"))


if __name__ == "__main__":
    # zorg dat er een app context is als je lokaal runt
    with app.app_context():
        # GEEN db.create_all(): Supabase beheert de tabellen al
        pass

    app.run(debug=True)
