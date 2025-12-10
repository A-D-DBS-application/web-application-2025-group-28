from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy.orm import relationship

db = SQLAlchemy()


class Gebruiker(db.Model):
    __tablename__ = "gebruikers"

    gebruiker_id = db.Column(db.BigInteger, primary_key=True)
    aangemaakt_op = db.Column("aangemaakt_op", db.DateTime(timezone=True), default=datetime.utcnow)

    naam = db.Column("naam", db.String)
    email = db.Column("email", db.String, unique=True, nullable=False)
    functie = db.Column("functie", db.String)

    werf_id = db.Column(
        "werf_id",
        db.BigInteger,
        db.ForeignKey("werven.project_id", ondelete="SET NULL"),
        nullable=True
    )

    telefoonnummer = db.Column("telefoonnummer", db.Numeric, nullable=True)
    wachtwoord_hash = db.Column("wachtwoord_hash", db.String, nullable=True)

    # Admin status voor beheerfuncties
    is_admin = db.Column(db.Boolean, default=False)
    
    # Relationships
    project = db.relationship("Project", backref="gebruikers", foreign_keys=[werf_id])
    
    # Backward compatibility properties
    @property
    def created_at(self):
        return self.aangemaakt_op
    
    @created_at.setter
    def created_at(self, value):
        self.aangemaakt_op = value
    
    @property
    def Naam(self):
        return self.naam
    
    @Naam.setter
    def Naam(self, value):
        self.naam = value
    
    @property
    def Email(self):
        return self.email
    
    @Email.setter
    def Email(self, value):
        self.email = value
    
    @property
    def Functie(self):
        return self.functie
    
    @Functie.setter
    def Functie(self, value):
        self.functie = value
    
    @property
    def project_id(self):
        return self.werf_id
    
    @project_id.setter
    def project_id(self, value):
        self.werf_id = value
    
    @property
    def password_hash(self):
        return self.wachtwoord_hash
    
    @password_hash.setter
    def password_hash(self, value):
        self.wachtwoord_hash = value


class Project(db.Model):
    """
    Werf / project.
    Map naar Supabase tabel 'werven'.
    """
    __tablename__ = "werven"

    id = db.Column("project_id", db.BigInteger, primary_key=True)
    aangemaakt_op = db.Column("aangemaakt_op", db.DateTime(timezone=True), default=datetime.utcnow)

    name = db.Column("naam", db.String, nullable=True)
    address = db.Column("adres", db.String, nullable=True)

    start_date = db.Column("start_datum", db.Date, nullable=True)
    end_date = db.Column("eind_datum", db.Date, nullable=True)
    type = db.Column("type", db.String, nullable=True)

    image_url = db.Column("afbeelding_url", db.Text, nullable=True)
    note = db.Column("opmerking", db.Text, nullable=True)
    is_deleted = db.Column("is_verwijderd", db.Boolean, default=False)
    
    # Backward compatibility properties
    @property
    def created_at(self):
        return self.aangemaakt_op
    
    @created_at.setter
    def created_at(self, value):
        self.aangemaakt_op = value


