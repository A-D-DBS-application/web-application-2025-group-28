CREATE TABLE "activiteiten_log" (
  "id" bigint PRIMARY KEY,
  "aangemaakt_op" timestamp,
  "actie" text,
  "naam" text,
  "serienummer" text,
  "gebruiker_naam" text,
  "gebruiker_id" bigint
);

CREATE TABLE "documenten" (
  "id" bigint PRIMARY KEY,
  "aangemaakt_op" timestamp,
  "document_type" varchar,
  "bestand_pad" text,
  "bestand_naam" text,
  "bestand_grootte" bigint,
  "materiaal_id" bigint,
  "materiaal_type_id" bigint,
  "materiaal_type" varchar,
  "geupload_door" varchar,
  "gebruiker_id" bigint,
  "opmerking" text
);

CREATE TABLE "gebruikers" (
  "gebruiker_id" bigint PRIMARY KEY,
  "aangemaakt_op" timestamp,
  "naam" text,
  "email" text,
  "functie" text,
  "werf_id" bigint,
  "telefoonnummer" numeric,
  "wachtwoord_hash" text,
  "is_admin" boolean
);

CREATE TABLE "keuring_historiek" (
  "id" bigint PRIMARY KEY,
  "aangemaakt_op" timestamp,
  "materiaal_id" bigint,
  "serienummer" text,
  "keuring_datum" date,
  "resultaat" text,
  "uitgevoerd_door" text,
  "opmerkingen" text,
  "volgende_keuring_datum" date,
  "certificaat_pad" text,
  "updated_by" bigint
);

CREATE TABLE "keuring_status" (
  "id" bigint PRIMARY KEY,
  "aangemaakt_op" timestamp,
  "laatste_controle" date,
  "volgende_controle" date,
  "serienummer" text,
  "uitgevoerd_door" text,
  "opmerkingen" text,
  "updated_by" bigint
);

CREATE TABLE "materiaal_gebruik" (
  "id" bigint PRIMARY KEY,
  "materiaal_id" bigint,
  "gebruiker_id" bigint,
  "locatie" text,
  "opmerking" text,
  "start_tijd" timestamp,
  "eind_tijd" timestamp,
  "is_actief" boolean,
  "gebruikt_door" text,
  "werf_id" bigint,
  "updated_by" bigint
);

CREATE TABLE "materiaal_types" (
  "id" bigint PRIMARY KEY,
  "aangemaakt_op" timestamp,
  "naam" text,
  "beschrijving" text,
  "keuring_geldigheid_dagen" int,
  "type_afbeelding" text,
  "veiligheidsfiche" text
);

CREATE TABLE "materialen" (
  "id" bigint PRIMARY KEY,
  "aangemaakt_op" timestamp,
  "naam" text,
  "status" text,
  "keuring_id" bigint,
  "werf_id" bigint,
  "serienummer" text,
  "type" text,
  "aankoop_datum" date,
  "toegewezen_aan" text,
  "locatie" text,
  "opmerking" text,
  "nummer_op_materieel" text,
  "documentatie_pad" text,
  "keuring_status" text,
  "updated_by" bigint,
  "materiaal_type_id" bigint,
  "is_verwijderd" boolean,
  "laatste_keuring" date
);

CREATE TABLE "werven" (
  "project_id" bigint PRIMARY KEY,
  "start_datum" date,
  "eind_datum" date,
  "type" text,
  "aangemaakt_op" timestamp,
  "naam" text,
  "adres" text,
  "afbeelding_url" text,
  "opmerking" text,
  "is_verwijderd" boolean,
  "updated_by" bigint
);

ALTER TABLE "activiteiten_log" ADD FOREIGN KEY ("gebruiker_id") REFERENCES "gebruikers" ("gebruiker_id");

ALTER TABLE "documenten" ADD FOREIGN KEY ("materiaal_id") REFERENCES "materialen" ("id");

ALTER TABLE "documenten" ADD FOREIGN KEY ("materiaal_type_id") REFERENCES "materiaal_types" ("id");

ALTER TABLE "documenten" ADD FOREIGN KEY ("gebruiker_id") REFERENCES "gebruikers" ("gebruiker_id");

ALTER TABLE "gebruikers" ADD FOREIGN KEY ("werf_id") REFERENCES "werven" ("project_id");

ALTER TABLE "keuring_historiek" ADD FOREIGN KEY ("materiaal_id") REFERENCES "materialen" ("id");

ALTER TABLE "keuring_historiek" ADD FOREIGN KEY ("updated_by") REFERENCES "gebruikers" ("gebruiker_id");

ALTER TABLE "keuring_status" ADD FOREIGN KEY ("updated_by") REFERENCES "gebruikers" ("gebruiker_id");

ALTER TABLE "materiaal_gebruik" ADD FOREIGN KEY ("materiaal_id") REFERENCES "materialen" ("id");

ALTER TABLE "materiaal_gebruik" ADD FOREIGN KEY ("gebruiker_id") REFERENCES "gebruikers" ("gebruiker_id");

ALTER TABLE "materiaal_gebruik" ADD FOREIGN KEY ("werf_id") REFERENCES "werven" ("project_id");

ALTER TABLE "materiaal_gebruik" ADD FOREIGN KEY ("updated_by") REFERENCES "gebruikers" ("gebruiker_id");

ALTER TABLE "materialen" ADD FOREIGN KEY ("keuring_id") REFERENCES "keuring_status" ("id");

ALTER TABLE "materialen" ADD FOREIGN KEY ("werf_id") REFERENCES "werven" ("project_id");

ALTER TABLE "materialen" ADD FOREIGN KEY ("updated_by") REFERENCES "gebruikers" ("gebruiker_id");

ALTER TABLE "materialen" ADD FOREIGN KEY ("materiaal_type_id") REFERENCES "materiaal_types" ("id");

ALTER TABLE "werven" ADD FOREIGN KEY ("updated_by") REFERENCES "gebruikers" ("gebruiker_id");
