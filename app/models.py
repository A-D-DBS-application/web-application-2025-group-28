from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy.orm import relationship

db = SQLAlchemy()


class Gebruiker(db.Model):
    __tablename__ = "Gebruiker"

    gebruiker_id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    Naam = db.Column(db.String)                      # "Naam"
    Email = db.Column(db.String, unique=True, nullable=False)  # "Email"
    Functie = db.Column(db.String)                   # "Functie"

    # na de SQL hierboven is dit BIGINT in de database
    project_id = db.Column(
        db.BigInteger,
        db.ForeignKey("Project.ProjectID"),
        nullable=True
    )

    telefoon_nummer = db.Column(db.Numeric, nullable=True)
    password_hash = db.Column(db.String, nullable=True)

    # Admin status voor beheerfuncties
    is_admin = db.Column(db.Boolean, default=False)
    
    # Relationships
    project = db.relationship("Project", backref="gebruikers", foreign_keys=[project_id])


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
    
    # Foreign key to Keuringstatus
    keuring_id = db.Column(
        "Keuring",
        db.BigInteger,
        db.ForeignKey("Keuringstatus.id", ondelete="SET NULL"),
        nullable=True
    )

    # Foreign key to Project - Project table uses "ProjectID" as column name
    project_id = db.Column(
        "project_id",
        db.BigInteger,
        db.ForeignKey("Project.ProjectID", ondelete="SET NULL"),
        nullable=True
    )

    serial = db.Column("Serienummer", db.String, unique=True, nullable=False)
    
    # Foreign key to MaterialType - materials belong to a material_type
    material_type_id = db.Column(
        "material_type_id",
        db.BigInteger,
        db.ForeignKey("material_types.id", ondelete="SET NULL"),
        nullable=True
    )
    type = db.Column("type", db.String)              # "type" (legacy string field, kept for backward compatibility)

    purchase_date = db.Column("purchase_date", db.Date, nullable=True)
    assigned_to = db.Column("assigned_to", db.String, nullable=True)  # Denormalized user name (not FK - for display/historical purposes)
    site = db.Column("site", db.String, nullable=True)
    note = db.Column("note", db.String, nullable=True)

    documentation_path = db.Column("documentation_path", db.Text, nullable=True)
    safety_sheet_path = db.Column("safety_sheet_path", db.Text, nullable=True)

    nummer_op_materieel = db.Column("nummer_op_materieel", db.String, nullable=True)
    inspection_status = db.Column("inspection_status", db.String, nullable=True)

    # Relationships with optimized lazy loading
    # Using "select" lazy loading (default) - loads on access, but can be overridden with eager loading
    project = db.relationship(
        "Project",
        backref="materials",
        foreign_keys=[project_id],
        lazy="select",  # Explicit lazy loading strategy
    )
    
    # Relationship to Keuringstatus via keuring_id
    keuring = db.relationship(
        "Keuringstatus",
        backref="materials",
        foreign_keys=[keuring_id],
        uselist=False,  # One-to-one relationship
        lazy="select",  # Explicit lazy loading strategy
    )
    
    # Relationship to MaterialType via material_type_id
    material_type = db.relationship(
        "MaterialType",
        backref="materials",
        foreign_keys=[material_type_id],
        lazy="select",
    )


