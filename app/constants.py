"""
Constants for the application - centralized option lists and configuration values.
This ensures consistency across templates, routes, and JavaScript.
"""

# Material Inspection Status Options
INSPECTION_STATUSES = {
    "goedgekeurd": {
        "value": "goedgekeurd",
        "label": "Goedgekeurd",
        "badge_class": "badge-outline-success",
        "badge_style": "background-color: white; color: #212529; border: 1px solid #198754;",
        "bootstrap_class": "bg-success"
    },
    "afgekeurd": {
        "value": "afgekeurd",
        "label": "Afgekeurd",
        "badge_class": "badge-outline-danger",
        "badge_style": "background-color: white; color: #212529; border: 1px solid #dc3545;",
        "bootstrap_class": "bg-danger"
    },
    "keuring verlopen": {
        "value": "keuring verlopen",
        "label": "Keuring verlopen",
        "badge_class": "badge-outline-warning",
        "badge_style": "background-color: white; color: #212529; border: 1px solid #ffc107;",
        "bootstrap_class": "bg-warning"
    },
    "keuring gepland": {
        "value": "keuring gepland",
        "label": "Keuring gepland",
        "badge_class": "badge-outline-purple",
        "badge_style": "background-color: white; color: #212529; border: 1px solid #a855f7;",
        "bootstrap_class": "bg-purple"
    },
    "onder voorbehoud": {
        "value": "onder voorbehoud",
        "label": "Onder voorbehoud",
        "badge_class": "badge-outline-warning",
        "badge_style": "background-color: white; color: #212529; border: 1px solid #ffc107;",
        "bootstrap_class": "bg-warning"
    }
}

# Keuring Status Options for form dropdown (used in "Nieuw Materiaal" modal)
# NOTE: "keuring gepland" is verwijderd - te complex voor create flow
KEURING_STATUS_OPTIONS = {
    "goedgekeurd": {
        "value": "goedgekeurd",
        "label": "Goedgekeurd"
    },
    "afgekeurd": {
        "value": "afgekeurd",
        "label": "Afgekeurd"
    },
    "onder voorbehoud": {
        "value": "onder voorbehoud",
        "label": "Onder voorbehoud"
    }
}

# Material Usage Status Options
USAGE_STATUSES = {
    "in gebruik": {
        "value": "in gebruik",
        "label": "In gebruik",
        "badge_class": "bg-success"
    },
    "niet in gebruik": {
        "value": "niet in gebruik",
        "label": "Niet in gebruik",
        "badge_class": "bg-danger"
    }
}

# Keuring Result Options
KEURING_RESULTATEN = {
    "goedgekeurd": {
        "value": "goedgekeurd",
        "label": "✓ Goedgekeurd",
        "badge_class": "bg-success"
    },
    "afgekeurd": {
        "value": "afgekeurd",
        "label": "✗ Afgekeurd",
        "badge_class": "bg-danger"
    },
    "voorwaardelijk": {
        "value": "voorwaardelijk",
        "label": "⚠ Voorwaardelijk",
        "badge_class": "bg-warning"
    }
}

# Default inspection status
DEFAULT_INSPECTION_STATUS = "goedgekeurd"

# Valid inspection statuses list (for validation)
VALID_INSPECTION_STATUSES = list(INSPECTION_STATUSES.keys())

# Valid usage statuses list
VALID_USAGE_STATUSES = list(USAGE_STATUSES.keys())

# Valid keuring resultaten list
VALID_KEURING_RESULTATEN = list(KEURING_RESULTATEN.keys())

# Keuring Status Filter Options (for dropdowns in templates)
KEURING_STATUS_FILTERS = {
    "te_laat": {
        "value": "te_laat",
        "label": "Te laat"
    },
    "gepland": {
        "value": "gepland",
        "label": "Gepland"
    },
    "goedgekeurd": {
        "value": "goedgekeurd",
        "label": "Goedgekeurd"
    },
    "afgekeurd": {
        "value": "afgekeurd",
        "label": "Afgekeurd"
    }
}

# Valid keuring status filter values
VALID_KEURING_STATUS_FILTERS = list(KEURING_STATUS_FILTERS.keys())

# Period Filter Options (for geschiedenis page)
PERIOD_FILTERS = {
    "all": {"value": "all", "label": "Alle tijd"},
    "today": {"value": "today", "label": "Vandaag"},
    "week": {"value": "week", "label": "Afgelopen week"},
    "month": {"value": "month", "label": "Afgelopen maand"}
}

# Document Types
DOCUMENT_TYPES = [
    "Aankoopfactuur",
    "Keuringstatus",
    "Veiligheidsfiche",
    "Verkoopfactuur"
]


