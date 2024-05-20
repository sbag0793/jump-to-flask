from flask import Flask


def create_app():
    app = Flask(__name__)

    # Register blueprint
    from .views import main_views
    app.register_blueprint(main_views.bp)

    return app