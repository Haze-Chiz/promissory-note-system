from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name = db.Column(db.String(50), nullable=False)
    middle_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50), nullable=False)
    suffix = db.Column(db.String(10))
    email = db.Column(db.String(100), unique=True, nullable=False)
    _role = db.Column("role", db.String(20), nullable=False)
    _status = db.Column("status", db.String(20), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    plain_password = db.Column(db.String(100), nullable=False)
    year_level = db.Column(db.String(20))
    course = db.Column(db.String(100))

    @property
    def role(self):
        return self._role

    @role.setter
    def role(self, value):
        self._role = value.capitalize() if value else value

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        self._status = value.capitalize() if value else value

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.plain_password = password

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        parts = [self.first_name, self.middle_name,
                 self.last_name, self.suffix]
        return " ".join([p for p in parts if p])


class PromissoryRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey(
        'account.id'), nullable=False)
    student = db.relationship("Account", backref="promissory_requests")

    year_level = db.Column(db.String(20), nullable=False)
    course = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)

    reason_text = db.Column(db.Text)
    reason_doc = db.Column(db.String(255))
    valid_id = db.Column(db.String(255))

    semester_type = db.Column(db.String(50))
    semester = db.Column(db.String(50))
    school_year = db.Column(db.String(20))

    status = db.Column(db.String(20), default="Pending")
    comments = db.Column(db.Text)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<PromissoryRequest {self.id} by {self.student.full_name}>"


class ActiveSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    active_semester = db.Column(db.String(50), default="Not Set")
    active_school_year = db.Column(db.String(20), default="Not Set")

    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<ActiveSettings Semester={self.active_semester}, SY={self.active_school_year}>"


class ActiveCourse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ActiveCourse {self.name}>"