class Activity(db.Model):
    """
    Map naar Supabase tabel 'activity_log'
    kolommen: id, created_at, action, name, serial, user_name, user_id
    """
    __tablename__ = "activity_log"

    id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    action = db.Column(db.String)
    name = db.Column(db.String)
    serial = db.Column(db.String)
    user_name = db.Column(db.String)  # Denormalized user name (for historical reference)
    
    # Foreign key to Gebruiker - links activity to user
    user_id = db.Column(
        "user_id",
        db.BigInteger,
        db.ForeignKey("Gebruiker.gebruiker_id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Relationship to Gebruiker
    user = db.relationship(
        "Gebruiker",
        backref="activities",
        foreign_keys=[user_id],
        lazy="select",
    )


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

    # Foreign key to Project - Project table uses "ProjectID" as column name
    project_id = db.Column(
        "project_id",
        db.BigInteger,
        db.ForeignKey("Project.ProjectID", ondelete="SET NULL"),
        nullable=True
    )

    site = db.Column(db.Text, nullable=True)
    note = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    end_time = db.Column(db.DateTime(timezone=True), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    used_by = db.Column(db.Text, nullable=True)

    # Relationships with optimized lazy loading
    material = db.relationship("Material", backref="usages", lazy="select")
    user = db.relationship("Gebruiker", backref="usages", lazy="select")

    # Relationship to Project - now with proper ForeignKey, no need for primaryjoin
    project = db.relationship(
        "Project",
        backref="material_usages",
        lazy="select",
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
    
    # Relationships
    # Note: Material relationship is via keuring_id FK in Material model
    # This is a reverse relationship - materials reference this keuring


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
    material = db.relationship("Material", backref="keuring_historiek", lazy="select")


class Document(db.Model):
    """
    Map naar Supabase tabel 'documenten'
    
    Deze tabel slaat alle documenten op die geüpload worden via de documenten pagina.
    Document types: Aankoopfactuur, Keuringstatus, Verkoopfactuur, Veiligheidsfiche
    
    Als type = 'Veiligheidsfiche', dan is material_id NULL maar material_type verplicht (gelinked aan materiaal TYPE)
    Als type != 'Veiligheidsfiche', dan is material_id verplicht (gelinked aan specifiek materiaal)
    
    Kolommen in Supabase:
    id, created_at, document_type, file_path, file_name, file_size,
    material_id, material_type, uploaded_by, user_id, note
    """
    __tablename__ = "documenten"

    id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    
    document_type = db.Column("document_type", db.String, nullable=False)  # Legacy: behouden voor backward compatibility
    document_type_id = db.Column(
        db.BigInteger,
        db.ForeignKey("document_types.id", ondelete="SET NULL"),
        nullable=True,
    )
    file_path = db.Column("file_path", db.Text, nullable=False)
    file_name = db.Column("file_name", db.Text, nullable=False)
    file_size = db.Column("file_size", db.BigInteger, nullable=True)
    
    material_id = db.Column(
        db.BigInteger,
        db.ForeignKey("materials.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # material_type kolom - voeg deze toe aan database met: ALTER TABLE documenten ADD COLUMN material_type TEXT;
    material_type = db.Column("material_type", db.String, nullable=True)
    
    uploaded_by = db.Column("uploaded_by", db.String, nullable=True)
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("Gebruiker.gebruiker_id", ondelete="SET NULL"),
        nullable=True,
    )
    
    note = db.Column("note", db.Text, nullable=True)
    
    # Relationships with optimized lazy loading
    material = db.relationship("Material", backref="documenten", lazy="select")
    user = db.relationship("Gebruiker", backref="documenten", lazy="select")
    document_type_ref = db.relationship(
        "DocumentType",
        backref="documents",
        foreign_keys=[document_type_id],
        lazy="select",
    )


class MaterialType(db.Model):
    """
    Map naar Supabase tabel 'material_types'
    Referentietabel met alle mogelijke materiaal types
    Kolommen: id, created_at, name, description, inspection_validity_days, type_image, safety_sheet
    """
    __tablename__ = "material_types"
    
    id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    name = db.Column(db.String, nullable=False, unique=True)  # De naam van het materiaal type (bijv. "Boormachine")
    description = db.Column(db.Text, nullable=True)
    inspection_validity_days = db.Column(db.Integer, nullable=True)
    type_image = db.Column(db.Text, nullable=True)  # Pad naar type afbeelding
    safety_sheet = db.Column(db.Text, nullable=True)  # Pad naar veiligheidsfiche
    
    # Relationship with Material (backref defined in Material model)
    # Materials can reference MaterialType via material_type_id FK


class DocumentType(db.Model):
    """
    Referentietabel voor document types
    Kolommen: id, created_at, name, description, is_active
    """
    __tablename__ = "document_types"
    
    id = db.Column(db.BigInteger, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    name = db.Column(db.String, nullable=False, unique=True)  # Bijv. "Aankoopfactuur", "Veiligheidsfiche"
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Relationship with Document (already defined in Document model)
    # documents backref is defined in Document.document_type_ref