"""
Service layer for business logic - separates business rules from route handlers.
Routes should call these functions instead of containing business logic directly.
"""
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from models import (
    db, Material, MaterialUsage, Project, Keuringstatus, 
    KeuringHistoriek, MaterialType, Activity
)
from sqlalchemy import or_, func, and_, case
from constants import (
    DEFAULT_INSPECTION_STATUS, VALID_INSPECTION_STATUSES,
    VALID_USAGE_STATUSES
)


class MaterialService:
    """Service for material-related business logic"""
    
    @staticmethod
    def find_by_serial(serial: str) -> Material | None:
        """Find material by serial number (excludes deleted materials)"""
        if not serial:
            return None
        # SQLAlchemy mapt automatisch de Python attribuut 'serial' naar de database kolom 'serienummer'
        # Gebruik filter() met == voor betere compatibiliteit
        return Material.query.filter(
            Material.serial == serial,
            or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
        ).first()
    
    @staticmethod
    def find_by_name_or_number(name: str, nummer: str | None) -> Material | None:
        """Find material by nummer_op_materieel first, then by name (excludes deleted materials)"""
        item = None
        if nummer:
            item = Material.query.filter(
                Material.nummer_op_materieel == nummer,
                or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
            ).first()
        if not item and name:
            item = Material.query.filter(
                Material.name == name,
                or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
            ).first()
        return item
    
    @staticmethod
    def get_total_count() -> int:
        """Get total count of materials"""
        return Material.query.count()
    
    @staticmethod
    def get_in_use_count() -> int:
        """Get count of materials currently in use"""
        return (
            db.session.query(func.count(MaterialUsage.id))
            .filter(MaterialUsage.is_active.is_(True))
            .scalar()
        ) or 0
    
    @staticmethod
    def get_to_inspect_count() -> int:
        """Get count of materials requiring inspection"""
        keuring_verlopen = Material.query.filter_by(
            inspection_status="keuring verlopen"
        ).count()
        keuring_gepland = Material.query.filter_by(
            inspection_status="keuring gepland"
        ).count()
        return keuring_verlopen + keuring_gepland
    
    @staticmethod
    def check_inspection_expiry(material: Material) -> bool:
        """
        Check if a material's inspection is expired based on laatste_keuring + keuring_geldigheid_dagen.
        Only uses laatste_keuring (no fallback to purchase_date).
        Returns True if expired, False otherwise.
        """
        # Must have laatste_keuring (no fallback to purchase_date)
        if not material.laatste_keuring:
            return False
        
        # Must have material_type with validity days
        if not material.material_type_id or not material.material_type:
            return False
        
        validity_days = material.material_type.inspection_validity_days
        if not validity_days or validity_days <= 0:
            return False
        
        # Calculate expiry date: verloopdatum = laatste_keuring + keuring_geldigheid_dagen
        today = datetime.utcnow().date()
        expiry_date = material.laatste_keuring + timedelta(days=validity_days)
        
        # Check if expired: today > verloopdatum
        return today > expiry_date
    
    @staticmethod
    def update_expired_inspections() -> int:
        """
        Automatically update materials with expired inspections.
        For each material with laatste_keuring and material_type:
        - Calculate verloopdatum = laatste_keuring + materiaal_type.keuring_geldigheid_dagen
        - If today > verloopdatum, set keuring_status = "keuring verlopen"
        This status overrides any manually set status (except if already "keuring verlopen").
        Optimized to avoid N+1 queries.
        Returns count of updated materials.
        """
        today = datetime.utcnow().date()
        updated_count = 0
        
        # PART 1: Get keuringen with expired dates (existing logic)
        keuringen_met_verlopen_datum = Keuringstatus.query.filter(
            Keuringstatus.volgende_controle.isnot(None),
            Keuringstatus.volgende_controle < today,
            Keuringstatus.laatste_controle.is_(None)
        ).all()
        
        if keuringen_met_verlopen_datum:
            # Collect all serial numbers for batch lookup
            serials = [k.serienummer for k in keuringen_met_verlopen_datum if k.serienummer]
            
            if serials:
                # Single query to get all materials by serial numbers
                # Only update if status is NOT already "keuring verlopen"
                materials = Material.query.filter(
                    Material.serial.in_(serials),
                    Material.inspection_status != "keuring verlopen"
                ).all()
                
                # Create a map of serial -> material for O(1) lookup
                material_map = {m.serial: m for m in materials}
                
                # Update materials that need updating
                for keuring in keuringen_met_verlopen_datum:
                    if not keuring.serienummer:
                        continue
                    
                    material = material_map.get(keuring.serienummer)
                    if material:
                        material.inspection_status = "keuring verlopen"
                        updated_count += 1
        
        # PART 2: Check materials with laatste_keuring + keuring_geldigheid_dagen
        # Get all materials with laatste_keuring (NOT purchase_date) and material_type_id
        # Only check materials that are NOT already "keuring verlopen"
        materials_to_check = (
            Material.query
            .filter(
                Material.laatste_keuring.isnot(None),  # Only use laatste_keuring, no purchase_date fallback
                Material.material_type_id.isnot(None),
                Material.inspection_status != "keuring verlopen",  # Only update if not already expired
                or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
            )
            .all()
        )
        
        # Eager load material_type relationships to avoid N+1 queries
        material_type_ids = {m.material_type_id for m in materials_to_check if m.material_type_id}
        if material_type_ids:
            # Pre-load all material types with validity days > 0
            material_types = MaterialType.query.filter(
                MaterialType.id.in_(material_type_ids),
                MaterialType.inspection_validity_days.isnot(None),
                MaterialType.inspection_validity_days > 0
            ).all()
            material_type_map = {mt.id: mt for mt in material_types}
            
            # Check each material
            for material in materials_to_check:
                # Skip if material_type_id is missing
                if not material.material_type_id:
                    continue
                
                # Skip if material_type is missing or has no validity days
                material_type = material_type_map.get(material.material_type_id)
                if not material_type or not material_type.inspection_validity_days or material_type.inspection_validity_days <= 0:
                    continue
                
                # Skip if laatste_keuring is NULL (shouldn't happen due to filter, but double-check)
                if not material.laatste_keuring:
                    continue
                
                # Calculate verloopdatum = laatste_keuring + keuring_geldigheid_dagen
                expiry_date = material.laatste_keuring + timedelta(days=material_type.inspection_validity_days)
                
                # If today > verloopdatum, set keuring_status = "keuring verlopen"
                if today > expiry_date:
                    # Only update if current status is NOT already "keuring verlopen" (idempotent check)
                    if material.inspection_status != "keuring verlopen":
                        material.inspection_status = "keuring verlopen"
                        updated_count += 1
        
        if updated_count > 0:
            db.session.commit()
        
        return updated_count
    
    @staticmethod
    def is_material_in_use(material_id: int) -> bool:
        """Check if material is currently in use"""
        return MaterialUsage.query.filter_by(
            material_id=material_id,
            is_active=True
        ).count() > 0
    
    @staticmethod
    def get_active_usage(material_id: int) -> MaterialUsage | None:
        """Get active usage record for material"""
        return MaterialUsage.query.filter_by(
            material_id=material_id,
            is_active=True
        ).first()
    
    @staticmethod
    def update_material_status(material: Material) -> None:
        """
        Update material status based on active usages.
        Status = "in gebruik" if has active usage, else "niet in gebruik"
        """
        active_count = MaterialUsage.query.filter_by(
            material_id=material.id,
            is_active=True
        ).count()
        
        if active_count > 0:
            material.status = "in gebruik"
        else:
            material.status = "niet in gebruik"


