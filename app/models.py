from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Gebruiker(db.Model):
    __tablename__ = "Gebruiker"

    gebruiker_id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    Naam = db.Column(db.String)
    Email = db.Column(db.String, unique=True, nullable=False)
    Functie = db.Column(db.String)
    project_id = db.Column(db.Numeric, nullable=True)
    telefoon_nummer = db.Column(db.Numeric, nullable=True)
    password_hash = db.Column(db.String, nullable=True)


class Material(db.Model):
    __tablename__ = "materials"

    id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    # mappen op kolomnamen in Supabase
    name = db.Column("Naam", db.String)
    status = db.Column("Status", db.String)
    keuring_id = db.Column("Keuring", db.BigInteger, nullable=True)
    project_id = db.Column("project_id", db.Numeric, nullable=True)
    serial = db.Column("Serienummer", db.String, unique=True, nullable=False)
    category = db.Column("Categorie", db.String)
    type = db.Column("type", db.String)
    purchase_date = db.Column("purchase_date", db.Date, nullable=True)
    assigned_to = db.Column("assigned_to", db.String, nullable=True)
    site = db.Column("site", db.String, nullable=True)
    note = db.Column("note", db.String, nullable=True)
    documentation_path = db.Column("documentation_path", db.Text, nullable=True)
    safety_sheet_path = db.Column("safety_sheet_path", db.Text, nullable=True)

    # nieuw veld
    nummer_op_materieel = db.Column("nummer_op_materieel", db.String, nullable=True)


class Activity(db.Model):
    """
    Map naar Supabase tabel 'activity_log'
    kolommen: id, created_at, action, name, serial, user_name
    """
    __tablename__ = "activity_log"

    id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    action = db.Column(db.String)
    name = db.Column(db.String)
    serial = db.Column(db.String)
    user_name = db.Column(db.String)


class MaterialUsage(db.Model):
    """
    Map naar Supabase tabel 'material_usage'

    Kolommen volgens jouw screenshot:
    id, material_id, user_id, site, note, start_time, end_time, is_active, used_by
    """
    __tablename__ = "material_usage"

    id = db.Column(db.BigInteger, primary_key=True)

    material_id = db.Column(db.BigInteger,
                            db.ForeignKey("materials.id"),
                            nullable=False)
    user_id = db.Column(db.BigInteger,
                        db.ForeignKey("Gebruiker.gebruiker_id"),
                        nullable=True)

    site = db.Column(db.Text, nullable=True)
    note = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    end_time = db.Column(db.DateTime(timezone=True), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    used_by = db.Column(db.Text, nullable=True)

    # handige relaties
    material = db.relationship("Material", backref="usages")
    user = db.relationship("Gebruiker", backref="usages")
