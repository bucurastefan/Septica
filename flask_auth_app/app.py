from flask import Flask, render_template, url_for, redirect, request, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
import sqlite3
from datetime import datetime, timedelta
import logging
import random
import string
from game_logic import SepticaGame

# Initialize game storage
games = {}  # Dictionary to store active games
game_completion_messages = {}  # Dictionary to store completion messages for users

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

application = Flask(__name__)
application.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "default_secret_key")

# SQLAlchemy configuration
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'users.db')
application.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", f"sqlite:///{db_path}")
application.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize SQLAlchemy
db = SQLAlchemy(application)

# Initialize SocketIO
socketio = SocketIO(application, cors_allowed_origins="*")

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(application)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    """User loader function for Flask-Login"""
    return User.query.get(int(user_id))

# Define User model
class User(db.Model, UserMixin):
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
    player_count_type = db.Column(db.Integer, default=4)  # 3 or 4 player game
    
    # Lobby statistics and game multiplier
    team1_wins = db.Column(db.Integer, default=0)  # Team 1 wins in lobby
    team2_wins = db.Column(db.Integer, default=0)  # Team 2 wins in lobby  
    team3_wins = db.Column(db.Integer, default=0)  # Team 3 wins in lobby (for 3-player games)
    total_games_played = db.Column(db.Integer, default=0)  # Total number of games played
    next_game_multiplier = db.Column(db.Integer, default=1)  # Points multiplier for next game
    
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
    def team3_players(self):
        return [player for player in self.players if player.team == 3]
    
    @property
    def unassigned_players(self):
        return [player for player in self.players if player.team == 0]
    
    @property
    def is_full(self):
        return self.player_count >= self.player_count_type
    
    @property
    def max_teams(self):
        return 3 if self.player_count_type == 3 else 2
    
    def get_next_starter_info(self):
        """Get information about who will start the next game"""
        from game_logic import SepticaGame
        next_starter_position = SepticaGame.calculate_starting_player(self.total_games_played)
        
        # Get ordered players (Team Purple: positions 0,2; Team Black: positions 1,3)
        ordered_players = get_ordered_players(self.id)
        
        if len(ordered_players) >= 4:
            starter_player = ordered_players[next_starter_position]
            team_name = "Purple" if next_starter_position % 2 == 0 else "Black"
            player_number = 1 if next_starter_position < 2 else 2
            
            return {
                'username': starter_player.user.username,
                'position': next_starter_position,
                'team_name': team_name,
                'player_number': player_number,
                'can_show': True
            }
        
        return {'can_show': False}
    
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
        team3_count = len(self.team3_players) if self.player_count_type == 3 else 0
        
        if self.player_count_type == 3:
            # For 3-player games, each team has 1 player
            if team1_count == 0:
                player.team = 1
            elif team2_count == 0:
                player.team = 2
            elif team3_count == 0:
                player.team = 3
            else:
                # All teams are full
                return False
        else:
            # For 4-player games, assign to team with fewer players (max 2 per team)
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
    team = db.Column(db.Integer, default=0)  # 0 = unassigned, 1 = team 1, 2 = team 2, 3 = team 3 (for 3-player games)
    voted_reset_stats = db.Column(db.Boolean, default=False)  # Track if player voted to reset stats
    
    # Relationships
    lobby = db.relationship('Lobby', back_populates='players')
    user = db.relationship('User', back_populates='lobby_players')
    
    def __repr__(self):
        return f'<LobbyPlayer {self.user.username} in {self.lobby.code}, Team {self.team}>'

# Define PlayerStats model for tracking game statistics
class PlayerStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    games_played = db.Column(db.Integer, default=0)
    games_won = db.Column(db.Integer, default=0)
    games_lost = db.Column(db.Integer, default=0)
    total_points_scored = db.Column(db.Integer, default=0)
    total_points_conceded = db.Column(db.Integer, default=0)
    longest_win_streak = db.Column(db.Integer, default=0)
    current_win_streak = db.Column(db.Integer, default=0)
    longest_lose_streak = db.Column(db.Integer, default=0)
    current_lose_streak = db.Column(db.Integer, default=0)
    total_hands_played = db.Column(db.Integer, default=0)
    perfect_games = db.Column(db.Integer, default=0)  # Games won with opponent scoring 0
    comeback_wins = db.Column(db.Integer, default=0)  # Games won after being behind
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship with User
    user = db.relationship('User', backref=db.backref('stats', uselist=False))
    
    def __repr__(self):
        return f'<PlayerStats for {self.user.username}: {self.games_won}/{self.games_played}>'
    
    @property
    def win_rate(self):
        """Calculate win rate as percentage"""
        if self.games_played == 0:
            return 0.0
        return round((self.games_won / self.games_played) * 100, 2)
    
    @property
    def loss_rate(self):
        """Calculate loss rate as percentage"""
        if self.games_played == 0:
            return 0.0
        return round((self.games_lost / self.games_played) * 100, 2)
    
    @property
    def average_points_per_game(self):
        """Calculate average points scored per game"""
        if self.games_played == 0:
            return 0.0
        return round(self.total_points_scored / self.games_played, 2)
    
    @property
    def average_points_conceded_per_game(self):
        """Calculate average points conceded per game"""
        if self.games_played == 0:
            return 0.0
        return round(self.total_points_conceded / self.games_played, 2)
    
    @property
    def point_differential(self):
        """Calculate point differential (scored - conceded)"""
        return self.total_points_scored - self.total_points_conceded

