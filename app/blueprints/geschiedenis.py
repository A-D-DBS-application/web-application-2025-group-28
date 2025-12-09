"""
Geschiedenis blueprint - handles activity history routes
"""
from flask import Blueprint, render_template, request, Response
from models import Activity
from helpers import login_required
from services import ActivityService
from datetime import datetime
import csv
from io import StringIO

geschiedenis_bp = Blueprint('geschiedenis', __name__)


@geschiedenis_bp.route("/geschiedenis")
@login_required
def geschiedenis():
    """Geschiedenis overzicht met categorieën en filters"""
    from datetime import timedelta
    
    # Haal filter parameters op
    filter_type = request.args.get("type", "all")
    filter_user = request.args.get("user", "")
    filter_period = request.args.get("period", "all")
    search_q = request.args.get("q", "").strip().lower()
    
    # Use service layer for activity filtering (ORM-based)
    display_activities, counts = ActivityService.get_activities_filtered(
        filter_type=filter_type,
        filter_user=filter_user,
        filter_period=filter_period,
        search_q=search_q,
        limit=500
    )
    
    # Get unique users using service
    users_list = ActivityService.get_unique_users()
    
    return render_template(
        "geschiedenis.html",
        activities=display_activities,
        all_count=counts["all"],
        materiaal_count=counts["materiaal"],
        gebruik_count=counts["gebruik"],
        keuring_count=counts["keuring"],
        filter_type=filter_type,
        filter_user=filter_user,
        filter_period=filter_period,
        search_q=search_q,
        users_list=users_list,
    )


@geschiedenis_bp.route("/geschiedenis/export")
@login_required
def geschiedenis_export():
    """Export geschiedenis naar CSV"""
    import csv
    from io import StringIO
    from datetime import timedelta
    
    # Haal filter parameters op (zelfde als geschiedenis route)
    filter_type = request.args.get("type", "all")
    filter_user = request.args.get("user", "")
    filter_period = request.args.get("period", "all")
    search_q = request.args.get("q", "").strip().lower()
    
    # Use service layer for activity filtering (ORM-based)
    # For export, we want all matching activities, so use a high limit
    activities, _ = ActivityService.get_activities_filtered(
        filter_type=filter_type,
        filter_user=filter_user,
        filter_period=filter_period,
        search_q=search_q,
        limit=10000  # High limit for export
    )
    
    # Maak CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow(['Datum', 'Tijd', 'Actie', 'Materiaal', 'Serienummer', 'Gebruiker'])
    
    # Data
    for act in activities:
        writer.writerow([
            act.created_at.strftime('%Y-%m-%d') if act.created_at else '',
            act.created_at.strftime('%H:%M:%S') if act.created_at else '',
            act.action or '',
            act.name or '',
            act.serial or '',
            act.user_name or '',
        ])
    
    # Maak response
    output.seek(0)
    filename = f"geschiedenis_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

