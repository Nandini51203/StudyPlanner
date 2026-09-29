"""
Database migration script.
Run this if you have an existing study.db from a previous version
that doesn't have the users table or user_id column in materials.
"""
import os, sqlite3, config

def migrate():
    if not os.path.exists(config.DB):
        print("No existing database found. A new one will be created on first run.")
        return

    c = sqlite3.connect(config.DB)
    c.row_factory = sqlite3.Row

    # Check if users table exists
    tables = [r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    if "users" not in tables:
        print("Adding users table...")
        c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,email TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)")
        c.commit()
        print("  users table created.")

    # Check if materials has user_id column
    cols = [r["name"] for r in c.execute("PRAGMA table_info(materials)").fetchall()]
    if "user_id" not in cols:
        print("Adding user_id column to materials...")
        c.execute("ALTER TABLE materials ADD COLUMN user_id INTEGER DEFAULT 0")
        c.commit()
        print("  user_id column added.")

    c.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
