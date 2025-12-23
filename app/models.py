"""Database models for the property investment dashboard."""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json

db = SQLAlchemy()


class Property(db.Model):
    """Property listing model (both sales and rentals)."""
    __tablename__ = 'properties'

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(50), nullable=False)  # 'rightmove' or 'zoopla'
    source_id = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(500), nullable=False)

    price = db.Column(db.Integer, nullable=False)  # in GBP
    address = db.Column(db.String(500), nullable=False)
    postcode = db.Column(db.String(20))
    area = db.Column(db.String(100))  # e.g., "Chadderton", "Shaw"
    search_location = db.Column(db.String(100), default='Oldham')  # The location that was searched

    bedrooms = db.Column(db.Integer)
    bathrooms = db.Column(db.Integer)
    property_type = db.Column(db.String(50))  # terrace/semi/detached/flat

    # Geolocation
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    description = db.Column(db.Text)
    _image_urls = db.Column('image_urls', db.Text)  # JSON encoded list
    listing_date = db.Column(db.Date)

    is_rental = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Unique constraint on source + source_id
    __table_args__ = (
        db.UniqueConstraint('source', 'source_id', name='unique_source_property'),
    )

    @property
    def image_urls(self):
        """Get image URLs as a list."""
        if self._image_urls:
            return json.loads(self._image_urls)
        return []

    @image_urls.setter
    def image_urls(self, value):
        """Set image URLs from a list."""
        if value:
            self._image_urls = json.dumps(value)
        else:
            self._image_urls = None

    @property
    def main_image(self):
        """Get the main (first) image URL."""
        urls = self.image_urls
        return urls[0] if urls else None

    def to_dict(self):
        """Convert property to dictionary."""
        return {
            'id': self.id,
            'source': self.source,
            'source_id': self.source_id,
            'url': self.url,
            'price': self.price,
            'address': self.address,
            'postcode': self.postcode,
            'area': self.area,
            'search_location': self.search_location,
            'bedrooms': self.bedrooms,
            'bathrooms': self.bathrooms,
            'property_type': self.property_type,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'description': self.description,
            'image_urls': self.image_urls,
            'main_image': self.main_image,
            'listing_date': self.listing_date.isoformat() if self.listing_date else None,
            'is_rental': self.is_rental,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class User(UserMixin, db.Model):
    """User model for authentication."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    saved_properties = db.relationship('SavedProperty', backref='user', lazy='dynamic',
                                       cascade='all, delete-orphan')

    def set_password(self, password):
        """Hash and set the password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check if the password matches."""
        return check_password_hash(self.password_hash, password)


class SavedProperty(db.Model):
    """User's saved properties."""
    __tablename__ = 'saved_properties'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    property = db.relationship('Property', backref='saved_by')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'property_id', name='unique_user_property'),
    )

    def to_dict(self):
        """Convert to dictionary."""
        return {
            'id': self.id,
            'property_id': self.property_id,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'property': self.property.to_dict() if self.property else None
        }


class ScrapeLog(db.Model):
    """Log of scraping runs."""
    __tablename__ = 'scrape_logs'

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(50), nullable=False)  # 'rightmove', 'zoopla', or 'all'
    scrape_type = db.Column(db.String(20))  # 'sale' or 'rent'
    location = db.Column(db.String(100), default='Oldham')  # The location searched
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    properties_found = db.Column(db.Integer, default=0)
    properties_new = db.Column(db.Integer, default=0)
    properties_updated = db.Column(db.Integer, default=0)
    errors = db.Column(db.Text)
    status = db.Column(db.String(20), default='running')  # running, completed, failed

    def to_dict(self):
        """Convert to dictionary."""
        return {
            'id': self.id,
            'source': self.source,
            'scrape_type': self.scrape_type,
            'location': self.location,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'properties_found': self.properties_found,
            'properties_new': self.properties_new,
            'properties_updated': self.properties_updated,
            'errors': self.errors,
            'status': self.status
        }


class RentalAverage(db.Model):
    """Cached rental averages by bedroom count and location."""
    __tablename__ = 'rental_averages'

    id = db.Column(db.Integer, primary_key=True)
    bedrooms = db.Column(db.Integer, nullable=False)
    location = db.Column(db.String(100), nullable=False, default='All')  # search_location or 'All' for global
    average_rent = db.Column(db.Float, nullable=False)
    sample_count = db.Column(db.Integer, default=0)
    min_rent = db.Column(db.Integer)
    max_rent = db.Column(db.Integer)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert to dictionary."""
        return {
            'bedrooms': self.bedrooms,
            'location': self.location,
            'average_rent': round(self.average_rent, 2),
            'sample_count': self.sample_count,
            'min_rent': self.min_rent,
            'max_rent': self.max_rent,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