# Function to generate a unique lobby code
def generate_lobby_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Lobby.query.filter_by(code=code).first():
            return code

def get_ordered_players(lobby_id):
    """Get players ordered properly for game seating (Team Purple: positions 0,2; Team Black: positions 1,3)"""
    team1_players = LobbyPlayer.query.filter_by(lobby_id=lobby_id, team=1).order_by(LobbyPlayer.joined_at).all()
    team2_players = LobbyPlayer.query.filter_by(lobby_id=lobby_id, team=2).order_by(LobbyPlayer.joined_at).all()
    
    # Arrange players in alternating teams: Team1, Team2, Team1, Team2
    # This ensures Team Purple gets positions 0,2 and Team Black gets positions 1,3
    ordered_players = []
    for i in range(2):  # Max 2 players per team
        if i < len(team1_players):
            ordered_players.append(team1_players[i])
        if i < len(team2_players):
            ordered_players.append(team2_players[i])
    
    return ordered_players

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

def cleanup_guest_users():
    """Clean up guest users that are older than 24 hours or have no active sessions"""
    try:
        from datetime import timedelta
        
        # Find guest users (users with temporary email pattern)
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        old_guest_users = User.query.filter(
            User.email.like('guest_%@temporary.com'),
            User.created_at < cutoff_time
        ).all()
        
        for guest_user in old_guest_users:
            # Remove user from any lobbies they're in
            lobby_players = LobbyPlayer.query.filter_by(user_id=guest_user.id).all()
            for lobby_player in lobby_players:
                db.session.delete(lobby_player)
            
            # Delete the guest user
            db.session.delete(guest_user)
            logger.info(f"Cleaned up old guest user: {guest_user.username}")
        
        db.session.commit()
        logger.info(f"Cleaned up {len(old_guest_users)} old guest users")
        
    except Exception as e:
        logger.error(f"Error during guest user cleanup: {e}")
        db.session.rollback()

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

def add_lobby_stats_columns():
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Add team1_wins column
        if os.path.exists(db_path) and not column_exists('lobby', 'team1_wins'):
            logger.info("Adding team1_wins column to lobby table")
            cursor.execute("ALTER TABLE lobby ADD COLUMN team1_wins INTEGER DEFAULT 0")
            
        # Add team2_wins column
        if os.path.exists(db_path) and not column_exists('lobby', 'team2_wins'):
            logger.info("Adding team2_wins column to lobby table")
            cursor.execute("ALTER TABLE lobby ADD COLUMN team2_wins INTEGER DEFAULT 0")
            
        # Add total_games_played column
        if os.path.exists(db_path) and not column_exists('lobby', 'total_games_played'):
            logger.info("Adding total_games_played column to lobby table")
            cursor.execute("ALTER TABLE lobby ADD COLUMN total_games_played INTEGER DEFAULT 0")
            
        # Add next_game_multiplier column
        if os.path.exists(db_path) and not column_exists('lobby', 'next_game_multiplier'):
            logger.info("Adding next_game_multiplier column to lobby table")
            cursor.execute("ALTER TABLE lobby ADD COLUMN next_game_multiplier INTEGER DEFAULT 1")
            
        conn.commit()
        conn.close()
        logger.info("Lobby statistics columns added successfully")
    except Exception as e:
        logger.error(f"Error adding lobby statistics columns: {e}")

def add_voted_reset_stats_column():
    """Add voted_reset_stats column to lobby_player table"""
    try:
        if os.path.exists(db_path) and not column_exists('lobby_player', 'voted_reset_stats'):
            logger.info("Adding voted_reset_stats column to lobby_player table")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("ALTER TABLE lobby_player ADD COLUMN voted_reset_stats BOOLEAN DEFAULT 0")
            conn.commit()
            conn.close()
            logger.info("voted_reset_stats column added successfully")
    except Exception as e:
        logger.error(f"Error adding voted_reset_stats column: {e}")

