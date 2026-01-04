#!/usr/bin/env python3
"""Add location column to rental_averages table."""
import sqlite3
import os

def migrate():
    db_path = os.path.join(os.path.dirname(__file__), 'instance', 'properties.db')

    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        print("Run the app first to create the database, then run this script.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check existing columns in rental_averages table
    cursor.execute("PRAGMA table_info(rental_averages)")
    columns = [col[1] for col in cursor.fetchall()]

    changes_made = False

    # Add location column if not exists
    if 'location' not in columns:
        print("Adding 'location' column to rental_averages table...")
        cursor.execute("ALTER TABLE rental_averages ADD COLUMN location VARCHAR(100) DEFAULT 'All'")
        changes_made = True

        # Update existing rows to have location 'All'
        cursor.execute("UPDATE rental_averages SET location = 'All' WHERE location IS NULL")
        print("Updated existing records with location='All'")
    else:
        print("'location' column already exists in rental_averages table")

    # Check if there's a unique constraint on just bedrooms that we need to handle
    # SQLite doesn't support dropping constraints, so we need to recreate the table
    # For now, we'll just clear the old data and let it regenerate
    cursor.execute("SELECT COUNT(*) FROM rental_averages WHERE location = 'All' OR location IS NULL")
    count = cursor.fetchone()[0]

    if count > 0 and changes_made:
        print(f"\nNote: {count} existing rental average records found.")
        print("These will be updated with location-specific data on next scrape.")
        print("Run the scraper to refresh rental averages with location support.")

    if changes_made:
        conn.commit()
        print("\nMigration completed successfully!")
    else:
        print("\nNo changes needed - database is already up to date.")

    conn.close()

if __name__ == '__main__':
    migrate()
