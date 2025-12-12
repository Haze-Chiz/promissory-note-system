from flask import Blueprint, render_template, redirect, url_for, request, send_file, flash, session
import pandas as pd
import io
import random
import string
from models import db, Account, ActiveSettings, ActiveCourse, SystemLog
from functools import wraps
from datetime import datetime

admin_bp = Blueprint("admin", __name__, url_prefix="/admin",
                     template_folder="templates")

#UTILITY FUNCTION
def generate_random_password(last_name, length=6):
    random_str = ''.join(random.choices(
        string.ascii_letters + string.digits, k=length))
    return f"{last_name}{random_str}"


def get_full_name(acc):
    parts = [acc.first_name, acc.middle_name, acc.last_name, acc.suffix]
    return " ".join([p for p in parts if p and p.strip()])


def require_role(role=None):
    def wrapper(func):
        @wraps(func)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("Access denied.", "danger")
                return redirect(url_for("login"))
            return func(*args, **kwargs)
        return decorated_function
    return wrapper


def log_action(user_name, action):
    """Helper to log system actions."""
    log = SystemLog(user_name=user_name, action=action,
                    timestamp=datetime.utcnow())
    db.session.add(log)
    db.session.commit()


def get_active_settings():
    settings = ActiveSettings.query.first()
    if not settings:
        return "Not Set", "Not Set"
    return settings.active_semester, settings.active_school_year

#DASHBOARD
@admin_bp.route("/dashboard")
@require_role("Admin")
def dashboard():
    total_active = Account.query.filter_by(_status="Active").count()
    total_inactive = Account.query.filter_by(_status="Inactive").count()
    total_active_students = Account.query.filter_by(
        _status="Active", _role="Student").count()
    total_active_finance = Account.query.filter_by(
        _status="Active", _role="Finance").count()
    total_active_admin = Account.query.filter_by(
        _status="Active", _role="Admin").count()

    active_settings = ActiveSettings.query.first()
    active_semester = active_settings.active_semester if active_settings else "Not Set"
    active_school_year = active_settings.active_school_year if active_settings else "Not Set"
    active_course = getattr(
        active_settings, 'active_course', 'Not Set (using list model)')

    data = {
        "total_active_accounts": total_active,
        "total_unactivated_accounts": total_inactive,
        "total_active_students": total_active_students,
        "total_active_finance": total_active_finance,
        "total_active_admin": total_active_admin,
        "admin_user": session.get("user_name", "Admin User"),
        "active_semester": active_semester,
        "active_school_year": active_school_year,
        "active_course": active_course
    }

    log_action(session.get("user_name", "Admin User"), "Viewed dashboard")
    return render_template("admin/dashboard.html", data=data)

#ACCOUNTS 
@admin_bp.route("/accounts")
@require_role("Admin")
def accounts():
    search = request.args.get("search", "").strip()
    role_filter = request.args.get("role", "").strip().capitalize()
    status_filter = request.args.get("status", "").strip().capitalize()
    page = request.args.get("page", 1, type=int)
    per_page = 10

    query = Account.query
    if search:
        query = query.filter(
            (Account.first_name.ilike(f"%{search}%")) |
            (Account.last_name.ilike(f"%{search}%")) |
            (Account.email.ilike(f"%{search}%"))
        )
    if role_filter:
        query = query.filter(Account._role == role_filter)
    if status_filter:
        query = query.filter(Account._status == status_filter)

    pagination = query.order_by(Account.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False)

    active_settings = ActiveSettings.query.first()
    active_semester = active_settings.active_semester if active_settings else "Not Set"
    active_school_year = active_settings.active_school_year if active_settings else "Not Set"
    active_course = getattr(active_settings, 'active_course', 'Not Set')

    log_action(session.get("user_name", "Admin User"), f"Viewed accounts page")

    return render_template(
        "admin/accounts.html",
        accounts=pagination.items,
        pagination=pagination,
        page=page,
        total_pages=pagination.pages,
        admin_user=session.get("user_name", "Admin User"),
        search=search,
        role_filter=role_filter,
        status_filter=status_filter,
        active_semester=active_semester,
        active_school_year=active_school_year,
        active_course=active_course
    )

