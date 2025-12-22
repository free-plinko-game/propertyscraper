"""Flask application factory for the Oldham Property Investment Dashboard."""
import os
import click
from flask import Flask
from flask_login import LoginManager
from config import config

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'


def create_app(config_name=None):
    """Create and configure the Flask application."""
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Ensure instance folder exists
    os.makedirs(os.path.join(app.root_path, '..', 'instance'), exist_ok=True)

    # Initialize extensions
    from app.models import db
    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))

    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.api import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(api_bp, url_prefix='/api')

    # Register CLI commands
    register_cli_commands(app)

    return app


def register_cli_commands(app):
    """Register Flask CLI commands."""

    @app.cli.command('init-db')
    def init_db():
        """Initialize the database."""
        from app.models import db
        db.create_all()
        click.echo('Database initialized.')

    @app.cli.command('scrape-properties')
    @click.option('--force', is_flag=True, help='Ignore 24-hour cooldown')
    @click.option('--source', type=click.Choice(['all', 'rightmove', 'zoopla']),
                  default='all', help='Which source to scrape')
    @click.option('--type', 'scrape_type', type=click.Choice(['all', 'sale', 'rent']),
                  default='all', help='Type of listings to scrape')
    def scrape_properties(force, source, scrape_type):
        """Run the property scraper."""
        from app.scraper.runner import run_scraper
        run_scraper(force=force, source=source, scrape_type=scrape_type)

    @app.cli.command('update-rental-averages')
    def update_rental_averages():
        """Update rental average calculations."""
        from app.services.rental_analysis import update_rental_averages
        update_rental_averages()
        click.echo('Rental averages updated.')
