from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime

app = Flask(__name__)
app.secret_key = "dev"  # voor flash() in deze demo

# --- In-memory data (vervang later door DB) ---
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

# Recente activiteit (nieuw / bewerkt / verwijderd)
# item: {"ts": datetime, "action": "Toegevoegd|Bewerkt|Verwijderd", "name": str, "serial": str}
ACTIVITY_LOG: list[dict] = []


# --- Helpers ---
def log_activity(action: str, name: str, serial: str):
    ACTIVITY_LOG.insert(0, {
        "ts": datetime.now(),
        "action": action,
        "name": name,
        "serial": serial
    })
    # begrens lijst
    if len(ACTIVITY_LOG) > 50:
        ACTIVITY_LOG.pop()

def find_material(serial: str):
    for m in MATERIALS:
        if m["serial"] == serial:
            return m
    return None


# --- Routes ---
@app.route("/")
@app.route("/dashboard")
def dashboard():
    total_items = len(MATERIALS)
    to_inspect = sum(1 for m in MATERIALS if str(m.get("inspection_status","")).lower().startswith("due"))

    # toon de 8 meest recente activiteiten
    recent = ACTIVITY_LOG[:8]
    return render_template(
        "dashboard.html",
        total_items=total_items,
        to_inspect=to_inspect,
        recent_activity=recent
    )


@app.route("/materiaal", methods=["GET"])
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

    # eenvoudige check op duplicate serial
    if find_material(new_item["serial"]):
        flash("Serienummer bestaat al.", "danger")
        return redirect(url_for("materiaal"))

    MATERIALS.insert(0, new_item)
    log_activity("Toegevoegd", new_item["name"], new_item["serial"])
    flash("Materieel toegevoegd.", "success")
    return redirect(url_for("materiaal"))


@app.route("/materiaal/edit", methods=["POST"])
def materiaal_bewerken():
    f = request.form
    original_serial = f.get("original_serial","").strip()
    item = find_material(original_serial)
    if not item:
        flash("Item niet gevonden.", "danger")
        return redirect(url_for("materiaal"))

    # als serienummer wijzigt, check duplicate
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
def keuringen():
    # placeholder
    return redirect(url_for("materiaal"))


if __name__ == "__main__":
    app.run(debug=True)
