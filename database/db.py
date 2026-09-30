import os, sqlite3, config
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,email TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,full_name TEXT,course TEXT);
CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,name TEXT,content TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS summaries(material_id INTEGER PRIMARY KEY,data TEXT,demo INTEGER,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS quizzes(id INTEGER PRIMARY KEY AUTOINCREMENT,material_id INTEGER,questions TEXT,demo INTEGER,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,quiz_id INTEGER,material_id INTEGER,score INTEGER,total INTEGER,feedback TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY AUTOINCREMENT,attempt_id INTEGER,topic TEXT,selected INTEGER,correct INTEGER,is_correct INTEGER);
CREATE TABLE IF NOT EXISTS user_preferences(user_id INTEGER PRIMARY KEY,summary_style TEXT DEFAULT 'detailed',default_quiz_length INTEGER DEFAULT 5,daily_study_goal_minutes INTEGER DEFAULT 60,preferred_study_time TEXT DEFAULT 'flexible',updated_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS study_plans(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,title TEXT,exam_date TEXT,daily_minutes INTEGER,days_available INTEGER,preferred_study_time TEXT,material_id INTEGER,has_performance_data INTEGER DEFAULT 0,plan_source TEXT DEFAULT 'smart',warnings TEXT,notes TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,updated TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id),FOREIGN KEY(material_id) REFERENCES materials(id));
CREATE TABLE IF NOT EXISTS study_tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,plan_id INTEGER NOT NULL,day_number INTEGER,task_date TEXT,topic TEXT,description TEXT,objective TEXT,duration_minutes INTEGER,activity TEXT,priority TEXT,completed INTEGER DEFAULT 0,completed_at TEXT,FOREIGN KEY(plan_id) REFERENCES study_plans(id));
CREATE VIEW IF NOT EXISTS topic_performance AS SELECT t.material_id material_id,a.topic topic,COUNT(*) total,SUM(a.is_correct) correct FROM answers a JOIN attempts t ON t.id=a.attempt_id GROUP BY t.material_id,a.topic;
"""
def conn():
    c = sqlite3.connect(config.DB); c.row_factory = sqlite3.Row; return c
def init():
    os.makedirs(os.path.dirname(config.DB), exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        _migrate(c)
def _migrate(c):
    """Add columns/tables to databases created by older versions. Never drops data."""
    # Profile columns on users (older databases)
    cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
    if "full_name" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
    if "course" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN course TEXT")
    # A default preferences row for every existing user
    for (uid,) in c.execute("SELECT id FROM users").fetchall():
        c.execute("INSERT OR IGNORE INTO user_preferences(user_id) VALUES(?)", (uid,))
    # Planner columns (older databases)
    plan_cols = [r[1] for r in c.execute("PRAGMA table_info(study_plans)")]
    if "plan_source" not in plan_cols:
        c.execute("ALTER TABLE study_plans ADD COLUMN plan_source TEXT DEFAULT 'smart'")
    task_cols = [r[1] for r in c.execute("PRAGMA table_info(study_tasks)")]
    if "objective" not in task_cols:
        c.execute("ALTER TABLE study_tasks ADD COLUMN objective TEXT")
    c.commit()
def q(sql, args=(), one=False):
    c = conn(); r = c.execute(sql, args).fetchall(); c.close()
    return (r[0] if r else None) if one else r
def ex(sql, args=()):
    c = conn(); cur = c.execute(sql, args); c.commit(); i = cur.lastrowid; c.close(); return i
def topic_rows(material_id=None):
    if material_id:
        rows = q("SELECT topic,total,correct FROM topic_performance WHERE material_id=?", (material_id,))
    else:
        rows = q("SELECT topic,SUM(total) total,SUM(correct) correct FROM topic_performance GROUP BY topic")
    return [dict(r) for r in rows]
if __name__ == "__main__":
    init(); print("Database initialised at", config.DB)
