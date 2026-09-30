import json
import logging
from datetime import date, datetime

log = logging.getLogger(__name__)
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session, Response
from werkzeug.utils import secure_filename
import config
from database import db
from services.pdf_service import extract_text, build_pdf, safe_filename
from agents.study_graph import graph
from agents.weak_topic_agent import analyze
from agents import planner_agent, quiz_agent, summarizer_agent
from auth import (register_user, verify_user, login_required, get_current_user, is_logged_in,
                  get_user, update_profile, change_password, get_preferences, save_preferences,
                  SUMMARY_STYLES, QUIZ_LENGTHS, STUDY_TIMES)

app = Flask(__name__)
app.secret_key = config.SECRET
app.config["MAX_CONTENT_LENGTH"] = config.MAX_MB * 1024 * 1024
db.init()

@app.context_processor
def inject():
    # Always read fresh user data from the DB so profile edits show up immediately.
    user = None
    if "user_id" in session:
        u = db.q("SELECT id, username, email, full_name FROM users WHERE id=?", (session["user_id"],), one=True)
        if u:
            user = dict(u)
    return {"demo": config.DEMO, "current_user": user}

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
    uid = session["user_id"]

    # ── Metric cards ──────────────────────────────────────────────
    st = db.q("SELECT COUNT(*) n, AVG(score*100.0/total) avg FROM attempts a JOIN materials m ON m.id=a.material_id WHERE m.user_id=?", (uid,), one=True)
    n_mat = db.q("SELECT COUNT(*) c FROM materials WHERE user_id=?", (uid,), one=True)["c"]
    topics = analyze(db.topic_rows())
    weak_count = sum(t["status"] == "Needs Revision" for t in topics)

    # ── Today's study plan ────────────────────────────────────────
    today = date.today().isoformat()
    today_tasks = db.q(
        "SELECT t.* FROM study_tasks t JOIN study_plans p ON p.id=t.plan_id "
        "WHERE p.user_id=? AND t.task_date=? ORDER BY t.id", (uid, today))
    today_done = sum(t["completed"] for t in today_tasks)
    today_total = len(today_tasks)

    # ── Upcoming exam ─────────────────────────────────────────────
    upcoming_exam = db.q(
        "SELECT * FROM study_plans WHERE user_id=? AND exam_date IS NOT NULL AND exam_date>=? "
        "ORDER BY exam_date LIMIT 1", (uid, today), one=True)
    exam_countdown = None
    if upcoming_exam:
        try:
            exam_countdown = (date.fromisoformat(upcoming_exam["exam_date"]) - date.today()).days
        except ValueError:
            exam_countdown = None

    # ── Recommended next step (rule-based, no API call) ───────────
    recommendation = _get_recommendation(topics, today_tasks)

    # ── Study progress ────────────────────────────────────────────
    progress_row = db.q(
        "SELECT COUNT(*) total, SUM(completed) done FROM study_tasks t "
        "JOIN study_plans p ON p.id=t.plan_id WHERE p.user_id=?", (uid,), one=True)
    total_tasks = progress_row["total"] or 0
    done_tasks = progress_row["done"] or 0
    remaining_tasks = total_tasks - done_tasks
    progress_pct = round(done_tasks * 100 / total_tasks) if total_tasks else 0

    # ── Recent activity (multiple event types) ───────────────────
    recent = _get_recent_activity(uid)

    return render_template("dashboard.html",
        n_mat=n_mat, n_att=st["n"], avg=round(st["avg"] or 0), weak=weak_count,
        scores=scores(),
        today_tasks=[dict(t) for t in today_tasks],
        today_done=today_done, today_total=today_total,
        upcoming_exam=dict(upcoming_exam) if upcoming_exam else None,
        exam_countdown=exam_countdown,
        recommendation=recommendation,
        total_tasks=total_tasks, done_tasks=done_tasks,
        remaining_tasks=remaining_tasks, progress_pct=progress_pct,
        recent=recent)


