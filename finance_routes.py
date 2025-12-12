from flask import Blueprint, render_template, redirect, url_for, request, send_file, flash, session, Response
import pandas as pd
import io
import csv
from models import db, Account, PromissoryRequest, ActiveSettings, ActiveCourse, SystemLog
from functools import wraps
from datetime import datetime
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from collections import defaultdict
import calendar
import json

finance_bp = Blueprint("finance", __name__,
                       url_prefix="/finance", template_folder="templates")


#UTILITY FUNCTION
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


def get_full_name(acc):
    return " ".join(filter(None, [acc.first_name, acc.middle_name, acc.last_name, acc.suffix]))


def get_active_settings():
    settings = ActiveSettings.query.first()
    return (
        settings.active_semester if settings else "Not Set",
        settings.active_school_year if settings else "Not Set"
    )


def log_action(user_name, action):
    log = SystemLog(user_name=user_name, action=action)
    db.session.add(log)
    db.session.commit()


#DASHBOARD
@finance_bp.route("/dashboard")
@require_role("Finance")
def dashboard():
    user_name = session.get("user_name", "Finance User")
    active_semester, active_school_year = get_active_settings()

    base_query = PromissoryRequest.query.filter_by(
        semester=active_semester,
        school_year=active_school_year
    )

    data = {
        "total_promissory": base_query.count(),
        "total_pending": base_query.filter_by(status="Pending").count(),
        "total_approved": base_query.filter_by(status="Approved").count(),
        "total_rejected": base_query.filter_by(status="Rejected").count(),
    }

    recent_requests = base_query.join(Account, PromissoryRequest.student_id == Account.id) \
        .filter(PromissoryRequest.status == "Pending") \
        .order_by(PromissoryRequest.requested_at.desc()) \
        .limit(5).all()

    recent_requests = [{
        "student_name": f"{r.student.first_name} {r.student.middle_name or ''} {r.student.last_name} {r.student.suffix or ''}",
        "course": r.course,
        "semester": r.semester,
        "semester_type": r.semester_type,
        "date_submitted": r.requested_at,
        "status": r.status
    } for r in recent_requests]

    log_action(user_name, "Viewed finance dashboard")

    return render_template(
        "finance/dashboard.html",
        finance_user=user_name,
        active_semester=active_semester,
        active_school_year=active_school_year,
        data=data,
        recent_requests=recent_requests
    )


#PROMISSORY LIST
@finance_bp.route("/promissory-notes")
@require_role("Finance")
def promissory_notes():
    user_name = session.get("user_name", "Finance User")
    active_semester, active_school_year = get_active_settings()

    all_courses = [c.name for c in ActiveCourse.query.order_by(ActiveCourse.name).all()]
    all_semesters = [s[0] for s in db.session.query(PromissoryRequest.semester).distinct()]
    all_semester_types = [s[0] for s in db.session.query(PromissoryRequest.semester_type).distinct()]
    all_school_years = [s[0] for s in db.session.query(
        PromissoryRequest.school_year).distinct().order_by(PromissoryRequest.school_year.desc())]

    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "Pending").capitalize()
    semester_filter = request.args.get("semester", active_semester)
    semester_type_filter = request.args.get("semester_type", "")
    school_year_filter = request.args.get("school_year", active_school_year)
    course_filter = request.args.get("course", "")
    export_format = request.args.get("export")
    page = request.args.get("page", 1, type=int)
    per_page = 8

    query = PromissoryRequest.query.join(
        Account, PromissoryRequest.student_id == Account.id
    )

    if search:
        term = f"%{search}%"
        query = query.filter(
            func.concat(Account.first_name, ' ', Account.last_name).ilike(term) |
            (Account.first_name.ilike(term)) |
            (Account.last_name.ilike(term))
        )

    if status_filter != "All":
        query = query.filter(PromissoryRequest.status == status_filter)
    if semester_filter:
        query = query.filter(PromissoryRequest.semester == semester_filter)
    if semester_type_filter:
        query = query.filter(PromissoryRequest.semester_type == semester_type_filter)
    if school_year_filter:
        query = query.filter(PromissoryRequest.school_year == school_year_filter)
    if course_filter:
        query = query.filter(PromissoryRequest.course == course_filter)

    results = query.options(joinedload(PromissoryRequest.student)) \
                   .order_by(PromissoryRequest.requested_at.desc()) \
                   .all()

    if export_format in ["csv", "excel"]:
        log_action(
            user_name,
            f"Exported promissory requests ({export_format.upper()}) "
            f"with filters: status={status_filter}, semester={semester_filter}, course={course_filter}"
        )
        return export_promissory_requests(results, export_format)

    pagination = query.options(joinedload(PromissoryRequest.student)) \
                      .order_by(PromissoryRequest.requested_at.desc()) \
                      .paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        "finance/promissory_notes.html",
        promissory_requests=pagination.items,
        finance_user=user_name,
        search=search,
        status_filter=status_filter,
        selected_semester=semester_filter,
        selected_semester_type=semester_type_filter,
        selected_school_year=school_year_filter,
        selected_course=course_filter,
        all_courses=all_courses,
        all_semesters=all_semesters,
        all_semester_types=all_semester_types,
        all_school_years=all_school_years,
        active_semester=active_semester,
        active_school_year=active_school_year,
        pagination=pagination,
        total_pages=pagination.pages
    )


