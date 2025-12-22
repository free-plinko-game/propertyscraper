"""Configuration for the Oldham Property Investment Dashboard."""
import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'instance', 'properties.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Scraper settings
    SCRAPE_COOLDOWN_HOURS = 24
    MAX_PROPERTIES_PER_SCRAPE = 50
    SCRAPE_DELAY_MIN = 3  # seconds
    SCRAPE_DELAY_MAX = 7  # seconds

    # Location settings
    LOCATION = "Oldham, Greater Manchester"
    LOCATION_AREAS = [
        "Oldham",
        "Chadderton",
        "Failsworth",
        "Royton",
        "Shaw",
        "Lees",
        "Saddleworth",
        "Uppermill",
        "Hollinwood",
        "Crompton",
        "Greenfield",
        "Delph"
    ]

    # BTL Calculator defaults
    DEFAULT_DEPOSIT_PERCENT = 25
    DEFAULT_INTEREST_RATE = 5.5
    DEFAULT_MORTGAGE_TERM_YEARS = 25


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
