#!/usr/bin/env python3
"""Add search_location columns to existing database."""
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
    property_columns = [col[1] for col in cursor.fetchall()]

    # Check existing columns in scrape_logs table
    cursor.execute("PRAGMA table_info(scrape_logs)")
    log_columns = [col[1] for col in cursor.fetchall()]

    changes_made = False

    # Add search_location to properties if not exists
    if 'search_location' not in property_columns:
        print("Adding 'search_location' column to properties table...")
        cursor.execute("ALTER TABLE properties ADD COLUMN search_location VARCHAR(100) DEFAULT 'Oldham'")
        changes_made = True
    else:
        print("'search_location' column already exists in properties table")

    # Add location to scrape_logs if not exists
    if 'location' not in log_columns:
        print("Adding 'location' column to scrape_logs table...")
        cursor.execute("ALTER TABLE scrape_logs ADD COLUMN location VARCHAR(100) DEFAULT 'Oldham'")
        changes_made = True
    else:
        print("'location' column already exists in scrape_logs table")

    if changes_made:
        conn.commit()
        print("\nMigration completed successfully!")
    else:
        print("\nNo changes needed - database is already up to date.")

    conn.close()

if __name__ == '__main__':
    migrate()
