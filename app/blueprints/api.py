"""
API blueprint - handles API endpoints
"""
from flask import Blueprint, request, jsonify, g
from models import db, Material, MaterialUsage, Keuringstatus
from helpers import login_required, get_file_url_from_path
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route("/search", methods=["GET"])
@login_required
def api_search():
    """
    API endpoint for searching materials - returns JSON.
    Optimized with eager loading and subqueries to avoid N+1 query problems.
    """
    try:
        q = (request.args.get("q") or "").strip().lower()
        
        if not q:
            return jsonify({"items": []}), 200
        
        like = f"%{q}%"
        
        # Optimized query with eager loading for keuring relationship
        # This loads keuring data in a single query instead of N queries
        items = (
            Material.query
            .options(joinedload(Material.keuring))  # Eager load keuring relationship
            .filter(or_(Material.name.ilike(like), Material.serial.ilike(like)))
            .limit(10)
            .all()
        )
        
        if not items:
            return jsonify({"items": []}), 200
        
        # Get all material IDs for batch querying
        material_ids = [item.id for item in items]
        
        # Single query to get active usage counts for all materials at once
        # This avoids N+1 queries by using a subquery/aggregation
        active_usage_counts = (
            db.session.query(
                MaterialUsage.material_id,
                func.count(MaterialUsage.id).label('count')
            )
            .filter(
                MaterialUsage.material_id.in_(material_ids),
                MaterialUsage.is_active.is_(True)
            )
            .group_by(MaterialUsage.material_id)
            .all()
        )
        
        # Convert to dictionary for O(1) lookup
        usage_count_map = {row[0]: row[1] for row in active_usage_counts}
        
        # Also query keuring by serienummer for materials that don't have keuring_id
        # This handles the fallback case more efficiently
        serials = [item.serial for item in items if item.serial]
        keuring_by_serial = {
            k.serienummer: k 
            for k in Keuringstatus.query.filter(
                Keuringstatus.serienummer.in_(serials)
            ).all()
            if k.serienummer
        }
        
        results = []
        for item in items:
            try:
                # Get active usage count from pre-loaded map
                active_usages_count = usage_count_map.get(item.id, 0)
                
                # Determine actual status: if has active usages, status is "in gebruik"
                actual_status = "in gebruik" if active_usages_count > 0 else (item.status or "")
                
                # Get keuring info - first try eager-loaded relationship, then fallback
                keuring_info = None
                if item.keuring:
                    keuring_info = item.keuring
                elif item.serial and item.serial in keuring_by_serial:
                    keuring_info = keuring_by_serial[item.serial]
                
                # Safe date formatting for keuring dates
                keuring_gepland = None
                laatste_keuring = None
                if keuring_info:
                    if keuring_info.volgende_controle:
                        try:
                            keuring_gepland = keuring_info.volgende_controle.strftime("%Y-%m-%d")
                        except (AttributeError, ValueError):
                            keuring_gepland = None
                    if keuring_info.laatste_controle:
                        try:
                            laatste_keuring = keuring_info.laatste_controle.strftime("%Y-%m-%d")
                        except (AttributeError, ValueError):
                            laatste_keuring = None
                
                # Build URLs for documentation and safety sheets using storage helper
                documentation_url = get_file_url_from_path(item.documentation_path) if item.documentation_path else ""
                safety_sheet_url = get_file_url_from_path(item.safety_sheet_path) if item.safety_sheet_path else ""
                
                results.append(
                    {
                    "serial": item.serial or "",
                    "name": item.name or "",
                    "type": item.type or "",
                    "status": actual_status,
                    "is_in_use": active_usages_count > 0,
                    "assigned_to": item.assigned_to or "",
                    "site": item.site or "",
                    "purchase_date": item.purchase_date.strftime("%Y-%m-%d")
                        if item.purchase_date
                        else "",
                    "note": item.note or "",
                    "nummer_op_materieel": item.nummer_op_materieel or "",
                    "documentation_path": item.documentation_path or "",
                    "documentation_url": documentation_url,
                    "safety_sheet_path": item.safety_sheet_path or "",
                    "safety_sheet_url": safety_sheet_url,
                    "inspection_status": item.inspection_status or "",
                    "keuring_gepland": keuring_gepland,
                    "laatste_keuring": laatste_keuring,
                    }
                )
            except Exception as e:
                # Log error for this item but continue with other items
                print(f"Error processing material {item.serial if item else 'unknown'}: {e}")
                continue
        
        return jsonify({"items": results}), 200
    except Exception as e:
        # Log the error and return a proper error response
        print(f"Error in api_search: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "items": []}), 500

