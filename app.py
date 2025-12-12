from flask import Flask, redirect, url_for, render_template, request, flash, session
from functools import wraps
from datetime import datetime
from models import db, Account, SystemLog
from admin_routes import admin_bp
from finance_routes import finance_bp
from student_routes import student_bp
import os
from datetime import datetime, timedelta


# --- Initialize Flask app ---
app = Flask(__name__)

# --- Configuration ---
app.secret_key = "your_super_secret_key_123"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///promissory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# --- Register Blueprints ---
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(finance_bp, url_prefix="/finance")
app.register_blueprint(student_bp, url_prefix="/student")

# --- Helper Functions ---
def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("Access denied.", "danger")
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapped
    return decorator

def log_action(user_email, action):
    """Record system log for login/logout actions."""
    log = SystemLog(user_name=user_email, action=action, timestamp=datetime.utcnow())
    db.session.add(log)
    db.session.commit()

# --- Route Protection ---
@app.before_request
def protect_admin_routes():
    if request.path.startswith("/admin"):
        if "user_id" not in session or session.get("role") != "Admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("login"))

# --- Routes ---
@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        remember = request.form.get("remember")  # <-- NEW

        user = Account.query.filter_by(email=email).first()

        if user and user.check_password(password):

            # Make session permanent if "Remember Me" is checked
            if remember:
                session.permanent = True  # cookie persists
                app.permanent_session_lifetime = timedelta(days=30)
            else:
                session.permanent = False  # session ends on browser close

            session["user_id"] = user.id
            session["role"] = user.role
            session["user_name"] = f"{user.first_name} {user.last_name}"

            log_action(user.email, "Logged in")

            if user.role == "Admin":
                return redirect(url_for("admin.dashboard"))
            elif user.role == "Finance":
                return redirect(url_for("finance.dashboard"))
            elif user.role == "Student":
                return redirect(url_for("student.dashboard"))
            else:
                flash("Unknown role. Contact administrator.", "danger")
                return redirect(url_for("login"))

        else:
            flash("Invalid email or password", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    user_email = session.get("user_name") or "Unknown"
    log_action(user_email, "Logged out")
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

# --- Example Finance Dashboard for testing ---
@app.route("/finance/dashboard")
@login_required(role="Finance")
def finance_dashboard():
    return "<h1>Finance Dashboard</h1>"

# --- Initialize DB and run app ---
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
