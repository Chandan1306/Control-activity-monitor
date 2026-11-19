from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Lab(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    department = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    admins    = db.relationship('User',    backref='lab', lazy=True)
    machines  = db.relationship('Machine', backref='lab', lazy=True)
    subjects  = db.relationship('Subject', backref='lab', lazy=True)


class User(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    username   = db.Column(db.String(50), unique=True, nullable=False)
    password   = db.Column(db.String(200), nullable=False)
    lab_id     = db.Column(db.Integer, db.ForeignKey('lab.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Machine(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    lab_id       = db.Column(db.Integer, db.ForeignKey('lab.id'), nullable=False)
    pc_number    = db.Column(db.String(20), nullable=False)
    hostname     = db.Column(db.String(100))
    token        = db.Column(db.String(64), unique=True, nullable=False)
    last_seen    = db.Column(db.DateTime)
    is_online    = db.Column(db.Boolean, default=False)
    # Live state columns — updated on every heartbeat
    current_app    = db.Column(db.String(100))
    current_title  = db.Column(db.String(200))
    current_allowed = db.Column(db.Boolean, default=True)

    activities = db.relationship('Activity', backref='machine', lazy=True, cascade='all, delete-orphan')
    alerts     = db.relationship('Alert',    backref='machine', lazy=True, cascade='all, delete-orphan')
    stats      = db.relationship('MachineSessionStat', backref='machine', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('lab_id', 'pc_number', name='unique_lab_pc'),
    )


class Subject(db.Model):
    id     = db.Column(db.Integer, primary_key=True)
    lab_id = db.Column(db.Integer, db.ForeignKey('lab.id'), nullable=False)
    name   = db.Column(db.String(100), nullable=False)

    allowed_apps = db.relationship('AllowedApp', backref='subject', lazy=True, cascade='all, delete-orphan')
    sessions     = db.relationship('Session',    backref='subject', lazy=True)


class AllowedApp(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    subject_id  = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    app_name    = db.Column(db.String(100), nullable=False)
    allow_browser = db.Column(db.Boolean, default=False)


class Session(db.Model):
    """A lab session: master picks a subject and starts monitoring."""
    id         = db.Column(db.Integer, primary_key=True)
    lab_id     = db.Column(db.Integer, db.ForeignKey('lab.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at   = db.Column(db.DateTime)
    is_active  = db.Column(db.Boolean, default=True)

    activities = db.relationship('Activity', backref='session', lazy=True)
    alerts     = db.relationship('Alert',    backref='session', lazy=True)
    stats      = db.relationship('MachineSessionStat', backref='session', lazy=True, cascade='all, delete-orphan')


class Activity(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    machine_id   = db.Column(db.Integer, db.ForeignKey('machine.id'), nullable=False)
    session_id   = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=True)
    app_name     = db.Column(db.String(100))
    window_title = db.Column(db.String(200))
    is_allowed   = db.Column(db.Boolean, default=True)
    start_time   = db.Column(db.DateTime, default=datetime.utcnow)
    end_time     = db.Column(db.DateTime)


class Alert(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    machine_id     = db.Column(db.Integer, db.ForeignKey('machine.id'), nullable=False)
    session_id     = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=True)
    app_name       = db.Column(db.String(100))
    message        = db.Column(db.String(200))
    seen           = db.Column(db.Boolean, default=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    screenshot_path = db.Column(db.String(200))   # path to screenshot file, if captured


class MachineSessionStat(db.Model):
    """Tracks compliance stats per machine per session for real-time score."""
    __tablename__ = 'machine_session_stat'
    id                  = db.Column(db.Integer, primary_key=True)
    machine_id          = db.Column(db.Integer, db.ForeignKey('machine.id'), nullable=False)
    session_id          = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)
    total_heartbeats    = db.Column(db.Integer, default=0)
    allowed_heartbeats  = db.Column(db.Integer, default=0)
    violation_count     = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.UniqueConstraint('machine_id', 'session_id', name='unique_machine_session'),
    )

    @property
    def compliance_score(self):
        if self.total_heartbeats == 0:
            return 100
        return round((self.allowed_heartbeats / self.total_heartbeats) * 100)