def _get_recommendation(topics, today_tasks):
    """Generate a study recommendation based on weak topics and today's tasks.

    Uses only local data — no Gemini API call.
    """
    # Find the weakest topic that hasn't been completed today
    weak = [t for t in topics if t["status"] == "Needs Revision"]
    if not weak:
        weak = [t for t in topics if t["status"] == "Improving"]
    if not weak:
        return None

    # Sort by accuracy (lowest first)
    weak.sort(key=lambda t: t["accuracy"])
    weakest = weak[0]

    # Check if there's already a completed task for this topic today
    completed_topics = {t["topic"].lower() for t in today_tasks if t["completed"]}
    if weakest["topic"].lower() in completed_topics:
        # Find next weakest not yet completed
        for t in weak:
            if t["topic"].lower() not in completed_topics:
                return {
                    "topic": t["topic"],
                    "accuracy": t["accuracy"],
                    "reason": f"Your quiz accuracy on {t['topic']} is {t['accuracy']}%. More practice will help.",
                }
        return None

    return {
        "topic": weakest["topic"],
        "accuracy": weakest["accuracy"],
        "reason": f"Your quiz accuracy on {weakest['topic']} is {weakest['accuracy']}%. More practice will help.",
    }


def _get_recent_activity(uid):
    """Collect recent activity from multiple sources, sorted by date."""
    activities = []

    # Notes uploaded
    for r in db.q("SELECT name, created FROM materials WHERE user_id=? ORDER BY created DESC LIMIT 3", (uid,)):
        activities.append({
            "icon": "bi-folder2-open", "color": "text-primary",
            "text": f"Uploaded notes: {r['name']}",
            "date": r["created"],
        })

    # Quizzes attempted
    for r in db.q("SELECT a.id, a.score, a.total, a.created, m.name FROM attempts a JOIN materials m ON m.id=a.material_id WHERE m.user_id=? ORDER BY a.created DESC LIMIT 3", (uid,)):
        activities.append({
            "icon": "bi-patch-question", "color": "text-success",
            "text": f"Quiz: {r['name']} — {r['score']}/{r['total']}",
            "date": r["created"],
        })

    # Study plans created
    for r in db.q("SELECT title, created FROM study_plans WHERE user_id=? ORDER BY created DESC LIMIT 3", (uid,)):
        activities.append({
            "icon": "bi-calendar-week", "color": "text-info",
            "text": f"Created plan: {r['title']}",
            "date": r["created"],
        })

    # Tasks completed (most recent)
    for r in db.q(
        "SELECT t.topic, t.completed_at FROM study_tasks t JOIN study_plans p ON p.id=t.plan_id "
        "WHERE p.user_id=? AND t.completed=1 AND t.completed_at IS NOT NULL "
        "ORDER BY t.completed_at DESC LIMIT 3", (uid,)):
        activities.append({
            "icon": "bi-check-circle", "color": "text-success",
            "text": f"Completed: {r['topic']}",
            "date": r["completed_at"],
        })

    # Sort by date descending, most recent first
    activities.sort(key=lambda a: a["date"] or "", reverse=True)
    return activities[:8]

@app.route("/materials")
@login_required
def materials():
    prefs = get_preferences(session["user_id"])
    return render_template("materials.html", items=db.q("SELECT id,name,created FROM materials WHERE user_id=? ORDER BY id DESC", (session["user_id"],)),
        pref_n=prefs["default_quiz_length"])

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

