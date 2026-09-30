from functools import wraps
from flask import session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import db

# ── Learning preference choices (shared with the frontend) ────────────
SUMMARY_STYLES = ("concise", "detailed")
QUIZ_LENGTHS = (5, 10, 15)
STUDY_TIMES = ("morning", "afternoon", "evening", "flexible")


def register_user(username, password, email=None):
    """Register a new user. Returns (user_id, error_message)."""
    if not username or not password:
        return None, "Username and password are required."
    if len(username) < 3:
        return None, "Username must be at least 3 characters."
    if len(password) < 6:
        return None, "Password must be at least 6 characters."
    existing = db.q("SELECT id FROM users WHERE username=?", (username,), one=True)
    if existing:
        return None, "Username already exists."
    pw_hash = generate_password_hash(password)
    uid = db.ex("INSERT INTO users(username,password_hash,email) VALUES(?,?,?)", (username, pw_hash, email))
    db.ex("INSERT OR IGNORE INTO user_preferences(user_id) VALUES(?)", (uid,))
    return uid, None


def verify_user(username, password):
    """Verify login credentials. Returns (user_dict, error_message)."""
    user = db.q("SELECT * FROM users WHERE username=?", (username,), one=True)
    if not user:
        return None, "Invalid username or password."
    if not check_password_hash(user["password_hash"], password):
        return None, "Invalid username or password."
    return {"id": user["id"], "username": user["username"], "email": user["email"]}, None


def login_required(f):
    """Decorator to require login for a route."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    """Get the currently logged-in user dict, or None."""
    return session.get("user")
def is_logged_in():
    """Check if a user is currently logged in."""
    return "user_id" in session


# ── Profile management ────────────────────────────────────────────────

def get_user(uid):
    """Get the full user record (safe columns only) for the profile page."""
    return db.q("SELECT id, username, email, full_name, course, created FROM users WHERE id=?", (uid,), one=True)


def update_profile(uid, full_name, course):
    """Update a user's display name and course/department."""
    db.ex("UPDATE users SET full_name=?, course=? WHERE id=?",
          (full_name or None, course or None, uid))


def change_password(uid, current, new):
    """Change a user's password after verifying the current one.

    Returns None on success, or an error message string.
    """
    user = db.q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if not user or not check_password_hash(user["password_hash"], current):
        return "Current password is incorrect."
    if len(new) < 6:
        return "New password must be at least 6 characters."
    db.ex("UPDATE users SET password_hash=? WHERE id=?",
          (generate_password_hash(new), uid))
    return None


# ── Learning preferences ──────────────────────────────────────────────

def get_preferences(uid):
    """Get a user's learning preferences, creating defaults if missing."""
    p = db.q("SELECT * FROM user_preferences WHERE user_id=?", (uid,), one=True)
    if not p:
        db.ex("INSERT OR IGNORE INTO user_preferences(user_id) VALUES(?)", (uid,))
        p = db.q("SELECT * FROM user_preferences WHERE user_id=?", (uid,), one=True)
    return p


def save_preferences(uid, summary_style, quiz_length, daily_minutes, study_time):
    """Save a user's learning preferences (validated by the caller)."""
    db.ex("UPDATE user_preferences SET summary_style=?,default_quiz_length=?,daily_study_goal_minutes=?,preferred_study_time=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
          (summary_style, quiz_length, daily_minutes, study_time, uid))
    db.ex("INSERT OR IGNORE INTO user_preferences(user_id,summary_style,default_quiz_length,daily_study_goal_minutes,preferred_study_time) VALUES(?,?,?,?,?)",
          (uid, summary_style, quiz_length, daily_minutes, study_time))