#EXPORT PROMISSORY
def export_promissory_requests(results, export_format):
    data = [{
        "Student Name": f"{r.student.first_name} {r.student.middle_name or ''} {r.student.last_name} {r.student.suffix or ''}",
        "Course": r.course,
        "Year Level": r.year_level,
        "Semester": r.semester,
        "Semester Type": r.semester_type,
        "Status": r.status
    } for r in results]

    if export_format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
        output.seek(0)
        return send_file(io.BytesIO(output.getvalue().encode()), mimetype="text/csv",
                         as_attachment=True, download_name="promissory_requests.csv")

    elif export_format == "excel":
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Promissory Requests')
        output.seek(0)
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="promissory_requests.xlsx"
        )


#ALL PROMISSORY ANALYTICS
@finance_bp.route("/all-promissory")
@require_role("Finance")
def all_promissory():
    active_semester, active_school_year = get_active_settings()

    course_filter = request.args.get("course", "").strip() or None
    semester_filter = request.args.get("semester", active_semester)
    if semester_filter == "all":
        semester_filter = None

    status_filter = request.args.get("status", "all").lower()
    semester_type_filter = request.args.get("semester_type", "").strip() or None
    school_year_filter = request.args.get("school_year", active_school_year).strip()
    if school_year_filter.lower() == "all":
        school_year_filter = None

    all_students_query = Account.query.filter(Account._role == "Student")
    if course_filter:
        all_students_query = all_students_query.filter(Account.course == course_filter)

    all_students = all_students_query.all()
    total_students = len(all_students)

    requests_query = PromissoryRequest.query.join(
        Account, PromissoryRequest.student_id == Account.id
    )

    if course_filter:
        requests_query = requests_query.filter(PromissoryRequest.course == course_filter)
    if semester_filter:
        requests_query = requests_query.filter(PromissoryRequest.semester == semester_filter)
    if semester_type_filter:
        requests_query = requests_query.filter(PromissoryRequest.semester_type == semester_type_filter)
    if school_year_filter:
        requests_query = requests_query.filter(PromissoryRequest.school_year == school_year_filter)
    if status_filter != "all":
        requests_query = requests_query.filter(PromissoryRequest.status.ilike(status_filter))

    promissory_requests = requests_query.options(joinedload(PromissoryRequest.student)).all()

    export_format = request.args.get("export")
    if export_format in ("csv", "excel"):
        data = []
        for r in promissory_requests:
            student_name = f"{getattr(r.student, 'first_name', '')} {getattr(r.student, 'last_name', '')}".strip() or "N/A"
            data.append({
                "Student Name": student_name,
                "Course": r.course,
                "Semester": r.semester,
                "Semester Type": r.semester_type,
                "School Year": r.school_year,
                "Date Submitted": r.requested_at.strftime("%b %d, %Y"),
                "Status": r.status
            })

        df = pd.DataFrame(data)
        output = io.BytesIO()

        if export_format == "csv":
            return Response(
                df.to_csv(index=False),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=promissory_requests.csv"}
            )
        else:
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Promissory Requests')
            output.seek(0)
            return Response(
                output,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=promissory_requests.xlsx"}
            )

    unique_student_ids = {r.student_id for r in promissory_requests}
    total_requested = len(unique_student_ids)
    selected_status = status_filter

    courses = [c[0] for c in db.session.query(PromissoryRequest.course).distinct()]
    semesters = [s[0] for s in db.session.query(PromissoryRequest.semester).distinct()]
    semester_types = [s[0] for s in db.session.query(PromissoryRequest.semester_type).distinct()]
    school_years = sorted(
        [y[0] for y in db.session.query(PromissoryRequest.school_year).distinct()],
        key=lambda x: int(x.split('-')[0])
    )

    monthly_course_counts = defaultdict(lambda: [0]*12)
    course_student_counts = defaultdict(set)

    for r in promissory_requests:
        idx = r.requested_at.month - 1
        monthly_course_counts[r.course][idx] += 1
        course_student_counts[r.course].add(r.student_id)

    top_course = max(monthly_course_counts.items(), key=lambda x: sum(x[1]))[0] if monthly_course_counts else "N/A"
    months = [calendar.month_abbr[i+1] for i in range(12)]
    top_course_monthly = monthly_course_counts.get(top_course, [0]*12)

    courses_sorted = [c for c, _ in sorted(
        ((course, len(students)) for course, students in course_student_counts.items()),
        key=lambda x: x[1]
    )]

    counts_sorted = [len(course_student_counts[c]) for c in courses_sorted]
    totals_sorted = [sum(1 for s in all_students if s.course == c) for c in courses_sorted]

    percentages_sorted = [
        round((counts_sorted[i] / totals_sorted[i]) * 100, 2) if totals_sorted[i] else 0
        for i in range(len(courses_sorted))
    ]

    sorted_percentages = sorted(
        zip(courses_sorted, percentages_sorted), key=lambda x: x[1], reverse=True
    )

    if sorted_percentages:
        percentage_courses_sorted, percentages_sorted_desc = zip(*sorted_percentages)
    else:
        percentage_courses_sorted, percentages_sorted_desc = [], []

    bar_data = {
        "labels": ["Total Students", "Requested Promissory"],
        "values": [total_students, total_requested]
    }

    return render_template(
        "finance/all_promissory.html",
        finance_user=session.get("user_name", "Finance User"),
        courses=courses,
        semesters=semesters,
        semester_types=semester_types,
        school_years=school_years,
        selected_course=course_filter or "",
        selected_semester=semester_filter or "",
        selected_semester_type=semester_type_filter or "",
        selected_school_year=school_year_filter or "",
        selected_status=selected_status,
        total_students=total_students,
        total_requested=total_requested,
        active_semester=active_semester,
        active_school_year=active_school_year,
        bar_data=json.dumps(bar_data),
        top_course=top_course,
        months=json.dumps(months),
        monthly_counts=json.dumps(top_course_monthly),
        courses_sorted=json.dumps(courses_sorted),
        counts_sorted=json.dumps(counts_sorted),
        totals_sorted=json.dumps(totals_sorted),
        percentages_sorted=json.dumps(percentages_sorted),
        percentage_courses_sorted=json.dumps(percentage_courses_sorted),
        percentages_sorted_desc=json.dumps(percentages_sorted_desc)
    )