#ADD NEW ACCOUNT
@admin_bp.route("/add_new_account", methods=["GET", "POST"])
@require_role("Admin")
def add_new_account():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if Account.query.filter_by(email=email).first():
            flash("Email already exists.", "danger")
            active_courses = ActiveCourse.query.order_by(
                ActiveCourse.name.asc()).all()
            return render_template("admin/add_new_account.html", active_courses=active_courses)

        last_name = request.form.get("lastName", "").strip()
        password = generate_random_password(last_name)
        role = request.form.get("role")

        account = Account(
            first_name=request.form.get("firstName", "").strip(),
            middle_name=request.form.get("middleName", "").strip(),
            last_name=last_name,
            suffix=request.form.get("suffix", "").strip(),
            email=email,
            role=role.capitalize(),
            status="Active"
        )

        if role == "Student":
            account.year_level = request.form.get("year_level")
            account.course = request.form.get("course")
        else:
            account.year_level = None
            account.course = None

        account.set_password(password)
        db.session.add(account)
        db.session.commit()

        log_action(session.get("user_name", "Admin User"),
                   f"Added new account: {account.full_name} ({email})")
        return redirect(url_for("admin.show_generated_password", pwd=password, email=email))

    active_courses = ActiveCourse.query.order_by(ActiveCourse.name.asc()).all()
    return render_template("admin/add_new_account.html", active_courses=active_courses)

#EDIT ACCOUNT 
@admin_bp.route("/edit_account/<int:account_id>", methods=["GET", "POST"])
@require_role("Admin")
def edit_account(account_id):
    account = Account.query.get_or_404(account_id)
    new_password = None

    if request.method == "POST":
        if "reset_password" in request.form:
            new_password = generate_random_password(account.last_name)
            account.set_password(new_password)
            db.session.commit()
            flash(
                f"Password reset successfully. New password: {new_password}", "success")
            log_action(session.get("user_name", "Admin User"),
                       f"Reset password for {account.full_name}")
        else:
            account.first_name = request.form.get("first_name").strip()
            account.middle_name = request.form.get("middle_name").strip()
            account.last_name = request.form.get("last_name").strip()
            account.suffix = request.form.get("suffix").strip()
            account.email = request.form.get("email").strip()

            role_value = request.form.get("role", "").strip().capitalize()
            status_value = request.form.get("status", "").strip().capitalize()
            setattr(account, '_role', role_value)
            setattr(account, '_status', status_value)

            if role_value == "Student":
                account.year_level = request.form.get("year_level")
                account.course = request.form.get("course")
            else:
                account.year_level = None
                account.course = None

            db.session.commit()
            flash("Account updated successfully", "success")
            log_action(session.get("user_name", "Admin User"),
                       f"Updated account: {account.full_name}")

        return redirect(url_for("admin.edit_account", account_id=account.id))

    active_courses = ActiveCourse.query.order_by(ActiveCourse.name.asc()).all()
    return render_template("admin/edit_account.html", account=account, new_password=new_password, active_courses=active_courses)