@app.get("/summary/<int:mid>/download")
@login_required
def download_summary_pdf(mid):
    """Generate and download the study notes as a formatted PDF (on-the-fly)."""
    m = material(mid)
    if not m: return redirect(url_for("materials"))
    s = db.q("SELECT * FROM summaries WHERE material_id=?", (mid,), one=True)
    if not s:
        flash("No summary available to download. Generate a summary first.", "warning")
        return redirect(url_for("summary", mid=mid))
    try:
        pdf_bytes = build_pdf(json.loads(s["data"]), m["name"])
    except Exception as e:
        flash(f"Could not generate the PDF: {e}", "danger")
        return redirect(url_for("summary", mid=mid))
    filename = safe_filename(m["name"])
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})

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
    # Summary style comes from the user's saved learning preference (frontend may override).
    style = d.get("style") or get_preferences(session["user_id"])["summary_style"]

    stage = d.get("stage", "quiz")

    # Handle quiz generation with local fallback
    if stage in ("quiz", "full"):
        try:
            questions, source = quiz_agent.generate(m["content"], n, focus)
            qid = db.ex("INSERT INTO quizzes(material_id,questions,demo) VALUES(?,?,?)",
                         (mid, json.dumps(questions), int(config.DEMO)))
            if stage == "full":
                # Also generate summary
                try:
                    summary, _ = summarizer_agent.run(m["content"], style)
                    db.ex("INSERT OR REPLACE INTO summaries(material_id,data,demo) VALUES(?,?,?)",
                          (mid, json.dumps(summary), int(config.DEMO)))
                except Exception:
                    pass  # Summary failure shouldn't block quiz
            return jsonify(ok=True, quiz_id=qid, source=source)
        except Exception as e:
            log.warning("Quiz generation failed: %s", e)
            return jsonify(error="Quiz generation is temporarily unavailable. Please try again later."), 500

    # Handle summary-only generation
    if stage == "summary":
        try:
            summary, source = summarizer_agent.run(m["content"], style)
            db.ex("INSERT OR REPLACE INTO summaries(material_id,data,demo) VALUES(?,?,?)",
                  (mid, json.dumps(summary), int(config.DEMO)))
            return jsonify(ok=True, source=source)
        except Exception as e:
            log.warning("Summary generation failed: %s", e)
            return jsonify(error="Summary generation is temporarily unavailable. Please try again later."), 500

    # Handle evaluation stage
    if stage == "evaluate":
        try:
            out = graph.invoke({"stage": "evaluate", "topic_rows": db.topic_rows(mid)})
            return jsonify(ok=True)
        except Exception as e:
            log.warning("Evaluation failed: %s", e)
            return jsonify(error="Evaluation failed. Please try again."), 500

    return jsonify(error="Invalid stage"), 400

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

# ── Profile Routes ───────────────────────────────────────────

@app.route("/profile")
@login_required
def profile():
    user = get_user(session["user_id"])
    prefs = get_preferences(session["user_id"])
    stats = db.q("SELECT (SELECT COUNT(*) FROM materials WHERE user_id=?) AS n_mat, (SELECT COUNT(*) FROM attempts a JOIN materials m ON m.id=a.material_id WHERE m.user_id=?) AS n_att, (SELECT COUNT(*) FROM study_plans WHERE user_id=?) AS n_plans", (session["user_id"], session["user_id"], session["user_id"]), one=True)
    return render_template("profile.html", user=user, prefs=prefs, n_mat=stats["n_mat"], n_att=stats["n_att"], n_plans=stats["n_plans"])

@app.post("/profile/update")
@login_required
def profile_update():
    full_name = request.form.get("full_name", "").strip()[:80]
    course = request.form.get("course", "").strip()[:120]
    update_profile(session["user_id"], full_name, course)
    flash("Profile updated.", "success")
    return redirect(url_for("profile"))

@app.post("/profile/preferences")
@login_required
def profile_preferences():
    style = request.form.get("summary_style", "detailed")
    if style not in SUMMARY_STYLES: style = "detailed"
    try: qlen = int(request.form.get("quiz_length", 5))
    except (TypeError, ValueError): qlen = 5
    if qlen not in QUIZ_LENGTHS: qlen = 5
    # Daily goal: preset value or custom minutes
    daily_raw = request.form.get("daily_goal", "60")
    if daily_raw == "custom":
        try: daily = int(request.form.get("daily_goal_custom", 60))
        except (TypeError, ValueError): daily = 60
    else:
        try: daily = int(daily_raw)
        except (TypeError, ValueError): daily = 60
    if not (15 <= daily <= 720): daily = 60
    stime = request.form.get("study_time", "flexible")
    if stime not in STUDY_TIMES: stime = "flexible"
    save_preferences(session["user_id"], style, qlen, daily, stime)
    flash("Learning preferences saved.", "success")
    return redirect(url_for("profile"))

@app.post("/profile/password")
@login_required
def profile_password():
    cur = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    conf = request.form.get("confirm_password", "")
    if new != conf:
        flash("New passwords do not match.", "danger")
        return redirect(url_for("profile"))
    err = change_password(session["user_id"], cur, new)
    if err:
        flash(err, "danger")
    else:
        flash("Password changed successfully.", "success")
    return redirect(url_for("profile"))

# ── Study Planner Routes ─────────────────────────────────────

