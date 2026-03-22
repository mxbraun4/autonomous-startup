import os
import sqlite3
from datetime import timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Force Jinja2 to reload templates on every request
app.jinja_env.cache = {}

# Session configuration for proper cookie handling
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_NAME'] = 'startup_vc_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # Allow for localhost/127.0.0.1
app.config['SESSION_COOKIE_SECURE'] = False  # For local dev

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
    """Initialize database with schema and seed data"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            user_type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Startups table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS startups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            industry TEXT NOT NULL,
            funding_stage TEXT NOT NULL,
            funding_amount INTEGER,
            website TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Investors table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS investors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            firm_name TEXT,
            description TEXT,
            preferred_industries TEXT,
            preferred_stages TEXT,
            min_investment INTEGER,
            max_investment INTEGER,
            website TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Matches table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            startup_id INTEGER NOT NULL,
            investor_id INTEGER NOT NULL,
            score INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (startup_id) REFERENCES startups (id),
            FOREIGN KEY (investor_id) REFERENCES investors (id)
        )
    ''')
    
    conn.commit()
    
    # Add seed test data if tables are empty
    cursor.execute('SELECT COUNT(*) FROM users')
    if cursor.fetchone()[0] == 0:
        # Add test startup user
        cursor.execute(
            'INSERT INTO users (username, email, password, user_type) VALUES (?, ?, ?, ?)',
            ('test_startup', 'startup@test.com', 'password123', 'startup')
        )
        startup_user_id = cursor.lastrowid
        
        cursor.execute(
            'INSERT INTO startups (user_id, name, industry, funding_stage, description, funding_amount) VALUES (?, ?, ?, ?, ?, ?)',
            (startup_user_id, 'QATest Innovations', 'Technology', 'Seed', 'A revolutionary tech startup', 500000)
        )
        
        # Add test investor user
        cursor.execute(
            'INSERT INTO users (username, email, password, user_type) VALUES (?, ?, ?, ?)',
            ('test_investor', 'investor@test.com', 'password123', 'investor')
        )
        investor_user_id = cursor.lastrowid
        
        cursor.execute(
            'INSERT INTO investors (user_id, name, firm_name, description, preferred_industries, preferred_stages, min_investment, max_investment) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (investor_user_id, 'John Smith', 'Smith Ventures', 'Seed stage investor', 'Technology,SaaS', 'Seed,Series A', 100000, 1000000)
        )
        
        conn.commit()
    
    conn.close()

def is_session_valid():
    """Validate session has all required fields"""
    return (
        session.get('user_id') is not None and
        session.get('username') is not None and
        session.get('user_type') in ('startup', 'investor')
    )

def login_required(f):
    """Enhanced login_required decorator with proper session handling"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            session.clear()
            flash('Session expired. Please log in again.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Helper function to calculate match score
def calculate_match_score(startup, investor):
    """Calculate compatibility score between startup and investor"""
    score = 0
    
    # Industry match
    startup_industry = startup['industry'].lower()
    investor_industries = investor['preferred_industries'].lower() if investor['preferred_industries'] else ''
    
    if startup_industry in investor_industries or investor_industries in startup_industry:
        score += 50
    
    # Funding stage match
    startup_stage = startup['funding_stage'].lower()
    investor_stages = investor['preferred_stages'].lower() if investor['preferred_stages'] else ''
    
    if startup_stage in investor_stages or investor_stages in startup_stage:
        score += 30
    
    # Funding amount match
    if startup['funding_amount'] and investor['min_investment'] and investor['max_investment']:
        if investor['min_investment'] <= startup['funding_amount'] <= investor['max_investment']:
            score += 20
    
    return min(score, 100)

def generate_matches():
    """Generate matches between startups and investors"""
    db = get_db()
    
    startups = db.execute('SELECT * FROM startups').fetchall()
    investors = db.execute('SELECT * FROM investors').fetchall()
    
    for startup in startups:
        for investor in investors:
            score = calculate_match_score(startup, investor)
            if score > 0:
                # Check if match already exists
                existing = db.execute(
                    'SELECT id FROM matches WHERE startup_id = ? AND investor_id = ?',
                    (startup['id'], investor['id'])
                ).fetchone()
                
                if not existing:
                    db.execute(
                        'INSERT INTO matches (startup_id, investor_id, score) VALUES (?, ?, ?)',
                        (startup['id'], investor['id'], score)
                    )
    
    db.commit()

# ==================== ROUTES ====================

@app.route('/')
def index():
    return render_template('index.html')

# Authentication routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    """Register route - renders register.html for GET, processes registration for POST"""
    # Clear any stale session if visiting register while logged in
    if session.get('user_id'):
        session.clear()
    
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        user_type = request.form['user_type']
        
        db = get_db()
        try:
            cursor = db.execute(
                'INSERT INTO users (username, email, password, user_type) VALUES (?, ?, ?, ?)',
                (username, email, password, user_type)
            )
            db.commit()
            user_id = cursor.lastrowid
            
            if user_type == 'startup':
                db.execute(
                    'INSERT INTO startups (user_id, name, industry, funding_stage) VALUES (?, ?, ?, ?)',
                    (user_id, request.form.get('company_name', username), request.form.get('industry', 'Technology'), request.form.get('funding_stage', 'Seed'))
                )
            else:
                db.execute(
                    'INSERT INTO investors (user_id, name, firm_name) VALUES (?, ?, ?)',
                    (user_id, request.form.get('contact_name', username), request.form.get('firm_name', 'Unknown'))
                )
            db.commit()
            
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists.', 'error')
    
    # GET request - render the register.html template
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login route - renders login.html for GET, processes login for POST"""
    # If already logged in, redirect to appropriate dashboard
    if session.get('user_id'):
        if session.get('user_type') == 'startup':
            return redirect(url_for('startup_dashboard'))
        else:
            return redirect(url_for('investor_dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        db = get_db()
        user = db.execute(
            'SELECT * FROM users WHERE username = ? AND password = ?',
            (username, password)
        ).fetchone()
        
        if user:
            # Set session variables
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['user_type'] = user['user_type']
            
            # Mark session as permanent and modified for proper cookie handling
            session.permanent = True
            session.modified = True
            
            if user['user_type'] == 'startup':
                return redirect(url_for('startup_dashboard'))
            else:
                return redirect(url_for('investor_dashboard'))
        else:
            flash('Invalid username or password.', 'error')
    
    # GET request - render the login.html template
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    if '_flashes' in session:
        session.pop('_flashes', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

# Startup routes
@app.route('/startup/dashboard')
@login_required
def startup_dashboard():
    if session.get('user_type') != 'startup':
        return redirect(url_for('index'))
    
    db = get_db()
    startup = db.execute(
        'SELECT * FROM startups WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    matches = db.execute('''
        SELECT m.*, i.name as investor_name, i.firm_name, i.preferred_industries, i.min_investment, i.max_investment
        FROM matches m
        JOIN investors i ON m.investor_id = i.id
        WHERE m.startup_id = ?
        ORDER BY m.score DESC
    ''', (startup['id'],)).fetchall() if startup else []
    
    return render_template('startup_dashboard.html', startup=startup, matches=matches)

@app.route('/startup/profile', methods=['GET', 'POST'])
@login_required
def startup_profile():
    if session.get('user_type') != 'startup':
        return redirect(url_for('index'))
    
    db = get_db()
    startup = db.execute(
        'SELECT * FROM startups WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if request.method == 'POST':
        db.execute('''
            UPDATE startups 
            SET name = ?, description = ?, industry = ?, funding_stage = ?, funding_amount = ?, website = ?
            WHERE user_id = ?
        ''', (
            request.form['name'],
            request.form['description'],
            request.form['industry'],
            request.form['funding_stage'],
            request.form.get('funding_amount', 0),
            request.form['website'],
            session['user_id']
        ))
        db.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('startup_profile'))
    
    return render_template('startup_profile.html', startup=startup)

@app.route('/startup/investors')
@login_required
def startup_browse_investors():
    if session.get('user_type') != 'startup':
        return redirect(url_for('index'))
    
    db = get_db()
    investors = db.execute('SELECT * FROM investors').fetchall()
    return render_template('investor_list.html', investors=investors)

@app.route('/startup/matches')
@login_required
def startup_matches():
    if session.get('user_type') != 'startup':
        return redirect(url_for('index'))
    
    db = get_db()
    startup = db.execute(
        'SELECT * FROM startups WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if startup:
        matches = db.execute('''
            SELECT m.*, i.name as investor_name, i.firm_name, i.preferred_industries, 
                   i.preferred_stages, i.min_investment, i.max_investment
            FROM matches m
            JOIN investors i ON m.investor_id = i.id
            WHERE m.startup_id = ?
            ORDER BY m.score DESC
        ''', (startup['id'],)).fetchall()
    else:
        matches = []
    
    return render_template('matches.html', matches=matches, user_type='startup')

# Investor routes
@app.route('/investor/dashboard')
@login_required
def investor_dashboard():
    if session.get('user_type') != 'investor':
        return redirect(url_for('index'))
    
    db = get_db()
    investor = db.execute(
        'SELECT * FROM investors WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    matches = db.execute('''
        SELECT m.*, s.name as startup_name, s.industry, s.funding_stage, s.funding_amount
        FROM matches m
        JOIN startups s ON m.startup_id = s.id
        WHERE m.investor_id = ?
        ORDER BY m.score DESC
    ''', (investor['id'],)).fetchall() if investor else []
    
    return render_template('investor_dashboard.html', investor=investor, matches=matches)

@app.route('/investor/profile', methods=['GET', 'POST'])
@login_required
def investor_profile():
    if session.get('user_type') != 'investor':
        return redirect(url_for('index'))
    
    db = get_db()
    investor = db.execute(
        'SELECT * FROM investors WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if request.method == 'POST':
        db.execute('''
            UPDATE investors 
            SET name = ?, firm_name = ?, description = ?, preferred_industries = ?, 
                preferred_stages = ?, min_investment = ?, max_investment = ?, website = ?
            WHERE user_id = ?
        ''', (
            request.form['name'],
            request.form['firm_name'],
            request.form['description'],
            request.form['preferred_industries'],
            request.form['preferred_stages'],
            request.form.get('min_investment', 0),
            request.form.get('max_investment', 0),
            request.form['website'],
            session['user_id']
        ))
        db.commit()
        # Regenerate matches after profile update
        generate_matches()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('investor_profile'))
    
    return render_template('investor_profile.html', investor=investor)

@app.route('/investor/startups')
@login_required
def investor_browse_startups():
    if session.get('user_type') != 'investor':
        return redirect(url_for('index'))
    
    db = get_db()
    startups = db.execute('SELECT * FROM startups').fetchall()
    return render_template('startup_list.html', startups=startups)

@app.route('/investor/matches')
@login_required
def investor_matches():
    if session.get('user_type') != 'investor':
        return redirect(url_for('index'))
    
    db = get_db()
    investor = db.execute(
        'SELECT * FROM investors WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if investor:
        matches = db.execute('''
            SELECT m.*, s.name as startup_name, s.industry, s.funding_stage, 
                   s.funding_amount, s.description
            FROM matches m
            JOIN startups s ON m.startup_id = s.id
            WHERE m.investor_id = ?
            ORDER BY m.score DESC
        ''', (investor['id'],)).fetchall()
    else:
        matches = []
    
    return render_template('matches.html', matches=matches, user_type='investor')

@app.route('/generate-matches')
@login_required
def manual_generate_matches():
    generate_matches()
    flash('Matches generated successfully!', 'success')
    if session.get('user_type') == 'startup':
        return redirect(url_for('startup_matches'))
    return redirect(url_for('investor_matches'))

# Run the app
if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Get host and port from environment variables
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    
    app.run(host=host, port=port, debug=True)