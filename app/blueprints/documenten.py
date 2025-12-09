from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from helpers import login_required
from constants import DOCUMENT_TYPES


documenten_bp = Blueprint("documenten", __name__, url_prefix="/documenten")


@documenten_bp.route("/", methods=["GET"])
@login_required
def documenten():
    """Render het documentenoverzicht (placeholder data)."""
    search_query = request.args.get("q", "")
    selected_type = request.args.get("type", "alle")

    # Use document types from constants (also available via context processor)
    documents = []
    all_materials = []
    material_types_list = []

    return render_template(
        "documenten.html",
        search_query=search_query,
        selected_type=selected_type,
        document_types=DOCUMENT_TYPES,
        documents=documents,
        all_materials=all_materials,
        material_types_list=material_types_list,
    )


@documenten_bp.route("/upload", methods=["POST"])
@login_required
def documenten_upload():
    """Placeholder upload handler."""
    flash("Document uploaden is nog niet geïmplementeerd.", "warning")
    return redirect(url_for("documenten.documenten"))


@documenten_bp.record_once
def _register_plain_endpoint(state):
    """Expose alias zodat url_for('documenten') blijft werken."""
    state.app.add_url_rule("/documenten", "documenten", documenten)