@app.route("/planner")
@login_required
def planner():
    plans = [dict(p) for p in db.q("SELECT * FROM study_plans WHERE user_id=? ORDER BY id DESC", (session["user_id"],))]
    for p in plans:
        st = db.q("SELECT COUNT(*) n, SUM(completed) d FROM study_tasks WHERE plan_id=?", (p["id"],), one=True)
        p["n_tasks"], p["n_done"] = st["n"], st["d"] or 0
    materials = db.q("SELECT id,name FROM materials WHERE user_id=? ORDER BY id DESC", (session["user_id"],))
    prefs = get_preferences(session["user_id"])
    return render_template("planner.html", plans=plans, materials=materials, prefs=prefs)

@app.post("/planner/generate")
@login_required
def planner_generate():
    d = request.get_json() or {}
    title = str(d.get("title", "")).strip()[:120]
    exam_date = str(d.get("exam_date", "")).strip() or None
    try:
        daily_minutes = int(d.get("daily_minutes", 60))
    except (TypeError, ValueError):
        return jsonify(error="Invalid study time."), 400
    if not title:
        return jsonify(error="Plan title is required."), 400
    if not (15 <= daily_minutes <= 720):
        return jsonify(error="Daily study time must be between 15 and 720 minutes."), 400

    # Calculate days_available from exam date, or use default
    days_per_week = int(d.get("days_per_week", 7))
    if not (1 <= days_per_week <= 7):
        days_per_week = 7

    if exam_date:
        try:
            ed = date.fromisoformat(exam_date)
        except ValueError:
            return jsonify(error="Invalid exam date. Use YYYY-MM-DD."), 400
        if ed < date.today():
            return jsonify(error="Exam date cannot be in the past."), 400
        # Calculate available days from today to exam date
        days_available = (ed - date.today()).days
        if days_available < 1:
            days_available = 1
        if days_available > 90:
            days_available = 90
    else:
        # No exam date — use a reasonable default
        days_available = 7

    # Optional study material
    material = None
    if d.get("material_id"):
        try:
            material = db.q("SELECT * FROM materials WHERE id=? AND user_id=?", (int(d["material_id"]), session["user_id"]), one=True)
        except (TypeError, ValueError):
            return jsonify(error="Invalid material selected."), 400
        if not material:
            return jsonify(error="Material not found."), 404

    # Optional syllabus / topic list (one per line)
    topics = [t.strip() for t in str(d.get("topics", "")).splitlines() if t.strip()][:30]

    # Weak-topic / performance data from existing quiz history (automatic)
    perf_rows = db.topic_rows()
    has_perf = bool(perf_rows)
    performance = analyze(perf_rows) if has_perf else []

    study_time = str(d.get("study_time", "")).strip()
    if study_time not in STUDY_TIMES:
        study_time = get_preferences(session["user_id"])["preferred_study_time"]

    try:
        plan = planner_agent.generate_plan(
            title=title, exam_date=exam_date, daily_minutes=daily_minutes,
            days_available=days_available, preferred_study_time=study_time,
            material_text=material["content"] if material else None,
            topics=topics or None, performance=performance, has_performance_data=has_perf)
    except Exception as e:
        log.warning("Plan generation error: %s", e)
        return jsonify(error="Plan generation failed. Please try again."), 500

    if plan.get("error"):
        return jsonify(error=plan["error"]), 400

    plan_source = plan.get("source", "smart")
    if plan_source == "ai":
        notes_msg = "AI personalization is available. Your plan was generated with AI enhancement."
    else:
        notes_msg = "AI personalization is currently unavailable. Your plan was generated using Smart Planning."

    pid = db.ex("INSERT INTO study_plans(user_id,title,exam_date,daily_minutes,days_available,preferred_study_time,material_id,has_performance_data,plan_source,warnings,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (session["user_id"], title, exam_date, daily_minutes, days_available, study_time,
                 material["id"] if material else None, int(has_perf), plan_source,
                 json.dumps(plan.get("warnings", [])), notes_msg))
    for day in plan["days"]:
        for t in day["tasks"]:
            db.ex("INSERT INTO study_tasks(plan_id,day_number,task_date,topic,description,objective,duration_minutes,activity,priority) VALUES(?,?,?,?,?,?,?,?,?)",
                  (pid, day["day_number"], day["date"], t["topic"], t["description"],
                   t.get("description", ""), t["duration_minutes"], t["activity"], t["priority"]))
    return jsonify(ok=True, plan_id=pid, source=plan_source)

