import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'ptit_lab_progress.db')

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("ALTER TABLE commitments ADD COLUMN admin_review_note TEXT;")
    cursor.execute("ALTER TABLE commitments ADD COLUMN reviewed_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL;")
    cursor.execute("ALTER TABLE commitments ADD COLUMN reviewed_at DATETIME;")
    conn.commit()
    print("Successfully added review columns to commitments table.")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("Column already exists.")
    else:
        print(f"Error: {e}")
finally:
    if 'conn' in locals() and conn:
        conn.close()