class MaterialUsageService:
    """Service for material usage-related business logic"""
    
    @staticmethod
    def start_usage(
        material: Material,
        user_id: int,
        used_by: str,
        project_id: int | None = None,
        site: str | None = None
    ) -> MaterialUsage:
        """
        Start a new material usage session.
        Returns the created MaterialUsage object.
        """
        # Check if already in use
        existing = MaterialUsageService.get_active_usage(material.id)
        if existing:
            raise ValueError("Material is already in use")
        
        # Create usage record
        usage = MaterialUsage(
            material_id=material.id,
            user_id=user_id,
            site=site or (material.site if material.site else None),
            start_time=datetime.utcnow(),
            is_active=True,
            used_by=used_by,
            project_id=project_id
        )
        
        db.session.add(usage)
        
        # Update material
        material.assigned_to = used_by
        if project_id:
            material.werf_id = project_id
        if site:
            material.site = site
        material.status = "in gebruik"
        
        db.session.commit()
        return usage
    
    @staticmethod
    def stop_usage(usage_id: int, user_name: str, is_admin: bool = False) -> MaterialUsage:
        """
        Stop an active material usage session.
        Returns the updated MaterialUsage object.
        """
        usage = MaterialUsage.query.filter_by(id=usage_id).first()
        if not usage or not usage.is_active:
            raise ValueError("Usage record not found or not active")
        
        # Check permissions
        usage_name = (usage.used_by or "").strip()
        is_own_usage = usage_name.lower() == user_name.lower()
        
        if not is_own_usage and not is_admin:
            raise PermissionError("Can only stop own material usage")
        
        # Update usage
        usage.is_active = False
        usage.end_time = datetime.utcnow()
        
        # Update material if needed
        material = Material.query.filter_by(id=usage.material_id).first()
        if material:
            if material.assigned_to == usage.used_by:
                material.assigned_to = None
                material.site = None
            
            # Check if other active usages exist
            other_active = MaterialUsage.query.filter_by(
                material_id=material.id,
                is_active=True
            ).count()
            
            if other_active == 0:
                material.status = "niet in gebruik"
        
        db.session.commit()
        return usage
    
    @staticmethod
    def get_active_usage(material_id: int) -> MaterialUsage | None:
        """Get active usage for material"""
        return MaterialUsage.query.filter_by(
            material_id=material_id,
            is_active=True
        ).first()
    
    @staticmethod
    def assign_to_project(usage_id: int, project_id: int) -> MaterialUsage:
        """
        Assign an active usage to a project.
        Returns the updated MaterialUsage object.
        """
        usage = MaterialUsage.query.filter_by(id=usage_id, is_active=True).first()
        if not usage:
            raise ValueError("Active usage not found")
        
        project = Project.query.filter_by(id=project_id, is_deleted=False).first()
        if not project:
            raise ValueError("Project not found")
        
        material = Material.query.filter_by(id=usage.material_id).first()
        if not material:
            raise ValueError("Material not found")
        
        # Update usage and material
        usage.project_id = project_id  # project_id is alias voor werf_id via property
        usage.site = project.name
        material.werf_id = project_id
        material.site = project.name
        
        db.session.commit()
        return usage


