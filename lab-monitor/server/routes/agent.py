"""
Endpoints called by the silent agent running on each student PC.
Auth: machine token passed as Authorization: Bearer <token>
"""
from flask import Blueprint, request, jsonify, current_app
from models import db, Machine, Session, Activity, Alert, AllowedApp, MachineSessionStat
from datetime import datetime, timedelta
import base64, os, uuid

agent_bp = Blueprint('agent', __name__)

BROWSER_APPS = {"google chrome", "microsoft edge", "mozilla firefox", "chromium", "firefox"}

def extract_website_from_title(app_name: str, window_title: str) -> str | None:
    """
    Extract the website/page name from a browser window title.
    Chrome/Edge format: "Page Title - Browser Name"
    Firefox format:     "Page Title — Mozilla Firefox"
    Returns the site/page name or None if not a browser.
    """
    if not app_name or app_name.lower() not in BROWSER_APPS:
        return None
    if not window_title:
        return None

    # Strip known browser suffixes
    suffixes = [
        " - Google Chrome", " - Microsoft Edge", " - Mozilla Firefox",
        " — Mozilla Firefox", " - Chromium", " - Brave"
    ]
    title = window_title
    for suffix in suffixes:
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()
            break

    # Return cleaned page title (this is the website/page being viewed)
    return title if title else None


def get_machine_from_token():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:].strip()
    return Machine.query.filter_by(token=token).first()


def is_app_allowed(app_name, window_title, session):
    """
    Returns True if the app is permitted for this session's subject.
    Matching is case-insensitive and partial (substring).
    """
    allowed_apps = AllowedApp.query.filter_by(subject_id=session.subject_id).all()
    if not allowed_apps:
        return True  # no restrictions defined yet — allow all

    app_lower   = (app_name or '').lower().strip()
    title_lower = (window_title or '').lower().strip()

    for rule in allowed_apps:
        rule_lower = rule.app_name.lower().strip()

        # Direct or substring match on app name
        if rule_lower in app_lower or app_lower in rule_lower:
            return True

        # Browser rule: if allow_browser flag is set, allow browser apps
        if rule.allow_browser and app_lower in BROWSER_APPS:
            return True

    # Nothing matched
    return False


def get_or_create_stat(machine_id, session_id):
    stat = MachineSessionStat.query.filter_by(
        machine_id=machine_id, session_id=session_id
    ).first()
    if not stat:
        stat = MachineSessionStat(machine_id=machine_id, session_id=session_id)
        db.session.add(stat)
        db.session.flush()
    return stat


def save_screenshot(machine_id, b64_data):
    """Save base64-encoded screenshot to disk, return relative path."""
    try:
        screenshots_dir = os.path.join(current_app.root_path, 'screenshots')
        os.makedirs(screenshots_dir, exist_ok=True)
        filename = f"{machine_id}_{uuid.uuid4().hex[:8]}.jpg"
        filepath = os.path.join(screenshots_dir, filename)
        img_bytes = base64.b64decode(b64_data)
        with open(filepath, 'wb') as f:
            f.write(img_bytes)
        return f"screenshots/{filename}"
    except Exception as e:
        print(f"[Server] Screenshot save error: {e}")
        return None


# ── Heartbeat ─────────────────────────────────────────────────────────────────

@agent_bp.route('/agent/heartbeat', methods=['POST'])
def heartbeat():
    """Agent posts current window info every 5 seconds."""
    machine = get_machine_from_token()
    if not machine:
        return jsonify({'msg': 'Unauthorized'}), 401

    data         = request.get_json(force=True) or {}
    app_name     = (data.get('app_name') or 'Unknown').strip()
    window_title = (data.get('window_title') or '').strip()
    screenshot_b64 = data.get('screenshot')

    now = datetime.utcnow()
    machine.last_seen = now
    machine.is_online = True

    # Extract website from browser title
    website = extract_website_from_title(app_name, window_title)

    active_session = Session.query.filter_by(lab_id=machine.lab_id, is_active=True).first()

    allowed = True

    # Import paused_machines from admin blueprint
    try:
        from routes.admin import paused_machines
        is_paused = machine.id in paused_machines
    except Exception:
        is_paused = False

    if active_session and not is_paused:
        allowed = is_app_allowed(app_name, window_title, active_session)

        # ── Update live state on machine ──────────────────────────────────
        machine.current_app     = app_name
        machine.current_title   = website if website else window_title
        machine.current_allowed = allowed

        # ── Update compliance stats ───────────────────────────────────────
        stat = get_or_create_stat(machine.id, active_session.id)
        stat.total_heartbeats += 1
        if allowed:
            stat.allowed_heartbeats += 1

        # ── Activity log ─────────────────────────────────────────────────
        prev = Activity.query.filter_by(
            machine_id=machine.id,
            session_id=active_session.id,
            end_time=None
        ).first()

        if prev and prev.app_name != app_name:
            prev.end_time = now
            prev = None

        if not prev:
            activity = Activity(
                machine_id=machine.id,
                session_id=active_session.id,
                app_name=app_name,
                window_title=window_title,
                is_allowed=allowed
            )
            db.session.add(activity)

        # ── Alert on violation (deduplicated per 60 seconds) ──────────────
        if not allowed:
            stat.violation_count += 1
            sixty_sec_ago = now - timedelta(seconds=60)
            last_alert = Alert.query.filter(
                Alert.machine_id == machine.id,
                Alert.app_name   == app_name,
                Alert.created_at >= sixty_sec_ago
            ).first()

            if not last_alert:
                screenshot_path = None
                if screenshot_b64:
                    screenshot_path = save_screenshot(machine.id, screenshot_b64)

                alert = Alert(
                    machine_id      = machine.id,
                    session_id      = active_session.id,
                    app_name        = app_name,
                    message         = (
                        f"{machine.pc_number} opened '{website}' in {app_name} — not allowed during {active_session.subject.name}"
                        if website else
                        f"{machine.pc_number} opened '{app_name}' — not allowed during {active_session.subject.name}"
                    ),
                    screenshot_path = screenshot_path
                )
                db.session.add(alert)
    else:
        # No active session or machine is paused — track online state only
        machine.current_app     = app_name
        machine.current_title   = website if website else window_title
        machine.current_allowed = True

    db.session.commit()
    return jsonify({
        'allowed':        allowed,
        'session_active': active_session is not None,
        'is_paused':      is_paused
    })


# ── Offline ────────────────────────────────────────────────────────────────────

@agent_bp.route('/agent/offline', methods=['POST'])
def go_offline():
    """Agent posts this on graceful shutdown."""
    machine = get_machine_from_token()
    if not machine:
        return jsonify({'msg': 'Unauthorized'}), 401

    machine.is_online       = False
    machine.current_app     = None
    machine.current_title   = None
    machine.current_allowed = True

    # close open activities
    open_acts = Activity.query.filter_by(machine_id=machine.id, end_time=None).all()
    for a in open_acts:
        a.end_time = datetime.utcnow()

    db.session.commit()
    return jsonify({'msg': 'ok'})