#SYSTEM LOGS
@admin_bp.route('/logs')
@require_role("Admin")
def logs():
    user_filter = request.args.get('user', '').strip()
    action_filter = request.args.get('action', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10

    query = SystemLog.query
    if user_filter:
        query = query.filter(SystemLog.user_name.ilike(f'%{user_filter}%'))
    if action_filter:
        query = query.filter(SystemLog.action.ilike(f'%{action_filter}%'))

    logs_pagination = query.order_by(SystemLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False)

    active_semester, active_school_year = get_active_settings()

    return render_template(
        'admin/logs.html',
        logs=logs_pagination,
        active_semester=active_semester,
        active_school_year=active_school_year,
        user_filter=user_filter,
        action_filter=action_filter,
        total_pages=logs_pagination.pages
    )

#ACTIVE SEMESTER
@admin_bp.route("/semester", methods=["GET", "POST"])
@require_role("Admin")
def semester():
    active_settings = ActiveSettings.query.first()
    if not active_settings:
        active_settings = ActiveSettings()
        db.session.add(active_settings)
        db.session.commit()

    if request.method == "POST":
        old_semester = active_settings.active_semester
        active_settings.active_semester = request.form.get(
            "semester", "").strip()
        db.session.commit()
        flash("Active semester updated successfully!", "success")
        log_action(session.get("user_name", "Admin User"),
                   f"Changed semester from '{old_semester}' to '{active_settings.active_semester}'")
        return redirect(url_for("admin.semester"))

    return render_template("admin/semester.html", active_semester=active_settings.active_semester)

#ACTIVE SCHOOL YEAR
@admin_bp.route("/school_year", methods=["GET", "POST"])
@require_role("Admin")
def school_year():
    active_settings = ActiveSettings.query.first()
    if not active_settings:
        active_settings = ActiveSettings()
        db.session.add(active_settings)
        db.session.commit()

    if request.method == "POST":
        old_year = active_settings.active_school_year
        active_settings.active_school_year = request.form.get(
            "school_year", "").strip()
        db.session.commit()
        flash("Active school year updated successfully!", "success")
        log_action(session.get("user_name", "Admin User"),
                   f"Changed school year from '{old_year}' to '{active_settings.active_school_year}'")
        return redirect(url_for("admin.school_year"))

    return render_template("admin/school_year.html", active_school_year=active_settings.active_school_year)

#ACTIVE COURSE
@admin_bp.route("/course", methods=["GET", "POST"])
@require_role("Admin")
def course():
    if request.method == "POST":
        course_name = request.form.get("course_name", "").strip()
        if not course_name:
            flash("Course name cannot be empty.", "danger")
            return redirect(url_for("admin.course"))

        existing_course = ActiveCourse.query.filter_by(
            name=course_name).first()
        if existing_course:
            flash(f"Course '{course_name}' is already active.", "warning")
            return redirect(url_for("admin.course"))

        new_course = ActiveCourse(name=course_name)
        db.session.add(new_course)
        db.session.commit()
        flash(
            f"Course '{course_name}' added to active list successfully!", "success")
        log_action(session.get("user_name", "Admin User"),
                   f"Added new course '{course_name}'")
        return redirect(url_for("admin.course"))

    active_courses = ActiveCourse.query.order_by(ActiveCourse.name.asc()).all()
    return render_template("admin/course.html", active_courses=active_courses)

#REMOVE COURSE
@admin_bp.route("/course/delete/<int:course_id>", methods=["POST"])
@require_role("Admin")
def delete_course(course_id):
    course = ActiveCourse.query.get_or_404(course_id)
    db.session.delete(course)
    db.session.commit()
    flash(f"Course '{course.name}' removed from active list.", "info")
    log_action(session.get("user_name", "Admin User"),
               f"Deleted course '{course.name}'")
    return redirect(url_for("admin.course"))

#IMPORT ACCOUNTS
@admin_bp.route("/upload_accounts", methods=["POST"])
@require_role("Admin")
def upload_accounts():
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("No file selected.", "warning")
        return redirect(url_for("admin.accounts"))

    try:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(file)
        elif file.filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(file)
        else:
            flash("Unsupported file type. Please use CSV or Excel.", "danger")
            return redirect(url_for("admin.accounts"))

        df = df.fillna("")
        uploaded_rows = []

        for _, row in df.iterrows():
            email = str(row.get("email")).strip()
            if not email or Account.query.filter_by(email=email).first():
                continue

            first_name = str(row.get("first_name")).strip()
            middle_name = str(row.get("middle_name")).strip()
            last_name = str(row.get("last_name")).strip()
            suffix = str(row.get("suffix")).strip()
            role = str(row.get("role")).strip().capitalize() or "Student"
            status = str(row.get("status")).strip().capitalize() or "Inactive"
            password = generate_random_password(last_name)

            acc = Account(
                first_name=first_name,
                middle_name=middle_name,
                last_name=last_name,
                suffix=suffix,
                email=email,
                _role=role,
                _status=status
            )
            if acc.role == "Student":
                acc.year_level = str(row.get("year_level")).strip()
                acc.course = str(row.get("course")).strip()

            acc.set_password(password)
            db.session.add(acc)
            uploaded_rows.append(acc.full_name)

        db.session.commit()
        if uploaded_rows:
            flash(
                f"Successfully uploaded {len(uploaded_rows)} accounts.", "success")
            log_action(session.get("user_name", "Admin User"),
                       f"Uploaded accounts: {', '.join(uploaded_rows)}")
        else:
            flash("No new accounts were added (all emails exist or invalid).", "info")

        return redirect(url_for("admin.accounts"))

    except Exception as e:
        db.session.rollback()
        flash(f"Upload failed: {str(e)}", "danger")
        return redirect(url_for("admin.accounts"))

#DOWNLOAD IMPORT ACCOUNT TEMPLATE
@admin_bp.route("/download_template")
@require_role("Admin")
def download_template():
    headers = ["first_name", "middle_name", "last_name", "suffix",
               "email", "role", "status", "year_level", "course"]
    df = pd.DataFrame(columns=headers)
    out = io.StringIO()
    df.to_csv(out, index=False)
    out.seek(0)
    log_action(session.get("user_name", "Admin User"),
               "Downloaded account upload template")
    return send_file(
        io.BytesIO(out.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="account_upload_template.csv"
    )

#EXPORT AS CSV
@admin_bp.route("/export_csv")
@require_role("Admin")
def export_csv():
    accounts = Account.query.all()
    data = [{
        "ID": a.id,
        "First_Name": a.first_name,
        "Middle_Name": a.middle_name,
        "Last_Name": a.last_name,
        "Suffix": a.suffix,
        "Email": a.email,
        "Role": a.role,
        "Status": a.status,
        "Year_Level": getattr(a, "year_level", ""),
        "Course": getattr(a, "course", ""),
        "Password": getattr(a, 'plain_password', 'N/A')
    } for a in accounts]

    df = pd.DataFrame(data)
    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)

    log_action(session.get("user_name", "Admin User"),
               "Exported all accounts to CSV")
    return send_file(io.BytesIO(output.getvalue().encode()),
                     mimetype="text/csv",
                     as_attachment=True,
                     download_name="accounts.csv")

#EXPORT AS EXCEL
@admin_bp.route("/export_excel")
@require_role("Admin")
def export_excel():
    accounts = Account.query.all()
    data = [{
        "ID": a.id,
        "First_Name": a.first_name,
        "Middle_Name": a.middle_name,
        "Last_Name": a.last_name,
        "Suffix": a.suffix,
        "Email": a.email,
        "Role": a.role,
        "Status": a.status,
        "Year_Level": getattr(a, "year_level", ""),
        "Course": getattr(a, "course", ""),
        "Password": getattr(a, 'plain_password', 'N/A')
    } for a in accounts]

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Accounts")

    log_action(session.get("user_name", "Admin User"),
               "Exported all accounts to Excel")
    return send_file(io.BytesIO(output.getvalue()),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True,
                     download_name="accounts.xlsx")

#LOGOUT
@admin_bp.route("/logout")
def logout():
    user_name = session.get("user_name", "Admin User")
    session.clear()
    flash("You have been logged out.", "danger")
    log_action(user_name, "Logged out")
    return redirect(url_for("login"))