class ActivityService:
    """Service for activity-related business logic and filtering"""
    
    @staticmethod
    def get_activities_filtered(
        filter_type: str = "all",
        filter_user: str = "",
        filter_period: str = "all",
        search_q: str = "",
        limit: int | None = 500
    ) -> tuple[list[Activity], dict]:
        """
        Get filtered activities using ORM queries.
        Returns (activities_list, counts_dict)
        """
        today = datetime.utcnow().date()
        query = Activity.query
        
        # Filter by period using ORM (gebruik aangemaakt_op in plaats van created_at)
        if filter_period == "today":
            start_date = datetime.combine(today, datetime.min.time())
            query = query.filter(Activity.aangemaakt_op >= start_date)
        elif filter_period == "week":
            start_date = datetime.combine(today - timedelta(days=7), datetime.min.time())
            query = query.filter(Activity.aangemaakt_op >= start_date)
        elif filter_period == "month":
            start_date = datetime.combine(today - timedelta(days=30), datetime.min.time())
            query = query.filter(Activity.aangemaakt_op >= start_date)
        
        # Filter by user using ORM (gebruik gebruiker_naam in plaats van user_name)
        if filter_user:
            query = query.filter(Activity.user_name.ilike(f"%{filter_user}%"))  # user_name is alias voor gebruiker_naam
        
        # Filter by search query using ORM
        if search_q:
            query = query.filter(
                or_(
                    Activity.name.ilike(f"%{search_q}%"),  # name is alias voor naam
                    Activity.serial.ilike(f"%{search_q}%"),  # serial is alias voor serienummer
                    Activity.action.ilike(f"%{search_q}%"),  # action is alias voor actie
                )
            )
        
        # Count by category using ORM subqueries (more efficient than Python loops)
        materiaal_query = query.filter(
            or_(
                Activity.action.ilike("%toegevoegd%"),
                Activity.action.ilike("%bewerkt%"),
                Activity.action.ilike("%verwijderd%"),
            )
        )
        gebruik_query = query.filter(
            or_(
                Activity.action.ilike("%in gebruik%"),
                Activity.action.ilike("%verplaatst%"),
                Activity.action.ilike("%gekoppeld%"),
            )
        )
        keuring_query = query.filter(Activity.action.ilike("%keuring%"))
        
        # Get counts
        materiaal_count = materiaal_query.count()
        gebruik_count = gebruik_query.count()
        keuring_count = keuring_query.count()
        
        # Filter by type if specified, then apply limit
        if filter_type == "materiaal":
            display_query = materiaal_query.order_by(Activity.aangemaakt_op.desc())
        elif filter_type == "gebruik":
            display_query = gebruik_query.order_by(Activity.aangemaakt_op.desc())
        elif filter_type == "keuring":
            display_query = keuring_query.order_by(Activity.aangemaakt_op.desc())
        else:
            display_query = query.order_by(Activity.aangemaakt_op.desc())
        
        # Apply limit if specified
        if limit:
            display_activities = display_query.limit(limit).all()
            all_activities = query.order_by(Activity.aangemaakt_op.desc()).limit(limit).all()
        else:
            display_activities = display_query.all()
            all_activities = query.order_by(Activity.aangemaakt_op.desc()).all()
        
        counts = {
            "all": len(all_activities),
            "materiaal": materiaal_count,
            "gebruik": gebruik_count,
            "keuring": keuring_count,
        }
        
        return display_activities, counts
    
    @staticmethod
    def get_unique_users() -> list[str]:
        """Get unique user names using ORM"""
        unique_users = db.session.query(Activity.user_name).filter(  # user_name is alias voor gebruiker_naam
            Activity.user_name.isnot(None),
            Activity.user_name != ""
        ).distinct().order_by(Activity.user_name).all()
        return [u[0] for u in unique_users if u[0]]