class Material(db.Model):
    __tablename__ = "materialen"

    id = db.Column(db.BigInteger, primary_key=True)
    aangemaakt_op = db.Column("aangemaakt_op", db.DateTime(timezone=True), default=datetime.utcnow)

    name = db.Column("naam", db.String)
    status = db.Column("status", db.String)
    
    # Foreign key to Keuringstatus
    keuring_id = db.Column(
        "keuring_id",
        db.BigInteger,
        db.ForeignKey("keuring_status.id", ondelete="SET NULL"),
        nullable=True
    )

    # Foreign key to Project (werven)
    werf_id = db.Column(
        "werf_id",
        db.BigInteger,
        db.ForeignKey("werven.project_id", ondelete="SET NULL"),
        nullable=True
    )

    serial = db.Column("serienummer", db.String, unique=True, nullable=False)
    
    # Foreign key to MaterialType
    material_type_id = db.Column(
        "materiaal_type_id",
        db.BigInteger,
        db.ForeignKey("materiaal_types.id", ondelete="SET NULL"),
        nullable=True
    )
    type = db.Column("type", db.String)              # "type" (legacy string field, kept for backward compatibility)

    purchase_date = db.Column("aankoop_datum", db.Date, nullable=True)
    assigned_to = db.Column("toegewezen_aan", db.String, nullable=True)  # Denormalized user name (not FK - for display/historical purposes)
    site = db.Column("locatie", db.String, nullable=True)
    note = db.Column("opmerking", db.String, nullable=True)

    documentation_path = db.Column("documentatie_pad", db.Text, nullable=True)

    nummer_op_materieel = db.Column("nummer_op_materieel", db.String, nullable=True)
    inspection_status = db.Column("keuring_status", db.String, nullable=True)
    laatste_keuring = db.Column("laatste_keuring", db.Date, nullable=True)
    is_deleted = db.Column("is_verwijderd", db.Boolean, default=False, nullable=False)

    # Relationships with optimized lazy loading
    project = db.relationship(
        "Project",
        backref="materials",
        foreign_keys=[werf_id],
        lazy="select",
    )
    
    # Relationship to Keuringstatus via keuring_id
    keuring = db.relationship(
        "Keuringstatus",
        backref="materials",
        foreign_keys=[keuring_id],
        uselist=False,  # One-to-one relationship
        lazy="select",
    )
    
    # Relationship to MaterialType via material_type_id
    material_type = db.relationship(
        "MaterialType",
        backref="materials",
        foreign_keys=[material_type_id],
        lazy="select",
    )
    
    # Backward compatibility properties
    @property
    def created_at(self):
        return self.aangemaakt_op
    
    @created_at.setter
    def created_at(self, value):
        self.aangemaakt_op = value
    
    @created_at.setter
    def created_at(self, value):
        self.aangemaakt_op = value
    
    @property
    def project_id(self):
        return self.werf_id  # Alias voor werf_id
    
    @project_id.setter
    def project_id(self, value):
        self.werf_id = value


