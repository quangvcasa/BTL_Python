import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'ptit_lab_progress.db')

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("ALTER TABLE execution_item_updates ADD COLUMN update_type VARCHAR(30) DEFAULT 'progress_update' NOT NULL;")
    conn.commit()
    print("Successfully added update_type column to execution_item_updates table.")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("Column update_type already exists.")
    else:
        print(f"Error: {e}")
finally:
    if 'conn' in locals() and conn:
        conn.close()
