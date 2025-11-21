# models.py
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
    password_hash = db.Column(db.String, nullable=True)  # voorlopig niet gebruikt


class Material(db.Model):
    __tablename__ = "materials"

    id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    # Python-attribuut -> kolomnaam in Supabase
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

    # Let op: GEEN kolom "inspection_status" in de DB,
    # dus hier ook niet definiëren. Jinja zal dan gewoon "-" tonen
    # door `{{ it.inspection_status or "-" }}`.
