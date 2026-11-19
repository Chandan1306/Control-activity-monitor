"""
One-time migration: add new columns to existing lab_monitor.db
Run once: python3.14.exe migrate_db.py
"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'lab_monitor.db')

migrations = [
    # Machine live-state columns
    "ALTER TABLE machine ADD COLUMN current_app     TEXT",
    "ALTER TABLE machine ADD COLUMN current_title   TEXT",
    "ALTER TABLE machine ADD COLUMN current_allowed INTEGER DEFAULT 1",
    # Alert screenshot column
    "ALTER TABLE alert ADD COLUMN screenshot_path TEXT",
    # MachineSessionStat table (create if missing)
    """CREATE TABLE IF NOT EXISTS machine_session_stat (
        id                 INTEGER PRIMARY KEY,
        machine_id         INTEGER NOT NULL REFERENCES machine(id),
        session_id         INTEGER NOT NULL REFERENCES session(id),
        total_heartbeats   INTEGER DEFAULT 0,
        allowed_heartbeats INTEGER DEFAULT 0,
        violation_count    INTEGER DEFAULT 0,
        UNIQUE(machine_id, session_id)
    )""",
]

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()

for sql in migrations:
    try:
        cur.execute(sql)
        print(f"OK: {sql[:60].strip()}...")
    except sqlite3.OperationalError as e:
        print(f"SKIP ({e}): {sql[:60].strip()}...")

conn.commit()
conn.close()
print("\n✅ Migration complete.")
