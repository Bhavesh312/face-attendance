"""
One-time migration script.
Adds the new 'created_at' column to the existing 'sessions' table
in attendance.db, WITHOUT deleting any existing data.

Run this ONCE, before running the app with the new app.py / db_utils.py.
"""

import sqlite3
from datetime import datetime

DB_PATH = "attendance.db"  # must be run from the same folder as attendance.db

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Check if the column already exists (so this script is safe to re-run)
cur.execute("PRAGMA table_info(sessions)")
existing_columns = [row[1] for row in cur.fetchall()]

if "created_at" in existing_columns:
    print("✅ 'created_at' column already exists. Nothing to do.")
else:
    cur.execute("ALTER TABLE sessions ADD COLUMN created_at DATETIME")
    # Backfill old sessions with the current time (since we don't know their real date)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE sessions SET created_at = ? WHERE created_at IS NULL", (now_str,))
    conn.commit()
    print("✅ 'created_at' column added successfully. Old sessions backfilled with today's date/time.")

conn.close()
