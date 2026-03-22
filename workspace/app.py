import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Database configuration
DATABASE = 'startup_vc.db'

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

def init_db():
    """Initialize database tables"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Startup profiles
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS startup_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            company_name TEXT NOT NULL,
            description TEXT,
            industry TEXT NOT NULL,
            stage TEXT NOT NULL,
            location TEXT,
            website TEXT,
            funding_needed TEXT,
            team_size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Investor profiles
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS investor_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            firm_name TEXT NOT NULL,
            description TEXT,
            industry_focus TEXT NOT NULL,
            stage_focus TEXT NOT NULL,
            location TEXT,
            website TEXT,
            investment_range TEXT,
            portfolio_size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Connections/Matches table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (from_user_id) REFERENCES users(id),
            FOREIGN KEY (to_user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()


# ============================================================
# PROTECTED ROUTES - REWRITTEN FROM SCRATCH
# ============================================================

@app.route('/dashboard')
def dashboard():
    """
    Dashboard - Protected route requiring authentication.
    Returns appropriate dashboard based on user role.
    """
    # Check authentication
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    role = session.get('role')
    db = get_db()
    
    if role == 'startup':
        # Fetch startup profile
        profile = db.execute('SELECT * FROM startup_profiles WHERE user_id = ?', (user_id,)).fetchone()
        
        if not profile:
            # No profile yet, redirect to create one
            return redirect(url_for('create_startup_profile'))
        
        # Get pending connection requests (from investors)
        connections = db.execute('''
            SELECT c.*, u.email, ip.firm_name 
            FROM connections c 
            JOIN users u ON c.from_user_id = u.id
            JOIN investor_profiles ip ON u.id = ip.user_id
            WHERE c.to_user_id = ? AND c.status = 'pending'
        ''', (user_id,)).fetchall()
        
        # Get accepted connections
        accepted = db.execute('''
            SELECT c.*, u.email, ip.firm_name 
            FROM connections c 
            JOIN users u ON c.from_user_id = u.id
            JOIN investor_profiles ip ON u.id = ip.user_id
            WHERE c.to_user_id = ? AND c.status = 'accepted'
        ''', (user_id,)).fetchall()
        
        # Get suggested investors based on matching
        suggested = db.execute('''
            SELECT * FROM investor_profiles 
            WHERE industry_focus = ? AND stage_focus = ?
        ''', (profile['industry'], profile['stage'])).fetchall()
        
        return render_template('dashboard_startup.html', 
                               profile=profile, 
                               connections=connections, 
                               accepted=accepted, 
                               suggested=suggested)
    else:
        # Fetch investor profile
        profile = db.execute('SELECT * FROM investor_profiles WHERE user_id = ?', (user_id,)).fetchone()
        
        if not profile:
            return redirect(url_for('create_investor_profile'))
        
        # Get pending connection requests (from startups)
        connections = db.execute('''
            SELECT c.*, u.email, sp.company_name 
            FROM connections c 
            JOIN users u ON c.from_user_id = u.id
            JOIN startup_profiles sp ON u.id = sp.user_id
            WHERE c.to_user_id = ? AND c.status = 'pending'
        ''', (user_id,)).fetchall()
        
        # Get accepted connections
        accepted = db.execute('''
            SELECT c.*, u.email, sp.company_name 
            FROM connections c 
            JOIN users u ON c.from_user_id = u.id
            JOIN startup_profiles sp ON u.id = sp.user_id
            WHERE c.to_user_id = ? AND c.status = 'accepted'
        ''', (user_id,)).fetchall()
        
        # Get suggested startups based on matching
        suggested = db.execute('''
            SELECT * FROM startup_profiles 
            WHERE industry = ? AND stage = ?
        ''', (profile['industry_focus'], profile['stage_focus'])).fetchall()
        
        return render_template('dashboard_investor.html', 
                               profile=profile,
                               connections=connections, 
                               accepted=accepted, 
                               suggested=suggested)


@app.route('/startup/profile', methods=['GET', 'POST'])
def create_startup_profile():
    """
    Startup profile creation/editing - Protected route.
    """
    # Check authentication
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    # Ensure user is a startup
    if session.get('role') != 'startup':
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        db = get_db()
        
        # Check if profile already exists
        existing = db.execute('SELECT id FROM startup_profiles WHERE user_id = ?', (user_id,)).fetchone()
        
        if existing:
            db.execute('''
                UPDATE startup_profiles 
                SET company_name=?, description=?, industry=?, stage=?, 
                    location=?, website=?, funding_needed=?, team_size=?
                WHERE user_id=?
            ''', (
                request.form['company_name'], request.form['description'],
                request.form['industry'], request.form['stage'],
                request.form['location'], request.form['website'],
                request.form['funding_needed'], request.form.get('team_size', 0),
                user_id
            ))
        else:
            db.execute('''
                INSERT INTO startup_profiles 
                (user_id, company_name, description, industry, stage, location, website, funding_needed, team_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, request.form['company_name'], request.form['description'],
                request.form['industry'], request.form['stage'], request.form['location'],
                request.form['website'], request.form['funding_needed'], request.form.get('team_size', 0)
            ))
        
        db.commit()
        flash('Profile saved successfully!')
        return redirect(url_for('dashboard'))
    
    db = get_db()
    profile = db.execute('SELECT * FROM startup_profiles WHERE user_id = ?', (user_id,)).fetchone()
    return render_template('profile_startup.html', profile=profile)


@app.route('/investor/profile', methods=['GET', 'POST'])
def create_investor_profile():
    """
    Investor profile creation/editing - Protected route.
    """
    # Check authentication
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    # Ensure user is an investor
    if session.get('role') != 'investor':
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        db = get_db()
        
        existing = db.execute('SELECT id FROM investor_profiles WHERE user_id = ?', (user_id,)).fetchone()
        
        if existing:
            db.execute('''
                UPDATE investor_profiles 
                SET firm_name=?, description=?, industry_focus=?, stage_focus=?,
                    location=?, website=?, investment_range=?, portfolio_size=?
                WHERE user_id=?
            ''', (
                request.form['firm_name'], request.form['description'],
                request.form['industry_focus'], request.form['stage_focus'],
                request.form['location'], request.form['website'],
                request.form['investment_range'], request.form.get('portfolio_size', 0),
                user_id
            ))
        else:
            db.execute('''
                INSERT INTO investor_profiles 
                (user_id, firm_name, description, industry_focus, stage_focus, 
                 location, website, investment_range, portfolio_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, request.form['firm_name'], request.form['description'],
                request.form['industry_focus'], request.form['stage_focus'],
                request.form['location'], request.form['website'],
                request.form['investment_range'], request.form.get('portfolio_size', 0)
            ))
        
        db.commit()
        flash('Profile saved successfully!')
        return redirect(url_for('dashboard'))
    
    db = get_db()
    profile = db.execute('SELECT * FROM investor_profiles WHERE user_id = ?', (user_id,)).fetchone()
    return render_template('profile_investor.html', profile=profile)


@app.route('/search/startups')
def search_startups():
    """
    Search startups - Protected route.
    """
    # Check authentication
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    industry = request.args.get('industry', '')
    stage = request.args.get('stage', '')
    location = request.args.get('location', '')
    
    db = get_db()
    query = 'SELECT * FROM startup_profiles WHERE 1=1'
    params = []
    
    if industry:
        query += ' AND industry = ?'
        params.append(industry)
    if stage:
        query += ' AND stage = ?'
        params.append(stage)
    if location:
        query += ' AND location LIKE ?'
        params.append(f'%{location}%')
    
    startups = db.execute(query, params).fetchall()
    return render_template('startups_list.html', startups=startups)


@app.route('/search/investors')
def search_investors():
    """
    Search investors - Protected route.
    """
    # Check authentication
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    industry = request.args.get('industry', '')
    stage = request.args.get('stage', '')
    location = request.args.get('location', '')
    
    db = get_db()
    query = 'SELECT * FROM investor_profiles WHERE 1=1'
    params = []
    
    if industry:
        query += ' AND industry_focus = ?'
        params.append(industry)
    if stage:
        query += ' AND stage_focus = ?'
        params.append(stage)
    if location:
        query += ' AND location LIKE ?'
        params.append(f'%{location}%')
    
    investors = db.execute(query, params).fetchall()
    return render_template('investors_list.html', investors=investors)


# ============================================================
# REMAINING ROUTES
# ============================================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        
        db = get_db()
        try:
            password_hash = generate_password_hash(password)
            cursor = db.execute(
                'INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)',
                (email, password_hash, role)
            )
            db.commit()
            session['user_id'] = cursor.lastrowid
            session['role'] = role
            session['email'] = email
            
            # Redirect to profile creation
            if role == 'startup':
                return redirect(url_for('create_startup_profile'))
            else:
                return redirect(url_for('create_investor_profile'))
        except sqlite3.IntegrityError:
            flash('Email already registered')
            return redirect(url_for('register'))
    
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['email'] = user['email']
            
            # Check if profile exists
            if user['role'] == 'startup':
                profile = db.execute('SELECT id FROM startup_profiles WHERE user_id = ?', (user['id'],)).fetchone()
                if not profile:
                    return redirect(url_for('create_startup_profile'))
            else:
                profile = db.execute('SELECT id FROM investor_profiles WHERE user_id = ?', (user['id'],)).fetchone()
                if not profile:
                    return redirect(url_for('create_investor_profile'))
            
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password')
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/connect/<user_id>', methods=['POST'])
def connect(user_id):
    """Connect with another user - Protected route."""
    # Check authentication
    user_id_session = session.get('user_id')
    if not user_id_session:
        return redirect(url_for('login'))
    
    message = request.form.get('message', '')
    db = get_db()
    
    # Check if connection already exists
    existing = db.execute('''
        SELECT id FROM connections 
        WHERE from_user_id = ? AND to_user_id = ?
    ''', (user_id_session, user_id)).fetchone()
    
    if not existing:
        db.execute('''
            INSERT INTO connections (from_user_id, to_user_id, message)
            VALUES (?, ?, ?)
        ''', (user_id_session, user_id, message))
        db.commit()
        flash('Connection request sent!')
    else:
        flash('Connection already exists')
    
    return redirect(request.referrer or url_for('dashboard'))


@app.route('/accept_connection/<connection_id>')
def accept_connection(connection_id):
    """Accept a connection request - Protected route."""
    # Check authentication
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    db = get_db()
    db.execute('UPDATE connections SET status = ? WHERE id = ? AND to_user_id = ?',
               ('accepted', connection_id, user_id))
    db.commit()
    flash('Connection accepted!')
    return redirect(url_for('dashboard'))


@app.route('/decline_connection/<connection_id>')
def decline_connection(connection_id):
    """Decline a connection request - Protected route."""
    # Check authentication
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    db = get_db()
    db.execute('DELETE FROM connections WHERE id = ? AND to_user_id = ?',
               (connection_id, user_id))
    db.commit()
    flash('Connection declined')
    return redirect(url_for('dashboard'))


if __name__ == '__main__':
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    app.run(host=host, port=port, debug=True)
