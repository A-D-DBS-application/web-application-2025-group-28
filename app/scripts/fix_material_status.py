"""
Data-correctie script om foutieve status waarden in materialen tabel te herstellen.

Probleem:
- Sommige materialen hebben status = "goedgekeurd", "afgekeurd", etc. (keuringstatus waarden)
- Status moet alleen "in gebruik" of "niet in gebruik" zijn (gebruiksstatus)

Fix:
1. Vind materialen waar status NIET IN ("in gebruik", "niet in gebruik")
2. Als keuring_status leeg/NULL is: zet keuring_status = status (verplaats foutieve waarde)
3. Herbereken status op basis van werf_id (werf_id aanwezig => "in gebruik", anders => "niet in gebruik")

Gebruik:
    python -m app.scripts.fix_material_status
    of
    flask shell
    >>> from app.scripts.fix_material_status import fix_material_statuses
    >>> fix_material_statuses()
"""
from app import app
from models import db, Material
from services import MaterialService


def fix_material_statuses(dry_run: bool = True) -> dict:
    """
    Fix foutieve status waarden in materialen tabel.
    
    Args:
        dry_run: Als True, toon alleen wat er zou worden aangepast zonder te committen.
    
    Returns:
        Dict met statistieken over de fix operatie.
    """
    valid_statuses = {"in gebruik", "niet in gebruik"}
    
    # Vind materialen met foutieve status
    all_materials = Material.query.filter(
        Material.is_deleted.isnot(True)
    ).all()
    
    fixed_count = 0
    moved_to_keuring_status = 0
    recalculated_status = 0
    errors = []
    
    for material in all_materials:
        needs_fix = False
        original_status = material.status
        original_keuring_status = material.inspection_status
        
        # Check of status foutief is
        if material.status not in valid_statuses:
            needs_fix = True
        
        if needs_fix:
            try:
                # Stap 1: Als keuring_status leeg is, verplaats foutieve status waarde
                if not material.inspection_status and material.status:
                    material.inspection_status = material.status
                    moved_to_keuring_status += 1
                    print(f"  → Verplaatst status '{material.status}' naar keuring_status voor {material.serial}")
                
                # Stap 2: Herbereken status op basis van werf_id
                new_status = MaterialService.calculate_material_status_from_werf(material)
                if material.status != new_status:
                    print(f"  → Status '{material.status}' → '{new_status}' voor {material.serial} (werf_id: {material.werf_id})")
                    material.status = new_status
                    recalculated_status += 1
                
                fixed_count += 1
                
            except Exception as e:
                errors.append(f"Fout bij materiaal {material.serial}: {e}")
                print(f"  ✗ Fout bij {material.serial}: {e}")
    
    if not dry_run and fixed_count > 0:
        try:
            db.session.commit()
            print(f"\n✓ {fixed_count} materialen gefixed en gecommit.")
        except Exception as e:
            db.session.rollback()
            errors.append(f"Commit fout: {e}")
            print(f"\n✗ Commit fout: {e}")
    elif dry_run:
        print(f"\n[DRY RUN] {fixed_count} materialen zouden worden gefixed.")
        print("Run met dry_run=False om daadwerkelijk op te slaan.")
    
    stats = {
        "total_checked": len(all_materials),
        "fixed_count": fixed_count,
        "moved_to_keuring_status": moved_to_keuring_status,
        "recalculated_status": recalculated_status,
        "errors": errors
    }
    
    return stats


if __name__ == "__main__":
    with app.app_context():
        print("=" * 60)
        print("Data-correctie: Fix foutieve status waarden")
        print("=" * 60)
        print("\n[DRY RUN MODE - geen wijzigingen worden opgeslagen]")
        print("-" * 60)
        stats = fix_material_statuses(dry_run=True)
        print("\n" + "=" * 60)
        print("Statistieken:")
        print(f"  Totaal gecontroleerd: {stats['total_checked']}")
        print(f"  Te fixen: {stats['fixed_count']}")
        print(f"  Verplaatst naar keuring_status: {stats['moved_to_keuring_status']}")
        print(f"  Status herberekend: {stats['recalculated_status']}")
        if stats['errors']:
            print(f"  Fouten: {len(stats['errors'])}")
            for error in stats['errors']:
                print(f"    - {error}")
        print("=" * 60)
        print("\nOm daadwerkelijk te fixen, run:")
        print("  >>> from app.scripts.fix_material_status import fix_material_statuses")
        print("  >>> fix_material_statuses(dry_run=False)")

