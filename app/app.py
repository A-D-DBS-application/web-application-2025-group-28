# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from datetime import datetime
from functools import wraps
import json, os

app = Flask(__name__)
app.secret_key = "dev"  # voor flash() + sessies

# ---------------- In-memory data (materiaal) ----------------
MATERIALS = [
    {
        "name": "Boormachine Bosch",
        "serial": "BH-2024-001",
        "category": "klein materieel",
        "type": "Elektrisch gereedschap",
        "purchase_date": "2025-01-15",
        "assigned_to": "",
        "site": "",
        "note": "",
        "status": "goedgekeurd",
        "inspection_status": "OK 2025-06",
    }
]

# Recente activiteit
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

def find_material(serial: str):
    for m in MATERIALS:
        if m["serial"] == serial:
            return m
    return None

# ---------------- Eenvoudige lokale "users database" ----------------
USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return []
    return []

def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

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
    for u in load_users():
        if u["Email"] == email:
            g.user = u
            break

@app.context_processor
def inject_user():
    # in templates beschikbaar als {{ current_user }}
    return {"current_user": g.user}

# ---------------- Auth routes (wachtwoordloos) ----------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    users = load_users()
    if request.method == "POST":
        naam = (request.form.get("naam") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        functie = (request.form.get("functie") or "").strip()

        if not email:
            flash("E-mail is verplicht.", "danger")
            return render_template("auth_signup.html")

        if any(u["Email"] == email for u in users):
            flash("E-mail bestaat al. Log in a.u.b.", "warning")
            return redirect(url_for("login", email=email))

        new_user = {"Naam": naam, "Email": email, "Functie": functie}
        users.append(new_user)
        save_users(users)

        session["user_email"] = email
        flash("Account aangemaakt en ingelogd.", "success")
        return redirect(url_for("dashboard"))

    # GET
    return render_template("auth_signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    users = load_users()
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if not email:
            flash("E-mail is verplicht.", "danger")
            return render_template("auth_login.html")

        user = next((u for u in users if u["Email"] == email), None)
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
    total_items = len(MATERIALS)
    to_inspect = sum(1 for m in MATERIALS if str(m.get("inspection_status","")).lower().startswith("due"))
    recent = ACTIVITY_LOG[:8]
    return render_template(
        "dashboard.html",
        total_items=total_items,
        to_inspect=to_inspect,
        recent_activity=recent
    )

@app.route("/materiaal", methods=["GET"])
@login_required
def materiaal():
    q = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "").strip().lower()
    status = (request.args.get("status") or "").strip().lower()

    items = MATERIALS
    if q:
        items = [m for m in items if q in m["name"].lower() or q in m["serial"].lower()]
    if category:
        items = [m for m in items if m["category"].lower() == category]
    if status:
        items = [m for m in items if m["status"].lower() == status]

    total_items = len(MATERIALS)
    in_use = sum(1 for m in MATERIALS if (m.get("site") or "").strip() != "")

    return render_template(
        "materiaal.html",
        items=items,
        total_items=total_items,
        in_use=in_use,
    )

@app.route("/materiaal/new", methods=["POST"])
@login_required
def materiaal_toevoegen():
    f = request.form
    new_item = {
        "name": f.get("name","").strip(),
        "serial": f.get("serial","").strip(),
        "category": f.get("category","").strip(),
        "type": f.get("type","").strip(),
        "purchase_date": f.get("purchase_date","").strip(),
        "assigned_to": f.get("assigned_to","").strip(),
        "site": f.get("site","").strip(),
        "note": f.get("note","").strip(),
        "status": (f.get("status","goedgekeurd") or "goedgekeurd").strip(),
        "inspection_status": f.get("inspection_status","").strip(),
    }

    if find_material(new_item["serial"]):
        flash("Serienummer bestaat al.", "danger")
        return redirect(url_for("materiaal"))

    MATERIALS.insert(0, new_item)
    log_activity("Toegevoegd", new_item["name"], new_item["serial"])
    flash("Materieel toegevoegd.", "success")
    return redirect(url_for("materiaal"))

@app.route("/materiaal/edit", methods=["POST"])
@login_required
def materiaal_bewerken():
    f = request.form
    original_serial = f.get("original_serial","").strip()
    item = find_material(original_serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

    new_serial = f.get("serial","").strip()
    if new_serial != original_serial and find_material(new_serial):
        flash("Nieuw serienummer bestaat al.", "danger")
        return redirect(url_for("materiaal"))

    item.update({
        "name": f.get("name","").strip(),
        "serial": new_serial,
        "category": f.get("category","").strip(),
        "type": f.get("type","").strip(),
        "purchase_date": f.get("purchase_date","").strip(),
        "assigned_to": f.get("assigned_to","").strip(),
        "site": f.get("site","").strip(),
        "note": f.get("note","").strip(),
        "status": (f.get("status","goedgekeurd") or "goedgekeurd").strip(),
        "inspection_status": f.get("inspection_status","").strip(),
    })
    log_activity("Bewerkt", item["name"], item["serial"])
    flash("Materieel bewerkt.", "success")
    return redirect(url_for("materiaal"))

@app.route("/materiaal/delete", methods=["POST"])
@login_required
def materiaal_verwijderen():
    serial = (request.form.get("serial") or "").strip()
    item = find_material(serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

    MATERIALS.remove(item)
    log_activity("Verwijderd", item["name"], serial)
    flash("Materieel verwijderd.", "success")
    return redirect(url_for("materiaal"))

@app.route("/keuringen")
@login_required
def keuringen():
    return redirect(url_for("materiaal"))

if __name__ == "__main__":
    app.run(debug=True)
