#!/usr/bin/env python3
"""Run the Oldham Property Investment Dashboard."""
import os
from app import create_app
from app.models import db

app = create_app(os.environ.get('FLASK_CONFIG', 'development'))


@app.shell_context_processor
def make_shell_context():
    """Add useful imports to flask shell."""
    from app.models import User, Property, SavedProperty, ScrapeLog, RentalAverage
    return {
        'db': db,
        'User': User,
        'Property': Property,
        'SavedProperty': SavedProperty,
        'ScrapeLog': ScrapeLog,
        'RentalAverage': RentalAverage
    }


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
