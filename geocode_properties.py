#!/usr/bin/env python3
"""Geocode existing properties that don't have coordinates."""
import sys
import os

# Add the app to the path
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.services.geocoding import geocode_all_properties
from app.models import Property


def main():
    app = create_app()

    with app.app_context():
        # Count properties needing geocoding
        total_needing = Property.query.filter(
            (Property.latitude.is_(None)) | (Property.longitude.is_(None))
        ).count()

        if total_needing == 0:
            print("All properties already have coordinates!")
            return

        print(f"Found {total_needing} properties needing geocoding...")
        print("Note: Geocoding is rate-limited to 1 request/second")
        print()

        processed = 0
        while processed < total_needing:
            stats = geocode_all_properties(batch_size=50)

            if stats['total'] == 0:
                break

            processed += stats['total']
            print(f"Batch complete: {stats['success']} success, {stats['failed']} failed")
            print(f"Progress: {processed}/{total_needing}")

        print()
        print("Geocoding complete!")

        # Show final stats
        geocoded = Property.query.filter(
            Property.latitude.isnot(None),
            Property.longitude.isnot(None)
        ).count()

        total = Property.query.count()
        print(f"Properties with coordinates: {geocoded}/{total}")


if __name__ == '__main__':
    main()
