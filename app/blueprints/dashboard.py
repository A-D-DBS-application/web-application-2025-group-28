"""
Dashboard blueprint - handles dashboard and root redirect routes
"""
from flask import Blueprint, render_template, redirect, url_for, jsonify
from models import db, Material, Activity, MaterialUsage, Project, Keuringstatus
from helpers import login_required, get_file_url_from_path
from services import MaterialService
from datetime import datetime
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route("/")
@login_required
def root_redirect():
    return redirect(url_for("dashboard.dashboard"))


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    # Update automatisch verlopen keuringen
    updated_count = MaterialService.update_expired_inspections()
    if updated_count > 0:
        db.session.commit()
    
    # Use service layer for business logic
    total_items = MaterialService.get_total_count()
    to_inspect = MaterialService.get_to_inspect_count()
    today = datetime.utcnow().date()

    # recente activiteit uit activiteiten_log tabel
    recent = Activity.query.order_by(Activity.aangemaakt_op.desc()).limit(8).all()

    # Haal geplande keuringen op (volgende_controle in de toekomst)
    geplande_keuringen = (
        Keuringstatus.query
        .filter(Keuringstatus.volgende_controle > today)
        .order_by(Keuringstatus.volgende_controle.asc())
        .limit(10)  # Toon maximaal 10 komende keuringen
        .all()
    )

    # Data voor "Materiaal in gebruik nemen" modal
    all_materials = Material.query.all()
    
    # Bepaal welke materialen in gebruik zijn
    active_material_ids = set()
    all_active_usages = MaterialUsage.query.filter(MaterialUsage.is_active.is_(True)).all()
    for usage in all_active_usages:
        active_material_ids.add(usage.material_id)
    
    projects = (
        Project.query.filter_by(is_deleted=False)
        .order_by(Project.start_date.asc())
        .all()
    )

    return render_template(
        "dashboard.html",
        total_items=total_items,
        to_inspect=to_inspect,
        recent_activity=recent,
        all_materials=all_materials,
        projects=projects,
        today=today,
        geplande_keuringen=geplande_keuringen,
        active_material_ids=active_material_ids,
    )

