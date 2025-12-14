"""
Service layer for business logic - separates business rules from route handlers.
Routes should call these functions instead of containing business logic directly.
"""
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
from typing import Optional, Union
from models import (
    db, Material, MaterialUsage, Project, Keuringstatus, 
    KeuringHistoriek, MaterialType, Activity, Gebruiker
)
from sqlalchemy import or_, func, and_, case
from constants import (
    DEFAULT_INSPECTION_STATUS, VALID_INSPECTION_STATUSES,
    VALID_USAGE_STATUSES
)


class MaterialService:
    """Service for material-related business logic"""
    
    @staticmethod
    def find_by_serial(serial: str) -> Optional[Material]:
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
    def find_by_name_or_number(name: str, nummer: Optional[str]) -> Optional[Material]:
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
        """Get total count of active (non-deleted) materials"""
        return Material.query.filter(
            or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
        ).count()
    
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
        """Get count of materials requiring inspection (status: 'keuring verlopen' OR 'keuring gepland')"""
        return Material.query.filter(
            Material.inspection_status.in_(["keuring verlopen", "keuring gepland"]),
            or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))  # Exclude deleted items
        ).count()
    
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
        
        BELANGRIJK: Alleen materialen met status "goedgekeurd" worden automatisch gewijzigd naar "keuring verlopen".
        Alle andere statussen ("afgekeurd", "onder voorbehoud", "keuring gepland", etc.) blijven altijd behouden.
        
        Part 1: Updates materials based on expired Keuringstatus records.
        - Alleen materialen met inspection_status == "goedgekeurd"
        
        Part 2: Updates materials based on laatste_keuring/purchase_date + validity days.
        - Uses laatste_keuring if available, otherwise falls back to purchase_date
        - Alleen materialen met inspection_status == "goedgekeurd"
        - Optionally fills in laatste_keuring with purchase_date for consistency
        - Optimized to avoid N+1 queries.
        
        Returns count of updated materials (only counts status changes from "goedgekeurd" to "keuring verlopen").
        """
        today = datetime.utcnow().date()
        updated_count = 0
        
        # PART 1: Get keuringen with expired dates
        # Update alleen materialen waarvan inspection_status == "goedgekeurd"
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
                # ALLEEN materialen met status "goedgekeurd" - alle andere statussen blijven onaangeroerd
                materials = Material.query.filter(
                    Material.serial.in_(serials),
                    Material.inspection_status == "goedgekeurd"  # Alleen "goedgekeurd" mag worden aangepast
                ).all()
                
                # Create a map of serial -> material for O(1) lookup
                material_map = {m.serial: m for m in materials}
                
                # Update materials that need updating
                for keuring in keuringen_met_verlopen_datum:
                    if not keuring.serienummer:
                        continue
                    
                    material = material_map.get(keuring.serienummer)
                    if material:
                        # Extra veiligheidscheck: alleen updaten als status nog steeds "goedgekeurd" is
                        # Dit voorkomt race conditions en zorgt voor idempotentie
                        if material.inspection_status == "goedgekeurd":
                            material.inspection_status = "keuring verlopen"
                            updated_count += 1
        
        # PART 2: Check materials with laatste_keuring/purchase_date + keuring_geldigheid_dagen
        # Get materials that have:
        # - Either laatste_keuring OR purchase_date (fallback)
        # - material_type_id is set
        # - Status is exactly "goedgekeurd" (ALLEEN "goedgekeurd" mag worden aangepast)
        # - Not deleted
        materials_to_check = (
            Material.query
            .filter(
                or_(
                    Material.laatste_keuring.isnot(None),
                    Material.purchase_date.isnot(None)  # Include materials with purchase_date as fallback
                ),
                Material.material_type_id.isnot(None),
                Material.inspection_status == "goedgekeurd",  # ALLEEN "goedgekeurd" - andere statussen blijven behouden
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
                
                # Determine base date: use laatste_keuring if available, otherwise fallback to purchase_date
                base_date = material.laatste_keuring or material.purchase_date
                
                # Skip if both dates are missing (edge case)
                if not base_date:
                    continue
                
                # Optional: Fill in laatste_keuring with purchase_date for consistency
                # Only when laatste_keuring is missing and purchase_date exists
                # Dit overschrijft GEEN statussen (behalve "goedgekeurd" → "keuring verlopen" hieronder)
                if not material.laatste_keuring and material.purchase_date:
                    material.laatste_keuring = material.purchase_date
                    # Note: We don't count this as an "update" for updated_count
                    # Only status changes are counted
                
                # Calculate expiry_date = base_date + validity_days
                expiry_date = base_date + timedelta(days=material_type.inspection_validity_days)
                
                # If today > expiry_date and status is "goedgekeurd", set to "keuring verlopen"
                if today > expiry_date:
                    # Double-check status is still "goedgekeurd" (idempotent check + extra veiligheid)
                    # Als status al "keuring verlopen" is, doe niets (idempotent)
                    # Als status iets anders is ("afgekeurd", "onder voorbehoud", etc.), blijf ongemoeid
                    if material.inspection_status == "goedgekeurd":
                        material.inspection_status = "keuring verlopen"
                        updated_count += 1
        
        # NOTE: We do NOT commit here - let the caller handle transaction boundaries
        # This prevents issues where this function is called within a larger transaction
        # (e.g., during material creation) and would commit prematurely or interfere
        # with the caller's commit logic.
        # Callers should call db.session.commit() after this function if needed.
        
        return updated_count
    
    @staticmethod
    def is_material_in_use(material_id: int) -> bool:
        """Check if material is currently in use"""
        return MaterialUsage.query.filter_by(
            material_id=material_id,
            is_active=True
        ).count() > 0
    
    @staticmethod
    def get_active_usage(material_id: int) -> Optional[MaterialUsage]:
        """Get active usage record for material"""
        return MaterialUsage.query.filter_by(
            material_id=material_id,
            is_active=True
        ).first()
    
    @staticmethod
    def calculate_material_status_from_werf(material: Material) -> str:
        """
        Bereken materiaal status (gebruiksstatus) op basis van werf_id.
        
        Business rule:
        - Als werf_id aanwezig en niet None: status = "in gebruik"
        - Anders: status = "niet in gebruik"
        
        Returns:
            "in gebruik" of "niet in gebruik"
        """
        if material.werf_id is not None:
            return "in gebruik"
        else:
            return "niet in gebruik"
    
    @staticmethod
    def update_material_status(material: Material) -> None:
        """
        Update material status based on active usages AND werf_id.
        Status = "in gebruik" if has active usage OR has werf_id, else "niet in gebruik"
        
        Priority:
        1. Active usage (highest priority)
        2. Werf_id (if no active usage)
        3. Otherwise "niet in gebruik"
        """
        active_count = MaterialUsage.query.filter_by(
            material_id=material.id,
            is_active=True
        ).count()
        
        if active_count > 0:
            material.status = "in gebruik"
        else:
            # Fallback to werf_id-based calculation
            material.status = MaterialService.calculate_material_status_from_werf(material)


class MaterialUsageService:
    """Service for material usage-related business logic"""
    
    @staticmethod
    def start_usage(
        material: Material,
        user_id: int,
        used_by: str,
        project_id: Optional[int] = None,
        site: Optional[str] = None
    ) -> MaterialUsage:
        """
        Start a new material usage session.
        Returns the created MaterialUsage object.
        """
        # Check if already in use
        existing = MaterialUsageService.get_active_usage(material.id)
        if existing:
            # Deze error message wordt getoond wanneer materiaal al in gebruik is
            error_msg = "Materiaal al in gebruik"
            print(f"DEBUG: Material {material.id} ({material.serial or material.name}) is already in use, raising: {error_msg}")
            raise ValueError(error_msg)
        
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
    def get_active_usage(material_id: int) -> Optional[MaterialUsage]:
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
        limit: Optional[int] = 500
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
        """
        Get unique user names from activities, but only for users that currently exist in the system.
        Uses JOIN with Gebruiker table to ensure only active users are returned.
        """
        # Get unique user names from Activity that also exist in Gebruiker table
        # Join on user_name matching Gebruiker.naam
        unique_users = (
            db.session.query(Activity.user_name)
            .join(Gebruiker, Activity.user_name == Gebruiker.naam)
            .filter(
                Activity.user_name.isnot(None),
                Activity.user_name != ""
            )
            .distinct()
            .order_by(Activity.user_name)
            .all()
        )
        return [u[0] for u in unique_users if u[0]]


class MaterialUsageRepository:
    """Repository for material usage queries - handles ORM-based filtering"""
    
    @staticmethod
    def get_active_usages_grouped(user_name: Optional[str] = None) -> tuple[list[dict], list[dict], list[dict]]:
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
        """
        Get priority counts for keuringen cards.
        Uses the same data source and logic as get_filtered_keuringen() table.
        
        Definitions:
        - te_laat: Items where Material.inspection_status == "keuring verlopen" (exact match)
        - vandaag: Items where Keuringstatus.volgende_controle == today (has planned inspection today)
        - binnen_30_dagen: Items where volgende_controle > today AND <= today+30 days
        """
        # Use the same base filter as get_filtered_keuringen()
        # Een materiaal verschijnt in keuringentabel als:
        # - laatste_keuring is ingevuld OF
        # - keuringsstatus is "Onder voorbehoud" of "Afgekeurd"
        base_filter = and_(
            or_(
                Material.laatste_keuring.isnot(None),
                Material.inspection_status.in_(["onder voorbehoud", "afgekeurd", "Onder voorbehoud", "Afgekeurd"])
            ),
            or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))  # Exclude soft-deleted materials
        )
        
        # 1. Te laat: Count items where inspection_status exactly equals "keuring verlopen"
        te_laat_count = (
            db.session.query(Material)
            .filter(base_filter)
            .filter(Material.inspection_status == "keuring verlopen")
            .count()
        )
        
        # 2. Te keuren vandaag: Items with volgende_controle == today
        # Must have a volgende_controle date (no NULL dates count)
        vandaag_count = (
            db.session.query(Material)
            .outerjoin(Keuringstatus, Material.keuring_id == Keuringstatus.id)
            .filter(base_filter)
            .filter(Keuringstatus.volgende_controle.isnot(None))
            .filter(Keuringstatus.volgende_controle == today)
            .distinct()
            .count()
        )
        
        # 3. Binnen 30 dagen: Items with volgende_controle between tomorrow and today+30 days (inclusive)
        # date > today AND date <= today + 30 days
        binnen_30_dagen_count = (
            db.session.query(Material)
            .outerjoin(Keuringstatus, Material.keuring_id == Keuringstatus.id)
            .filter(base_filter)
            .filter(Keuringstatus.volgende_controle.isnot(None))
            .filter(Keuringstatus.volgende_controle > today)
            .filter(Keuringstatus.volgende_controle <= (today + relativedelta(days=30)))
            .distinct()
            .count()
        )
        
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
        
        # Build base query - NIEUWE LOGICA: Direct Material records die voldoen aan voorwaarden
        # Een materiaal verschijnt in keuringentabel als:
        # - laatste_keuring is ingevuld OF
        # - keuringsstatus is "Onder voorbehoud" of "Afgekeurd"
        
        # Basis filter: laatste_keuring ingevuld OF status is "Onder voorbehoud" of "Afgekeurd"
        # EN materiaal is niet verwijderd (soft delete filter)
        base_filter = and_(
            or_(
                Material.laatste_keuring.isnot(None),
                Material.inspection_status.in_(["onder voorbehoud", "afgekeurd", "Onder voorbehoud", "Afgekeurd"])
            ),
            or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))  # Exclude soft-deleted materials
        )
        
        # Query Material records die voldoen aan voorwaarden
        # LEFT JOIN met Keuringstatus voor backward compatibility (template verwacht keuring object)
        # maar de echte data komt uit Material
        # JOIN met Project om werf naam op te halen
        query = db.session.query(Keuringstatus, Material).outerjoin(
            Keuringstatus, Material.keuring_id == Keuringstatus.id
        ).outerjoin(
            Project, Material.werf_id == Project.id
        ).filter(
            base_filter
        ).distinct()
        
        # Apply priority filter - QUICK FILTER LOGIC: Priority filters hebben voorrang op status_filter
        # Als een priority filter actief is, overschrijft deze de status_filter
        priority_status_override = None
        priority_date_from = None
        priority_date_to = None
        
        if priority_filter == "te_laat":
            # Te laat: Filter op inspection_status = "keuring verlopen"
            # Dit overschrijft status_filter, zelfs als die op "Alle statussen" staat
            priority_status_override = "keuring verlopen"
        elif priority_filter == "vandaag":
            # Te keuren vandaag: Filter op volgende_keuring_datum === vandaag
            # Stel date filters in op vandaag → vandaag
            priority_date_from = today
            priority_date_to = today
        elif priority_filter == "binnen_30":
            # Binnen 30 dagen: Filter op volgende_keuring_datum > vandaag AND <= vandaag + 30 dagen
            # Stel date filters in
            priority_date_from = today + relativedelta(days=1)  # Morgen
            priority_date_to = today + relativedelta(days=30)  # Vandaag + 30 dagen
        
        # Text search
        if search_q:
            like = f"%{search_q}%"
            query = query.filter(
                or_(
                    Material.name.ilike(like),
                    Material.serial.ilike(like)
                )
            )
        
        # Status filter - wordt overschreven door priority filter als die actief is
        if priority_status_override:
            # Priority filter heeft voorrang: gebruik de override status
            query = query.filter(Material.inspection_status == priority_status_override)
        elif status_filter:
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
        
        # Werf filter - Note: This filters on material.werf_id/material.site for initial filtering
        # The actual display location comes from active usage (handled in Python after query)
        # This filter is a best-effort approximation - exact filtering by active usage location
        # would require a more complex query with subqueries
        if werf_filter:
            if werf_filter.isdigit():
                # Filter by project_id (can match either material.werf_id or active usage project_id)
                query = query.filter(Material.werf_id == int(werf_filter))
            else:
                # Text search on material.site (approximation)
                query = query.filter(Material.site.ilike(f"%{werf_filter}%"))
        
        # Type filter
        if type_filter:
            query = query.filter(Material.type.ilike(f"%{type_filter}%"))
        
        # Performer filter
        if performer_filter:
            query = query.filter(Keuringstatus.uitgevoerd_door.ilike(f"%{performer_filter}%"))
        
        # Date range filter - priority filter heeft voorrang
        if priority_date_from is not None:
            # Priority filter heeft voorrang: gebruik priority date filters
            query = query.filter(Keuringstatus.volgende_controle.isnot(None))
            query = query.filter(Keuringstatus.volgende_controle >= priority_date_from)
            if priority_date_to is not None:
                query = query.filter(Keuringstatus.volgende_controle <= priority_date_to)
        else:
            # Gebruik normale date filters alleen als geen priority filter actief is
            if date_from:
                try:
                    date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
                    query = query.filter(Keuringstatus.volgende_controle.isnot(None))
                    query = query.filter(Keuringstatus.volgende_controle >= date_from_obj)
                except ValueError:
                    pass
            if date_to:
                try:
                    date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
                    query = query.filter(Keuringstatus.volgende_controle.isnot(None))
                    query = query.filter(Keuringstatus.volgende_controle <= date_to_obj)
                except ValueError:
                    pass
        
        # Check if we need to sort by risk (requires Python-side sorting)
        needs_risk_sorting = (sort_by == "risk" or not sort_by)
        
        # If sorting by risk, we need to get ALL items first, calculate risk, sort, then paginate
        # Otherwise, we can use database pagination
        if needs_risk_sorting:
            # Get all items (no pagination yet)
            all_inspection_items = query.all()
            total_items = len(all_inspection_items)
        else:
            # Apply database sorting for non-risk sorts
            if sort_by == "materieel":
                if sort_order == "desc":
                    query = query.order_by(Material.name.desc())
                else:
                    query = query.order_by(Material.name.asc())
            elif sort_by == "laatste_keuring":
                # Sorteer op material.laatste_keuring (direct van materiaal)
                if sort_order == "desc":
                    query = query.order_by(Material.laatste_keuring.desc().nulls_last())
                else:
                    query = query.order_by(Material.laatste_keuring.asc().nulls_last())
            elif sort_by == "volgende_keuring":
                # Volgende keuring is altijd leeg volgens nieuwe logica, maar sorteer op NULL voor consistentie
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
                # Default: sort by volgende_controle
                query = query.order_by(Keuringstatus.volgende_controle.asc().nulls_last())
            
            # Pagination for non-risk sorts
            total_items = query.count()
            pagination = query.paginate(page=page, per_page=per_page, error_out=False)
            all_inspection_items = pagination.items
        
        # Import risk calculation algorithm and helper
        from algorithms.inspection_risk import calculate_inspection_risk
        from helpers import get_file_url_from_path
        
        # Pre-fetch all active usage records for materials to avoid N+1 queries
        material_ids = [m.id for _, m in all_inspection_items]
        active_usages = {}
        if material_ids:
            now = datetime.utcnow()
            usage_records = MaterialUsage.query.filter(
                MaterialUsage.material_id.in_(material_ids),
                MaterialUsage.is_active.is_(True),
                or_(
                    MaterialUsage.end_time.is_(None),
                    MaterialUsage.end_time > now
                )
            ).order_by(MaterialUsage.start_time.desc()).all()
            
            # Group by material_id, keeping only the most recent active usage per material
            for usage in usage_records:
                if usage.material_id not in active_usages:
                    active_usages[usage.material_id] = usage
        
        # Build inspection list with computed status and risk
        # NIEUWE LOGICA: Direct mapping van Material naar keuringentabel
        inspection_list = []
        for keuring, material in all_inspection_items:
            # Resultaat badge: gebruik direct material.inspection_status
            status_badge = "gepland"
            status_class = "secondary"
            dagen_verschil = None
            
            # Map inspection_status direct naar status_badge
            if material.inspection_status:
                status_lower = material.inspection_status.lower()
                if status_lower == "goedgekeurd":
                    status_badge = "goedgekeurd"
                    status_class = "success"
                elif status_lower == "afgekeurd":
                    status_badge = "afgekeurd"
                    status_class = "danger"
                elif status_lower in ["onder voorbehoud", "keuring onder voorbehoud"]:
                    status_badge = "onder_voorbehoud"
                    status_class = "warning"
                else:
                    # Andere statussen: default "gepland"
                    status_badge = "gepland"
                    status_class = "secondary"
            
            # Volgende keuring is altijd leeg volgens nieuwe logica (geen automatische berekening)
            # dagen_verschil blijft None
            
            # Check certificate
            has_certificate = False
            certificaat_url = None
            latest_history = KeuringHistoriek.query.filter_by(
                material_id=material.id
            ).order_by(KeuringHistoriek.keuring_datum.desc()).first()
            if latest_history and latest_history.certificaat_path:
                has_certificate = True
                from helpers import get_document_url
                certificaat_url = get_document_url("Keuringstatus", latest_history.certificaat_path)
            
            # Calculate risk using algorithm
            risk_data = calculate_inspection_risk(material, keuring, today)
            
            # NIEUWE LOGICA: Gebruik material.werf_id als bron van waarheid voor werf/locatie
            # Dit is consistent met hoe materiaal wordt aangemaakt (directe koppeling via werf_id)
            current_location = None
            current_werf_name = None
            in_gebruik = False
            
            # Check of materiaal aan een werf gekoppeld is via werf_id (directe koppeling)
            if material.werf_id and material.project:
                # Materiaal is direct gekoppeld aan een werf
                current_werf_name = material.project.name
                current_location = current_werf_name
                in_gebruik = True
            elif material.werf_id:
                # Werf_id bestaat maar project relatie is niet geladen, haal project op
                project = Project.query.filter_by(id=material.werf_id, is_deleted=False).first()
                if project:
                    current_werf_name = project.name
                    current_location = current_werf_name
                    in_gebruik = True
            
            # Fallback: als er geen directe werf koppeling is, check active usage (voor backward compatibility)
            if not current_location:
                active_usage = active_usages.get(material.id)
                if active_usage:
                    in_gebruik = True
                    # Prefer werf name from project, otherwise use locatie from usage
                    if active_usage.project_id and active_usage.project:
                        current_werf_name = active_usage.project.name
                        current_location = current_werf_name
                    elif active_usage.site:
                        current_location = active_usage.site
                    elif active_usage.project_id:
                        # Try to get project name if project relationship is not loaded
                        project = Project.query.filter_by(id=active_usage.project_id, is_deleted=False).first()
                        if project:
                            current_werf_name = project.name
                            current_location = current_werf_name
            
            # Maak een dummy Keuringstatus object voor backward compatibility met template
            # Template verwacht keuring.laatste_controle en keuring.volgende_controle
            # Maar we gebruiken nu direct material.laatste_keuring
            class DummyKeuring:
                def __init__(self, material, keuring):
                    # Laatste controle: gebruik material.laatste_keuring
                    self.laatste_controle = material.laatste_keuring
                    # Volgende controle: gebruik echte volgende_controle als die bestaat (handmatig ingepland)
                    # Anders None (geen automatische berekening meer)
                    self.volgende_controle = keuring.volgende_controle if keuring else None
                    # Andere velden voor backward compatibility
                    self.id = keuring.id if keuring else None
                    self.serienummer = material.serial
                    self.opmerkingen = keuring.opmerkingen if keuring else None
                    self.uitgevoerd_door = keuring.uitgevoerd_door if keuring else None
                    self.updated_by = keuring.updated_by if keuring else None
            
            dummy_keuring = DummyKeuring(material, keuring)
            
            inspection_list.append({
                'keuring': dummy_keuring,  # Gebruik dummy object met material data
                'material': material,
                'status_badge': status_badge,
                'status_class': status_class,
                'dagen_verschil': dagen_verschil,  # Altijd None (geen volgende keuring)
                'has_certificate': has_certificate,
                'certificaat_url': certificaat_url,
                'risk_score': risk_data['risk_score'],
                'risk_level': risk_data['risk_level'],
                'risk_explanation': risk_data['risk_explanation'],
                'in_gebruik': in_gebruik,
                'current_location': current_location,  # Will be None if not in use
                'current_werf_name': current_werf_name,  # Will be None if not in use
            })
        
        # Helper function for pagination iteration (only used for risk sorting)
        def _iter_pages_helper(current_page, total_pages, left_edge, right_edge, left_current, right_current):
            """Helper to generate page numbers for pagination"""
            last = 0
            for num in range(1, total_pages + 1):
                if num <= left_edge or \
                   (num > current_page - left_current - 1 and num < current_page + right_current) or \
                   num > total_pages - right_edge:
                    if last + 1 != num:
                        yield None
                    yield num
                    last = num
        
        # Sort by risk if requested, or default to risk_score DESC if no sort specified
        if needs_risk_sorting:
            # Default sorting: risk_score DESC if no sort specified
            reverse = (sort_order == "desc") if sort_by == "risk" else True
            inspection_list.sort(key=lambda x: x['risk_score'], reverse=reverse)
            
            # Manual pagination for risk-sorted results
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            paginated_list = inspection_list[start_idx:end_idx]
            
            # Create a pagination-like object for compatibility
            from math import ceil
            total_pages = ceil(total_items / per_page) if total_items > 0 else 1
            
            # Create a simple object that mimics Flask-SQLAlchemy's Pagination
            class PaginationObject:
                def __init__(self, page, per_page, total, pages):
                    self.page = page
                    self.per_page = per_page
                    self.total = total
                    self.pages = pages
                    self.has_prev = page > 1
                    self.has_next = page < pages
                    self.prev_num = page - 1 if page > 1 else None
                    self.next_num = page + 1 if page < pages else None
                
                def iter_pages(self, left_edge=1, right_edge=1, left_current=2, right_current=2):
                    return _iter_pages_helper(self.page, self.pages, left_edge, right_edge, left_current, right_current)
            
            pagination = PaginationObject(page, per_page, total_items, total_pages)
            inspection_list = paginated_list
        else:
            # For non-risk sorts, inspection_list is already paginated from database
            pass
        
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


def ensure_keuring_status_and_historiek_for_new_material(
    material: Material,
    geplande_keuringsdatum: Optional[date] = None,
    user_id: Optional[int] = None
) -> None:
    """
    NIEUWE SIMPELE LOGICA: Maak alleen keuring_status record aan als nodig voor backward compatibility.
    
    Een materiaal verschijnt in keuringentabel als:
    - laatste_keuring is ingevuld OF
    - keuringsstatus is "Onder voorbehoud" of "Afgekeurd"
    
    GEEN automatische berekeningen voor volgende_controle.
    GEEN geplande keuringen.
    
    Args:
        material: Het Material object dat net is aangemaakt (moet material.id hebben)
        geplande_keuringsdatum: Genegeerd (niet meer gebruikt)
        user_id: Optionele user_id voor updated_by veld
    """
    from sqlalchemy import and_
    
    if not material.id:
        raise ValueError("Material must have an id before calling this function")
    
    if not material.serial:
        # Geen serienummer, kan geen keuring_status record maken
        return
    
    # NIEUWE LOGICA: Check of materiaal moet verschijnen in keuringentabel
    heeft_laatste_keuring = material.laatste_keuring is not None
    status_onder_voorbehoud_of_afgekeurd = (
        material.inspection_status and 
        material.inspection_status.lower() in ["onder voorbehoud", "afgekeurd", "keuring onder voorbehoud"]
    )
    
    # Alleen keuring_status record aanmaken als nodig
    moet_keuring_status = heeft_laatste_keuring or status_onder_voorbehoud_of_afgekeurd
    
    if not moet_keuring_status:
        return
    
    # Upsert keuring_status op serienummer (voor backward compatibility)
    keuring_status = Keuringstatus.query.filter_by(serienummer=material.serial).first()
    
    if not keuring_status:
        keuring_status = Keuringstatus(serienummer=material.serial)
        db.session.add(keuring_status)
    
    # Update laatste_controle: gebruik material.laatste_keuring
    keuring_status.laatste_controle = material.laatste_keuring if heeft_laatste_keuring else None
    
    # GEEN automatische berekening voor volgende_controle - altijd None
    keuring_status.volgende_controle = None
    
    keuring_status.updated_by = user_id
    
    # Flush om keuring_status.id te krijgen voor link met material
    db.session.flush()
    
    # Link material aan keuring_status via keuring_id (voor backward compatibility)
    material.keuring_id = keuring_status.id
    
    # Als laatste_keuring ingevuld, maak ook historiek record
    if heeft_laatste_keuring:
        # Bepaal resultaat voor historiek op basis van inspection_status
        resultaat = None
        if material.inspection_status:
            status_lower = material.inspection_status.lower()
            if status_lower == "goedgekeurd":
                resultaat = "Goedgekeurd"
            elif status_lower == "afgekeurd":
                resultaat = "Afgekeurd"
            elif status_lower in ["onder voorbehoud", "keuring onder voorbehoud"]:
                resultaat = "Onder voorbehoud"
            else:
                # Fallback: gebruik status als resultaat
                resultaat = material.inspection_status
        
        if not resultaat:
            resultaat = "Te keuren"  # Default fallback
        
        # Check of er al een historiek record bestaat (idempotentie)
        existing_historiek = KeuringHistoriek.query.filter(
            and_(
                KeuringHistoriek.material_id == material.id,
                KeuringHistoriek.keuring_datum == material.laatste_keuring,
                KeuringHistoriek.resultaat == resultaat
            )
        ).first()
        
        if not existing_historiek:
            # Bepaal uitgevoerd_door: gebruik gebruikersnaam als beschikbaar, anders "Onbekend"
            uitgevoerd_door = "Onbekend"
            if user_id:
                user = Gebruiker.query.get(user_id)
                if user and user.naam:
                    uitgevoerd_door = user.naam
            
            historiek = KeuringHistoriek(
                material_id=material.id,
                serienummer=material.serial,
                keuring_datum=material.laatste_keuring,
                resultaat=resultaat,
                uitgevoerd_door=uitgevoerd_door,
                opmerkingen=None,
                volgende_keuring_datum=None,  # GEEN automatische berekening
                certificaat_path=None
            )
            db.session.add(historiek)