# Create tables and admin user if it doesn't exist
with application.app_context():
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
    
    # Then make sure lobby statistics columns exist
    add_lobby_stats_columns()
    
    # Then make sure voted_reset_stats column exists
    add_voted_reset_stats_column()
    
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

@application.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('lobbies'))
    return redirect(url_for('login'))

@application.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        try:
            user = User.query.filter_by(username=username).first()
            
            if user and check_password_hash(user.password, password):
                login_user(user)
                session['username'] = username
                session['is_admin'] = bool(user.is_admin)
                flash('Login successful!', 'success')
                return redirect(url_for('lobbies'))
            else:
                flash('Invalid username or password!', 'error')
        except Exception as e:
            logger.error(f"Error during login: {e}")
            flash('An error occurred during login. Please try again.', 'error')
    
    return render_template('login.html')

@application.route('/guest_login', methods=['POST'])
def guest_login():
    """Allow guest users to play without registration"""
    guest_name = request.form.get('guest_name', '').strip()
    
    if not guest_name:
        flash('Please enter a guest name!', 'error')
        return redirect(url_for('login'))
    
    if len(guest_name) > 20:
        flash('Guest name must be 20 characters or less!', 'error')
        return redirect(url_for('login'))
    
    # Check if guest name conflicts with existing usernames (including other guests)
    existing_user = User.query.filter_by(username=guest_name).first()
    if existing_user:
        flash('This name is already taken. Please choose another name.', 'error')
        return redirect(url_for('login'))
    
    try:
        # Create a temporary user entry for the guest
        guest_user = User(
            username=guest_name,
            email=f"guest_{datetime.utcnow().timestamp()}@temporary.com",  # Temporary email
            password="guest_temp_password",  # Temporary password
            is_admin=False
        )
        
        db.session.add(guest_user)
        db.session.commit()
        
        # Set session variables for guest user
        session['username'] = guest_name
        session['is_guest'] = True
        session['guest_user_id'] = guest_user.id
        session['is_admin'] = False
        
        flash(f'Welcome, {guest_name}! You are playing as a guest. Your data will be deleted when you leave.', 'success')
        return redirect(url_for('lobbies'))
        
    except Exception as e:
        logger.error(f"Error creating guest user: {e}")
        flash('An error occurred while creating guest account. Please try again.', 'error')
        return redirect(url_for('login'))

