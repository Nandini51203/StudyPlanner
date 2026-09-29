from functools import wraps
from flask import session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import db


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
