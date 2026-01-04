#!/usr/bin/env python3
"""Add latitude/longitude columns to properties table."""
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

    # Check existing columns in properties table
    cursor.execute("PRAGMA table_info(properties)")
    columns = [col[1] for col in cursor.fetchall()]

    changes_made = False

    # Add latitude column if not exists
    if 'latitude' not in columns:
        print("Adding 'latitude' column to properties table...")
        cursor.execute("ALTER TABLE properties ADD COLUMN latitude FLOAT")
        changes_made = True
    else:
        print("'latitude' column already exists")

    # Add longitude column if not exists
    if 'longitude' not in columns:
        print("Adding 'longitude' column to properties table...")
        cursor.execute("ALTER TABLE properties ADD COLUMN longitude FLOAT")
        changes_made = True
    else:
        print("'longitude' column already exists")

    if changes_made:
        conn.commit()
        print("\nMigration completed successfully!")
        print("Run 'python geocode_properties.py' to geocode existing properties.")
    else:
        print("\nNo changes needed - database is already up to date.")

    conn.close()

if __name__ == '__main__':
    migrate()
