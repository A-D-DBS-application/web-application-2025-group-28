from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# --- Demo data (vervang later door DB) ---
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

@app.route("/")
@app.route("/dashboard")
def dashboard():
    total_items = len(MATERIALS)
    to_inspect = sum(1 for m in MATERIALS if str(m.get("inspection_status","")).lower().startswith("due"))
    return render_template("dashboard.html", total_items=total_items, to_inspect=to_inspect)

# --- Lijst + filters ---
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

# --- POST van de modal ---
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
    MATERIALS.insert(0, new_item)  # bovenaan tonen
    return redirect(url_for("materiaal"))

@app.route("/keuringen")
def keuringen():
    return render_template("keuringen.html")

if __name__ == "__main__":
    app.run(debug=True)