@application.route('/convert_guest', methods=['GET', 'POST'])
def convert_guest():
    """Convert a guest account to a registered account"""
    if not session.get('is_guest', False):
        flash('This feature is only available for guest users.', 'error')
        return redirect(url_for('lobbies'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Please provide both email and password.', 'error')
            return render_template('convert_guest.html')
        
        try:
            # Check if email already exists
            existing_user = User.query.filter_by(email=email).first()
            if existing_user and not existing_user.email.startswith('guest_'):
                flash('This email is already registered.', 'error')
                return render_template('convert_guest.html')
            
            # Get the guest user
            guest_user_id = session.get('guest_user_id')
            guest_user = User.query.get(guest_user_id)
            
            if guest_user:
                # Update the guest user to a regular user
                guest_user.email = email
                guest_user.password = generate_password_hash(password)
                db.session.commit()
                
                # Update session
                session['is_guest'] = False
                session.pop('guest_user_id', None)
                
                flash('Your guest account has been converted to a registered account! Your game progress is now saved.', 'success')
                return redirect(url_for('lobbies'))
            else:
                flash('Guest user not found.', 'error')
                return redirect(url_for('login'))
                
        except Exception as e:
            logger.error(f"Error converting guest account: {e}")
            flash('An error occurred while converting your account. Please try again.', 'error')
    
    return render_template('convert_guest.html')

@application.route('/register', methods=['GET', 'POST'])
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

@application.route('/home')
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

@application.route('/rules')
def rules():
    return render_template('rules.html')

@application.route('/statistics')
def statistics():
    """Show player statistics page"""
    if 'username' not in session:
        flash('You need to be logged in to view statistics!', 'error')
        return redirect(url_for('login'))
    
    # Check if user is a guest
    if session.get('is_guest', False):
        flash('Statistics are not available for guest users. Register for an account to track your progress!', 'info')
        return redirect(url_for('lobbies'))
    
    try:
        username = session.get('username')
        user = User.query.filter_by(username=username).first()
        if not user:
            flash('User not found!', 'error')
            return redirect(url_for('login'))
        
        # Get or create player statistics
        stats = PlayerStats.query.filter_by(user_id=user.id).first()
        if not stats:
            stats = PlayerStats(user_id=user.id)
            db.session.add(stats)
            db.session.commit()
        
        # Get leaderboard data (top 10 players by wins)
        leaderboard = db.session.query(PlayerStats, User).join(User).filter(
            PlayerStats.games_played > 0
        ).order_by(PlayerStats.games_won.desc()).limit(10).all()
        
        # Get user's rank
        user_rank = db.session.query(PlayerStats).filter(
            PlayerStats.games_won > stats.games_won,
            PlayerStats.games_played > 0
        ).count() + 1
        
        return render_template('statistics.html', user=user, stats=stats, leaderboard=leaderboard, user_rank=user_rank)
        
    except Exception as e:
        logger.error(f"Error accessing statistics page: {e}")
        flash('An error occurred while loading statistics.', 'error')
        return redirect(url_for('lobbies'))

@application.route('/logout')
def logout():
    try:
        # Check if user is a guest and delete their data
        if session.get('is_guest', False) and 'guest_user_id' in session:
            guest_user_id = session['guest_user_id']
            guest_user = User.query.get(guest_user_id)
            
            if guest_user:
                # Remove user from any lobbies they're in
                lobby_players = LobbyPlayer.query.filter_by(user_id=guest_user_id).all()
                for lobby_player in lobby_players:
                    db.session.delete(lobby_player)
                
                # Delete the guest user
                db.session.delete(guest_user)
                db.session.commit()
                logger.info(f"Deleted guest user: {guest_user.username}")
    
    except Exception as e:
        logger.error(f"Error deleting guest user during logout: {e}")
        db.session.rollback()
    
    logout_user()
    session.clear()
    flash('You have been logged out!', 'success')
    return redirect(url_for('login'))

@application.route('/status')
def status():
    """A diagnostic route to check if database is connected"""
    try:
        db_status = User.query.first() is not None
        return "Database connected successfully!"
    except Exception as e:
        return f"Database connection failed: {e}"

@application.route('/admin/dashboard')
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

@application.route('/admin/users')
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

@application.route('/admin/user/<int:user_id>')
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

@application.route('/admin/user/<int:user_id>/edit', methods=['GET', 'POST'])
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

@application.route('/admin/user/<int:user_id>/delete', methods=['POST'])
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

@application.route('/admin/lobbies')
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

@application.route('/admin/lobby/<lobby_code>')
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

@application.route('/admin/lobby/<lobby_code>/delete', methods=['POST'])
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
@application.route('/lobbies')
def lobbies():
    """View available lobbies or create/join one"""
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    try:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        
        if not user:
            flash('User not found!', 'error')
            return redirect(url_for('login'))
        
        # Check for game completion message
        if username in game_completion_messages:
            message_data = game_completion_messages[username]
            flash(message_data['message'], message_data['type'])
            # Remove the message after displaying it
            del game_completion_messages[username]
        
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

@application.route('/lobby/create', methods=['POST'])
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
        
        # Get player count type (3 or 4 players)
        player_count_type = int(request.form.get('player_count_type', 4))
        if player_count_type not in [3, 4]:
            player_count_type = 4  # Default to 4 if invalid value
        
        logger.debug(f"Creating lobby with is_public={is_public}, player_count_type={player_count_type}")
        
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
            is_public=is_public,
            player_count_type=player_count_type
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

@application.route('/lobby/join', methods=['POST'])
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

@application.route('/lobby/<lobby_code>')
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

@application.route('/lobby/<lobby_code>/leave', methods=['POST'])
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

@application.route('/lobby/<lobby_code>/update_settings', methods=['POST'])
def update_lobby_settings(lobby_code):
    """Update lobby settings (only for lobby owner)"""
    if 'username' not in session:
        flash('Please login first!', 'error')
        return redirect(url_for('login'))
    
    try:
        username = session['username']
        user = User.query.filter_by(username=username).first()
        lobby = Lobby.query.filter_by(code=lobby_code, is_active=True).first()
        
        if not lobby:
            flash('Lobby not found!', 'error')
            return redirect(url_for('lobbies'))
        
        # Check if user is the lobby owner
        if lobby.owner_id != user.id:
            flash('Only the lobby owner can update settings!', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Check if game has already started
        if lobby.game_started:
            flash('Cannot update settings after game has started!', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Get new player count type
        new_player_count_type = int(request.form.get('player_count_type', 4))
        if new_player_count_type not in [3, 4]:
            flash('Invalid game type!', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # If changing from 4-player to 3-player or vice versa, reset all team assignments
        if lobby.player_count_type != new_player_count_type:
            # Reset all players to unassigned
            for player in lobby.players:
                player.team = 0
            
            # Update lobby settings
            lobby.player_count_type = new_player_count_type
            
            # Remove game type suffix from lobby name if it exists
            if lobby.name and "(" in lobby.name:
                lobby.name = lobby.name.split("(")[0].strip()
            
            db.session.commit()
            flash(f'Lobby updated to {new_player_count_type}-player game! All team assignments have been reset.', 'success')
        else:
            flash('No changes made to lobby settings.', 'info')
        
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
    except Exception as e:
        logger.error(f"Error updating lobby settings: {str(e)}")
        flash('An error occurred while updating lobby settings. Please try again.', 'error')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))

@application.route('/lobby/<lobby_code>/start', methods=['POST'])
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
        
        # Check if there are the correct number of players
        required_players = lobby.player_count_type
        if lobby.player_count != required_players:
            flash(f'You need exactly {required_players} players to start the game!', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Check if all players are assigned to teams
        if len(lobby.unassigned_players) > 0:
            flash('All players must be assigned to a team before starting!', 'error')
            return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
        # Check if teams are balanced based on game type
        if lobby.player_count_type == 3:
            # For 3-player games, each team should have exactly 1 player
            if len(lobby.team1_players) != 1 or len(lobby.team2_players) != 1 or len(lobby.team3_players) != 1:
                flash('Each team must have exactly 1 player in a 3-player game!', 'error')
                return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        else:
            # For 4-player games, each team should have exactly 2 players
            if len(lobby.team1_players) != 2 or len(lobby.team2_players) != 2:
                flash('Each team must have exactly 2 players in a 4-player game!', 'error')
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

@application.route('/lobby/<lobby_code>/change_team', methods=['POST'])
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
            team_name = "Team Purple" if new_team == 1 else "Team Black"
            if len(team_players) >= 2:
                flash(f'{team_name} is already full!', 'error')
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
            team_name = "Team Purple" if new_team == 1 else "Team Black"
            flash(f'You joined {team_name}!', 'success')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))
    except Exception as e:
        logger.error(f"Error changing team: {e}")
        db.session.rollback()
        flash('An error occurred while changing team. Please try again.', 'error')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))