class MaterialUsageRepository:
    """Repository for material usage queries - handles ORM-based filtering"""
    
    @staticmethod
    def get_active_usages_grouped(user_name: str | None = None) -> tuple[list[dict], list[dict], list[dict]]:
        """
        Get active usages grouped by user using ORM queries.
        Returns (my_usages, other_usages, usages_without_project)
        """
        # Base query with joins - exclude deleted materials
        query = (
            db.session.query(MaterialUsage, Material)
            .join(Material, MaterialUsage.material_id == Material.id)
            .filter(MaterialUsage.is_active.is_(True))
            .filter(or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None)))
            .order_by(MaterialUsage.start_time.desc())
        )
        
        # Get all active usages
        active_usages = query.all()
        
        # Build result dictionaries
        my_usages = []
        other_usages = []
        usages_without_project = []
        
        user_name_lower = (user_name or "").lower()
        
        for usage, material in active_usages:
            row = {
                "id": usage.id,
                "material_id": material.id,
                "name": material.name,
                "serial": material.serial,
                "site": usage.site or "",
                "used_by": usage.used_by or "",
                "start_time": usage.start_time,
                "project_id": usage.project_id,
                "material": material,
                "project": usage.project,
            }
            
            # Check if usage has no project
            if usage.project_id is None:
                usages_without_project.append(row)
            
            # Check if the "used_by" name matches the logged-in user's name
            usage_name = (usage.used_by or "").strip().lower()
            if user_name_lower and usage_name == user_name_lower:
                my_usages.append(row)
            else:
                other_usages.append(row)
        
        return my_usages, other_usages, usages_without_project
    
    @staticmethod
    def get_active_material_ids() -> set[int]:
        """Get set of material IDs that are currently in use using ORM"""
        active_ids = (
            db.session.query(MaterialUsage.material_id)
            .filter(MaterialUsage.is_active.is_(True))
            .distinct()
            .all()
        )
        return {row[0] for row in active_ids}


