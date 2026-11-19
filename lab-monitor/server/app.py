from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from werkzeug.security import generate_password_hash
from models import db, Lab, User
import secrets, os
app = Flask(__name__, static_folder='../client', static_url_path='')
# ── Config ────────────────────────────────────────────────────────────────────
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lab_monitor.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
if not os.path.exists('jwt_secret.txt'):
    with open('jwt_secret.txt', 'w') as f:
        f.write(secrets.token_urlsafe(32))
with open('jwt_secret.txt') as f:
    app.config['JWT_SECRET_KEY'] = f.read().strip()
from datetime import timedelta
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=12)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
db.init_app(app)
jwt = JWTManager(app)
# ── Blueprints ────────────────────────────────────────────────────────────────
from routes.auth  import auth_bp
from routes.admin import admin_bp
from routes.agent import agent_bp
app.register_blueprint(auth_bp,  url_prefix='/api')
app.register_blueprint(admin_bp, url_prefix='/api')
app.register_blueprint(agent_bp, url_prefix='/api')
# ── Health ─────────────────────────────────────────────────────────────────────
@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'version': '2.0'})
# ── Serve frontend ────────────────────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')
# ── Seed DB ───────────────────────────────────────────────────────────────────
def seed():
    with app.app_context():
        db.create_all()
        if not Lab.query.first():
            lab = Lab(name='CS Lab 1', department='Computer Science')
            db.session.add(lab)
            db.session.flush()
            admin = User(
                username = 'admin',
                password = generate_password_hash('Admin@123'),
                lab_id   = lab.id
            )
            db.session.add(admin)
            db.session.commit()
            print("✅ Default lab 'CS Lab 1' and admin created")
            print("   Username: admin  |  Password: Admin@123")
        print("✅ Database ready")
        print("🚀 Server starting on http://0.0.0.0:5001")
        print("   Open dashboard at http://localhost:5001")
if __name__ == '__main__':
    seed()
    app.run(host='0.0.0.0', port=5001, debug=True)