@application.route('/lobby/<lobby_code>/vote_reset_stats', methods=['POST'])
def vote_reset_stats(lobby_code):
    """Vote to reset lobby statistics"""
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
        
        # Toggle vote
        lobby_player.voted_reset_stats = not lobby_player.voted_reset_stats
        db.session.commit()
        
        # Get all players and vote count
        all_players = LobbyPlayer.query.filter_by(lobby_id=lobby.id).all()
        votes_count = sum(1 for p in all_players if p.voted_reset_stats)
        
        # Always emit vote update to all players in lobby
        vote_status = {
            'votes_count': votes_count,
            'total_needed': 4,
            'voters': [p.user.username for p in all_players if p.voted_reset_stats],
            'total_players': len(all_players)
        }
        socketio.emit('reset_vote_update', vote_status, room=lobby_code)
        
        # Check if we have 4 players and all voted
        if len(all_players) == 4 and votes_count == 4:
            # All players voted - reset statistics
            lobby.team1_wins = 0
            lobby.team2_wins = 0
            lobby.total_games_played = 0
            lobby.next_game_multiplier = 1
            
            # Reset all votes
            for player in all_players:
                player.voted_reset_stats = False
            
            db.session.commit()
            
            # Emit event to all players in lobby
            socketio.emit('stats_reset', {
                'message': 'Lobby statistics have been reset!',
                'team1_wins': 0,
                'team2_wins': 0,
                'total_games_played': 0,
                'next_game_multiplier': 1
            }, room=lobby_code)
            
            flash('Statistics have been reset successfully!', 'success')
        else:
            # Provide feedback to the user who voted
            if lobby_player.voted_reset_stats:
                if len(all_players) == 4:
                    flash(f'You voted to reset statistics! ({votes_count}/4 votes)', 'info')
                else:
                    flash(f'You voted to reset statistics! Need 4 players in lobby first. ({len(all_players)}/4 players)', 'warning')
            else:
                flash('You withdrew your vote to reset statistics.', 'info')
        
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))
        
    except Exception as e:
        logger.error(f"Error voting for stats reset: {e}")
        db.session.rollback()
        flash('An error occurred while voting. Please try again.', 'error')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))