class Activity(db.Model):
    """
    Map naar Supabase tabel 'activiteiten_log'
    """
    __tablename__ = "activiteiten_log"

    id = db.Column(db.BigInteger, primary_key=True)
    aangemaakt_op = db.Column("aangemaakt_op", db.DateTime(timezone=True), default=datetime.utcnow)
    action = db.Column("actie", db.String)
    name = db.Column("naam", db.String)
    serial = db.Column("serienummer", db.String)
    user_name = db.Column("gebruiker_naam", db.String)  # Denormalized user name (for historical reference)
    
    # Foreign key to Gebruiker - links activity to user
    user_id = db.Column(
        "gebruiker_id",
        db.BigInteger,
        db.ForeignKey("gebruikers.gebruiker_id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Relationship to Gebruiker
    user = db.relationship(
        "Gebruiker",
        backref="activities",
        foreign_keys=[user_id],
        lazy="select",
    )
    
    # Backward compatibility properties
    @property
    def created_at(self):
        return self.aangemaakt_op
    
    @created_at.setter
    def created_at(self, value):
        self.aangemaakt_op = value


class MaterialUsage(db.Model):
    """
    Map naar Supabase tabel 'materiaal_gebruik'
    """
    __tablename__ = "materiaal_gebruik"

    id = db.Column(db.BigInteger, primary_key=True)

    material_id = db.Column(
        "materiaal_id",
        db.BigInteger,
        db.ForeignKey("materialen.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        "gebruiker_id",
        db.BigInteger,
        db.ForeignKey("gebruikers.gebruiker_id", ondelete="SET NULL"),
        nullable=True,
    )

    # Foreign key to Project (werven)
    project_id = db.Column(
        "werf_id",
        db.BigInteger,
        db.ForeignKey("werven.project_id", ondelete="SET NULL"),
        nullable=True
    )

    site = db.Column("locatie", db.Text, nullable=True)
    note = db.Column("opmerking", db.Text, nullable=True)
    start_time = db.Column("start_tijd", db.DateTime(timezone=True), default=datetime.utcnow)
    end_time = db.Column("eind_tijd", db.DateTime(timezone=True), nullable=True)
    is_active = db.Column("is_actief", db.Boolean, default=True)
    used_by = db.Column("gebruikt_door", db.Text, nullable=True)

    # Relationships with optimized lazy loading
    material = db.relationship("Material", backref="usages", lazy="select")
    user = db.relationship("Gebruiker", backref="usages", lazy="select")

    # Relationship to Project
    project = db.relationship(
        "Project",
        backref="material_usages",
        lazy="select",
    )
    
    # Backward compatibility properties
    @property
    def materiaal_id(self):
        return self.material_id
    
    @property
    def gebruiker_id(self):
        return self.user_id


class Keuringstatus(db.Model):
    """
    Map naar Supabase tabel 'keuring_status'
    """
    __tablename__ = "keuring_status"

    id = db.Column(db.BigInteger, primary_key=True)
    aangemaakt_op = db.Column("aangemaakt_op", db.DateTime(timezone=True), default=datetime.utcnow)
    
    laatste_controle = db.Column("laatste_controle", db.Date, nullable=True)
    volgende_controle = db.Column("volgende_controle", db.Date, nullable=True)
    serienummer = db.Column("serienummer", db.String, nullable=True)
    uitgevoerd_door = db.Column("uitgevoerd_door", db.String, nullable=True)
    opmerkingen = db.Column("opmerkingen", db.Text, nullable=True)
    updated_by = db.Column("updated_by", db.BigInteger, nullable=True)
    
    # Relationships
    # Note: Material relationship is via keuring_id FK in Material model
    # This is a reverse relationship - materials reference this keuring
    
    # Backward compatibility properties
    @property
    def created_at(self):
        return self.aangemaakt_op
    
    @created_at.setter
    def created_at(self, value):
        self.aangemaakt_op = value


class KeuringHistoriek(db.Model):
    """
    Map naar Supabase tabel 'keuring_historiek'
    
    Deze tabel slaat alle uitgevoerde keuringen op voor historiek.
    Elke keer dat een keuring wordt uitgevoerd, wordt hier een record aangemaakt.
    """
    __tablename__ = "keuring_historiek"

    id = db.Column(db.BigInteger, primary_key=True)
    aangemaakt_op = db.Column("aangemaakt_op", db.DateTime(timezone=True), default=datetime.utcnow)
    
    material_id = db.Column(
        "materiaal_id",
        db.BigInteger,
        db.ForeignKey("materialen.id", ondelete="CASCADE"),
        nullable=False,
    )
    serienummer = db.Column(db.String, nullable=False)
    
    keuring_datum = db.Column("keuring_datum", db.Date, nullable=False)
    resultaat = db.Column(db.String, nullable=False)  # 'goedgekeurd', 'afgekeurd', 'voorwaardelijk'
    uitgevoerd_door = db.Column("uitgevoerd_door", db.String, nullable=False)
    opmerkingen = db.Column("opmerkingen", db.Text, nullable=True)
    
    volgende_keuring_datum = db.Column("volgende_keuring_datum", db.Date, nullable=True)
    certificaat_path = db.Column("certificaat_pad", db.Text, nullable=True)
    
    # Relatie naar Material
    material = db.relationship("Material", backref="keuring_historiek", lazy="select")
    
    # Backward compatibility properties
    @property
    def created_at(self):
        return self.aangemaakt_op
    
    @created_at.setter
    def created_at(self, value):
        self.aangemaakt_op = value


class Document(db.Model):
    """
    Map naar Supabase tabel 'documenten'
    
    Deze tabel slaat alle documenten op die geüpload worden via de documenten pagina.
    Document types: Aankoopfactuur, Keuringstatus, Verkoopfactuur, Veiligheidsfiche
    """
    __tablename__ = "documenten"

    id = db.Column(db.BigInteger, primary_key=True)
    aangemaakt_op = db.Column("aangemaakt_op", db.DateTime(timezone=True), default=datetime.utcnow)
    
    document_type = db.Column("document_type", db.String, nullable=False)  # Document type as string (e.g., "Aankoopfactuur", "Veiligheidsfiche")
    file_path = db.Column("bestand_pad", db.Text, nullable=False)
    file_name = db.Column("bestand_naam", db.Text, nullable=False)
    file_size = db.Column("bestand_grootte", db.BigInteger, nullable=True)
    
    material_id = db.Column(
        "materiaal_id",
        db.BigInteger,
        db.ForeignKey("materialen.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Link to MaterialType (proper FK instead of string)
    # Can link to EITHER a specific Material (via material_id) OR a MaterialType (via material_type_id)
    material_type_id = db.Column(
        "materiaal_type_id",
        db.BigInteger,
        db.ForeignKey("materiaal_types.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Legacy: keep material_type as string for backward compatibility during migration
    # Can be removed after migrating existing data to material_type_id
    material_type = db.Column("materiaal_type", db.String, nullable=True)
    
    uploaded_by = db.Column("geupload_door", db.String, nullable=True)
    user_id = db.Column(
        "gebruiker_id",
        db.BigInteger,
        db.ForeignKey("gebruikers.gebruiker_id", ondelete="SET NULL"),
        nullable=True,
    )
    
    note = db.Column("opmerking", db.Text, nullable=True)
    
    # Relationships with optimized lazy loading
    material = db.relationship("Material", backref="documents", lazy="select")
    material_type_ref = db.relationship("MaterialType", backref="documents", lazy="select", foreign_keys=[material_type_id])
    user = db.relationship("Gebruiker", backref="documents", lazy="select")
    
    # Backward compatibility properties
    @property
    def created_at(self):
        return self.aangemaakt_op
    
    @created_at.setter
    def created_at(self, value):
        self.aangemaakt_op = value
    
    @property
    def linked_entity(self):
        """Return the linked entity (Material or MaterialType)"""
        if self.material_id:
            return self.material
        elif self.material_type_id:
            return self.material_type_ref
        return None
    
    @property
    def linked_entity_name(self):
        """Return the name of the linked entity"""
        if self.material_id and self.material:
            return self.material.name
        elif self.material_type_id and self.material_type_ref:
            return self.material_type_ref.name
        elif self.material_type:  # Fallback to legacy string field
            return self.material_type
        return None


class MaterialType(db.Model):
    """
    Map naar Supabase tabel 'materiaal_types'
    Referentietabel met alle mogelijke materiaal types
    """
    __tablename__ = "materiaal_types"
    
    id = db.Column(db.BigInteger, primary_key=True)
    aangemaakt_op = db.Column("aangemaakt_op", db.DateTime(timezone=True), default=datetime.utcnow)
    name = db.Column("naam", db.String, nullable=False, unique=True)  # De naam van het materiaal type (bijv. "Boormachine")
    description = db.Column("beschrijving", db.Text, nullable=True)
    inspection_validity_days = db.Column("keuring_geldigheid_dagen", db.Integer, nullable=True)
    type_image = db.Column("type_afbeelding", db.Text, nullable=True)  # Pad naar type afbeelding
    safety_sheet = db.Column("veiligheidsfiche", db.Text, nullable=True)  # Pad naar veiligheidsfiche
    
    # Relationship with Material (backref defined in Material model)
    # Materials can reference MaterialType via material_type_id FK
    
    # Backward compatibility properties
    @property
    def created_at(self):
        return self.aangemaakt_op
    
    @created_at.setter
    def created_at(self, value):
        self.aangemaakt_op = value