@app.route("/planner/<int:pid>")
@login_required
def plan_detail(pid):
    p = db.q("SELECT * FROM study_plans WHERE id=? AND user_id=?", (pid, session["user_id"]), one=True)
    if not p: return redirect(url_for("planner"))
    tasks = db.q("SELECT * FROM study_tasks WHERE plan_id=? ORDER BY day_number, id", (pid,))
    days = {}
    for t in tasks:
        days.setdefault(t["day_number"], {"date": t["task_date"], "tasks": []})["tasks"].append(dict(t))
    total = len(tasks)
    done = sum(t["completed"] for t in tasks)
    total_min = sum(t["duration_minutes"] for t in tasks)
    countdown = None
    if p["exam_date"]:
        try:
            countdown = (date.fromisoformat(p["exam_date"]) - date.today()).days
        except ValueError:
            countdown = None
    p_dict = dict(p)
    return render_template("plan_detail.html", p=p_dict, days=days, total=total, done=done,
        total_min=total_min, countdown=countdown,
        warnings=json.loads(p["warnings"] or "[]"),
        plan_source=p_dict.get("plan_source", "smart"))

@app.post("/planner/<int:pid>/task/<int:tid>/toggle")
@login_required
def task_toggle(pid, tid):
    t = db.q("SELECT t.* FROM study_tasks t JOIN study_plans p ON p.id=t.plan_id WHERE t.id=? AND p.id=? AND p.user_id=?", (tid, pid, session["user_id"]), one=True)
    if not t: return jsonify(error="Task not found"), 404
    new = 0 if t["completed"] else 1
    db.ex("UPDATE study_tasks SET completed=?, completed_at=? WHERE id=?",
          (new, datetime.now().isoformat(timespec="seconds") if new else None, tid))
    st = db.q("SELECT COUNT(*) n, SUM(completed) d FROM study_tasks WHERE plan_id=?", (pid,), one=True)
    return jsonify(ok=True, completed=new, done=st["d"] or 0, total=st["n"],
                   pct=round((st["d"] or 0) * 100 / st["n"]))

@app.post("/planner/<int:pid>/delete")
@login_required
def plan_delete(pid):
    p = db.q("SELECT * FROM study_plans WHERE id=? AND user_id=?", (pid, session["user_id"]), one=True)
    if not p: return redirect(url_for("planner"))
    db.ex("DELETE FROM study_tasks WHERE plan_id=?", (pid,))
    db.ex("DELETE FROM study_plans WHERE id=?", (pid,))
    flash("Study plan deleted.", "info")
    return redirect(url_for("planner"))

@app.post("/planner/<int:pid>/task/add")
@login_required
def task_add(pid):
    """Add a new task to an existing plan."""
    p = db.q("SELECT * FROM study_plans WHERE id=? AND user_id=?", (pid, session["user_id"]), one=True)
    if not p: return jsonify(error="Plan not found"), 404
    d = request.get_json() or {}
    topic = str(d.get("topic", "")).strip()[:120]
    desc = str(d.get("description", "")).strip()[:500]
    try:
        dur = int(d.get("duration_minutes", 30))
    except (TypeError, ValueError):
        dur = 30
    act = str(d.get("activity", "read")).lower()
    if act not in ("read", "revise", "practice", "quiz"):
        act = "read"
    pri = str(d.get("priority", "medium")).lower()
    if pri not in ("high", "medium", "low"):
        pri = "medium"
    if not topic:
        return jsonify(error="Topic is required"), 400
    # Find the next day number and date
    last = db.q("SELECT MAX(day_number) mn, MAX(task_date) md FROM study_tasks WHERE plan_id=?", (pid,), one=True)
    next_day = (last["mn"] or 0) + 1
    next_date = last["md"] or date.today().isoformat()
    tid = db.ex("INSERT INTO study_tasks(plan_id,day_number,task_date,topic,description,objective,duration_minutes,activity,priority) VALUES(?,?,?,?,?,?,?,?,?)",
                (pid, next_day, next_date, topic, desc, desc, dur, act, pri))
    return jsonify(ok=True, task_id=tid)

