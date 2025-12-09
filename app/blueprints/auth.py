"""
Authentication blueprint - handles login, signup, logout
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import db, Gebruiker
from werkzeug.security import generate_password_hash, check_password_hash
from helpers import login_required

auth_bp = Blueprint('auth', __name__)


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        naam = (request.form.get("naam") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        functie = (request.form.get("functie") or "").strip()
        password = (request.form.get("password") or "").strip()

        if not email or not password:
            flash("E-mail en wachtwoord zijn verplicht.", "danger")
            return render_template("auth_signup.html")

        # bestaat al in Supabase?
        if Gebruiker.query.filter_by(Email=email).first():
            flash("E-mail bestaat al. Log in a.u.b.", "warning")
            return redirect(url_for("auth.login", email=email))

        pw_hash = generate_password_hash(password)

        new_user = Gebruiker(
            Naam=naam or None,
            Email=email,
            Functie=functie or None,
            password_hash=pw_hash,
        )
        db.session.add(new_user)
        db.session.commit()

        session["user_email"] = email
        flash("Account aangemaakt en ingelogd.", "success")
        return redirect(url_for("dashboard.dashboard"))

    # GET
    return render_template("auth_signup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    prefill_email = request.args.get("email", "")
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()

        if not email or not password:
            flash("E-mail en wachtwoord zijn verplicht.", "danger")
            return render_template("auth_login.html", prefill_email=prefill_email)

        user = Gebruiker.query.filter_by(Email=email).first()
        if not user or not user.password_hash:
            flash("Geen account gevonden. Registreer je even.", "info")
            return redirect(url_for("auth.signup", email=email))

        if not check_password_hash(user.password_hash, password):
            flash("Onjuist wachtwoord.", "danger")
            return render_template("auth_login.html", prefill_email=email)

        session["user_email"] = email
        flash("Je bent ingelogd.", "success")
        next_url = request.args.get("next")
        return redirect(next_url or url_for("dashboard.dashboard"))

    # GET
    return render_template("auth_login.html", prefill_email=prefill_email)


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Je bent uitgelogd.", "info")
    return redirect(url_for("auth.login"))