class KeuringService:
    """Service for keuring-related business logic and filtering"""
    
    @staticmethod
    def get_priority_counts(today: datetime.date) -> dict:
        """Get priority counts for keuringen cards"""
        te_laat_count = db.session.query(Keuringstatus, Material).join(
            Material, Material.keuring_id == Keuringstatus.id
        ).filter(
            Keuringstatus.volgende_controle.isnot(None),
            Keuringstatus.volgende_controle < today,
            Keuringstatus.laatste_controle.is_(None)
        ).count()
        
        vandaag_count = db.session.query(Keuringstatus, Material).join(
            Material, Material.keuring_id == Keuringstatus.id
        ).filter(
            Keuringstatus.volgende_controle == today,
            Keuringstatus.laatste_controle.is_(None)
        ).count()
        
        binnen_30_dagen_count = db.session.query(Keuringstatus, Material).join(
            Material, Material.keuring_id == Keuringstatus.id
        ).filter(
            Keuringstatus.volgende_controle.isnot(None),
            Keuringstatus.volgende_controle > today,
            Keuringstatus.volgende_controle <= (today + relativedelta(days=30)),
            Keuringstatus.laatste_controle.is_(None)
        ).count()
        
        return {
            "te_laat": te_laat_count,
            "vandaag": vandaag_count,
            "binnen_30_dagen": binnen_30_dagen_count
        }
    
    @staticmethod
    def get_filtered_keuringen(
        today: datetime.date,
        search_q: str = "",
        status_filter: str = "",
        werf_filter: str = "",
        type_filter: str = "",
        performer_filter: str = "",
        date_from: str = "",
        date_to: str = "",
        priority_filter: str = "",
        sort_by: str = "volgende_controle",
        sort_order: str = "asc",
        page: int = 1,
        per_page: int = 25
    ) -> tuple:
        """
        Get filtered and paginated keuringen.
        Returns (inspection_list, pagination, total_items, filter_options)
        """
        from dateutil.relativedelta import relativedelta
        
        # Build base query
        query = db.session.query(Keuringstatus, Material).join(
            Material, Material.keuring_id == Keuringstatus.id
        )
        
        # Apply priority filter
        if priority_filter == "te_laat":
            query = query.filter(
                Keuringstatus.volgende_controle.isnot(None),
                Keuringstatus.volgende_controle < today,
                Keuringstatus.laatste_controle.is_(None)
            )
        elif priority_filter == "vandaag":
            query = query.filter(
                Keuringstatus.volgende_controle == today,
                Keuringstatus.laatste_controle.is_(None)
            )
        elif priority_filter == "binnen_30":
            query = query.filter(
                Keuringstatus.volgende_controle.isnot(None),
                Keuringstatus.volgende_controle > today,
                Keuringstatus.volgende_controle <= (today + relativedelta(days=30)),
                Keuringstatus.laatste_controle.is_(None)
            )
        
        # Text search
        if search_q:
            like = f"%{search_q}%"
            query = query.filter(
                or_(
                    Material.name.ilike(like),
                    Material.serial.ilike(like)
                )
            )
        
        # Status filter
        if status_filter:
            if status_filter == "te_laat":
                query = query.filter(
                    Keuringstatus.volgende_controle.isnot(None),
                    Keuringstatus.volgende_controle < today,
                    Keuringstatus.laatste_controle.is_(None)
                )
            elif status_filter == "gepland":
                query = query.filter(
                    Keuringstatus.volgende_controle.isnot(None),
                    Keuringstatus.volgende_controle > today,
                    Keuringstatus.laatste_controle.is_(None)
                )
            elif status_filter == "goedgekeurd":
                query = query.filter(Material.inspection_status == "goedgekeurd")
            elif status_filter == "afgekeurd":
                query = query.filter(Material.inspection_status == "afgekeurd")
        
        # Werf filter
        if werf_filter:
            query = query.filter(
                or_(
                    Material.site.ilike(f"%{werf_filter}%"),
                    Material.werf_id == int(werf_filter) if werf_filter.isdigit() else None
                )
            )
        
        # Type filter
        if type_filter:
            query = query.filter(Material.type.ilike(f"%{type_filter}%"))
        
        # Performer filter
        if performer_filter:
            query = query.filter(Keuringstatus.uitgevoerd_door.ilike(f"%{performer_filter}%"))
        
        # Date range filter
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
                query = query.filter(Keuringstatus.volgende_controle >= date_from_obj)
            except ValueError:
                pass
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
                query = query.filter(Keuringstatus.volgende_controle <= date_to_obj)
            except ValueError:
                pass
        
        # Sorting
        if sort_by == "materieel":
            if sort_order == "desc":
                query = query.order_by(Material.name.desc())
            else:
                query = query.order_by(Material.name.asc())
        elif sort_by == "laatste_keuring":
            if sort_order == "desc":
                query = query.order_by(Keuringstatus.laatste_controle.desc().nulls_last())
            else:
                query = query.order_by(Keuringstatus.laatste_controle.asc().nulls_last())
        elif sort_by == "volgende_keuring":
            if sort_order == "desc":
                query = query.order_by(Keuringstatus.volgende_controle.desc().nulls_last())
            else:
                query = query.order_by(Keuringstatus.volgende_controle.asc().nulls_last())
        elif sort_by == "resultaat":
            if sort_order == "desc":
                query = query.order_by(Material.inspection_status.desc().nulls_last())
            else:
                query = query.order_by(Material.inspection_status.asc().nulls_last())
        else:
            query = query.order_by(Keuringstatus.volgende_controle.asc().nulls_last())
        
        # Pagination
        total_items = query.count()
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        inspection_items = pagination.items
        
        # Build inspection list with computed status
        inspection_list = []
        for keuring, material in inspection_items:
            status_badge = "gepland"
            status_class = "secondary"
            dagen_verschil = None
            
            if keuring.laatste_controle:
                if material.inspection_status == "goedgekeurd":
                    status_badge = "goedgekeurd"
                    status_class = "success"
                elif material.inspection_status == "afgekeurd":
                    status_badge = "afgekeurd"
                    status_class = "danger"
                else:
                    status_badge = "gepland"
                    status_class = "secondary"
            else:
                if keuring.volgende_controle:
                    if keuring.volgende_controle < today:
                        status_badge = "te laat"
                        status_class = "danger"
                        dagen_verschil = (today - keuring.volgende_controle).days
                    elif keuring.volgende_controle == today:
                        status_badge = "vandaag"
                        status_class = "warning"
                        dagen_verschil = 0
                    elif keuring.volgende_controle <= (today + relativedelta(days=30)):
                        status_badge = "binnenkort"
                        status_class = "warning"
                        dagen_verschil = (keuring.volgende_controle - today).days
                    else:
                        status_badge = "gepland"
                        status_class = "secondary"
                        dagen_verschil = (keuring.volgende_controle - today).days
            
            # Check certificate
            has_certificate = False
            latest_history = KeuringHistoriek.query.filter_by(
                material_id=material.id
            ).order_by(KeuringHistoriek.keuring_datum.desc()).first()
            if latest_history and latest_history.certificaat_path:
                has_certificate = True
            
            inspection_list.append({
                'keuring': keuring,
                'material': material,
                'status_badge': status_badge,
                'status_class': status_class,
                'dagen_verschil': dagen_verschil,
                'has_certificate': has_certificate,
            })
        
        # Get filter options
        all_projects = Project.query.filter_by(is_deleted=False).order_by(Project.name).all()
        unique_types = db.session.query(Material.type).filter(
            Material.type.isnot(None),
            Material.type != ""
        ).distinct().order_by(Material.type).all()
        types_list = [t[0] for t in unique_types if t[0]]
        
        unique_performers = db.session.query(Keuringstatus.uitgevoerd_door).filter(
            Keuringstatus.uitgevoerd_door.isnot(None),
            Keuringstatus.uitgevoerd_door != ""
        ).distinct().order_by(Keuringstatus.uitgevoerd_door).all()
        performers_list = [p[0] for p in unique_performers if p[0]]
        
        all_materials = Material.query.order_by(Material.name).all()
        
        filter_options = {
            "all_projects": all_projects,
            "types_list": types_list,
            "performers_list": performers_list,
            "all_materials": all_materials,
        }
        
        return inspection_list, pagination, total_items, filter_options


class KeuringRepository:
    """Repository for keuring queries - handles ORM-based filtering"""
    
    @staticmethod
    def get_uitgevoerde_keuringen(today: datetime.date) -> list[Keuringstatus]:
        """Get executed keuringen using ORM"""
        return (
            Keuringstatus.query
            .filter(Keuringstatus.laatste_controle.isnot(None))
            .filter(Keuringstatus.laatste_controle <= today)
            .order_by(Keuringstatus.laatste_controle.desc())
            .all()
        )
    
    @staticmethod
    def get_geplande_keuringen(today: datetime.date) -> list[Keuringstatus]:
        """Get planned keuringen using ORM"""
        return (
            Keuringstatus.query
            .filter(Keuringstatus.volgende_controle.isnot(None))
            .filter(Keuringstatus.volgende_controle > today)
            .filter(Keuringstatus.laatste_controle.is_(None))
            .order_by(Keuringstatus.volgende_controle.asc())
            .all()
        )

