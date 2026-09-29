import json
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session
from werkzeug.utils import secure_filename
import config
from database import db
from services.pdf_service import extract_text
from agents.study_graph import graph
from agents.weak_topic_agent import analyze
from auth import register_user, verify_user, login_required, get_current_user, is_logged_in

app = Flask(__name__)
app.secret_key = config.SECRET
app.config["MAX_CONTENT_LENGTH"] = config.MAX_MB * 1024 * 1024
db.init()

@app.context_processor
def inject():
    return {"demo": config.DEMO, "current_user": get_current_user()}

def material(mid):
    return db.q("SELECT * FROM materials WHERE id=? AND user_id=?", (mid, session["user_id"]), one=True)

def scores():
    return [{"label": f"#{r['id']}", "pct": round(r["score"] * 100 / r["total"])} for r in db.q(
        "SELECT a.* FROM attempts a JOIN materials m ON m.id=a.material_id WHERE m.user_id=? ORDER BY a.id", (session["user_id"],))]

# ── Auth Routes ──────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if is_logged_in():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user, error = verify_user(username, password)
        if error:
            flash(error, "danger")
            return redirect(url_for("login"))
        session["user_id"] = user["id"]
        session["user"] = user
        flash(f"Welcome back, {user['username']}!", "success")
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if is_logged_in():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip() or None
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))
        uid, error = register_user(username, password, email)
        if error:
            flash(error, "danger")
            return redirect(url_for("register"))
        session["user_id"] = uid
        session["user"] = {"id": uid, "username": username, "email": email}
        flash("Account created successfully!", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

# ── Protected Routes ─────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    st = db.q("SELECT COUNT(*) n, AVG(score*100.0/total) avg FROM attempts a JOIN materials m ON m.id=a.material_id WHERE m.user_id=?", (session["user_id"],), one=True)
    topics = analyze(db.topic_rows())
    return render_template("dashboard.html", n_mat=db.q("SELECT COUNT(*) c FROM materials WHERE user_id=?", (session["user_id"],), one=True)["c"],
        n_att=st["n"], avg=round(st["avg"] or 0), weak=sum(t["status"] == "Needs Revision" for t in topics),
        recent=db.q("SELECT a.*,m.name FROM attempts a JOIN materials m ON m.id=a.material_id WHERE m.user_id=? ORDER BY a.id DESC LIMIT 5", (session["user_id"],)),
        scores=scores())

@app.route("/materials")
@login_required
def materials():
    return render_template("materials.html", items=db.q("SELECT id,name,created FROM materials WHERE user_id=? ORDER BY id DESC", (session["user_id"],)))

@app.post("/materials")
@login_required
def upload():
    f, topic = request.files.get("file"), request.form.get("topic", "").strip()
    try:
        if f and f.filename:
            name = secure_filename(f.filename)
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            # Validate extension
            if ext not in config.ALLOWED:
                raise ValueError("Unsupported file format. Please upload a PDF or TXT file.")
            # Validate file size (additional check beyond Flask's MAX_CONTENT_LENGTH)
            f.stream.seek(0, 2)  # Seek to end
            file_size = f.stream.tell()
            f.stream.seek(0)  # Reset to beginning
            if file_size > config.MAX_MB * 1024 * 1024:
                raise ValueError(f"File exceeds the maximum allowed size of {config.MAX_MB} MB.")
            if file_size == 0:
                raise ValueError("The selected file is empty.")
            # Extract text (includes PDF page count validation)
            text = extract_text(f.stream, ext)
        elif topic:
            name, text = topic[:60], topic
        else:
            raise ValueError("Choose a file or type a topic.")
        db.ex("INSERT INTO materials(user_id,name,content) VALUES(?,?,?)", (session["user_id"], name, text))
        flash("Material added.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("materials"))

@app.post("/materials/delete/<int:mid>")
@login_required
def delete(mid):
    m = material(mid)
    if not m: return redirect(url_for("materials"))
    for s in ("DELETE FROM answers WHERE attempt_id IN (SELECT id FROM attempts WHERE material_id=?)", "DELETE FROM attempts WHERE material_id=?",
              "DELETE FROM quizzes WHERE material_id=?", "DELETE FROM summaries WHERE material_id=?", "DELETE FROM materials WHERE id=?"):
        db.ex(s, (mid,))
    return redirect(url_for("materials"))

@app.route("/summary/<int:mid>")
@login_required
def summary(mid):
    m = material(mid)
    if not m: return redirect(url_for("materials"))
    s = db.q("SELECT * FROM summaries WHERE material_id=?", (mid,), one=True)
    lq = db.q("SELECT id FROM quizzes WHERE material_id=? ORDER BY id DESC LIMIT 1", (mid,), one=True)
    return render_template("summary.html", m=m, s=json.loads(s["data"]) if s else None, s_demo=s and s["demo"], quiz_id=lq["id"] if lq else None)

@app.post("/api/run/<int:mid>")
@login_required
def run(mid):
    m, d = material(mid), request.get_json() or {}
    if not m: return jsonify(error="Material not found"), 404
    n = int(d.get("n", 5)); n = n if n in (5, 10, 15) else 5
    focus = []
    if d.get("weak"):
        focus = [a["topic"] for a in analyze(db.topic_rows(mid)) if a["status"] == "Needs Revision"]
        if not focus: return jsonify(error="No confirmed weak topics yet. Take a few quizzes first."), 400
    try: out = graph.invoke({"stage": d.get("stage", "quiz"), "text": m["content"], "n": n, "focus": focus})
    except Exception as e: return jsonify(error=str(e)), 500
    qid = None
    if out.get("summary"): db.ex("INSERT OR REPLACE INTO summaries(material_id,data,demo) VALUES(?,?,?)", (mid, json.dumps(out["summary"]), int(config.DEMO)))
    if out.get("questions"): qid = db.ex("INSERT INTO quizzes(material_id,questions,demo) VALUES(?,?,?)", (mid, json.dumps(out["questions"]), int(config.DEMO)))
    return jsonify(ok=True, quiz_id=qid)

@app.route("/quiz/<int:qid>")
@login_required
def quiz(qid):
    r = db.q("SELECT q.* FROM quizzes q JOIN materials m ON m.id=q.material_id WHERE q.id=? AND m.user_id=?", (qid, session["user_id"]), one=True)
    if not r: return redirect(url_for("materials"))
    return render_template("quiz.html", qid=qid, questions=json.loads(r["questions"]), q_demo=r["demo"])

@app.post("/api/submit/<int:qid>")
@login_required
def submit(qid):
    r = db.q("SELECT q.* FROM quizzes q JOIN materials m ON m.id=q.material_id WHERE q.id=? AND m.user_id=?", (qid, session["user_id"]), one=True)
    if not r: return jsonify(error="Quiz not found"), 404
    qs = json.loads(r["questions"]); ans = (request.get_json() or {}).get("answers", [])
    ans = (ans + [None] * len(qs))[:len(qs)]
    score = sum(a == q["answer"] for q, a in zip(qs, ans))
    aid = db.ex("INSERT INTO attempts(quiz_id,material_id,score,total,feedback) VALUES(?,?,?,?,'')", (qid, r["material_id"], score, len(qs)))
    for q, a in zip(qs, ans):
        db.ex("INSERT INTO answers(attempt_id,topic,selected,correct,is_correct) VALUES(?,?,?,?,?)",
              (aid, q["topic"], -1 if a is None else a, q["answer"], int(a == q["answer"])))
    out = graph.invoke({"stage": "evaluate", "topic_rows": db.topic_rows(r["material_id"])})
    db.ex("UPDATE attempts SET feedback=? WHERE id=?", (json.dumps({"analysis": out["analysis"], "recs": out["recommendations"]}), aid))
    return jsonify(attempt_id=aid)

@app.route("/results/<int:aid>")
@login_required
def results(aid):
    a = db.q("SELECT a.* FROM attempts a JOIN materials m ON m.id=a.material_id WHERE a.id=? AND m.user_id=?", (aid, session["user_id"]), one=True)
    if not a: return redirect(url_for("dashboard"))
    qs = json.loads(db.q("SELECT questions FROM quizzes WHERE id=?", (a["quiz_id"],), one=True)["questions"])
    sel = [x["selected"] for x in db.q("SELECT selected FROM answers WHERE attempt_id=? ORDER BY id", (aid,))]
    return render_template("results.html", a=a, rows=list(zip(qs, sel)), fb=json.loads(a["feedback"] or "{}"))

@app.route("/progress")
@login_required
def progress():
    return render_template("progress.html", scores=scores(), topics=analyze(db.topic_rows()),
        materials=db.q("SELECT id,name FROM materials WHERE user_id=?", (session["user_id"],)))

if __name__ == "__main__":
    app.run(debug=True)
