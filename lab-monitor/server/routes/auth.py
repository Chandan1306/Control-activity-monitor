from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash
from models import db, User

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')

    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'msg': 'Invalid credentials'}), 401

    token = create_access_token(identity=str(user.id))
    return jsonify({
        'token': token,
        'username': user.username,
        'lab_id': user.lab_id
    })
