import os, sqlite3, config
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,email TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,name TEXT,content TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS summaries(material_id INTEGER PRIMARY KEY,data TEXT,demo INTEGER,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS quizzes(id INTEGER PRIMARY KEY AUTOINCREMENT,material_id INTEGER,questions TEXT,demo INTEGER,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,quiz_id INTEGER,material_id INTEGER,score INTEGER,total INTEGER,feedback TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY AUTOINCREMENT,attempt_id INTEGER,topic TEXT,selected INTEGER,correct INTEGER,is_correct INTEGER);
CREATE VIEW IF NOT EXISTS topic_performance AS SELECT t.material_id material_id,a.topic topic,COUNT(*) total,SUM(a.is_correct) correct FROM answers a JOIN attempts t ON t.id=a.attempt_id GROUP BY t.material_id,a.topic;
"""
def conn():
    c = sqlite3.connect(config.DB); c.row_factory = sqlite3.Row; return c
def init():
    os.makedirs(os.path.dirname(config.DB), exist_ok=True)
    with conn() as c: c.executescript(SCHEMA)
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
