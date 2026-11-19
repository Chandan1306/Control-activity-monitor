from flask import Blueprint, request, jsonify, send_from_directory, current_app, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, Lab, Machine, Subject, AllowedApp, Session, Activity, Alert, MachineSessionStat
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import secrets, os, io

admin_bp = Blueprint('admin', __name__)

# In-memory set of paused machine IDs — no DB change needed
# {machine_id: True} means monitoring is paused for that machine
paused_machines: set = set()


def get_current_user():
    return User.query.get(int(get_jwt_identity()))


def lab_guard(user, lab_id):
    return user.lab_id == lab_id


# ── Dashboard (live snapshot) ─────────────────────────────────────────────────

@admin_bp.route('/labs/<int:lab_id>/dashboard', methods=['GET'])
@jwt_required()
def dashboard(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    machines = Machine.query.filter_by(lab_id=lab_id).order_by(Machine.pc_number).all()
    active_session = Session.query.filter_by(lab_id=lab_id, is_active=True).first()

    # mark machines offline if no heartbeat in last 15 seconds
    cutoff = datetime.utcnow() - timedelta(seconds=15)
    machine_data = []
    for m in machines:
        if m.is_online and m.last_seen and m.last_seen < cutoff:
            m.is_online = False
            db.session.commit()

        compliance_score = 100
        violation_count  = 0
        if active_session:
            stat = MachineSessionStat.query.filter_by(
                machine_id=m.id, session_id=active_session.id
            ).first()
            if stat:
                compliance_score = stat.compliance_score
                violation_count  = stat.violation_count

        unseen_alerts = Alert.query.filter_by(machine_id=m.id, seen=False).count()

        machine_data.append({
            'id':              m.id,
            'pc_number':       m.pc_number,
            'hostname':        m.hostname,
            'is_online':       m.is_online,
            'last_seen':       m.last_seen.isoformat() if m.last_seen else None,
            'current_app':     m.current_app,
            'current_title':   m.current_title,
            'current_allowed': m.current_allowed,
            'compliance_score': compliance_score,
            'violation_count': violation_count,
            'unseen_alerts':   unseen_alerts,
            'is_paused':       m.id in paused_machines,
        })

    session_data = None
    if active_session:
        session_data = {
            'id':           active_session.id,
            'subject_id':   active_session.subject_id,
            'subject_name': active_session.subject.name,
            'started_at':   active_session.started_at.isoformat(),
        }

    # unseen alert count for badge
    machine_ids = [m.id for m in machines]
    total_unseen = 0
    if machine_ids:
        total_unseen = Alert.query.filter(
            Alert.machine_id.in_(machine_ids), Alert.seen == False
        ).count()

    return jsonify({
        'machines':      machine_data,
        'active_session': session_data,
        'total_unseen':  total_unseen,
    })


# ── Machines ──────────────────────────────────────────────────────────────────

@admin_bp.route('/labs/<int:lab_id>/machines', methods=['GET'])
@jwt_required()
def get_machines(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    machines = Machine.query.filter_by(lab_id=lab_id).order_by(Machine.pc_number).all()
    return jsonify([{
        'id':         m.id,
        'pc_number':  m.pc_number,
        'hostname':   m.hostname,
        'token':      m.token,
        'is_online':  m.is_online,
        'last_seen':  m.last_seen.isoformat() if m.last_seen else None,
    } for m in machines])


@admin_bp.route('/labs/<int:lab_id>/machines', methods=['POST'])
@jwt_required()
def add_machine(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    data      = request.get_json()
    pc_number = (data.get('pc_number') or '').strip()
    if not pc_number:
        return jsonify({'msg': 'pc_number required'}), 400

    token   = secrets.token_hex(32)
    machine = Machine(
        lab_id=lab_id,
        pc_number=pc_number,
        hostname=data.get('hostname', ''),
        token=token
    )
    db.session.add(machine)
    db.session.commit()
    return jsonify({'id': machine.id, 'pc_number': machine.pc_number, 'token': token}), 201


@admin_bp.route('/labs/<int:lab_id>/machines/<int:machine_id>', methods=['DELETE'])
@jwt_required()
def delete_machine(lab_id, machine_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    machine = Machine.query.filter_by(id=machine_id, lab_id=lab_id).first_or_404()
    db.session.delete(machine)
    db.session.commit()
    return jsonify({'msg': 'Deleted'})


# ── Subjects & Allowed Apps ───────────────────────────────────────────────────

@admin_bp.route('/labs/<int:lab_id>/subjects', methods=['GET'])
@jwt_required()
def get_subjects(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    subjects = Subject.query.filter_by(lab_id=lab_id).all()
    return jsonify([{
        'id':   s.id,
        'name': s.name,
        'allowed_apps': [{
            'id':            a.id,
            'app_name':      a.app_name,
            'allow_browser': a.allow_browser
        } for a in s.allowed_apps]
    } for s in subjects])


@admin_bp.route('/labs/<int:lab_id>/subjects', methods=['POST'])
@jwt_required()
def add_subject(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    data = request.get_json()
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'msg': 'name required'}), 400

    subject = Subject(lab_id=lab_id, name=name)
    db.session.add(subject)
    db.session.flush()

    for app in data.get('allowed_apps', []):
        db.session.add(AllowedApp(
            subject_id    = subject.id,
            app_name      = (app.get('app_name') or '').strip(),
            allow_browser = app.get('allow_browser', False)
        ))

    db.session.commit()
    return jsonify({'id': subject.id, 'name': subject.name}), 201


@admin_bp.route('/labs/<int:lab_id>/subjects/<int:subject_id>', methods=['PUT'])
@jwt_required()
def update_subject(lab_id, subject_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    subject = Subject.query.filter_by(id=subject_id, lab_id=lab_id).first_or_404()
    data    = request.get_json()

    if 'name' in data:
        subject.name = data['name'].strip()

    if 'allowed_apps' in data:
        AllowedApp.query.filter_by(subject_id=subject.id).delete()
        for app in data['allowed_apps']:
            db.session.add(AllowedApp(
                subject_id    = subject.id,
                app_name      = (app.get('app_name') or '').strip(),
                allow_browser = app.get('allow_browser', False)
            ))

    db.session.commit()
    return jsonify({'msg': 'Updated'})


@admin_bp.route('/labs/<int:lab_id>/subjects/<int:subject_id>', methods=['DELETE'])
@jwt_required()
def delete_subject(lab_id, subject_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    subject = Subject.query.filter_by(id=subject_id, lab_id=lab_id).first_or_404()

    # Block deletion if this subject is used by an active session
    active = Session.query.filter_by(subject_id=subject_id, is_active=True).first()
    if active:
        return jsonify({'msg': 'Cannot delete — this subject has an active session. End the session first.'}), 409

    # Nullify subject_id on past (ended) sessions before deleting
    past_sessions = Session.query.filter_by(subject_id=subject_id, is_active=False).all()
    for s in past_sessions:
        s.subject_id = None  # won't hit NOT NULL since we checked active above

    db.session.delete(subject)
    db.session.commit()
    return jsonify({'msg': 'Deleted'})


# ── Sessions ──────────────────────────────────────────────────────────────────

@admin_bp.route('/labs/<int:lab_id>/sessions/active', methods=['GET'])
@jwt_required()
def get_active_session(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    session = Session.query.filter_by(lab_id=lab_id, is_active=True).first()
    if not session:
        return jsonify(None)

    return jsonify({
        'id':           session.id,
        'subject_id':   session.subject_id,
        'subject_name': session.subject.name,
        'started_at':   session.started_at.isoformat(),
    })


@admin_bp.route('/labs/<int:lab_id>/sessions/start', methods=['POST'])
@jwt_required()
def start_session(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    # end any existing active session
    existing = Session.query.filter_by(lab_id=lab_id, is_active=True).first()
    if existing:
        existing.is_active = False
        existing.ended_at  = datetime.utcnow()

    data       = request.get_json()
    subject_id = data.get('subject_id')
    subject    = Subject.query.filter_by(id=subject_id, lab_id=lab_id).first_or_404()

    new_session = Session(lab_id=lab_id, subject_id=subject.id)
    db.session.add(new_session)
    db.session.commit()
    return jsonify({'id': new_session.id, 'subject_name': subject.name}), 201


@admin_bp.route('/labs/<int:lab_id>/sessions/end', methods=['POST'])
@jwt_required()
def end_session(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    session = Session.query.filter_by(lab_id=lab_id, is_active=True).first()
    if not session:
        return jsonify({'msg': 'No active session'}), 404

    session.is_active = False
    session.ended_at  = datetime.utcnow()
    db.session.commit()

    # build session report
    report = _build_session_report(session)
    return jsonify({'msg': 'Session ended', 'report': report})


def _build_session_report(session):
    """Compute per-machine stats for the session summary popup."""
    stats = MachineSessionStat.query.filter_by(session_id=session.id).all()
    machine_reports = []
    for stat in stats:
        machine_reports.append({
            'pc_number':        stat.machine.pc_number,
            'compliance_score': stat.compliance_score,
            'violation_count':  stat.violation_count,
            'total_heartbeats': stat.total_heartbeats,
        })

    # sort by most violations first
    machine_reports.sort(key=lambda x: x['violation_count'], reverse=True)

    # top violating apps
    alerts = Alert.query.filter_by(session_id=session.id).all()
    app_counts = {}
    for a in alerts:
        app_counts[a.app_name] = app_counts.get(a.app_name, 0) + 1
    top_apps = sorted(app_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    duration_secs = 0
    if session.ended_at and session.started_at:
        duration_secs = int((session.ended_at - session.started_at).total_seconds())

    return {
        'subject_name':   session.subject.name,
        'started_at':     session.started_at.isoformat(),
        'ended_at':       session.ended_at.isoformat(),
        'duration_secs':  duration_secs,
        'total_alerts':   len(alerts),
        'machines':       machine_reports,
        'top_apps':       [{'app': a[0], 'count': a[1]} for a in top_apps],
    }


# ── Alerts ────────────────────────────────────────────────────────────────────

@admin_bp.route('/labs/<int:lab_id>/alerts', methods=['GET'])
@jwt_required()
def get_alerts(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    unseen_only = request.args.get('unseen_only', 'false') == 'true'
    machine_ids = [m.id for m in Machine.query.filter_by(lab_id=lab_id).all()]

    query = Alert.query.filter(Alert.machine_id.in_(machine_ids))
    if unseen_only:
        query = query.filter_by(seen=False)

    alerts = query.order_by(Alert.created_at.desc()).limit(200).all()
    return jsonify([{
        'id':              a.id,
        'pc_number':       a.machine.pc_number,
        'app_name':        a.app_name,
        'message':         a.message,
        'seen':            a.seen,
        'created_at':      a.created_at.isoformat(),
        'screenshot_path': a.screenshot_path,
    } for a in alerts])


@admin_bp.route('/labs/<int:lab_id>/alerts/mark-seen', methods=['POST'])
@jwt_required()
def mark_alerts_seen(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    machine_ids = [m.id for m in Machine.query.filter_by(lab_id=lab_id).all()]
    Alert.query.filter(
        Alert.machine_id.in_(machine_ids),
        Alert.seen == False
    ).update({'seen': True}, synchronize_session=False)
    db.session.commit()
    return jsonify({'msg': 'Marked seen'})


# ── Machine activity timeline ─────────────────────────────────────────────────

@admin_bp.route('/labs/<int:lab_id>/machines/<int:machine_id>/activities', methods=['GET'])
@jwt_required()
def get_machine_activities(lab_id, machine_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    machine    = Machine.query.filter_by(id=machine_id, lab_id=lab_id).first_or_404()
    session_id = request.args.get('session_id', type=int)

    query = Activity.query.filter_by(machine_id=machine.id)
    if session_id:
        query = query.filter_by(session_id=session_id)
    activities = query.order_by(Activity.start_time.desc()).limit(80).all()

    return jsonify([{
        'app_name':     a.app_name,
        'window_title': a.window_title,
        'is_allowed':   a.is_allowed,
        'start_time':   a.start_time.isoformat(),
        'end_time':     a.end_time.isoformat() if a.end_time else None,
    } for a in activities])


# ── Serve screenshots ─────────────────────────────────────────────────────────

@admin_bp.route('/screenshots/<path:filename>', methods=['GET'])
def serve_screenshot(filename):
    screenshots_dir = os.path.join(current_app.root_path, 'screenshots')
    return send_from_directory(screenshots_dir, filename)


# ── History ───────────────────────────────────────────────────────────────────

@admin_bp.route('/labs/<int:lab_id>/history/sessions', methods=['GET'])
@jwt_required()
def session_history(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    sessions = Session.query.filter_by(lab_id=lab_id, is_active=False)\
        .order_by(Session.started_at.desc()).limit(50).all()

    result = []
    for s in sessions:
        duration = 0
        if s.started_at and s.ended_at:
            duration = int((s.ended_at - s.started_at).total_seconds())

        alert_count = Alert.query.filter_by(session_id=s.id).count()
        machine_ids = [m.id for m in Machine.query.filter_by(lab_id=lab_id).all()]
        from models import MachineSessionStat
        stats = MachineSessionStat.query.filter_by(session_id=s.id).all()
        avg_compliance = 0
        if stats:
            avg_compliance = round(sum(st.compliance_score for st in stats) / len(stats))

        result.append({
            'id':             s.id,
            'subject_name':   s.subject.name if s.subject else 'Deleted Subject',
            'started_at':     s.started_at.isoformat() if s.started_at else None,
            'ended_at':       s.ended_at.isoformat() if s.ended_at else None,
            'duration_secs':  duration,
            'alert_count':    alert_count,
            'avg_compliance': avg_compliance,
            'machines_count': len(stats),
        })

    return jsonify(result)


@admin_bp.route('/labs/<int:lab_id>/history/machines', methods=['GET'])
@jwt_required()
def machine_history(lab_id):
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    machines = Machine.query.filter_by(lab_id=lab_id).order_by(Machine.pc_number).all()
    result = []
    for m in machines:
        total_alerts = Alert.query.filter_by(machine_id=m.id).count()
        total_activities = Activity.query.filter_by(machine_id=m.id).count()
        from models import MachineSessionStat
        stats = MachineSessionStat.query.filter_by(machine_id=m.id).all()
        avg_compliance = 0
        if stats:
            avg_compliance = round(sum(st.compliance_score for st in stats) / len(stats))

        # last seen session
        last_stat = MachineSessionStat.query.filter_by(machine_id=m.id)\
            .order_by(MachineSessionStat.id.desc()).first()
        last_session_name = None
        if last_stat:
            sess = Session.query.get(last_stat.session_id)
            if sess and sess.subject:
                last_session_name = sess.subject.name

        result.append({
            'id':               m.id,
            'pc_number':        m.pc_number,
            'hostname':         m.hostname,
            'is_online':        m.is_online,
            'total_alerts':     total_alerts,
            'total_activities': total_activities,
            'avg_compliance':   avg_compliance,
            'sessions_count':   len(stats),
            'last_session':     last_session_name,
            'last_seen':        m.last_seen.isoformat() if m.last_seen else None,
        })

    return jsonify(result)


# ── Agent ZIP generation ──────────────────────────────────────────────────────

@admin_bp.route('/labs/<int:lab_id>/machines/<int:machine_id>/generate-agent', methods=['POST'])
@jwt_required()
def generate_agent(lab_id, machine_id):
    """
    Generate a ready-to-deploy ZIP package for a student PC.
    Returns a downloadable ZIP with agent, config, installer.
    """
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403

    machine = Machine.query.filter_by(id=machine_id, lab_id=lab_id).first_or_404()

    # Get server URL from request or auto-detect
    data       = request.get_json(silent=True) or {}
    server_url = data.get('server_url') or _detect_server_url()

    # Import builder
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from agent_builder import build_agent_zip

    try:
        zip_bytes = build_agent_zip(
            machine_token = machine.token,
            machine_name  = machine.pc_number,
            server_url    = server_url
        )
    except Exception as e:
        return jsonify({'msg': f'ZIP generation failed: {str(e)}'}), 500

    zip_name = f"{machine.pc_number.replace(' ', '_')}_agent.zip"

    return send_file(
        io.BytesIO(zip_bytes),
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_name
    )


def _detect_server_url():
    """Auto-detect the server's LAN IP for config.json."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return f"http://{ip}:5001"
    except Exception:
        return "http://localhost:5001"

# ── Pause / Resume monitoring for a machine ───────────────────────────────────

@admin_bp.route('/labs/<int:lab_id>/machines/<int:machine_id>/pause', methods=['POST'])
@jwt_required()
def pause_machine(lab_id, machine_id):
    """Pause monitoring for a machine (e.g. when lecturer uses it)."""
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403
    Machine.query.filter_by(id=machine_id, lab_id=lab_id).first_or_404()
    paused_machines.add(machine_id)
    return jsonify({'msg': 'Paused', 'is_paused': True})


@admin_bp.route('/labs/<int:lab_id>/machines/<int:machine_id>/resume', methods=['POST'])
@jwt_required()
def resume_machine(lab_id, machine_id):
    """Resume monitoring for a machine."""
    user = get_current_user()
    if not lab_guard(user, lab_id):
        return jsonify({'msg': 'Forbidden'}), 403
    Machine.query.filter_by(id=machine_id, lab_id=lab_id).first_or_404()
    paused_machines.discard(machine_id)
    return jsonify({'msg': 'Resumed', 'is_paused': False})
