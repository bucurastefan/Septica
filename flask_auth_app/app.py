from flask import Flask, render_template, url_for, redirect, request, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
import os
import sqlite3
from datetime import datetime
import logging
import random
import string

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "default_secret_key")

# SQLAlchemy configuration
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'users.db')
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", f"sqlite:///{db_path}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Define User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)
    
    # Relationship with LobbyPlayer
    lobby_players = db.relationship('LobbyPlayer', back_populates='user', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<User {self.username}>'

# Define Lobby model
class Lobby(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(6), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Relationships
    owner = db.relationship('User', foreign_keys=[owner_id])
    players = db.relationship('LobbyPlayer', back_populates='lobby', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Lobby {self.code}>'
    
    @property
    def player_count(self):
        return len(self.players)

# Define LobbyPlayer model (association table with additional data)
class LobbyPlayer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lobby_id = db.Column(db.Integer, db.ForeignKey('lobby.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    lobby = db.relationship('Lobby', back_populates='players')
    user = db.relationship('User', back_populates='lobby_players')
    
    def __repr__(self):
        return f'<LobbyPlayer {self.user.username} in {self.lobby.code}>'

# Function to generate a unique lobby code
def generate_lobby_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Lobby.query.filter_by(code=code).first():
            return code

# Function to check if column exists in SQLite table
def column_exists(table_name, column_name):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        conn.close()
        
        for column in columns:
            if column[1] == column_name:
                return True
        return False
    except Exception as e:
        logger.error(f"Error checking column: {e}")
        return False

# Function to add is_admin column if it doesn't exist
def add_is_admin_column():
    try:
        if os.path.exists(db_path) and not column_exists('user', 'is_admin'):
            logger.info("Adding is_admin column to user table")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0")
            conn.commit()
            conn.close()
            logger.info("is_admin column added successfully")
    except Exception as e:
        logger.error(f"Error adding is_admin column: {e}")

# Create tables and admin user if it doesn't exist
with app.app_context():
    # First make sure the is_admin column exists
    add_is_admin_column()
    
    # Then create tables if they don't exist
    db.create_all()
    
    # Check if admin user exists
    admin_user = User.query.filter_by(username="admin").first()
    if not admin_user:
        # Create the admin user
        admin_password = generate_password_hash("superboss")
        admin = User(
            username="admin",
            email="admin@example.com",
            password=admin_password,
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()
        logger.info("Admin user created with username 'admin' and password 'superboss'")

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('lobbies'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        try:
            user = User.query.filter_by(username=username).first()
            
            if user and check_password_hash(user.password, password):
                session['username'] = username
                session['is_admin'] = user.is_admin
                flash('Login successful!', 'success')
                
                # Redirect directly to lobbies page for all users
                return redirect(url_for('lobbies'))
            else:
                flash('Invalid username or password!', 'error')
        except Exception as e:
            logger.error(f"Error during login: {e}")
            flash('An error occurred during login. Please try again.', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            # Check if username or email already exists
            existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
            
            if existing_user:
                flash('Username or email already exists!', 'error')
                return redirect(url_for('register'))
            
            # Create new user
            hashed_password = generate_password_hash(password)
            new_user = User(
                username=username,
                email=email,
                password=hashed_password
            )
            
            db.session.add(new_user)
            db.session.commit()
            
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            logger.error(f"Error during registration: {e}")
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'error')
    
    return render_template('register.html')

@app.route('/home')
def home():
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    try:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        
        if not user:
            flash('User not found!', 'error')
            return redirect(url_for('logout'))
            
        return render_template('home.html', username=username, email=user.email)
    except Exception as e:
        logger.error(f"Error accessing home page: {e}")
        flash('An error occurred. Please try again.', 'error')
        return redirect(url_for('logout'))

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('You have been logged out!', 'success')
    return redirect(url_for('login'))

@app.route('/status')
def status():
    """A diagnostic route to check if database is connected"""
    try:
        db_status = User.query.first() is not None
        return "Database connected successfully!"
    except Exception as e:
        return f"Database connection failed: {e}"

@app.route('/admin/dashboard')
def admin_dashboard():
    """Admin dashboard - only accessible to admin users"""
    if not session.get('is_admin', False):
        flash('You do not have permission to access the admin dashboard!', 'error')
        return redirect(url_for('lobbies'))
    
    try:
        # Get count of total users
        user_count = User.query.filter(User.is_admin == False).count()
        
        # Get count of active lobbies
        lobby_count = Lobby.query.filter_by(is_active=True).count()
        
        return render_template('admin_dashboard.html', user_count=user_count, lobby_count=lobby_count)
    except Exception as e:
        logger.error(f"Error accessing admin dashboard: {e}")
        flash('An error occurred while accessing admin dashboard.', 'error')
        return redirect(url_for('lobbies'))

@app.route('/admin/users')
def admin_users():
    """Admin page to view all users - only accessible to admin users"""
    if not session.get('is_admin', False):
        flash('You do not have permission to access this page!', 'error')
        return redirect(url_for('lobbies'))
    
    try:
        users = User.query.filter(User.is_admin == False).all()
        return render_template('admin_users.html', users=users)
    except Exception as e:
        logger.error(f"Error accessing admin users page: {e}")
        flash('An error occurred while retrieving users.', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/<int:user_id>')
def admin_user_details(user_id):
    """Admin page to view details of a specific user"""
    if not session.get('is_admin', False):
        flash('You do not have permission to access this page!', 'error')
        return redirect(url_for('lobbies'))
    
    try:
        user = User.query.get_or_404(user_id)
        if user.is_admin:
            flash('Cannot view admin user details!', 'error')
            return redirect(url_for('admin_users'))
            
        return render_template('admin_user_details.html', user=user)
    except Exception as e:
        logger.error(f"Error accessing user details: {e}")
        flash('An error occurred while retrieving user details.', 'error')
        return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:user_id>/edit', methods=['GET', 'POST'])
def admin_edit_user(user_id):
    """Admin page to edit a user"""
    if not session.get('is_admin', False):
        flash('You do not have permission to access this page!', 'error')
        return redirect(url_for('lobbies'))
    
    try:
        user = User.query.get_or_404(user_id)
        if user.is_admin:
            flash('Cannot edit admin user!', 'error')
            return redirect(url_for('admin_users'))
        
        if request.method == 'POST':
            username = request.form.get('username')
            email = request.form.get('email')
            
            # Check if the new username or email is already taken by another user
            existing_user = User.query.filter(
                ((User.username == username) | (User.email == email)) & 
                (User.id != user_id)
            ).first()
            
            if existing_user:
                flash('Username or email already exists!', 'error')
                return render_template('admin_edit_user.html', user=user)
            
            # Update user data
            user.username = username
            user.email = email
            
            # Update password if provided
            new_password = request.form.get('password')
            if new_password:
                user.password = generate_password_hash(new_password)
            
            db.session.commit()
            flash('User updated successfully!', 'success')
            return redirect(url_for('admin_user_details', user_id=user.id))
        
        return render_template('admin_edit_user.html', user=user)
    except Exception as e:
        logger.error(f"Error editing user: {e}")
        flash('An error occurred while editing user.', 'error')
        return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    """Admin action to delete a user"""
    if not session.get('is_admin', False):
        flash('You do not have permission to perform this action!', 'error')
        return redirect(url_for('lobbies'))
    
    try:
        user = User.query.get_or_404(user_id)
        if user.is_admin:
            flash('Cannot delete admin user!', 'error')
            return redirect(url_for('admin_users'))
        
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!', 'success')
        return redirect(url_for('admin_users'))
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        flash('An error occurred while deleting user.', 'error')
        return redirect(url_for('admin_users'))

@app.route('/admin/lobbies')
def admin_lobbies():
    """Admin page to view all lobbies - only accessible to admin users"""
    if not session.get('is_admin', False):
        flash('You do not have permission to access this page!', 'error')
        return redirect(url_for('lobbies'))
    
    try:
        # Get all active lobbies
        lobbies = Lobby.query.filter_by(is_active=True).all()
        return render_template('admin_lobbies.html', lobbies=lobbies)
    except Exception as e:
        logger.error(f"Error accessing admin lobbies page: {e}")
        flash('An error occurred while retrieving lobbies.', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/lobby/<lobby_code>')
def admin_lobby_detail(lobby_code):
    """Admin page to view details of a specific lobby"""
    if not session.get('is_admin', False):
        flash('You do not have permission to access this page!', 'error')
        return redirect(url_for('lobbies'))
    
    try:
        lobby = Lobby.query.filter_by(code=lobby_code).first()
        if not lobby:
            flash('Lobby not found!', 'error')
            return redirect(url_for('admin_lobbies'))
            
        return render_template('admin_lobby_detail.html', lobby=lobby)
    except Exception as e:
        logger.error(f"Error accessing lobby details: {e}")
        flash('An error occurred while retrieving lobby details.', 'error')
        return redirect(url_for('admin_lobbies'))

@app.route('/admin/lobby/<lobby_code>/delete', methods=['POST'])
def admin_delete_lobby(lobby_code):
    """Admin action to delete a lobby"""
    if not session.get('is_admin', False):
        flash('You do not have permission to perform this action!', 'error')
        return redirect(url_for('lobbies'))
    
    try:
        lobby = Lobby.query.filter_by(code=lobby_code).first()
        if not lobby:
            flash('Lobby not found!', 'error')
            return redirect(url_for('admin_lobbies'))
        
        # Mark lobby as inactive instead of hard delete
        lobby.is_active = False
        db.session.commit()
        
        flash('Lobby deleted successfully!', 'success')
        return redirect(url_for('admin_lobbies'))
    except Exception as e:
        logger.error(f"Error deleting lobby: {e}")
        flash('An error occurred while deleting lobby.', 'error')
        return redirect(url_for('admin_lobbies'))

# Lobby Routes
@app.route('/lobbies')
def lobbies():
    """View available lobbies or create/join one"""
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    try:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        
        # Get lobbies the user is in
        user_lobbies = []
        for lobby_player in user.lobby_players:
            if lobby_player.lobby.is_active:
                user_lobbies.append(lobby_player.lobby)
        
        return render_template('lobbies.html', user=user, user_lobbies=user_lobbies)
    except Exception as e:
        logger.error(f"Error accessing lobbies page: {e}")
        flash('An error occurred. Please try again.', 'error')
        return redirect(url_for('login'))

@app.route('/lobby/create', methods=['POST'])
def create_lobby():
    """Create a new lobby"""
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    try:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        
        # Generate a unique code for the lobby
        lobby_code = generate_lobby_code()
        
        # Create the lobby
        new_lobby = Lobby(
            code=lobby_code,
            owner_id=user.id,
            is_active=True
        )
        db.session.add(new_lobby)
        db.session.flush()  # Flush to get the lobby ID
        
        # Add the creator as a player
        lobby_player = LobbyPlayer(
            lobby_id=new_lobby.id,
            user_id=user.id
        )
        db.session.add(lobby_player)
        db.session.commit()
        
        flash(f'Lobby created successfully! Your lobby code is: {lobby_code}', 'success')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error creating lobby: {e}")
        db.session.rollback()
        flash('An error occurred while creating lobby. Please try again.', 'error')
        return redirect(url_for('lobbies'))

@app.route('/lobby/join', methods=['POST'])
def join_lobby():
    """Join an existing lobby using a code"""
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    try:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        lobby_code = request.form.get('lobby_code', '').strip().upper()
        
        if not lobby_code:
            flash('Please enter a lobby code!', 'error')
            return redirect(url_for('lobbies'))
        
        # Check if lobby exists
        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()
        if not lobby:
            flash('Invalid lobby code or lobby no longer active!', 'error')
            return redirect(url_for('lobbies'))
        
        # Check if user is already in this lobby
        existing_player = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first()
        if existing_player:
            flash('You are already in this lobby!', 'info')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Add user to lobby
        lobby_player = LobbyPlayer(
            lobby_id=lobby.id,
            user_id=user.id
        )
        db.session.add(lobby_player)
        db.session.commit()
        
        # Emit a real-time event to all users in the lobby
        socketio.emit('player_joined', {
            'username': username,
            'user_id': user.id,
            'joined_at': datetime.utcnow().strftime('%H:%M:%S')
        }, room=lobby_code)
        
        flash(f'Successfully joined lobby {lobby_code}!', 'success')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error joining lobby: {e}")
        db.session.rollback()
        flash('An error occurred while joining lobby. Please try again.', 'error')
        return redirect(url_for('lobbies'))

@app.route('/lobby/<lobby_code>')
def lobby_detail(lobby_code):
    """View lobby details and players"""
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    try:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        
        # Get lobby
        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()
        if not lobby:
            flash('Lobby not found or no longer active!', 'error')
            return redirect(url_for('lobbies'))
        
        # Check if user is in this lobby
        is_player = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first() is not None
        if not is_player:
            flash('You are not a member of this lobby!', 'error')
            return redirect(url_for('lobbies'))
        
        # Check if user is owner
        is_owner = lobby.owner_id == user.id
        
        return render_template('lobby_detail.html', 
                               lobby=lobby, 
                               is_owner=is_owner,
                               user=user)
    except Exception as e:
        logger.error(f"Error viewing lobby: {e}")
        flash('An error occurred. Please try again.', 'error')
        return redirect(url_for('lobbies'))

@app.route('/lobby/<lobby_code>/leave', methods=['POST'])
def leave_lobby(lobby_code):
    """Leave a lobby"""
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    try:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        
        # Get lobby
        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()
        if not lobby:
            flash('Lobby not found or no longer active!', 'error')
            return redirect(url_for('lobbies'))
        
        # Remove user from lobby
        lobby_player = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first()
        if lobby_player:
            db.session.delete(lobby_player)
            
            # Check if this was the last player
            remaining_players = LobbyPlayer.query.filter_by(lobby_id=lobby.id).count()
            if remaining_players == 0:
                # If last player leaves, delete lobby
                lobby.is_active = False
                # Make sure to commit the change to mark lobby as inactive
                db.session.commit()
                # No need to emit an event if lobby is deleted
            else:
                # Commit first to ensure database is updated
                db.session.commit()
                
                # Emit a real-time event to all users in the lobby
                socketio.emit('player_left', {
                    'username': username,
                    'user_id': user.id
                }, room=lobby_code)
            
            flash('Successfully left the lobby!', 'success')
        else:
            flash('You are not a member of this lobby!', 'error')
        
        return redirect(url_for('lobbies'))
    except Exception as e:
        logger.error(f"Error leaving lobby: {e}")
        db.session.rollback()
        flash('An error occurred while leaving lobby. Please try again.', 'error')
        return redirect(url_for('lobbies'))

@app.route('/lobby/<lobby_code>/start', methods=['POST'])
def start_game(lobby_code):
    """Start the game (placeholder for now)"""
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    try:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        
        # Get lobby
        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()
        if not lobby:
            flash('Lobby not found or no longer active!', 'error')
            return redirect(url_for('lobbies'))
        
        # Check if user is the owner
        if lobby.owner_id != user.id:
            flash('Only the lobby owner can start the game!', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Here you would start the game logic - for now just redirect back with a message
        flash('Game started! (This is a placeholder - implement actual game logic)', 'success')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error starting game: {e}")
        flash('An error occurred while starting game. Please try again.', 'error')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))

# SocketIO event handlers
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    if 'username' in session:
        username = session['username']
        logger.info(f"User {username} connected")
    else:
        logger.info("Anonymous user connected")

@socketio.on('join_lobby_room')
def handle_join_lobby_room(data):
    """Join a SocketIO room for a specific lobby"""
    lobby_code = data.get('lobby_code')
    if not lobby_code:
        return
    
    # Use the lobby code as the room name
    join_room(lobby_code)
    logger.info(f"User joined room: {lobby_code}")

@socketio.on('leave_lobby_room')
def handle_leave_lobby_room(data):
    """Leave a SocketIO room for a specific lobby"""
    lobby_code = data.get('lobby_code')
    if not lobby_code:
        return
    
    # Use the lobby code as the room name
    leave_room(lobby_code)
    logger.info(f"User left room: {lobby_code}")

# Update the run statement to use SocketIO
if __name__ == '__main__':
    # For development:
    # app.run(debug=True)
    socketio.run(app, debug=True)
    
    # For production hosting (allows external connections):
    # socketio.run(app, host='0.0.0.0', port=5000, debug=False)