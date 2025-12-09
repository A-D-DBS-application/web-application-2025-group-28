"""
Shared helper functions used across multiple blueprints
"""
from flask import g, session, redirect, url_for, request
from models import db, Gebruiker, Activity
from datetime import datetime


def login_required(view):
    """Decorator to require login for a route"""
    from functools import wraps
    from flask import redirect, url_for, request, session
    
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_email") is None:
            return redirect(url_for("auth.login", next=request.path))
        
        if getattr(g, "user", None) is None:
            session.clear()
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    
    return wrapped


def load_current_user():
    """Load current user from session"""
    g.user = None
    email = session.get("user_email")
    if not email:
        return
    g.user = Gebruiker.query.filter_by(Email=email).first()


def log_activity_db(action: str, name: str, serial: str):
    """Schrijf een activiteit weg naar de activity_log tabel in Supabase."""
    user_name = None
    if getattr(g, "user", None) and g.user.Naam:
        user_name = g.user.Naam

    act = Activity(
        action=action,
        name=name or "",
        serial=serial or "",
        user_name=user_name or "Onbekend",
        created_at=datetime.utcnow(),
    )
    db.session.add(act)
    db.session.commit()

