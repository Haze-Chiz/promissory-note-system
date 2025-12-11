from flask import Blueprint, render_template, redirect, url_for, request, flash, session 
from functools import wraps
from datetime import datetime
from models import db, Account, PromissoryRequest, ActiveSettings
import os
from werkzeug.utils import secure_filename

student_bp = Blueprint("student", __name__,
                       url_prefix="/student", template_folder="templates")


def require_role(role=None):
    def wrapper(func):
        @wraps(func)
        def decorated(*args, **kwargs):
            user_id = session.get("user_id")
            if not user_id:
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))

            user = Account.query.get(user_id)
            if not user or user.status == "Inactive":
                flash("Your account is inactive. Please contact the admin.", "danger")
                return redirect(url_for("student.inactive_notice"))

            if role and user.role != role:
                flash("Access denied.", "danger")
                return redirect(url_for("login"))

            return func(*args, **kwargs)
        return decorated
    return wrapper


def get_full_name(acc):
    return " ".join(filter(None, [acc.first_name, acc.middle_name, acc.last_name, getattr(acc, "suffix", "")]))


def save_file(file_obj, student_id, category="reason"):
    if not file_obj or not getattr(file_obj, 'filename', None):
        return None

    parts = file_obj.filename.rsplit('.', 1)
    ext = parts[1].lower() if len(parts) > 1 else ''

    student_folder = os.path.join('static', 'uploads', f'student_{student_id}')
    os.makedirs(student_folder, exist_ok=True)

    existing = [f for f in os.listdir(student_folder) if f.startswith(category)]
    numbers = []
    for f in existing:
        try:
            numbers.append(int(f.rsplit('_', 1)[-1].split('.')[0]))
        except ValueError:
            continue
    next_num = max(numbers) + 1 if numbers else 1

    filename = f"{category}_{next_num}{'.' + ext if ext else ''}"
    filepath = os.path.join(student_folder, filename)
    file_obj.save(filepath)

    return f"uploads/student_{student_id}/{filename}"


@student_bp.route("/inactive")
def inactive_notice():
    return render_template("student/inactive_notice.html")


@student_bp.route("/dashboard")
@require_role("Student")
def dashboard():
    student = Account.query.get(session["user_id"])
    total_promissory = PromissoryRequest.query.filter_by(
        student_id=student.id).count()
    active_promissory = PromissoryRequest.query.filter_by(
        student_id=student.id, status="Pending").count()

    recent_requests = PromissoryRequest.query.filter(
        PromissoryRequest.student_id == student.id,
        PromissoryRequest.status.in_(["Approved", "Rejected"])
    ).order_by(PromissoryRequest.requested_at.desc()).limit(5).all()

    rejected_requests = PromissoryRequest.query.filter_by(
        student_id=student.id, status="Rejected").all()
    incomplete_requests = PromissoryRequest.query.filter(
        PromissoryRequest.student_id == student.id,
        (PromissoryRequest.reason_doc == None) | (
            PromissoryRequest.valid_id == None)
    ).all()

    data = {
        "full_name": get_full_name(student),
        "role": student.role,
        "total_promissory": total_promissory,
        "active_promissory": active_promissory,
        "current_time": datetime.now().strftime("%B %d, %Y %I:%M %p")
    }

    return render_template("student/dashboard.html",
                           data=data,
                           recent_requests=recent_requests,
                           rejected_requests=rejected_requests,
                           incomplete_requests=incomplete_requests)



