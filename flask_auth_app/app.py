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
    name = db.Column(db.String(100), nullable=True)  # New field for lobby name
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    is_public = db.Column(db.Boolean, default=True)  
    game_started = db.Column(db.Boolean, default=False)  # New field to track if game has started
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Relationships
    owner = db.relationship('User', foreign_keys=[owner_id])
    players = db.relationship('LobbyPlayer', back_populates='lobby', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Lobby {self.code}>'
    
    @property
    def player_count(self):
        return len(self.players)
    
    @property
    def team1_players(self):
        return [player for player in self.players if player.team == 1]
    
    @property
    def team2_players(self):
        return [player for player in self.players if player.team == 2]
    
    @property
    def unassigned_players(self):
        return [player for player in self.players if player.team == 0]
    
    @property
    def is_full(self):
        return self.player_count >= 4
    
    def assign_team(self, user_id):
        player = LobbyPlayer.query.filter_by(lobby_id=self.id, user_id=user_id).first()
        if not player:
            return False
        
        # If player already has a team, do nothing
        if player.team != 0:
            return True
        
        # Count players in each team
        team1_count = len(self.team1_players)
        team2_count = len(self.team2_players)
        
        # Assign to team with fewer players
        if team1_count <= team2_count and team1_count < 2:
            player.team = 1
        elif team2_count < 2:
            player.team = 2
        else:
            # Both teams are full
            return False
        
        return True

# Define LobbyPlayer model (association table with additional data)
class LobbyPlayer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lobby_id = db.Column(db.Integer, db.ForeignKey('lobby.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    team = db.Column(db.Integer, default=0)  # 0 = unassigned, 1 = team 1, 2 = team 2
    
    # Relationships
    lobby = db.relationship('Lobby', back_populates='players')
    user = db.relationship('User', back_populates='lobby_players')
    
    def __repr__(self):
        return f'<LobbyPlayer {self.user.username} in {self.lobby.code}, Team {self.team}>'

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

# Function to add is_public column to lobby table if it doesn't exist
def add_is_public_column():
    try:
        if os.path.exists(db_path) and not column_exists('lobby', 'is_public'):
            logger.info("Adding is_public column to lobby table")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("ALTER TABLE lobby ADD COLUMN is_public BOOLEAN DEFAULT 1")
            conn.commit()
            conn.close()
            logger.info("is_public column added successfully")
    except Exception as e:
        logger.error(f"Error adding is_public column: {e}")

# Function to add name column to lobby table if it doesn't exist
def add_name_column():
    try:
        if os.path.exists(db_path) and not column_exists('lobby', 'name'):
            logger.info("Adding name column to lobby table")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("ALTER TABLE lobby ADD COLUMN name TEXT")
            conn.commit()
            conn.close()
            logger.info("name column added successfully")
    except Exception as e:
        logger.error(f"Error adding name column: {e}")

# Function to add game_started column to lobby table if it doesn't exist
def add_game_started_column():
    try:
        if os.path.exists(db_path) and not column_exists('lobby', 'game_started'):
            logger.info("Adding game_started column to lobby table")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("ALTER TABLE lobby ADD COLUMN game_started BOOLEAN DEFAULT 0")
            conn.commit()
            conn.close()
            logger.info("game_started column added successfully")
    except Exception as e:
        logger.error(f"Error adding game_started column: {e}")

# Function to add team column to lobbyplayer table if it doesn't exist
def add_team_column():
    try:
        if os.path.exists(db_path) and not column_exists('lobby_player', 'team'):
            logger.info("Adding team column to lobby_player table")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("ALTER TABLE lobby_player ADD COLUMN team INTEGER DEFAULT 0")
            conn.commit()
            conn.close()
            logger.info("team column added successfully")
    except Exception as e:
        logger.error(f"Error adding team column: {e}")

# Create tables and admin user if it doesn't exist
with app.app_context():
    # First make sure the is_admin column exists
    add_is_admin_column()
    
    # Then make sure the is_public column exists in lobby table
    add_is_public_column()
    
    # Then make sure the name column exists in lobby table
    add_name_column()
    
    # Then make sure the game_started column exists in lobby table
    add_game_started_column()
    
    # Then make sure the team column exists in lobby_player table
    add_team_column()
    
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
                session.clear()  # Clear any existing session data
                session['username'] = username
                session['is_admin'] = bool(user.is_admin)  # Ensure boolean conversion
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
        
        # Store info for notification before deleting
        lobby_code_for_notification = lobby.code
        lobby_name_for_notification = lobby.name
        
        # Completely delete the lobby instead of marking it inactive
        db.session.delete(lobby)
        db.session.commit()
        
        # Notify admins that lobby was deleted
        socketio.emit('admin_lobby_inactive', {
            'lobby_code': lobby_code_for_notification,
            'lobby_name': lobby_name_for_notification
        }, room='admin_room')
        
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
        user_active_games = []
        for lobby_player in user.lobby_players:
            if lobby_player.lobby.is_active:
                if lobby_player.lobby.game_started:
                    user_active_games.append(lobby_player.lobby)
                else:
                    user_lobbies.append(lobby_player.lobby)
        
        # Get public lobbies that the user is not in and where game has not started
        public_lobbies = Lobby.query.filter_by(
            is_active=True, 
            is_public=True, 
            game_started=False
        ).all()
        # Filter out lobbies the user is already in
        public_lobbies = [lobby for lobby in public_lobbies if lobby not in user_lobbies]
        
        return render_template(
            'lobbies.html', 
            user=user, 
            user_lobbies=user_lobbies, 
            public_lobbies=public_lobbies,
            user_active_games=user_active_games
        )
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
        
        # Check if user is already in an active lobby
        current_lobby = user_in_active_lobby(user.id)
        if current_lobby:
            flash(f'You are already in lobby {current_lobby.code}. Please leave that lobby first before creating a new one.', 'error')
            return redirect(url_for('lobby_detail', lobby_code=current_lobby.code))
        
        # Check if public or private lobby - handle the checkbox properly
        # When checkbox is checked, it's included in the form data
        # When it's unchecked, it's missing entirely
        is_public = request.form.get('is_public') is not None
        logger.debug(f"Creating lobby with is_public={is_public}")
        
        # Generate a unique code for the lobby
        lobby_code = generate_lobby_code()
        
        # Set lobby name based on creator's username
        lobby_name = f"Lobby {username}"
        
        # Create the lobby
        new_lobby = Lobby(
            code=lobby_code,
            name=lobby_name,
            owner_id=user.id,
            is_active=True,
            is_public=is_public
        )
        db.session.add(new_lobby)
        db.session.flush()  # Flush to get the lobby ID
        
        # Add the creator as a player
        lobby_player = LobbyPlayer(
            lobby_id=new_lobby.id,
            user_id=user.id,
            team=0  # Creator starts as unassigned
        )
        db.session.add(lobby_player)
        db.session.commit()
        
        # Emit event to admin room for real-time updates
        socketio.emit('admin_lobby_created', {
            'lobby_id': new_lobby.id,
            'lobby_code': lobby_code,
            'lobby_name': lobby_name,
            'owner_username': username,
            'owner_id': user.id,
            'is_public': is_public,
            'created_at': new_lobby.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }, room='admin_room')
        
        flash(f'Lobby created successfully! Your lobby code is: {lobby_code}. You need to select a team to play. Invite 3 more friends to join!', 'success')
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
        
        # Check if game has already started in this lobby
        if lobby.game_started:
            flash('Cannot join this lobby: the game has already started!', 'error')
            return redirect(url_for('lobbies'))
        
        # Check if lobby is full (max 4 players)
        if lobby.is_full:
            flash('This lobby is full (maximum 4 players)!', 'error')
            return redirect(url_for('lobbies'))
        
        # Check if user is already in this lobby
        existing_player = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first()
        if existing_player:
            flash('You are already in this lobby!', 'info')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Check if user is already in another active lobby
        current_lobby = user_in_active_lobby(user.id)
        if current_lobby:
            flash(f'You are already in lobby {current_lobby.code}. Please leave that lobby first before joining a new one.', 'error')
            return redirect(url_for('lobby_detail', lobby_code=current_lobby.code))
        
        # Add user to lobby
        lobby_player = LobbyPlayer(
            lobby_id=lobby.id,
            user_id=user.id,
            team=0  # Start unassigned
        )
        db.session.add(lobby_player)
        db.session.commit()
        
        # Current timestamp for both regular and admin events
        joined_at = datetime.utcnow().strftime('%H:%M:%S')
        
        # Emit a real-time event to all users in the lobby
        socketio.emit('player_joined', {
            'username': username,
            'user_id': user.id,
            'joined_at': joined_at,
            'team': lobby_player.team
        }, room=lobby_code)
        
        # Emit event to admin room for real-time updates
        socketio.emit('admin_player_joined', {
            'username': username,
            'user_id': user.id,
            'joined_at': joined_at,
            'lobby_code': lobby_code,
            'lobby_name': lobby.name,
            'player_count': lobby.player_count
        }, room='admin_room')
        
        # Also emit to specific admin lobby room
        admin_lobby_room = f"admin_lobby_{lobby_code}"
        socketio.emit('admin_lobby_player_joined', {
            'username': username,
            'user_id': user.id,
            'joined_at': joined_at
        }, room=admin_lobby_room)
        
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
            is_owner = lobby.owner_id == user.id
            db.session.delete(lobby_player)
            
            # Check if this was the last player
            remaining_players = LobbyPlayer.query.filter_by(lobby_id=lobby.id).all()
            new_owner_username = None
            new_owner_id = None
            
            if len(remaining_players) == 0:
                # If last player leaves, completely delete the lobby instead of marking it inactive
                lobby_code_for_notification = lobby.code  # Store code before deletion
                lobby_name_for_notification = lobby.name  # Store name before deletion
                
                # Delete the lobby completely
                db.session.delete(lobby)
                
                # Notify admins that lobby became inactive and was deleted
                socketio.emit('admin_lobby_inactive', {
                    'lobby_code': lobby_code_for_notification,
                    'lobby_name': lobby_name_for_notification
                }, room='admin_room')
            elif is_owner and len(remaining_players) > 0:
                # If the owner is leaving and there are still players, assign a new owner
                new_owner = remaining_players[0].user
                new_owner_username = new_owner.username
                new_owner_id = new_owner.id
                lobby.owner_id = new_owner_id
                
                # Notify users in the lobby about the owner change
                socketio.emit('owner_changed', {
                    'previous_owner': username,
                    'new_owner': new_owner_username,
                    'new_owner_id': new_owner_id
                }, room=lobby_code)
                
                # Notify admins about owner change
                socketio.emit('admin_owner_changed', {
                    'lobby_code': lobby.code,
                    'lobby_name': lobby.name,
                    'previous_owner': username,
                    'new_owner': new_owner_username
                }, room='admin_room')
            
            db.session.commit()
            
            # Emit a real-time event to all users in the lobby about the player leaving
            socketio.emit('player_left', {
                'username': username,
                'user_id': user.id
            }, room=lobby_code)
            
            # Notify admins about player leaving
            socketio.emit('admin_player_left', {
                'username': username,
                'user_id': user.id,
                'lobby_code': lobby_code,
                'lobby_name': lobby.name if lobby in db.session else lobby_name_for_notification,
                'player_count': len(remaining_players),
                'is_owner': is_owner,
                'new_owner': new_owner_username
            }, room='admin_room')
            
            # Also emit to specific admin lobby room
            admin_lobby_room = f"admin_lobby_{lobby_code}"
            socketio.emit('admin_lobby_player_left', {
                'username': username,
                'user_id': user.id,
                'is_owner': is_owner,
                'new_owner': new_owner_username
            }, room=admin_lobby_room)
            
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
    """Start the game and redirect players to the game page"""
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
        
        # Check if there are exactly 4 players
        if lobby.player_count != 4:
            flash('You need exactly 4 players to start the game!', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Check if all players are assigned to teams
        if len(lobby.unassigned_players) > 0:
            flash('All players must be assigned to a team before starting!', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Check if teams are balanced (2 players per team)
        if len(lobby.team1_players) != 2 or len(lobby.team2_players) != 2:
            flash('Each team must have exactly 2 players!', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Mark the lobby as game started
        lobby.game_started = True
        db.session.commit()
        
        # Emit a socket event to notify all players in the lobby that the game has started
        socketio.emit('game_started', {
            'lobby_code': lobby_code,
            'redirect_url': url_for('game_page', lobby_code=lobby_code)
        }, room=lobby_code)
        
        # Also emit a global event for users on the lobbies page
        socketio.emit('lobby_game_started', {
            'lobby_code': lobby_code,
            'lobby_name': lobby.name,
            'owner_username': username
        })
        
        # Redirect the owner to the game page
        return redirect(url_for('game_page', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error starting game: {e}")
        flash('An error occurred while starting game. Please try again.', 'error')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))

@app.route('/lobby/<lobby_code>/change_team', methods=['POST'])
def change_team(lobby_code):
    """Change a player's team in the lobby"""
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
        
        # Get player
        lobby_player = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first()
        if not lobby_player:
            flash('You are not a member of this lobby!', 'error')
            return redirect(url_for('lobbies'))
        
        # Get desired team from form
        new_team = int(request.form.get('team', 0))
        
        # Validate team choice (must be 0, 1, or 2)
        if new_team not in [0, 1, 2]:
            flash('Invalid team selection!', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        old_team = lobby_player.team
        
        # Check if the player is trying to go directly from one team to another
        if old_team != 0 and new_team != 0:
            flash('You must first leave your current team before joining a new one.', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
            
        # If joining a team, check if it's full
        if new_team in [1, 2]:
            team_players = lobby.team1_players if new_team == 1 else lobby.team2_players
            if len(team_players) >= 2:
                flash(f'Team {new_team} is already full!', 'error')
                return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Update team
        old_team = lobby_player.team
        lobby_player.team = new_team
        db.session.commit()
        
        # Emit event to room
        socketio.emit('player_team_changed', {
            'username': username,
            'user_id': user.id,
            'old_team': old_team,
            'new_team': new_team
        }, room=lobby_code)
        
        if new_team == 0:
            flash('You left your team and are now unassigned.', 'success')
        else:
            flash(f'You joined Team {new_team}!', 'success')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error changing team: {e}")
        db.session.rollback()
        flash('An error occurred while changing team. Please try again.', 'error')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))

@app.route('/game/<lobby_code>')
def game_page(lobby_code):
    """Show the game page for a lobby"""
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
        
        # Check if game has started
        if not lobby.game_started:
            flash('Game has not started yet!', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Check if user is in this lobby
        lobby_player = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first()
        if not lobby_player:
            flash('You are not a member of this lobby!', 'error')
            return redirect(url_for('lobbies'))
        
        return render_template('game_placeholder.html', lobby=lobby, user=user)
    except Exception as e:
        logger.error(f"Error accessing game page: {e}")
        flash('An error occurred. Please try again.', 'error')
        return redirect(url_for('lobbies'))

@app.route('/game/<lobby_code>/leave', methods=['POST'])
def leave_game(lobby_code):
    """Leave a game and the associated lobby"""
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
        lobby_player = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first()
        if not lobby_player:
            flash('You are not a member of this lobby!', 'error')
            return redirect(url_for('lobbies'))
        
        # Remove user from lobby
        db.session.delete(lobby_player)
        db.session.commit()
        
        # Get remaining players count after removal
        remaining_players_count = LobbyPlayer.query.filter_by(lobby_id=lobby.id).count()
        
        # Store lobby info for notifications in case we delete it
        lobby_name = lobby.name
        
        # If this was the last player to leave, delete the lobby
        if remaining_players_count == 0:
            logger.info(f"Auto-deleting empty lobby {lobby_code}")
            
            # Store lobby information before deletion for notifications
            lobby_info = {
                'lobby_code': lobby_code,
                'lobby_name': lobby_name,
                'is_auto_deleted': True
            }
            
            # Delete the lobby completely
            db.session.delete(lobby)
            db.session.commit()
            
            # Notify admins about the lobby deletion
            socketio.emit('admin_lobby_inactive', {
                'lobby_code': lobby_code,
                'lobby_name': lobby_name,
                'reason': 'Auto-deleted (all players left)',
                'time': datetime.utcnow().strftime('%H:%M:%S')
            }, room='admin_room')
        
        # Create player info dictionary for events
        player_info = {
            'username': username,
            'user_id': user.id,
            'team': lobby_player.team,
            'remaining_players': remaining_players_count
        }
        
        # Emit a real-time event to all users in the lobby about the player leaving
        socketio.emit('player_left_game', {
            'username': username,
            'user_id': user.id,
            'lobby_code': lobby_code,
            'team': lobby_player.team,
            'remaining_players': remaining_players_count,
            'is_last_player': remaining_players_count == 0
        }, room=lobby_code)
        
        # Emit to admin room
        socketio.emit('admin_player_left_game', {
            'username': username,
            'user_id': user.id,
            'lobby_code': lobby_code,
            'lobby_name': lobby_name,  # Use stored name in case lobby was deleted
            'team': lobby_player.team,
            'remaining_players': remaining_players_count,
            'time': datetime.utcnow().strftime('%H:%M:%S'),
            'is_last_player': remaining_players_count == 0
        }, room='admin_room')
        
        # Also emit to specific admin lobby room if the lobby still exists
        if remaining_players_count > 0:
            admin_lobby_room = f"admin_lobby_{lobby_code}"
            socketio.emit('admin_lobby_player_left_game', player_info, room=admin_lobby_room)
        
        flash('You have left the game and the lobby!', 'success')
        return redirect(url_for('lobbies'))
    except Exception as e:
        logger.error(f"Error leaving game: {e}")
        db.session.rollback()
        flash('An error occurred while leaving game. Please try again.', 'error')
        return redirect(url_for('lobbies'))

# Helper function to check if user is already in an active lobby
def user_in_active_lobby(user_id):
    """Check if a user is already in an active lobby"""
    user_lobby_players = LobbyPlayer.query.filter_by(user_id=user_id).all()
    for lobby_player in user_lobby_players:
        if lobby_player.lobby.is_active:
            return lobby_player.lobby
    return None

# SocketIO event handlers
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    if 'username' in session:
        username = session['username']
        logger.info(f"User {username} connected")
        
        # If admin user connects, add them to admin room for real-time updates
        if session.get('is_admin', False):
            join_room('admin_room')
            logger.info(f"Admin {username} joined admin room")
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

@socketio.on('leave_lobby_room')
def handle_leave_lobby_room(data):
    """Leave a SocketIO room for a specific lobby"""
    lobby_code = data.get('lobby_code')
    if not lobby_code:
        return
    
    # Use the lobby code as the room name
    leave_room(lobby_code)
    logger.info(f"User left room: {lobby_code}")

@socketio.on('join_admin_lobby_room')
def handle_join_admin_lobby_room(data):
    """Join a SocketIO room for admin to monitor a specific lobby"""
    if not session.get('is_admin', False):
        return
    
    lobby_code = data.get('lobby_code')
    if not lobby_code:
        return
    
    admin_lobby_room = f"admin_lobby_{lobby_code}"
    join_room(admin_lobby_room)
    logger.info(f"Admin joined room: {admin_lobby_room}")

# Update the run statement to use SocketIO
if __name__ == '__main__':
    import argparse

    # Add argument parsing
    parser = argparse.ArgumentParser(description="Run the Flask app.")
    parser.add_argument('--host-all', action='store_true', help="Bind the Flask app to 0.0.0.0 for external access.")
    parser.add_argument('--host', default='127.0.0.1', help="Specify the host to bind the Flask app.")
    parser.add_argument('--port', type=int, default=5000, help="Specify the port to run the Flask app.")

    args = parser.parse_args()

    if args.host_all:
        # Run the app on 0.0.0.0 if --host-all is passed
        socketio.run(app, host='0.0.0.0', port=args.port, debug=False)
    else:
        # Use the specified host and port
        socketio.run(app, host=args.host, port=args.port, debug=True)