@application.route('/game/<lobby_code>')
@login_required
def game_page(lobby_code):
    lobby = Lobby.query.filter_by(code=lobby_code).first_or_404()
    
    # Check if the game has actually started
    if not lobby.game_started:
        flash('The game has not been started yet. Please wait for the lobby owner to start the game.', 'warning')
        return redirect(url_for('lobby_detail', lobby_code=lobby_code))
    
    # Check if user is a member of this lobby
    username = session.get('username')
    if username:
        user = User.query.filter_by(username=username).first()
        if user:
            lobby_player = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first()
            if not lobby_player:
                flash('You are not a member of this lobby!', 'error')
                return redirect(url_for('lobbies'))
    
    return render_template('game.html', 
                         lobby=lobby,
                         current_user=current_user)  # Flask-Login makes current_user available automatically

@application.route('/game/<lobby_code>/leave', methods=['POST'])
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

@socketio.on('initialize_game')
def handle_initialize_game(data):
    """Initialize the game state when a player joins"""
    lobby_code = data.get('lobby_code')
    
    # Get the lobby and check if game has started
    lobby = Lobby.query.filter_by(code=lobby_code).first()
    if not lobby or not lobby.game_started:
        emit('error', {'message': 'Game has not been started yet'})
        return
    
    # Create new game if it doesn't exist
    if lobby_code not in games:
        # Calculate starting player based on actual games played (not points won)
        starting_player = SepticaGame.calculate_starting_player(lobby.total_games_played)
        games[lobby_code] = SepticaGame(starting_player)
    
    username = session.get('username')
    user = User.query.filter_by(username=username).first()
    if not user:
        emit('error', {'message': 'User not found'})
        return
    
    # Check if user is a member of this lobby
    lobby_player = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first()
    if not lobby_player:
        emit('error', {'message': 'You are not a member of this lobby'})
        return
    
    # Get players ordered properly for game (Team Purple: positions 0,2; Team Black: positions 1,3)
    lobby_players = get_ordered_players(lobby.id)
    player_position = next((i for i, lp in enumerate(lobby_players) if lp.user_id == user.id), None)
    
    if player_position is not None:
        # Join player-specific room
        player_room = f"{lobby_code}_player_{player_position}"
        join_room(player_room)
        
        # Get player names in order
        player_names = []
        for lp in lobby_players:
            player_names.append(lp.user.username)
        
        # Get and send initial game state to player
        game_state = games[lobby_code].get_game_state(player_position)
        game_state['position'] = player_position  # Add player position to game state
        game_state['username'] = username  # Add username to game state
        game_state['player_names'] = player_names  # Add all player names
        
        emit('game_state_update', game_state)

@socketio.on('play_card')
def handle_play_card(data):
    lobby_code = data.get('lobby_code')
    card_index = data.get('card_index')
    
    # Get the lobby and check if game has started
    lobby = Lobby.query.filter_by(code=lobby_code).first()
    if not lobby or not lobby.game_started:
        emit('error', {'message': 'Game has not been started yet'})
        return
    
    if lobby_code not in games:
        emit('error', {'message': 'Game not found'})
        return
        
    # Get player position
    username = session.get('username')
    user = User.query.filter_by(username=username).first()
    if not user:
        emit('error', {'message': 'User not found'})
        return
    
    # Check if user is a member of this lobby
    lobby_player = LobbyPlayer.query.filter_by(lobby_id=lobby.id, user_id=user.id).first()
    if not lobby_player:
        emit('error', {'message': 'You are not a member of this lobby'})
        return
    
    # Get players ordered properly for game (Team Purple: positions 0,2; Team Black: positions 1,3)
    lobby_players = get_ordered_players(lobby.id)
    player_position = next((i for i, lp in enumerate(lobby_players) if lp.user_id == user.id), None)
    
    if player_position is None:
        return
    
    # Get player names in order
    player_names = []
    for lp in lobby_players:
        player_names.append(lp.user.username)
        
    # Play the card
    success, error = games[lobby_code].play_card(player_position, card_index)
    
    if success:
        # Check if game is finished after playing the card
        if handle_game_completion(lobby_code, lobby, lobby_players):
            return  # Game completed, notifications already sent
            
        # Broadcast updated game state to all players
        for i, _ in enumerate(lobby_players):
            game_state = games[lobby_code].get_game_state(i)
            game_state['position'] = i
            game_state['player_names'] = player_names
            emit('game_state_update', game_state, room=f"{lobby_code}_player_{i}")
    else:
        emit('game_error', {'message': error})

def get_or_create_player_stats(user_id):
    """Get existing player stats or create new ones"""
    stats = PlayerStats.query.filter_by(user_id=user_id).first()
    if not stats:
        stats = PlayerStats(user_id=user_id)
        db.session.add(stats)
        db.session.flush()  # Flush to get the ID
    return stats

