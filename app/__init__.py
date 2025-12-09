from flask import Flask, g
from .models import db
from .config import Config
from .helpers import load_current_user

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    # Register blueprints
    from .blueprints import auth
    app.register_blueprint(auth.auth_bp)

    # Before request: load current user
    @app.before_request
    def before_request():
        load_current_user()

    # Context processor: make current_user available in templates
    @app.context_processor
    def inject_user():
        return {"current_user": g.user}

    with app.app_context():
        db.create_all()  # Create sql tables for our data models

    return app