@student_bp.route("/request", methods=["GET", "POST"])
@require_role("Student")
def request_promissory():
    student = Account.query.get(session["user_id"])
    active_settings = ActiveSettings.query.first()
    semester, school_year = (
        (active_settings.active_semester, active_settings.active_school_year)
        if active_settings else ("Not Set", "Not Set")
    )

    if request.method == "POST":
        reason_text = request.form.get("reason_text", "").strip()
        semester_type = request.form.get("semester_type")

        reason_file = request.files.get("reason_doc")
        valid_id_file = request.files.get("valid_id")

        reason_doc = save_file(reason_file, student.id, category="reason") if reason_file else None
        valid_id = save_file(valid_id_file, student.id, category="valid_id") if valid_id_file else None

        existing_request = PromissoryRequest.query.filter_by(
            student_id=student.id,
            semester_type=semester_type,
            semester=semester,
            school_year=school_year
        ).order_by(PromissoryRequest.requested_at.desc()).first()

        if existing_request:
            if existing_request.status == "Approved":
                flash(
                    f"Your {semester_type} request for {semester} ({school_year}) is already approved.", "info"
                )
                return redirect(url_for("student.request_promissory"))
            elif existing_request.status == "Pending":
                flash(
                    f"You already have a pending {semester_type} request for {semester} ({school_year}).", "danger"
                )
                return redirect(url_for("student.request_promissory"))

        if not reason_text and not reason_doc:
            flash("Please provide a reason or upload a document.", "danger")
            return redirect(url_for("student.request_promissory"))

        new_request = PromissoryRequest(
            student_id=student.id,
            year_level=student.year_level,
            course=student.course,
            email=student.email,
            reason_text=reason_text or None,
            reason_doc=reason_doc,
            valid_id=valid_id,
            semester_type=semester_type,
            semester=semester,
            school_year=school_year,
            status="Pending",
            requested_at=datetime.utcnow()
        )

        db.session.add(new_request)
        db.session.commit()

        flash("Your promissory request has been submitted.", "success")
        return redirect(url_for("student.request_promissory"))

    return render_template(
        "student/request.html",
        student=student,
        active_semester=semester,
        active_school_year=school_year
    )


@student_bp.route("/history")
@require_role("Student")
def history():
    student = Account.query.get(session["user_id"])
    query = PromissoryRequest.query.filter_by(student_id=student.id)

    # Apply filters
    for key in ["status", "semester", "semester_type", "school_year"]:
        value = request.args.get(key, "").strip()
        if value:
            query = query.filter(getattr(PromissoryRequest, key) == value)

    requests = query.order_by(PromissoryRequest.requested_at.desc()).all()

    school_years = [sy[0] for sy in db.session.query(PromissoryRequest.school_year)
                    .filter_by(student_id=student.id)
                    .distinct()
                    .order_by(PromissoryRequest.school_year.desc())
                    .all()]

    return render_template(
        "student/history.html",
        student=student,
        requests=requests,
        school_years=school_years
    )


@student_bp.route("/delete_request/<int:request_id>", methods=["POST"])
@require_role("Student")
def delete_request(request_id):
    student_id = session["user_id"]
    req = PromissoryRequest.query.filter_by(
        id=request_id, student_id=student_id).first()
    if not req:
        flash("Request not found.", "danger")
    elif req.status != "Pending":
        flash("Only pending requests can be deleted.", "warning")
    else:
        db.session.delete(req)
        db.session.commit()
        flash("Pending request has been deleted.", "success")
    return redirect(url_for("student.history"))


@student_bp.route("/setup", methods=["GET", "POST"])
@require_role("Student")
def setup():
    student = Account.query.get(session["user_id"])
    db.session.refresh(student)

    if request.method == "POST":

        for field in ["username", "first_name", "middle_name", "last_name", "email", "phone"]:
            value = request.form.get(field)
            if value is not None and value.strip() != "":
                setattr(student, field, value)

        password = request.form.get("password")
        if password is not None and password.strip() != "":
            student.set_password(password)

        db.session.commit()
        flash("Password updated successfully!", "success")
        return redirect(url_for("student.setup"))

    return render_template(
        "student/setup.html",
        student=student,
        student_user=session.get("user_name", "Student User")
    )


@student_bp.route("/view_request/<int:request_id>")
@require_role("Student")
def view_request(request_id):
    student_id = session["user_id"]
    student = Account.query.get(student_id)
    req = PromissoryRequest.query.filter_by(
        id=request_id, student_id=student_id).first()
    if not req:
        flash("Request not found.", "danger")
        return redirect(url_for("student.history"))

    return render_template("student/view_request.html", student=student, request=req)


@student_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))
