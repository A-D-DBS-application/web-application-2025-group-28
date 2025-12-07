from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Gebruiker(db.Model):
    __tablename__ = "Gebruiker"

    gebruiker_id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    Naam = db.Column(db.String)                      # "Naam"
    Email = db.Column(db.String, unique=True, nullable=False)  # "Email"
    Functie = db.Column(db.String)                   # "Functie"

    # na de SQL hierboven is dit BIGINT in de database
    project_id = db.Column(db.BigInteger, nullable=True)

    telefoon_nummer = db.Column(db.Numeric, nullable=True)
    password_hash = db.Column(db.String, nullable=True)

    # Admin status voor beheerfuncties
    is_admin = db.Column(db.Boolean, default=False)


class Project(db.Model):
    """
    Werf / project.
    Map naar Supabase tabel 'Project'.

    Belangrijk:
      - PK: ProjectID (bigint)
      - StartDate, EndDate, Type, created_at
      - extra: Naam, Adres, image_url, note, is_deleted
    """
    __tablename__ = "Project"

    id = db.Column("ProjectID", db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    # kolommen met hoofdletters zoals in Supabase
    name = db.Column("Naam", db.String, nullable=True)
    address = db.Column("Adres", db.String, nullable=True)

    start_date = db.Column("StartDate", db.Date, nullable=True)
    end_date = db.Column("EndDate", db.Date, nullable=True)
    type = db.Column("Type", db.String, nullable=True)

    image_url = db.Column("image_url", db.Text, nullable=True)
    note = db.Column("note", db.Text, nullable=True)
    is_deleted = db.Column("is_deleted", db.Boolean, default=False)


class Material(db.Model):
    __tablename__ = "materials"

    id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    # mappen op kolomnamen in Supabase
    name = db.Column("Naam", db.String)              # "Naam"
    status = db.Column("Status", db.String)          # "Status"
    keuring_id = db.Column("Keuring", db.BigInteger, nullable=True)

    # na SQL hierboven is dit BIGINT in de database
    project_id = db.Column("project_id", db.BigInteger, nullable=True)

    serial = db.Column("Serienummer", db.String, unique=True, nullable=False)
    type = db.Column("type", db.String)              # "type"

    purchase_date = db.Column("purchase_date", db.Date, nullable=True)
    assigned_to = db.Column("assigned_to", db.String, nullable=True)
    site = db.Column("site", db.String, nullable=True)
    note = db.Column("note", db.String, nullable=True)

    documentation_path = db.Column("documentation_path", db.Text, nullable=True)
    safety_sheet_path = db.Column("safety_sheet_path", db.Text, nullable=True)

    nummer_op_materieel = db.Column("nummer_op_materieel", db.String, nullable=True)
    inspection_status = db.Column("inspection_status", db.String, nullable=True)

    # handige (read-only) relatie naar Project
    project = db.relationship(
        "Project",
        backref="materials",
        primaryjoin="Project.id == foreign(Material.project_id)",
        viewonly=True,
    )


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

    Kolommen in Supabase:
    id, material_id, user_id, site, note,
    start_time, end_time, is_active, used_by, project_id
    """
    __tablename__ = "material_usage"

    id = db.Column(db.BigInteger, primary_key=True)

    material_id = db.Column(
        db.BigInteger,
        db.ForeignKey("materials.id"),
        nullable=False,
    )
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("Gebruiker.gebruiker_id"),
        nullable=True,
    )

    # na SQL hierboven is dit BIGINT
    project_id = db.Column("project_id", db.BigInteger, nullable=True)

    site = db.Column(db.Text, nullable=True)
    note = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    end_time = db.Column(db.DateTime(timezone=True), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    used_by = db.Column(db.Text, nullable=True)

    # handige relaties
    material = db.relationship("Material", backref="usages")
    user = db.relationship("Gebruiker", backref="usages")

    project = db.relationship(
        "Project",
        backref="material_usages",
        primaryjoin="Project.id == foreign(MaterialUsage.project_id)",
        viewonly=True,
    )


class Keuringstatus(db.Model):
    """
    Map naar Supabase tabel 'Keuringstatus'
    
    Kolommen in Supabase:
    id, created_at, laatste_controle, volgende_controle, serienummer, uitgevoerd_door, opmerkingen
    """
    __tablename__ = "Keuringstatus"

    id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    
    laatste_controle = db.Column("laatste_controle", db.Date, nullable=True)
    volgende_controle = db.Column("volgende_controle", db.Date, nullable=True)
    serienummer = db.Column("serienummer", db.String, nullable=True)
    uitgevoerd_door = db.Column("uitgevoerd_door", db.String, nullable=True)
    opmerkingen = db.Column("opmerkingen", db.Text, nullable=True)
    
    # Relatie naar Material via serienummer (niet via foreign key, maar via serienummer match)


class KeuringHistoriek(db.Model):
    """
    Map naar Supabase tabel 'keuring_historiek'
    
    Deze tabel slaat alle uitgevoerde keuringen op voor historiek.
    Elke keer dat een keuring wordt uitgevoerd, wordt hier een record aangemaakt.
    
    Kolommen in Supabase:
    id, created_at, material_id, serienummer, keuring_datum, resultaat,
    uitgevoerd_door, opmerkingen, volgende_keuring_datum, certificaat_path
    """
    __tablename__ = "keuring_historiek"

    id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    
    material_id = db.Column(
        db.BigInteger,
        db.ForeignKey("materials.id", ondelete="CASCADE"),
        nullable=False,
    )
    serienummer = db.Column(db.String, nullable=False)
    
    keuring_datum = db.Column("keuring_datum", db.Date, nullable=False)
    resultaat = db.Column(db.String, nullable=False)  # 'goedgekeurd', 'afgekeurd', 'voorwaardelijk'
    uitgevoerd_door = db.Column("uitgevoerd_door", db.String, nullable=False)
    opmerkingen = db.Column("opmerkingen", db.Text, nullable=True)
    
    volgende_keuring_datum = db.Column("volgende_keuring_datum", db.Date, nullable=True)
    certificaat_path = db.Column("certificaat_path", db.Text, nullable=True)
    
    # Relatie naar Material
    material = db.relationship("Material", backref="keuring_historiek")


class Document(db.Model):
    """
    Map naar Supabase tabel 'documenten'
    
    Deze tabel slaat alle documenten op die geüpload worden via de documenten pagina.
    Document types: Aankoopfactuur, Keuringstatus, Verkoopfactuur, Veiligheidsfiche
    
    Als type = 'Veiligheidsfiche', dan is material_id NULL (niet gelinked aan materiaal)
    Als type != 'Veiligheidsfiche', dan is material_id verplicht (gelinked aan materiaal)
    
    Kolommen in Supabase:
    id, created_at, document_type, file_path, file_name, file_size,
    material_id, uploaded_by, user_id, note
    """
    __tablename__ = "documenten"

    id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    
    document_type = db.Column("document_type", db.String, nullable=False)
    file_path = db.Column("file_path", db.Text, nullable=False)
    file_name = db.Column("file_name", db.Text, nullable=False)
    file_size = db.Column("file_size", db.BigInteger, nullable=True)
    
    material_id = db.Column(
        db.BigInteger,
        db.ForeignKey("materials.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    uploaded_by = db.Column("uploaded_by", db.String, nullable=True)
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("Gebruiker.gebruiker_id", ondelete="SET NULL"),
        nullable=True,
    )
    
    note = db.Column("note", db.Text, nullable=True)
    
    # Relaties
    material = db.relationship("Material", backref="documenten")
    user = db.relationship("Gebruiker", backref="documenten")