#STUDENTS PROMISSORY LIST
@finance_bp.route("/students-promissory")
@require_role("Finance")
def students_promissory():
    page = request.args.get("page", 1, type=int)
    per_page = 10
    export_format = request.args.get("export", None)

    active_semester, active_school_year = get_active_settings()

    all_courses = [c.name for c in ActiveCourse.query.order_by(ActiveCourse.name).all()]
    all_semesters = [s[0] for s in db.session.query(PromissoryRequest.semester).distinct()]
    all_school_years = [s[0] for s in db.session.query(PromissoryRequest.school_year).distinct()]

    search = request.args.get("search", "").strip()
    selected_semester = request.args.get("semester", None)
    selected_semester_type = request.args.get("semester_type", None)
    selected_course = request.args.get("course", None)
    selected_year_level = request.args.get("year_level", None)
    selected_school_year = request.args.get("school_year", None)

    if selected_semester is None and 'page' not in request.args:
        selected_semester = active_semester
    if selected_school_year is None and 'page' not in request.args:
        selected_school_year = active_school_year

    students_query = db.session.query(Account).filter(Account._role == "Student")

    if search:
        term = f"%{search}%"
        students_query = students_query.filter(
            func.concat(Account.first_name, ' ', Account.last_name).ilike(term) |
            Account.first_name.ilike(term) |
            Account.last_name.ilike(term)
        )

    if selected_course:
        students_query = students_query.filter(Account.course == selected_course)

    if selected_year_level:
        students_query = students_query.filter(Account.year_level == selected_year_level)

    requests_query = db.session.query(
        PromissoryRequest.student_id,
        func.count(PromissoryRequest.id).label("requests_count")
    ).group_by(PromissoryRequest.student_id)

    if selected_semester:
        requests_query = requests_query.filter(PromissoryRequest.semester == selected_semester)
    if selected_semester_type:
        requests_query = requests_query.filter(PromissoryRequest.semester_type == selected_semester_type)
    if selected_course:
        requests_query = requests_query.filter(PromissoryRequest.course == selected_course)
    if selected_school_year:
        requests_query = requests_query.filter(PromissoryRequest.school_year == selected_school_year)

    requests_subq = requests_query.subquery()

    students_query = students_query.outerjoin(
        requests_subq, requests_subq.c.student_id == Account.id
    ).add_columns(
        func.coalesce(requests_subq.c.requests_count, 0).label("requests_count")
    )

    students_query = students_query.filter(
        func.coalesce(requests_subq.c.requests_count, 0) > 0
    )

    students_query = students_query.order_by(
        func.coalesce(requests_subq.c.requests_count, 0).desc(),
        Account.last_name
    )

    if export_format in ["csv", "excel"]:
        students_data = students_query.all()
        data = [{
            "Student Name": get_full_name(s[0]),
            "Course": s[0].course,
            "Year Level": s[0].year_level,
            "Semester": selected_semester or "All",
            "Semester Type": selected_semester_type or "All",
            "School Year": selected_school_year or "All",
            "Requests Count": s[1]
        } for s in students_data]

        df = pd.DataFrame(data)
        output = io.BytesIO()

        if export_format == "csv":
            df.to_csv(output, index=False)
            output.seek(0)
            return send_file(output, mimetype="text/csv",
                             download_name="students_promissory.csv",
                             as_attachment=True)
        else:
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False,
                            sheet_name="Students Promissory")
            output.seek(0)
            return send_file(
                output,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                download_name="students_promissory.xlsx",
                as_attachment=True
            )

    students = students_query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        "finance/students_promissory.html",
        students=students,
        finance_user=session.get("user_name", "Finance User"),
        active_semester=active_semester,
        active_school_year=active_school_year,
        search=search,
        selected_semester=selected_semester,
        selected_semester_type=selected_semester_type,
        selected_course=selected_course,
        selected_year_level=selected_year_level,
        selected_school_year=selected_school_year,
        all_courses=all_courses,
        all_semesters=all_semesters,
        all_school_years=all_school_years
    )