def update_player_statistics(lobby, lobby_players, winner_team, is_tie, scores, hands_won, is_perfect_game):
    """Update player statistics after a game completion"""
    try:
        # Get team assignments
        team1_players = []  # Team Purple (positions 0, 2)
        team2_players = []  # Team Black (positions 1, 3)
        
        for i, player in enumerate(lobby_players):
            if i % 2 == 0:  # Positions 0, 2 = Team Purple
                team1_players.append(player.user_id)
            else:  # Positions 1, 3 = Team Black
                team2_players.append(player.user_id)
        
        # Determine winners and losers
        if is_tie:
            # Handle tie - no winners/losers, just update games played
            for player in lobby_players:
                stats = get_or_create_player_stats(player.user_id)
                stats.games_played += 1
                stats.total_hands_played += hands_won[0] + hands_won[1]  # Both teams' hands
                stats.last_updated = datetime.utcnow()
                # Reset lose streak on tie, don't affect win streak
                stats.current_lose_streak = 0
        else:
            # Determine winning and losing teams
            if winner_team == 0:  # Team Purple wins
                winning_players = team1_players
                losing_players = team2_players
                winning_score = scores[0]
                losing_score = scores[1]
                winning_hands = hands_won[0]
                losing_hands = hands_won[1]
            else:  # Team Black wins
                winning_players = team2_players
                losing_players = team1_players
                winning_score = scores[1]
                losing_score = scores[0]
                winning_hands = hands_won[1]
                losing_hands = hands_won[0]
            
            # Check if it was a comeback win (winning team was behind at some point)
            was_comeback = losing_score > 0 and winning_score > losing_score
            
            # Update statistics for winning players
            for user_id in winning_players:
                stats = get_or_create_player_stats(user_id)
                stats.games_played += 1
                stats.games_won += 1
                stats.total_points_scored += winning_score
                stats.total_points_conceded += losing_score
                stats.total_hands_played += winning_hands + losing_hands
                stats.current_win_streak += 1
                stats.current_lose_streak = 0
                
                # Update longest win streak
                if stats.current_win_streak > stats.longest_win_streak:
                    stats.longest_win_streak = stats.current_win_streak
                
                # Check for perfect game (opponent scored 0)
                if is_perfect_game:
                    stats.perfect_games += 1
                
                # Check for comeback win
                if was_comeback:
                    stats.comeback_wins += 1
                
                stats.last_updated = datetime.utcnow()
            
            # Update statistics for losing players
            for user_id in losing_players:
                stats = get_or_create_player_stats(user_id)
                stats.games_played += 1
                stats.games_lost += 1
                stats.total_points_scored += losing_score
                stats.total_points_conceded += winning_score
                stats.total_hands_played += losing_hands + winning_hands
                stats.current_lose_streak += 1
                stats.current_win_streak = 0
                
                # Update longest lose streak
                if stats.current_lose_streak > stats.longest_lose_streak:
                    stats.longest_lose_streak = stats.current_lose_streak
                
                stats.last_updated = datetime.utcnow()
        
        # Commit all statistics updates
        db.session.commit()
        logger.info(f"Updated player statistics for lobby {lobby.code}")
        
    except Exception as e:
        logger.error(f"Error updating player statistics: {e}")
        db.session.rollback()

