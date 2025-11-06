# app/app.py
from flask import Flask, render_template, request, redirect, url_for
from dataclasses import dataclass, asdict
from datetime import date

app = Flask(__name__)

# --- Eenvoudig in-memory "model" om te starten ---
@dataclass
class Material:
    name: str
    serial: str
    category: str
    type: str
    purchase_date: str  # ISO yyyy-mm-dd
    assigned_to: str | None = None
    site: str | None = None
    note: str | None = None
    status: str = "goedgekeurd"          # of "afgekeurd"
    inspection_status: str | None = None

# globaal lijstje (vervang dit later door DB/SQLAlchemy)
MATERIALS: list[Material] = [
    Material(name="Boormachine Bosch", serial="BH-2024-001",
             category="klein materieel", type="Elektrisch gereedschap",
             purchase_date=str(date.today()), status="goedgekeurd",
             inspection_status="OK 2025-06"),
]

# --- Bestaande dashboard route voorbeeld (optioneel) ---
@app.route("/")
def dashboard():
    total_items = len(MATERIALS)
    to_inspect = sum(1 for m in MATERIALS if (m.inspection_status or "").lower().startswith("due"))
    return render_template("dashboard.html",
                           total_items=total_items,
                           to_inspect=to_inspect)

# --- MATERIAAL: lijst + filters ---
@app.route("/materiaal", methods=["GET"])
def materiaal():
    q = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "").strip().lower()
    status = (request.args.get("status") or "").strip().lower()

    items = MATERIALS
    if q:
        items = [m for m in items if q in m.name.lower() or q in m.serial.lower()]
    if category:
        items = [m for m in items if m.category.lower() == category]
    if status:
        items = [m for m in items if m.status.lower() == status]

    total_items = len(MATERIALS)
    in_use = sum(1 for m in MATERIALS if (m.site or "").strip() != "")

    return render_template(
        "materiaal.html",
        items=items,
        total_items=total_items,
        in_use=in_use,
    )

# --- POST: nieuw materiaal opslaan ---
@app.route("/materiaal/new", methods=["POST"])
def materiaal_toevoegen():
    form = request.form

    new_item = Material(
        name=form.get("name","").strip(),
        serial=form.get("serial","").strip(),
        category=form.get("category","").strip(),
        type=form.get("type","").strip(),
        purchase_date=form.get("purchase_date","").strip(),
        assigned_to=form.get("assigned_to","").strip(),
        site=form.get("site","").strip(),
        note=form.get("note","").strip(),
        status=form.get("status","goedgekeurd").strip(),
        inspection_status=form.get("inspection_status","").strip(),
    )
    MATERIALS.insert(0, new_item)  # bovenaan tonen

    # terug naar de lijst (filters blijven behouden als je wilt)
    return redirect(url_for("materiaal"))

# --- Keuringen dummy (zodat je menu niet breekt) ---
@app.route("/keuringen")
def keuringen():
    return render_template("keuringen.html") if False else redirect(url_for("materiaal"))

if __name__ == "__main__":
    app.run(debug=True)


