"""
Keuringen blueprint - handles all inspection/keuring-related routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response, g, current_app
from models import db, Material, Keuringstatus, KeuringHistoriek, Project, Document
from helpers import login_required, log_activity_db, save_upload, save_upload_to_supabase
from services import MaterialService, KeuringService
from datetime import datetime
from dateutil.relativedelta import relativedelta
from sqlalchemy import or_, and_
from werkzeug.utils import secure_filename
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
    updated_count = update_verlopen_keuringen()
    if updated_count > 0:
        db.session.commit()
    
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
    sort_by = request.args.get("sort", "")  # Default: empty (will sort by risk)
    sort_order = request.args.get("order", "desc")  # Default: desc for risk sorting
    
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
        # Upload naar Supabase Storage bucket "Keuringsstatus documenten"
        bucket = "Keuringsstatus documenten"
        prefix = f"{keuring.serienummer or material.serial}_keuringstatus_{datetime.utcnow().strftime('%Y%m%d')}"
        
        certificaat_file.seek(0)  # Reset file pointer
        file_path = save_upload_to_supabase(
            certificaat_file,
            bucket_name=bucket,
            folder="",
            prefix=prefix
        )
        
        if file_path:
            certificaat_path = file_path
            
            # Bereken bestandsgrootte
            certificaat_file.seek(0, 2)  # Ga naar einde
            file_size = certificaat_file.tell()
            certificaat_file.seek(0)  # Reset
            
            filename = secure_filename(certificaat_file.filename)
            user_name = g.user.naam if g.user else "Onbekend"
            
            # Maak Document record aan voor keuringscertificaat
            document = Document(
                document_type="Keuringstatus",
                file_path=file_path,
                file_name=filename,
                file_size=file_size,
                material_id=material.id,
                material_type_id=None,
                material_type=None,
                uploaded_by=user_name,
                user_id=g.user.gebruiker_id if g.user else None,
                note=f"Keuring uitgevoerd op {keuring_datum.strftime('%Y-%m-%d')} - {resultaat}",
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
    
    # Filter op is_deleted om verwijderde materialen uit te sluiten
    material = Material.query.filter(
        Material.id == historiek.material_id,
        or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
    ).first() if historiek.material_id else None
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
        
        # Use current_location from active usage (item['current_location']) if available
        # Otherwise show "-" (not in use)
        location_display = item.get('current_location') or '-'
        
        writer.writerow([
            material.name or 'Onbekend',
            material.serial or '',
            location_display,
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
    
    # Filter op is_deleted om verwijderde materialen uit te sluiten
    material = Material.query.filter(
        Material.id == historiek.material_id,
        or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
    ).first()
    
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


@keuringen_bp.route("/api/keuring/historiek/<int:material_id>")
@login_required
def api_keuring_historiek(material_id):
    """API endpoint om alle keuring historiek voor een materiaal op te halen"""
    from helpers import get_file_url_from_path
    from datetime import date
    
    today = date.today()
    # Filter op is_deleted om verwijderde materialen uit te sluiten
    material = Material.query.filter(
        Material.id == material_id,
        or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
    ).first()
    
    if not material:
        return jsonify({"error": "Materiaal niet gevonden"}), 404
    
    keuring_status = None
    volgende_keuring_datum = None
    dagen_verschil = None
    if material.keuring_id:
        keuring = Keuringstatus.query.filter_by(id=material.keuring_id).first()
        if keuring:
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
        "volgende_keuring_datum": volgende_keuring_datum,
        "dagen_verschil": dagen_verschil,
        "historiek": historiek_list
    })


@keuringen_bp.route("/api/keuring/<int:keuring_historiek_id>/delete", methods=["POST"])
@login_required
def api_keuring_delete(keuring_historiek_id):
    """API endpoint to delete a keuring_historiek record and update keuring_status"""
    try:
        from datetime import date
        
        # Get the keuring_historiek record
        keuring_historiek = KeuringHistoriek.query.filter_by(id=keuring_historiek_id).first()
        if not keuring_historiek:
            return jsonify({"error": "Keuring niet gevonden"}), 404
        
        # Get material_id from request body or from the keuring record
        data = request.get_json() or {}
        material_id = data.get("material_id") or keuring_historiek.material_id
        
        if not material_id:
            return jsonify({"error": "Materiaal ID niet gevonden"}), 400
        
        # Get the material to find serial number
        material = Material.query.filter_by(id=material_id).first()
        if not material:
            return jsonify({"error": "Materiaal niet gevonden"}), 404
        
        serial = material.serial
        if not serial:
            return jsonify({"error": "Serienummer niet gevonden"}), 400
        
        # Delete the keuring_historiek record
        db.session.delete(keuring_historiek)
        db.session.flush()
        
        # Find the newest remaining keuring_historiek record for this material
        remaining_keuring = KeuringHistoriek.query.filter_by(
            material_id=material_id
        ).order_by(
            KeuringHistoriek.keuring_datum.desc()
        ).first()
        
        # Get or create keuring_status record
        keuring_status = None
        if material.keuring_id:
            keuring_status = Keuringstatus.query.filter_by(id=material.keuring_id).first()
        
        if not keuring_status:
            # Try to find by serial number
            keuring_status = Keuringstatus.query.filter_by(serienummer=serial).first()
        
        if remaining_keuring:
            # Update keuring_status with the newest remaining record
            if not keuring_status:
                # Create new keuring_status if it doesn't exist
                keuring_status = Keuringstatus(serienummer=serial)
                db.session.add(keuring_status)
                db.session.flush()
                material.keuring_id = keuring_status.id
            
            # Update with data from the newest remaining keuring
            keuring_status.laatste_controle = remaining_keuring.keuring_datum
            keuring_status.volgende_controle = remaining_keuring.volgende_keuring_datum
            
            # Update material inspection status based on resultaat
            if remaining_keuring.resultaat:
                material.inspection_status = remaining_keuring.resultaat
                material.laatste_keuring = remaining_keuring.keuring_datum
        else:
            # No remaining keuring records - clear keuring_status
            if keuring_status:
                keuring_status.laatste_controle = None
                keuring_status.volgende_controle = None
            
            # Reset material inspection status
            material.inspection_status = None
            material.laatste_keuring = None
            # Don't delete keuring_status record, just null the fields for stability
        
        db.session.commit()
        
        # Log activity
        log_activity_db("Keuring verwijderd", material.name or "", serial)
        
        return jsonify({
            "success": True,
            "message": "Keuring succesvol verwijderd"
        }), 200
        
    except Exception as e:
        db.session.rollback()
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in api_keuring_delete: {e}")
        print(f"Traceback: {error_details}")
        return jsonify({
            "error": f"Fout bij verwijderen: {str(e)}"
        }), 500


@keuringen_bp.route("/api/keuring/planning/delete", methods=["POST"])
@login_required
def api_keuring_planning_delete():
    """API endpoint to delete a planned keuring (clear planning in keuring_status)"""
    try:
        data = request.get_json() or {}
        serienummer = data.get("serienummer")
        
        if not serienummer:
            return jsonify({"error": "Serienummer is verplicht"}), 400
        
        # Find keuring_status by serienummer
        keuring_status = Keuringstatus.query.filter_by(serienummer=serienummer).first()
        
        if not keuring_status:
            return jsonify({"error": "Geplande keuring niet gevonden"}), 404
        
        # Check if there's a volgende_controle (planned keuring)
        if not keuring_status.volgende_controle:
            return jsonify({"error": "Geen geplande keuring om te verwijderen"}), 400
        
        # Clear the planning (but keep the record for stability)
        keuring_status.volgende_controle = None
        
        # If there's no laatste_controle either, we might want to remove the keuring_id link
        # But let's keep it simple and just clear volgende_controle
        
        # Find the material and update its status (exclude deleted materials)
        material = Material.query.filter(
            Material.serial == serienummer,
            or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
        ).first()
        if material:
            # If there's no historiek, clear the inspection_status
            historiek_count = KeuringHistoriek.query.filter_by(material_id=material.id).count()
            if historiek_count == 0:
                material.inspection_status = None
            # Don't change laatste_keuring as it might be from a previous keuring
        
        db.session.commit()
        
        # Log activity
        log_activity_db("Geplande keuring verwijderd", material.name if material else "", serienummer)
        
        return jsonify({
            "success": True,
            "message": "Geplande keuring succesvol verwijderd"
        }), 200
        
    except Exception as e:
        db.session.rollback()
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in api_keuring_planning_delete: {e}")
        print(f"Traceback: {error_details}")
        return jsonify({
            "error": f"Fout bij verwijderen: {str(e)}"
        }), 500