@app.post("/planner/<int:pid>/task/<int:tid>/edit")
@login_required
def task_edit(pid, tid):
    """Edit an existing task."""
    t = db.q("SELECT t.* FROM study_tasks t JOIN study_plans p ON p.id=t.plan_id WHERE t.id=? AND p.id=? AND p.user_id=?", (tid, pid, session["user_id"]), one=True)
    if not t: return jsonify(error="Task not found"), 404
    d = request.get_json() or {}
    topic = str(d.get("topic", t["topic"])).strip()[:120]
    desc = str(d.get("description", t["description"])).strip()[:500]
    try:
        dur = int(d.get("duration_minutes", t["duration_minutes"]))
    except (TypeError, ValueError):
        dur = t["duration_minutes"]
    act = str(d.get("activity", t["activity"])).lower()
    if act not in ("read", "revise", "practice", "quiz"):
        act = t["activity"]
    pri = str(d.get("priority", t["priority"])).lower()
    if pri not in ("high", "medium", "low"):
        pri = t["priority"]
    db.ex("UPDATE study_tasks SET topic=?, description=?, objective=?, duration_minutes=?, activity=?, priority=? WHERE id=?",
          (topic, desc, desc, dur, act, pri, tid))
    return jsonify(ok=True)

@app.post("/planner/<int:pid>/task/<int:tid>/delete")
@login_required
def task_delete(pid, tid):
    """Delete a task from a plan."""
    t = db.q("SELECT t.* FROM study_tasks t JOIN study_plans p ON p.id=t.plan_id WHERE t.id=? AND p.id=? AND p.user_id=?", (tid, pid, session["user_id"]), one=True)
    if not t: return jsonify(error="Task not found"), 404
    db.ex("DELETE FROM study_tasks WHERE id=?", (tid,))
    return jsonify(ok=True)

@app.post("/planner/<int:pid>/regenerate")
@login_required
def plan_regenerate(pid):
    """Regenerate remaining (incomplete) tasks for a plan.

    Preserves completed tasks. Removes incomplete tasks and regenerates them
    using the rule-based engine with updated data.
    """
    p = db.q("SELECT * FROM study_plans WHERE id=? AND user_id=?", (pid, session["user_id"]), one=True)
    if not p: return jsonify(error="Plan not found"), 404

    # Get incomplete tasks' topics
    incomplete = db.q("SELECT DISTINCT topic FROM study_tasks WHERE plan_id=? AND completed=0", (pid,))
    if not incomplete:
        return jsonify(ok=True, message="No incomplete tasks to regenerate.")

    topics = [r["topic"] for r in incomplete]

    # Get performance data
    perf_rows = db.topic_rows()
    performance = analyze(perf_rows) if perf_rows else []
    priorities = planner_agent.calculate_topic_priorities(topics, performance)
    weak_topics = planner_agent.get_weak_topics(performance)

    # Delete incomplete tasks
    db.ex("DELETE FROM study_tasks WHERE plan_id=? AND completed=0", (pid,))

    # Generate new plan for remaining topics
    start = date.today()
    exam = date.fromisoformat(p["exam_date"]) if p["exam_date"] else None
    plan = planner_agent.generate_rule_based_plan(
        topics, priorities, weak_topics, p["daily_minutes"],
        p["days_available"], start, exam, p["preferred_study_time"],
    )

    # Get the last day number
    last = db.q("SELECT MAX(day_number) mn FROM study_tasks WHERE plan_id=?", (pid,), one=True)
    last_day = last["mn"] or 0

    # Insert new tasks
    for day in plan["days"]:
        for t in day["tasks"]:
            db.ex("INSERT INTO study_tasks(plan_id,day_number,task_date,topic,description,objective,duration_minutes,activity,priority) VALUES(?,?,?,?,?,?,?,?,?)",
                  (pid, last_day + day["day_number"], day["date"], t["topic"], t["description"],
                   t["description"], t["duration_minutes"], t["activity"], t["priority"]))

    return jsonify(ok=True, message=f"Regenerated {len(plan['days'])} days of tasks.")

if __name__ == "__main__":
    app.run(debug=True)
