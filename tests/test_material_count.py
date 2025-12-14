"""
Test to verify that MaterialService.get_total_count() excludes deleted items.

Test case: 3 items created, 1 deleted → total should be 2.
"""
import pytest
from sqlalchemy import or_
from app import create_app
from app.models import db, Material
from app.services import MaterialService


@pytest.fixture
def app():
    """Create Flask app for testing"""
    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client"""
    return app.test_client()


def test_get_total_count_excludes_deleted_items(app):
    """
    Test that MaterialService.get_total_count() correctly excludes deleted items.
    
    Scenario:
    - Create 3 material items
    - Delete 1 item (soft delete: set is_deleted=True)
    - Verify total count is 2 (not 3)
    """
    with app.app_context():
        # Create 3 materials
        material1 = Material(
            name="Test Material 1",
            serial="SERIAL001",
            inspection_status="goedgekeurd"
        )
        material2 = Material(
            name="Test Material 2",
            serial="SERIAL002",
            inspection_status="goedgekeurd"
        )
        material3 = Material(
            name="Test Material 3",
            serial="SERIAL003",
            inspection_status="goedgekeurd"
        )
        
        db.session.add(material1)
        db.session.add(material2)
        db.session.add(material3)
        db.session.commit()
        
        # Verify we have 3 materials
        total_before_delete = MaterialService.get_total_count()
        assert total_before_delete == 3, f"Expected 3 materials, got {total_before_delete}"
        
        # Soft delete one material
        material1.is_deleted = True
        db.session.commit()
        
        # Verify total count is now 2 (deleted item excluded)
        total_after_delete = MaterialService.get_total_count()
        assert total_after_delete == 2, f"Expected 2 materials after delete, got {total_after_delete}"
        
        # Verify direct query also shows 2 active items
        active_count = Material.query.filter(
            or_(Material.is_deleted.is_(False), Material.is_deleted.is_(None))
        ).count()
        assert active_count == 2, f"Expected 2 active materials, got {active_count}"


def test_get_total_count_handles_none_deleted(app):
    """
    Test that materials with is_deleted=None are included in the count.
    """
    with app.app_context():
        # Create material with is_deleted=None (should be included)
        material1 = Material(
            name="Test Material None",
            serial="SERIALNONE",
            inspection_status="goedgekeurd",
            is_deleted=None
        )
        # Create material with is_deleted=False (should be included)
        material2 = Material(
            name="Test Material False",
            serial="SERIALFALSE",
            inspection_status="goedgekeurd",
            is_deleted=False
        )
        
        db.session.add(material1)
        db.session.add(material2)
        db.session.commit()
        
        # Both should be counted
        total = MaterialService.get_total_count()
        assert total == 2, f"Expected 2 materials (None and False), got {total}"


def test_get_total_count_excludes_only_deleted_true(app):
    """
    Test that only materials with is_deleted=True are excluded.
    """
    with app.app_context():
        # Create materials with different is_deleted values
        active1 = Material(name="Active 1", serial="A1", is_deleted=False)
        active2 = Material(name="Active 2", serial="A2", is_deleted=None)
        deleted1 = Material(name="Deleted 1", serial="D1", is_deleted=True)
        
        db.session.add(active1)
        db.session.add(active2)
        db.session.add(deleted1)
        db.session.commit()
        
        # Only active materials should be counted (2, not 3)
        total = MaterialService.get_total_count()
        assert total == 2, f"Expected 2 active materials, got {total}"