def handle_game_completion(lobby_code, lobby, lobby_players):
    """Handle game completion - update lobby stats and notify players"""
    game = games[lobby_code]
    
    if not game.is_game_finished():
        return False
    
    # Get game result
    result = game.get_game_result()
    winner_team = result['winner']
    is_tie = result['is_tie']
    scores = result['scores']
    hands_won = result['hands_won']
    
    # Increment total games played regardless of outcome
    lobby.total_games_played += 1
    
    # Update lobby statistics
    if is_tie:
        # Set multiplier for next game (max 2)
        lobby.next_game_multiplier = 2
        notification_message = f"Game ended in a tie! ({scores[0]}-{scores[1]}) Next game is worth 2 points."
        notification_type = "info"
    else:
        # Check if it's a perfect game (losing team won zero hands)
        is_perfect_game = (hands_won[0] == 0 and winner_team == 1) or (hands_won[1] == 0 and winner_team == 0)
        
        # Award points to winning team
        points_awarded = lobby.next_game_multiplier
        if is_perfect_game:
            points_awarded += 1  # Bonus point for perfect game
        
        if winner_team == 0:
            lobby.team1_wins += points_awarded
            team_name = "Team Purple"
        else:
            lobby.team2_wins += points_awarded
            team_name = "Team Black"
        
        # Reset multiplier
        lobby.next_game_multiplier = 1
        
        # Create notification message
        if is_perfect_game:
            notification_message = f"{team_name} wins PERFECTLY! ({scores[0]}-{scores[1]}, opponent won 0 hands) +{points_awarded} points awarded (including bonus for shutout)."
        else:
            notification_message = f"{team_name} wins! ({scores[0]}-{scores[1]}) +{points_awarded} points awarded."
        notification_type = "success"
    
    # Update player statistics
    update_player_statistics(lobby, lobby_players, winner_team, is_tie, scores, hands_won, is_perfect_game if not is_tie else False)
    
    # Save lobby changes
    db.session.commit()
    
    # Store completion message for all players in this lobby
    completion_message = f"{notification_message} Lobby Stats: Team Purple: {lobby.team1_wins} wins - Team Black: {lobby.team2_wins} wins"
    
    # Store message for each player
    for lp in lobby_players:
        game_completion_messages[lp.user.username] = {
            'message': completion_message,
            'type': notification_type,
            'lobby_code': lobby_code
        }
    
    # Reset lobby game status
    lobby.game_started = False
    db.session.commit()
    
    # Remove game from active games
    del games[lobby_code]
    
    # Prepare game completion data
    completion_data = {
        'game_finished': True,
        'winner_team': winner_team,
        'is_tie': is_tie,
        'scores': scores,
        'lobby_stats': {
            'team1_wins': lobby.team1_wins,
            'team2_wins': lobby.team2_wins,
            'next_game_multiplier': lobby.next_game_multiplier
        },
        'message': completion_message,
        'notification_type': notification_type
    }
    
    # Notify all players and set flash message for each
    for i, lp in enumerate(lobby_players):
        # Send the completion notification via SocketIO
        emit('game_completed', completion_data, room=f"{lobby_code}_player_{i}")
    
    # Also emit to the general lobby room
    emit('game_completed', completion_data, room=lobby_code)
    
    return True

@socketio.on('take_hand')
def handle_take_hand(data):
    lobby_code = data.get('lobby_code')
    
    if lobby_code not in games:
        return
        
    # Get player position
    lobby = Lobby.query.filter_by(code=lobby_code).first()
    username = session.get('username')
    user = User.query.filter_by(username=username).first()
    
    # Get players ordered properly for game (Team Purple: positions 0,2; Team Black: positions 1,3)
    lobby_players = get_ordered_players(lobby.id)
    player_position = next((i for i, lp in enumerate(lobby_players) if lp.user_id == user.id), None)
    
    if player_position is None:
        return
    
    # Get player names in order
    player_names = []
    for lp in lobby_players:
        player_names.append(lp.user.username)
        
    # Take the hand
    success, error = games[lobby_code].take_hand()
    
    if success:
        # Check if game is finished
        if handle_game_completion(lobby_code, lobby, lobby_players):
            return  # Game completed, notifications already sent
        
        # Broadcast updated game state to all players
        for i, _ in enumerate(lobby_players):
            game_state = games[lobby_code].get_game_state(i)
            game_state['position'] = i
            game_state['player_names'] = player_names
            emit('game_state_update', game_state, room=f"{lobby_code}_player_{i}")
    else:
        emit('game_error', {'message': error})

@socketio.on('forfeit_hand')
def handle_forfeit_hand(data):
    lobby_code = data.get('lobby_code')
    
    if lobby_code not in games:
        return
        
    # Get player position
    lobby = Lobby.query.filter_by(code=lobby_code).first()
    username = session.get('username')
    user = User.query.filter_by(username=username).first()
    
    # Get players ordered properly for game (Team Purple: positions 0,2; Team Black: positions 1,3)
    lobby_players = get_ordered_players(lobby.id)
    player_position = next((i for i, lp in enumerate(lobby_players) if lp.user_id == user.id), None)
    
    if player_position is None:
        return
    
    # Get player names in order
    player_names = []
    for lp in lobby_players:
        player_names.append(lp.user.username)
        
    # Forfeit the hand
    success, error = games[lobby_code].forfeit_hand()
    
    if success:
        # Check if game is finished
        if handle_game_completion(lobby_code, lobby, lobby_players):
            return  # Game completed, notifications already sent
        
        # Broadcast updated game state to all players
        for i, _ in enumerate(lobby_players):
            game_state = games[lobby_code].get_game_state(i)
            game_state['position'] = i
            game_state['player_names'] = player_names
            emit('game_state_update', game_state, room=f"{lobby_code}_player_{i}")
    else:
        emit('game_error', {'message': error})

# Update the run statement to use SocketIO
if __name__ == "__main__":
    # Clean up old guest users on startup
    with application.app_context():
        cleanup_guest_users()
    
    # Local development only
    socketio.run(application, host="0.0.0.0", port=5000, debug=True)