#UPDATE PROMISSORY 
@finance_bp.route("/promissory/<int:promissory_id>/update", methods=["POST"])
@require_role("Finance")
def update_promissory(promissory_id):
    user_name = session.get("user_name", "Finance User")
    promissory_req = PromissoryRequest.query.get_or_404(promissory_id)

    action = request.form.get("action")
    old_status = promissory_req.status

    if action in ["approve", "reject"]:
        promissory_req.status = "Approved" if action == "approve" else "Rejected"

    promissory_req.comments = request.form.get("comments", "").strip()
    promissory_req.updated_at = datetime.now()

    db.session.commit()

    log_action(
        user_name,
        f"{action.capitalize()}d promissory note ID {promissory_id} (from {old_status} to {promissory_req.status})"
    )

    flash(f"Promissory Note {action.capitalize()}d successfully.", "success")
    return redirect(url_for("finance.view_promissory", promissory_id=promissory_id))


#VIEW PROMISSORY DETAILS 
@finance_bp.route("/promissory/<int:promissory_id>")
@require_role("Finance")
def view_promissory(promissory_id):
    user_name = session.get("user_name", "Finance User")
    promissory_req = PromissoryRequest.query.get(promissory_id)

    if not promissory_req:
        flash("The selected promissory note was not found or has been deleted.", "warning")
        return render_template(
            "finance/promissory_details.html",
            student=None,
            promissory_data=None,
            promissory_history=[],
            finance_user=user_name
        )

    student = promissory_req.student

    history_query = PromissoryRequest.query.filter_by(
        student_id=student.id
    ).order_by(PromissoryRequest.requested_at.desc()).all()

    promissory_data = {
        "note_id": promissory_req.id,
        "reason_text": promissory_req.reason_text,
        "reason_doc": promissory_req.reason_doc,
        "valid_id": promissory_req.valid_id,
        "comments": promissory_req.comments,
        "semester": promissory_req.semester or "N/A",
        "semester_type": promissory_req.semester_type or "N/A",
        "date_submitted": promissory_req.requested_at.strftime('%b %d, %Y')
    }

    promissory_history = [{
        "date": r.requested_at.strftime('%b %d, %Y'),
        "note_id": r.id,
        "semester": r.semester or "N/A",
        "semester_type": r.semester_type or "N/A",
        "status": r.status
    } for r in history_query]

    log_action(user_name, f"Viewed promissory note ID {promissory_id} details")

    return render_template(
        "finance/promissory_details.html",
        student=student,
        promissory_data=promissory_data,
        promissory_history=promissory_history,
        finance_user=user_name
    )


#LOGOUT
@finance_bp.route("/logout")
def logout():
    user_name = session.get("user_name", "Finance User")
    session.clear()
    flash("You have been logged out.", "danger")

    log_action(user_name, "Logged out")
    return redirect(url_for("login"))
