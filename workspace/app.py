import os
import sqlite3
from datetime import timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, make_response
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.permanent_session_lifetime = timedelta(days=7)

# Session configuration for security
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=False,  # Set to True in production with HTTPS
    SESSION_COOKIE_SAMESITE='Lax',
)

DATABASE = 'platform.db'

# Context processor to inject session into all templates
@app.context_processor
def inject_session():
    return dict(session=session)

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# ==================== AUTH DECORATOR ====================
def login_required(f):
    """Decorator to require login for protected routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def init_db():
    """Initialize the database with all required tables."""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            user_type TEXT NOT NULL CHECK(user_type IN ('startup', 'vc')),
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Startup profiles
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS startup_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            company_name TEXT NOT NULL,
            industry TEXT,
            stage TEXT,
            description TEXT,
            funding_needed REAL,
            website TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # VC profiles
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vc_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            firm_name TEXT NOT NULL,
            investment_focus TEXT,
            stage_preference TEXT,
            description TEXT,
            min_investment REAL,
            max_investment REAL,
            website TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Matches table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            startup_id INTEGER NOT NULL,
            vc_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (startup_id) REFERENCES users(id),
            FOREIGN KEY (vc_id) REFERENCES users(id),
            UNIQUE(startup_id, vc_id)
        )
    ''')
    
    # Messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            subject TEXT,
            body TEXT NOT NULL,
            is_read BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    conn.close()

def seed_data():
    """Seed sample data for startups and VCs."""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Check if seed data already exists
    existing = cursor.execute("SELECT COUNT(*) FROM startup_profiles").fetchone()[0]
    if existing > 0:
        conn.close()
        return
    
    # Create sample startups
    startups = [
        ('techstart@demo.com', 'startup', 'TechStart Inc', 'TechStart', 'AI/ML', 'Series A', 'AI-powered automation platform for enterprise workflows', 500000),
        ('greenflow@demo.com', 'startup', 'GreenFlow', 'GreenFlow', 'CleanTech', 'Seed', 'Sustainable energy management system for commercial buildings', 250000),
        ('medtech@demo.com', 'startup', 'MediCare+', 'MediCare+', 'HealthTech', 'Series B', 'AI-driven diagnostic platform for early disease detection', 1000000)
    ]
    
    # Create sample VCs
    vcs = [
        ('vc1@demo.com', 'vc', 'Venture First', 'Venture First', 'Technology', 'Series A', 'Early-stage VC focused on enterprise software', 500000, 5000000),
        ('vc2@demo.com', 'vc', 'Green Ventures', 'Green Ventures', 'CleanTech', 'Seed', 'Impact investor specializing in sustainability startups', 100000, 1000000),
        ('vc3@demo.com', 'vc', 'Health Capital', 'Health Capital', 'HealthTech', 'Series A,B', 'Healthcare-focused investment firm', 1000000, 10000000)
    ]
    
    # Insert startups
    for email, user_type, name, company, industry, stage, description, funding in startups:
        password_hash = generate_password_hash('demo123')
        cursor.execute(
            'INSERT INTO users (email, password_hash, user_type, name) VALUES (?, ?, ?, ?)',
            (email, password_hash, user_type, name)
        )
        user_id = cursor.lastrowid
        cursor.execute(
            'INSERT INTO startup_profiles (user_id, company_name, industry, stage, description, funding_needed) VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, company, industry, stage, description, funding)
        )
    
    # Insert VCs
    for email, user_type, name, firm, focus, stage_pref, description, min_inv, max_inv in vcs:
        password_hash = generate_password_hash('demo123')
        cursor.execute(
            'INSERT INTO users (email, password_hash, user_type, name) VALUES (?, ?, ?, ?)',
            (email, password_hash, user_type, name)
        )
        user_id = cursor.lastrowid
        cursor.execute(
            'INSERT INTO vc_profiles (user_id, firm_name, investment_focus, stage_preference, description, min_investment, max_investment) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (user_id, firm, focus, stage_pref, description, min_inv, max_inv)
        )
    
    conn.commit()
    conn.close()

def get_current_user():
    if 'user_id' not in session:
        return None
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    return user

def get_platform_stats():
    """Get platform statistics for homepage."""
    db = get_db()
    startup_count = db.execute("SELECT COUNT(*) FROM startup_profiles").fetchone()[0]
    vc_count = db.execute("SELECT COUNT(*) FROM vc_profiles").fetchone()[0]
    matched_count = db.execute("SELECT COUNT(*) FROM matches WHERE status = 'accepted'").fetchone()[0]
    return {'startups': startup_count, 'vcs': vc_count, 'matches': matched_count}

# ==================== AUTH ROUTES ====================

@app.route('/register', methods=['GET', 'POST'])
def register():
    # FIRST check if user is authenticated - redirect to dashboard BEFORE clearing session
    if request.method == 'GET' and session.get('user_id'):
        if session.get('user_type') == 'startup':
            return redirect(url_for('startup_dashboard'))
        else:
            return redirect(url_for('vc_dashboard'))
    
    # THEN clear any stale session data for unauthenticated users on GET
    if request.method == 'GET':
        session.clear()
    
    # Handle POST (registration form submission)
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form.get('confirm_password')
        user_type = request.form['user_type']
        name = request.form['name']
        
        if not email or not password or not user_type or not name:
            flash('All fields are required.', 'error')
            return redirect(url_for('register'))
        
        # Check password confirmation
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('register'))
        
        # Check password strength (minimum 8 characters)
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return redirect(url_for('register'))
        
        password_hash = generate_password_hash(password)
        
        db = get_db()
        try:
            cursor = db.cursor()
            cursor.execute(
                'INSERT INTO users (email, password_hash, user_type, name) VALUES (?, ?, ?, ?)',
                (email, password_hash, user_type, name)
            )
            db.commit()
            user_id = cursor.lastrowid
            
            # Create profile based on user type
            if user_type == 'startup':
                cursor.execute(
                    'INSERT INTO startup_profiles (user_id, company_name) VALUES (?, ?)',
                    (user_id, name)
                )
            else:
                cursor.execute(
                    'INSERT INTO vc_profiles (user_id, firm_name) VALUES (?, ?)',
                    (user_id, name)
                )
            db.commit()
            
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already registered.', 'error')
            return redirect(url_for('register'))
    
    # GET request - return registration form with cache prevention
    response = make_response(render_template('auth/register.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/login', methods=['GET', 'POST'])
def login():
    # FIRST check if user is authenticated - redirect to dashboard BEFORE clearing session
    if request.method == 'GET' and session.get('user_id'):
        if session.get('user_type') == 'startup':
            return redirect(url_for('startup_dashboard'))
        else:
            return redirect(url_for('vc_dashboard'))
    
    # THEN clear any stale session data for unauthenticated users on GET
    if request.method == 'GET':
        session.clear()
    
    # Handle POST (login form submission)
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        if not email or not password:
            flash('Email and password are required.', 'error')
            return redirect(url_for('login'))
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        
        if user and check_password_hash(user['password_hash'], password):
            # Set new session after successful authentication
            session['user_id'] = user['id']
            session['user_type'] = user['user_type']
            session['user_name'] = user['name']
            session['unread_count'] = 0
            session.permanent = True  # Make session persist
            session.modified = True  # Mark session as modified
            
            flash(f'Welcome back, {user["name"]}!', 'success')
            
            # After successful auth, redirect to next if provided
            next_url = request.args.get('next')
            if next_url and next_url.startswith(request.host_url):
                return redirect(next_url)
            
            if user['user_type'] == 'startup':
                return redirect(url_for('startup_dashboard'))
            else:
                return redirect(url_for('vc_dashboard'))
        else:
            flash('Invalid email or password.', 'error')
            return redirect(url_for('login'))
    
    # GET request - return login form with cache prevention
    next_url = request.args.get('next', '')
    intended = request.args.get('intended', '')
    if next_url and not intended:
        if '/startup/' in next_url:
            intended = 'Startup Dashboard'
        elif '/vc/' in next_url:
            intended = 'VC Dashboard'
        else:
            intended = 'Dashboard'
    
    response = make_response(render_template('auth/login.html', next=next_url, intended=intended))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/logout')
def logout():
    # Clear all session data FIRST
    session.clear()
    
    # Create response, then delete session cookie properly
    response = make_response(redirect(url_for('index')))
    response.set_cookie(app.session_cookie_name, '', expires=0)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    flash('You have been logged out.', 'info')
    return response

# ==================== GENERAL ROUTES ====================

@app.route('/')
def index():
    stats = get_platform_stats()
    response = make_response(render_template('index.html', stats=stats))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/explore')
def explore():
    # FIX: Direct redirect to /explore/startups
    return redirect(url_for('explore_startups'))

@app.route('/explore/startups')
def explore_startups():
    # Get filter parameters
    industry = request.args.get('industry')
    stage = request.args.get('stage')
    min_funding = request.args.get('min_funding')
    max_funding = request.args.get('max_funding')
    
    # Filter out test/qa users
    query = '''
        SELECT u.id, u.name, sp.company_name, sp.industry, sp.stage, sp.description, sp.funding_needed
        FROM users u
        JOIN startup_profiles sp ON u.id = sp.user_id
        WHERE u.user_type = 'startup'
        AND u.email NOT LIKE '%test%' AND u.email NOT LIKE '%qa%'
    '''
    params = []
    
    if industry:
        query += ' AND sp.industry = ?'
        params.append(industry)
    if stage:
        query += ' AND sp.stage = ?'
        params.append(stage)
    if min_funding:
        query += ' AND sp.funding_needed >= ?'
        params.append(float(min_funding))
    if max_funding:
        query += ' AND sp.funding_needed <= ?'
        params.append(float(max_funding))
    
    query += ' ORDER BY sp.created_at DESC'
    
    db = get_db()
    startups = db.execute(query, params).fetchall()
    
    response = make_response(render_template('explore/startups.html', startups=startups, active_entity='startups',
                                             industry=industry, stage=stage, min_funding=min_funding, max_funding=max_funding))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/explore/vcs')
def explore_vcs():
    # Get filter parameters
    focus = request.args.get('focus')
    stage = request.args.get('stage')
    min_investment = request.args.get('min_investment')
    max_investment = request.args.get('max_investment')
    
    query = '''
        SELECT u.id, u.name, vp.firm_name, vp.investment_focus, vp.stage_preference, vp.description, vp.min_investment, vp.max_investment
        FROM users u
        JOIN vc_profiles vp ON u.id = vp.user_id
        WHERE u.user_type = 'vc'
        AND u.email NOT LIKE '%test%' AND u.email NOT LIKE '%qa%'
    '''
    params = []
    
    if focus:
        query += ' AND vp.investment_focus = ?'
        params.append(focus)
    if stage:
        query += ' AND vp.stage_preference LIKE ?'
        params.append(f'%{stage}%')
    if min_investment:
        query += ' AND vp.min_investment >= ?'
        params.append(float(min_investment))
    if max_investment:
        query += ' AND vp.max_investment <= ?'
        params.append(float(max_investment))
    
    query += ' ORDER BY vp.created_at DESC'
    
    db = get_db()
    vcs = db.execute(query, params).fetchall()
    
    response = make_response(render_template('explore/vcs.html', vcs=vcs, active_entity='vcs',
                                            focus=focus, stage=stage, min_investment=min_investment, max_investment=max_investment))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/profile/<int:user_id>')
def view_profile(user_id):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('index'))
    
    if user['user_type'] == 'startup':
        profile = db.execute('SELECT * FROM startup_profiles WHERE user_id = ?', (user_id,)).fetchone()
        response = make_response(render_template('profile/startup_profile.html', user=user, profile=profile))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    else:
        profile = db.execute('SELECT * FROM vc_profiles WHERE user_id = ?', (user_id,)).fetchone()
        response = make_response(render_template('profile/vc_profile.html', user=user, profile=profile))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

# ==================== STARTUP ROUTES ====================

@app.route('/startup/dashboard')
@login_required
def startup_dashboard():
    if session.get('user_type') != 'startup':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    db = get_db()
    user = get_current_user()
    profile = db.execute('SELECT * FROM startup_profiles WHERE user_id = ?', (session['user_id'],)).fetchone()
    
    # Get matches
    matches = db.execute('''
        SELECT m.*, u.name as vc_name, vp.firm_name, vp.investment_focus
        FROM matches m
        JOIN users u ON m.vc_id = u.id
        JOIN vc_profiles vp ON u.id = vp.user_id
        WHERE m.startup_id = ?
        ORDER BY m.created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    # Get unread messages count
    unread = db.execute(
        'SELECT COUNT(*) as cnt FROM messages WHERE receiver_id = ? AND is_read = 0',
        (session['user_id'],)
    ).fetchone()
    
    session['unread_count'] = unread['cnt']
    session.modified = True
    
    response = make_response(render_template('dashboard/startup_dashboard.html', 
                           user=user, profile=profile, matches=matches, unread_count=unread['cnt']))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/startup/profile', methods=['GET', 'POST'])
@login_required
def startup_profile():
    if session.get('user_type') != 'startup':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    db = get_db()
    
    if request.method == 'POST':
        company_name = request.form['company_name']
        industry = request.form['industry']
        stage = request.form['stage']
        description = request.form['description']
        funding_needed = request.form['funding_needed']
        website = request.form['website']
        
        db.execute('''
            UPDATE startup_profiles 
            SET company_name = ?, industry = ?, stage = ?, description = ?, funding_needed = ?, website = ?
            WHERE user_id = ?
        ''', (company_name, industry, stage, description, funding_needed, website, session['user_id']))
        db.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('startup_profile'))
    
    user = get_current_user()
    profile = db.execute('SELECT * FROM startup_profiles WHERE user_id = ?', (session['user_id'],)).fetchone()
    response = make_response(render_template('profile/startup_profile.html', user=user, profile=profile, edit=True))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/startup/matches')
@login_required
def startup_matches():
    if session.get('user_type') != 'startup':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    db = get_db()
    matches = db.execute('''
        SELECT m.*, u.name as vc_name, vp.firm_name, vp.investment_focus, vp.stage_preference
        FROM matches m
        JOIN users u ON m.vc_id = u.id
        JOIN vc_profiles vp ON u.id = vp.user_id
        WHERE m.startup_id = ?
        ORDER BY m.created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    response = make_response(render_template('matches/startup_matches.html', matches=matches))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/startup/messages')
@login_required
def startup_messages():
    if session.get('user_type') != 'startup':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    db = get_db()
    messages = db.execute('''
        SELECT m.*, u.name as sender_name
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.receiver_id = ?
        ORDER BY m.created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    response = make_response(render_template('messages/inbox.html', messages=messages))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ==================== VC ROUTES ====================

@app.route('/vc/dashboard')
@login_required
def vc_dashboard():
    if session.get('user_type') != 'vc':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    db = get_db()
    user = get_current_user()
    profile = db.execute('SELECT * FROM vc_profiles WHERE user_id = ?', (session['user_id'],)).fetchone()
    
    # Get matches
    matches = db.execute('''
        SELECT m.*, u.name as startup_name, sp.company_name, sp.industry, sp.stage
        FROM matches m
        JOIN users u ON m.startup_id = u.id
        JOIN startup_profiles sp ON u.id = sp.user_id
        WHERE m.vc_id = ?
        ORDER BY m.created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    # Get unread messages count
    unread = db.execute(
        'SELECT COUNT(*) as cnt FROM messages WHERE receiver_id = ? AND is_read = 0',
        (session['user_id'],)
    ).fetchone()
    
    session['unread_count'] = unread['cnt']
    session.modified = True
    
    response = make_response(render_template('dashboard/vc_dashboard.html', 
                           user=user, profile=profile, matches=matches, unread_count=unread['cnt']))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/vc/profile', methods=['GET', 'POST'])
@login_required
def vc_profile():
    if session.get('user_type') != 'vc':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    db = get_db()
    
    if request.method == 'POST':
        firm_name = request.form['firm_name']
        investment_focus = request.form['investment_focus']
        stage_preference = request.form['stage_preference']
        description = request.form['description']
        min_investment = request.form['min_investment']
        max_investment = request.form['max_investment']
        website = request.form['website']
        
        db.execute('''
            UPDATE vc_profiles 
            SET firm_name = ?, investment_focus = ?, stage_preference = ?, description = ?, min_investment = ?, max_investment = ?, website = ?
            WHERE user_id = ?
        ''', (firm_name, investment_focus, stage_preference, description, min_investment, max_investment, website, session['user_id']))
        db.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('vc_profile'))
    
    user = get_current_user()
    profile = db.execute('SELECT * FROM vc_profiles WHERE user_id = ?', (session['user_id'],)).fetchone()
    response = make_response(render_template('profile/vc_profile.html', user=user, profile=profile, edit=True))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/vc/matches')
@login_required
def vc_matches():
    if session.get('user_type') != 'vc':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    db = get_db()
    matches = db.execute('''
        SELECT m.*, u.name as startup_name, sp.company_name, sp.industry, sp.stage, sp.description, sp.funding_needed
        FROM matches m
        JOIN users u ON m.startup_id = u.id
        JOIN startup_profiles sp ON u.id = sp.user_id
        WHERE m.vc_id = ?
        ORDER BY m.created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    response = make_response(render_template('matches/vc_matches.html', matches=matches))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/vc/messages')
@login_required
def vc_messages():
    if session.get('user_type') != 'vc':
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    
    db = get_db()
    messages = db.execute('''
        SELECT m.*, u.name as sender_name
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.receiver_id = ?
        ORDER BY m.created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    response = make_response(render_template('messages/inbox.html', messages=messages))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ==================== MATCH ROUTES ====================

@app.route('/match/request/<int:user_id>', methods=['POST'])
@login_required
def match_request(user_id):
    db = get_db()
    current_user = get_current_user()
    
    # Determine who is the startup and who is the VC
    if session.get('user_type') == 'startup':
        startup_id = session['user_id']
        vc_id = user_id
    else:
        startup_id = user_id
        vc_id = session['user_id']
    
    # Check if match already exists
    existing = db.execute(
        'SELECT * FROM matches WHERE (startup_id = ? AND vc_id = ?) OR (startup_id = ? AND vc_id = ?)',
        (startup_id, vc_id, vc_id, startup_id)
    ).fetchone()
    
    if existing:
        flash('Match request already exists.', 'info')
        return redirect(request.referrer or url_for('index'))
    
    try:
        db.execute(
            'INSERT INTO matches (startup_id, vc_id, status) VALUES (?, ?, ?)',
            (startup_id, vc_id, 'pending')
        )
        db.commit()
        flash('Match request sent!', 'success')
    except sqlite3.IntegrityError:
        flash('Could not create match request.', 'error')
    
    return redirect(request.referrer or url_for('index'))

@app.route('/match/accept/<int:match_id>', methods=['POST'])
@login_required
def match_accept(match_id):
    db = get_db()
    db.execute("UPDATE matches SET status = 'accepted' WHERE id = ?", (match_id,))
    db.commit()
    flash('Match accepted!', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/match/reject/<int:match_id>', methods=['POST'])
@login_required
def match_reject(match_id):
    db = get_db()
    db.execute("UPDATE matches SET status = 'rejected' WHERE id = ?", (match_id,))
    db.commit()
    flash('Match rejected.', 'info')
    return redirect(request.referrer or url_for('index'))

# ==================== MESSAGE ROUTES ====================

@app.route('/messages/compose', methods=['GET', 'POST'])
@login_required
def compose_message():
    if request.method == 'POST':
        receiver_id = request.form['receiver_id']
        subject = request.form['subject']
        body = request.form['body']
        
        if not receiver_id or not body:
            flash('Recipient and message body are required.', 'error')
            return redirect(url_for('compose_message'))
        
        db = get_db()
        db.execute(
            'INSERT INTO messages (sender_id, receiver_id, subject, body) VALUES (?, ?, ?, ?)',
            (session['user_id'], receiver_id, subject, body)
        )
        db.commit()
        flash('Message sent!', 'success')
        return redirect(url_for('inbox'))
    
    db = get_db()
    receiver_id = request.args.get('receiver_id')
    user = None
    if receiver_id:
        user = db.execute('SELECT * FROM users WHERE id = ?', (receiver_id,)).fetchone()
    
    response = make_response(render_template('messages/compose.html', receiver=user))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/messages/inbox')
@login_required
def inbox():
    db = get_db()
    messages = db.execute('''
        SELECT m.*, u.name as sender_name, u.user_type as sender_type
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.receiver_id = ?
        ORDER BY m.created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    response = make_response(render_template('messages/inbox.html', messages=messages))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/messages/read/<int:message_id>')
@login_required
def read_message(message_id):
    db = get_db()
    message = db.execute('SELECT * FROM messages WHERE id = ? AND receiver_id = ?', 
                         (message_id, session['user_id'])).fetchone()
    
    if message:
        db.execute('UPDATE messages SET is_read = 1 WHERE id = ?', (message_id,))
        db.commit()
        sender = db.execute('SELECT * FROM users WHERE id = ?', (message['sender_id'],)).fetchone()
        response = make_response(render_template('messages/compose.html', message=message, sender=sender, read_only=True))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    
    flash('Message not found.', 'error')
    return redirect(url_for('inbox'))

# ==================== APP ENTRY POINT ====================

if __name__ == '__main__':
    init_db()
    seed_data()
    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    app.run(host=host, port=port, debug=True)