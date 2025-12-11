"""
Keuringen blueprint - handles all inspection/keuring-related routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response, g, current_app
from models import db, Material, Keuringstatus, KeuringHistoriek, Project
from helpers import login_required, log_activity_db, save_upload
from services import MaterialService, KeuringService
from datetime import datetime
from dateutil.relativedelta import relativedelta
from sqlalchemy import or_
import csv
from io import StringIO

keuringen_bp = Blueprint('keuringen', __name__)


def find_material_by_serial(serial: str):
    """Find material by serial number"""
    return MaterialService.find_by_serial(serial)


def update_verlopen_keuringen():
    """Wrapper for MaterialService.update_expired_inspections()"""
    return MaterialService.update_expired_inspections()


@keuringen_bp.route("/keuringen")
@login_required
def keuringen():
    """Keuringen overzicht pagina - verbeterd met filters, paginatie en prioriteit"""
    today = datetime.utcnow().date()
    
    # AUTOMATISCH ALGORITME: Update verlopen keuringen
    update_verlopen_keuringen()
    
    # Get priority counts
    priority_counts = KeuringService.get_priority_counts(today)
    
    # Get filter parameters
    search_q = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "").strip()
    werf_filter = (request.args.get("werf") or "").strip()
    type_filter = (request.args.get("type") or "").strip()
    performer_filter = (request.args.get("performer") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    priority_filter = (request.args.get("priority") or "").strip()
    
    page = request.args.get("page", 1, type=int)
    sort_by = request.args.get("sort", "volgende_controle")
    sort_order = request.args.get("order", "asc")
    
    # Get filtered keuringen using service
    inspection_list, pagination, total_items, filter_options = KeuringService.get_filtered_keuringen(
        today=today,
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
        page=page,
        per_page=25
    )
    
    return render_template(
        "keuringen.html",
        te_laat_count=priority_counts["te_laat"],
        vandaag_count=priority_counts["vandaag"],
        binnen_30_dagen_count=priority_counts["binnen_30_dagen"],
        today=today,
        inspection_list=inspection_list,
        pagination=pagination,
        total_items=total_items,
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
        all_projects=filter_options["all_projects"],
        types_list=filter_options["types_list"],
        performers_list=filter_options["performers_list"],
        all_materials=filter_options["all_materials"],
    )


@keuringen_bp.route("/keuringen/new", methods=["POST"])
@login_required
def keuring_toevoegen():
    """Nieuwe keuring aanmaken"""
    f = request.form
    
    serial = (f.get("serial") or "").strip()
    keuring_datum_str = (f.get("keuring_datum") or "").strip()
    uitgevoerd_door = (f.get("uitgevoerd_door") or "").strip()
    opmerking = (f.get("opmerking") or "").strip()
    
    if not serial or not keuring_datum_str or not uitgevoerd_door:
        flash("Serienummer, keuring datum en uitgevoerd door zijn verplicht.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    material = find_material_by_serial(serial)
    if not material:
        flash("Materiaal niet gevonden.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    try:
        keuring_datum = datetime.strptime(keuring_datum_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige datum formaat.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    volgende_keuring = keuring_datum
    
    nieuwe_keuring = Keuringstatus(
        serienummer=serial,
        laatste_controle=None,
        volgende_controle=volgende_keuring,
    )
    if hasattr(Keuringstatus, 'uitgevoerd_door'):
        nieuwe_keuring.uitgevoerd_door = uitgevoerd_door
    if hasattr(Keuringstatus, 'opmerkingen'):
        nieuwe_keuring.opmerkingen = opmerking if opmerking else None
    
    db.session.add(nieuwe_keuring)
    db.session.flush()
    
    material.keuring_id = nieuwe_keuring.id
    material.inspection_status = "keuring gepland"
    
    db.session.commit()
    
    log_activity_db("Keuring toegevoegd", material.name or "", serial)
    flash("Keuring succesvol toegevoegd.", "success")
    return redirect(url_for("keuringen.keuringen"))


@keuringen_bp.route("/keuringen/edit", methods=["POST"])
@login_required
def keuring_bewerken():
    """Bewerk een bestaande keuring"""
    f = request.form
    
    keuring_id_str = (f.get("keuring_id") or "").strip()
    volgende_keuring_str = (f.get("volgende_keuring_datum") or "").strip()
    uitgevoerd_door = (f.get("uitgevoerd_door") or "").strip()
    opmerking = (f.get("opmerking") or "").strip()
    
    if not keuring_id_str or not volgende_keuring_str or not uitgevoerd_door:
        flash("Keuring ID, volgende keuring datum en uitgevoerd door zijn verplicht.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    try:
        keuring_id = int(keuring_id_str)
    except ValueError:
        flash("Ongeldig keuring ID.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    keuring = Keuringstatus.query.filter_by(id=keuring_id).first()
    if not keuring:
        flash("Keuring niet gevonden.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    try:
        volgende_keuring = datetime.strptime(volgende_keuring_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige datum formaat.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    keuring.volgende_controle = volgende_keuring
    if hasattr(keuring, 'uitgevoerd_door'):
        keuring.uitgevoerd_door = uitgevoerd_door
    if hasattr(keuring, 'opmerkingen'):
        keuring.opmerkingen = opmerking if opmerking else None
    
    db.session.commit()
    
    log_activity_db("Keuring bewerkt", keuring.serienummer or "", keuring.serienummer or "")
    flash("Keuring succesvol bijgewerkt.", "success")
    return redirect(url_for("keuringen.keuringen"))


@keuringen_bp.route("/keuringen/resultaat", methods=["POST"])
@login_required
def keuring_resultaat():
    """Voer het resultaat van een keuring in en maak historiek record aan."""
    f = request.form
    
    keuring_id_str = (f.get("keuring_id") or "").strip()
    resultaat = (f.get("resultaat") or "").strip()
    keuring_datum_str = (f.get("keuring_datum") or "").strip()
    volgende_keuring_str = (f.get("volgende_keuring_datum") or "").strip()
    uitgevoerd_door = (f.get("uitgevoerd_door") or "").strip()
    opmerking = (f.get("opmerking") or "").strip()
    
    certificaat_file = request.files.get("certificaat")
    
    if not keuring_id_str or not resultaat or not keuring_datum_str or not uitgevoerd_door:
        flash("Alle velden zijn verplicht.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    try:
        keuring_id = int(keuring_id_str)
    except ValueError:
        flash("Ongeldig keuring ID.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    keuring = Keuringstatus.query.filter_by(id=keuring_id).first()
    if not keuring:
        flash("Keuring niet gevonden.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    material = find_material_by_serial(keuring.serienummer)
    if not material:
        flash("Materiaal niet gevonden.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    try:
        keuring_datum = datetime.strptime(keuring_datum_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Ongeldige datum formaat.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    if volgende_keuring_str:
        try:
            volgende_keuring = datetime.strptime(volgende_keuring_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Ongeldige datum formaat voor volgende keuring. Gebruik standaard 6 maanden.", "warning")
            volgende_keuring = keuring_datum + relativedelta(months=6)
    else:
        volgende_keuring = keuring_datum + relativedelta(months=6)
    
    certificaat_path = None
    if certificaat_file and certificaat_file.filename:
        prefix = f"{keuring.serienummer or material.serial}_cert_{datetime.utcnow().strftime('%Y%m%d')}"
        certificaat_path = save_upload(
            certificaat_file, current_app.config["CERTIFICATE_UPLOAD_FOLDER"], prefix
        )
        
        # Sla certificaat ook op als Document record voor documenten pagina
        from models import Document
        from werkzeug.utils import secure_filename
        
        # Bereken bestandsgrootte
        certificaat_file.seek(0, 2)  # Ga naar einde
        file_size = certificaat_file.tell()
        certificaat_file.seek(0)  # Reset
        
        user_name = g.user.naam if g.user else "Onbekend"
        document = Document(
            document_type="Keuringstatus",
            file_path=certificaat_path,
            file_name=secure_filename(certificaat_file.filename),
            file_size=file_size,
            material_id=material.id,
            material_type_id=None,
            material_type=None,
            uploaded_by=user_name,
            user_id=g.user.gebruiker_id if g.user else None,
            note=f"Certificaat voor keuring {keuring_datum.strftime('%Y-%m-%d')} - {resultaat}",
            aangemaakt_op=datetime.utcnow()
        )
        db.session.add(document)
    
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
    
    keuring.laatste_controle = keuring_datum
    keuring.volgende_controle = volgende_keuring
    if hasattr(keuring, 'uitgevoerd_door'):
        keuring.uitgevoerd_door = uitgevoerd_door
    if hasattr(keuring, 'opmerkingen'):
        keuring.opmerkingen = opmerking if opmerking else None
    
    # Update material.laatste_keuring to the keuring date
    material.laatste_keuring = keuring_datum
    material.inspection_status = resultaat
    
    # Check if inspection is expired based on laatste_keuring + keuring_geldigheid_dagen
    # This MUST override any manually set status (except "afgekeurd" which should remain)
    # Note: Since we just set laatste_keuring to today, it typically won't be expired,
    # but we check for consistency and edge cases (e.g., if validity days is 0 or negative)
    if resultaat != "afgekeurd" and MaterialService.check_inspection_expiry(material):
        material.inspection_status = "keuring verlopen"
    
    db.session.commit()
    
    log_activity_db(f"Keuring uitgevoerd: {resultaat}", material.name or "", material.serial or "")
    flash(f"Keuring resultaat succesvol opgeslagen: {resultaat}.", "success")
    return redirect(url_for("keuringen.keuringen"))


@keuringen_bp.route("/keuringen/delete", methods=["POST"])
@login_required
def keuring_verwijderen():
    """Verwijder een geplande keuring"""
    f = request.form
    
    keuring_id_str = (f.get("keuring_id") or "").strip()
    
    if not keuring_id_str:
        flash("Keuring ID is verplicht.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    try:
        keuring_id = int(keuring_id_str)
    except ValueError:
        flash("Ongeldig keuring ID.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    keuring = Keuringstatus.query.filter_by(id=keuring_id).first()
    if not keuring:
        flash("Keuring niet gevonden.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    serial = keuring.serienummer or ""
    material = find_material_by_serial(serial)
    
    if material and material.keuring_id == keuring_id:
        material.keuring_id = None
        if material.inspection_status == "keuring gepland":
            material.inspection_status = "keuring verlopen"
    
    db.session.delete(keuring)
    db.session.commit()
    
    log_activity_db("Keuring verwijderd", serial, serial)
    flash("Keuring succesvol verwijderd.", "success")
    return redirect(url_for("keuringen.keuringen"))


@keuringen_bp.route("/keuringen/dupliceer/<int:historiek_id>")
@login_required
def keuring_dupliceer(historiek_id):
    """Dupliceer een bestaande keuring"""
    historiek = KeuringHistoriek.query.filter_by(id=historiek_id).first()
    
    if not historiek:
        flash("Keuring niet gevonden.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    material = Material.query.filter_by(id=historiek.material_id).first() if historiek.material_id else None
    if not material:
        flash("Materiaal niet gevonden.", "danger")
        return redirect(url_for("keuringen.keuringen"))
    
    volgende_keuring_datum = historiek.volgende_keuring_datum
    if not volgende_keuring_datum:
        volgende_keuring_datum = datetime.utcnow().date() + relativedelta(months=6)
    
    nieuwe_keuring = Keuringstatus(
        serienummer=historiek.serienummer,
        laatste_controle=None,
        volgende_controle=volgende_keuring_datum,
        uitgevoerd_door=historiek.uitgevoerd_door,
        opmerkingen=f"Gedupliceerd van keuring {historiek.id}",
    )
    
    db.session.add(nieuwe_keuring)
    db.session.flush()
    
    material.keuring_id = nieuwe_keuring.id
    material.inspection_status = "keuring gepland"
    
    db.session.commit()
    
    log_activity_db("Keuring gedupliceerd", material.name or "", material.serial or "")
    flash("Keuring succesvol gedupliceerd.", "success")
    return redirect(url_for("keuringen.keuringen"))


@keuringen_bp.route("/keuringen/export")
@login_required
def keuringen_export():
    """Export keuringen naar CSV"""
    today = datetime.utcnow().date()
    
    search_q = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "").strip()
    werf_filter = (request.args.get("werf") or "").strip()
    type_filter = (request.args.get("type") or "").strip()
    performer_filter = (request.args.get("performer") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    priority_filter = (request.args.get("priority") or "").strip()
    
    # Get filtered keuringen (no pagination for export)
    inspection_list, _, total_items, _ = KeuringService.get_filtered_keuringen(
        today=today,
        search_q=search_q,
        status_filter=status_filter,
        werf_filter=werf_filter,
        type_filter=type_filter,
        performer_filter=performer_filter,
        date_from=date_from,
        date_to=date_to,
        priority_filter=priority_filter,
        sort_by="volgende_controle",
        sort_order="asc",
        page=1,
        per_page=10000  # High limit for export
    )
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow([
        'Materieel', 'Serienummer', 'Werf/Locatie', 'Laatste Keuring', 
        'Volgende Keuring', 'Resultaat', 'Uitgevoerd door', 'Opmerkingen'
    ])
    
    for item in inspection_list:
        keuring = item['keuring']
        material = item['material']
        
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
    
    output.seek(0)
    filename = f"keuringen_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@keuringen_bp.route("/api/keuring/<int:historiek_id>")
@login_required
def api_keuring_details(historiek_id):
    """API endpoint om keuring details op te halen"""
    from helpers import get_file_url_from_path
    
    historiek = KeuringHistoriek.query.filter_by(id=historiek_id).first()
    
    if not historiek:
        return jsonify({"error": "Keuring niet gevonden"}), 404
    
    material = Material.query.filter_by(id=historiek.material_id).first()
    
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
        "certificaat_url": get_file_url_from_path(historiek.certificaat_path) if historiek.certificaat_path else None,
        "created_at": historiek.created_at.strftime("%Y-%m-%d %H:%M") if historiek.created_at else "-",
    })


@keuringen_bp.route("/api/keuring/status/<int:keuring_id>")
@login_required
def api_keuring_status(keuring_id):
    """API endpoint om keuring status details op te halen voor bewerken"""
    keuring = Keuringstatus.query.filter_by(id=keuring_id).first()
    
    if not keuring:
        return jsonify({"error": "Keuring niet gevonden"}), 404
    
    return jsonify({
        "id": keuring.id,
        "uitgevoerd_door": keuring.uitgevoerd_door or "",
        "opmerkingen": keuring.opmerkingen or "",
        "volgende_controle": keuring.volgende_controle.strftime("%Y-%m-%d") if keuring.volgende_controle else "",
    })


@keuringen_bp.route("/api/keuring/historiek/<int:material_id>")
@login_required
def api_keuring_historiek(material_id):
    """API endpoint om alle keuring historiek voor een materiaal op te halen"""
    from helpers import get_file_url_from_path
    from datetime import date
    
    today = date.today()
    material = Material.query.filter_by(id=material_id).first()
    
    if not material:
        return jsonify({"error": "Materiaal niet gevonden"}), 404
    
    keuring_status = None
    volgende_keuring_datum = None
    dagen_verschil = None
    keuring_id = None
    if material.keuring_id:
        keuring = Keuringstatus.query.filter_by(id=material.keuring_id).first()
        if keuring:
            keuring_id = keuring.id
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
            "certificaat_url": get_file_url_from_path(hist.certificaat_path) if hist.certificaat_path else None,
        })
    
    return jsonify({
        "material_id": material_id,
        "material_name": material.name or "Onbekend",
        "serial": material.serial or "-",
        "inspection_status": material.inspection_status or "Onbekend",
        "keuring_id": keuring_id,
        "volgende_keuring_datum": volgende_keuring_datum,
        "dagen_verschil": dagen_verschil,
        "historiek": historiek_list
    })






