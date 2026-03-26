import os
import sqlite3
import re
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta

# =====================================================
# FLASK APP CONFIGURATION
# =====================================================

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Database path - absolute
DB_NAME = os.path.join(os.path.dirname(__file__), 'startup_vc.db')

# =====================================================
# BEFORE REQUEST - Inject user into all templates
# =====================================================

@app.before_request
def inject_user_for_all_routes():
    """Inject user variable consistently into all templates"""
    g.user = get_current_user()

# =====================================================
# DATABASE HELPER FUNCTIONS
# =====================================================

def get_db():
    """Get database connection with row factory"""
    conn = sqlite3.connect(DB_NAME, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            user_type TEXT NOT NULL CHECK(user_type IN ('startup', 'vc')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Startups table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS startups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            company_name TEXT NOT NULL,
            tagline TEXT,
            industry TEXT,
            stage TEXT,
            funding_amount_seeking REAL,
            description TEXT,
            website_url TEXT,
            location TEXT,
            team_size INTEGER DEFAULT 1,
            is_looking_for_investment BOOLEAN DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Investors table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS investors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            firm_name TEXT NOT NULL,
            fund_size REAL,
            preferred_stages TEXT,
            preferred_industries TEXT,
            min_investment REAL,
            max_investment REAL,
            portfolio_companies TEXT,
            investment_thesis TEXT,
            location TEXT,
            is_actively_investing BOOLEAN DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Matches table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            startup_id INTEGER NOT NULL,
            investor_id INTEGER NOT NULL,
            match_score REAL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (startup_id) REFERENCES startups(id),
            FOREIGN KEY (investor_id) REFERENCES investors(id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

# =====================================================
# AUTH DECORATORS - ROBUST VERSION
# =====================================================

def login_required(f):
    """Decorator to require authentication for a route"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Force session to load from cookie BEFORE checking
        _ = session.get('user_id')
        
        user_id = session.get('user_id')
        user_type = session.get('user_type')
        
        if not user_id or not user_type:
            next_url = request.url
            return redirect(url_for('login', next=next_url))
        
        # Verify user still exists in database
        user = get_current_user()
        if not user:
            session.clear()
            return redirect(url_for('login', next=request.url))
        
        return f(*args, **kwargs)
    return decorated_function

def api_login_required(f):
    """Decorator for API routes - returns JSON 401 for unauthenticated requests"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required', 'code': 'UNAUTHORIZED'}), 401
        return f(*args, **kwargs)
    return decorated_function

# =====================================================
# HELPER FUNCTIONS
# =====================================================

def get_current_user():
    """Get current authenticated user from session"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id, email, user_type, created_at FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            user_dict = dict(user)
            user_dict['_session_user_type'] = session.get('user_type')
            return user_dict
        return None
    except Exception as e:
        print(f"Error getting current user: {e}")
        return None

def calculate_profile_completeness(profile, user_type):
    """Calculate profile completeness percentage"""
    if user_type == 'startup':
        fields = ['company_name', 'industry', 'stage', 'funding_amount_seeking', 'description', 'website_url', 'location']
    else:
        fields = ['firm_name', 'fund_size', 'preferred_stages', 'preferred_industries', 'investment_thesis', 'location']
    
    filled = 0
    for field in fields:
        value = profile.get(field)
        if value and str(value).strip():
            filled += 1
    
    return int((filled / len(fields)) * 100)

def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def calculate_match_score(startup, investor):
    """Calculate compatibility score between startup and investor"""
    score = 0
    
    # Industry match (40 points max)
    if investor.get('preferred_industries') and startup.get('industry'):
        if startup['industry'] in investor['preferred_industries'].split(','):
            score += 40
        elif not investor['preferred_industries']:
            score += 20
    
    # Funding range match (40 points max)
    if startup.get('funding_amount_seeking') and investor.get('min_investment') and investor.get('max_investment'):
        if investor['min_investment'] <= startup['funding_amount_seeking'] <= investor['max_investment']:
            score += 40
    
    # Stage compatibility (20 points max)
    if investor.get('preferred_stages') and startup.get('stage'):
        if startup['stage'] in investor['preferred_stages'].split(','):
            score += 20
    
    return min(score, 100)

# =====================================================
# ROUTES
# =====================================================

@app.route('/')
def index():
    """Home/Landing page"""
    user = get_current_user()
    return render_template('index.html', user=user, page_title='Home')

# ----------------------------------------------------
# AUTH ROUTES
# ----------------------------------------------------

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registration page - renders register.html"""
    # Force session to load from cookie BEFORE checking
    _ = session.get('user_id')
    
    # Redirect authenticated users to their dashboard
    if session.get('user_id'):
        if session.get('user_type') == 'startup':
            return redirect(url_for('startup_dashboard'))
        else:
            return redirect(url_for('investor_dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '')
        password = request.form.get('password', '')
        user_type = request.form.get('user_type', 'startup')
        company_name = request.form.get('company_name', '').strip()
        firm_name = request.form.get('firm_name', '').strip()
        
        # Server-side validation
        errors = []
        
        if not email or not validate_email(email):
            errors.append('Please enter a valid email address.')
        
        if not password or len(password) < 8:
            errors.append('Password must be at least 8 characters long.')
        
        if user_type == 'startup':
            if not company_name:
                errors.append('Company name is required.')
            elif not company_name.strip():
                errors.append('Company name cannot be only whitespace.')
        else:
            if not firm_name:
                errors.append('Firm name is required.')
            elif not firm_name.strip():
                errors.append('Firm name cannot be only whitespace.')
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html', user=None, page_title='Register')
        
        password_hash = generate_password_hash(password)
        
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO users (email, password_hash, user_type) VALUES (?, ?, ?)',
                (email, password_hash, user_type)
            )
            user_id = cursor.lastrowid
            
            if user_type == 'startup':
                cursor.execute(
                    'INSERT INTO startups (user_id, company_name) VALUES (?, ?)',
                    (user_id, company_name)
                )
            else:
                cursor.execute(
                    'INSERT INTO investors (user_id, firm_name) VALUES (?, ?)',
                    (user_id, firm_name)
                )
            
            conn.commit()
            conn.close()
            
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already registered.', 'error')
        except Exception:
            flash('An error occurred during registration. Please try again.', 'error')
    
    # GET request - render the registration form
    session.modified = True
    return render_template('register.html', user=None, page_title='Register')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page - renders login.html"""
    # Force session to load from cookie BEFORE checking
    _ = session.get('user_id')
    
    # Redirect authenticated users to their dashboard
    if session.get('user_id'):
        user = get_current_user()
        if user and user.get('user_type') == 'startup':
            return redirect(url_for('startup_dashboard'))
        elif user and user.get('user_type') == 'vc':
            return redirect(url_for('investor_dashboard'))
        else:
            session.clear()
    
    next_url = request.args.get('next', '')
    
    if request.method == 'POST':
        email = request.form.get('email', '')
        password = request.form.get('password', '')
        
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
            user = cursor.fetchone()
            conn.close()
            
            if user and check_password_hash(user['password_hash'], password):
                session.clear()
                session['user_id'] = user['id']
                session['user_type'] = user['user_type']
                session.permanent = True
                
                flash('Login successful!', 'success')
                
                if next_url and next_url.startswith('/'):
                    return redirect(next_url)
                if user['user_type'] == 'startup':
                    return redirect(url_for('startup_dashboard'))
                else:
                    return redirect(url_for('investor_dashboard'))
            else:
                flash('Invalid email or password.', 'error')
        except Exception:
            flash('An error occurred. Please try again.', 'error')
    
    # GET request - render the login form
    session.modified = True
    return render_template('login.html', user=None, next_url=next_url, page_title='Login')

@app.route('/logout')
def logout():
    """Logout - clears session and redirects to home"""
    session.clear()
    return redirect(url_for('index'))

# ----------------------------------------------------
# DASHBOARD ROUTES (REQUIRE AUTH)
# ----------------------------------------------------

@app.route('/startup/dashboard', methods=['GET', 'POST'])
@login_required
def startup_dashboard():
    """Startup dashboard - renders startup_dashboard.html"""
    if session.get('user_type') != 'startup':
        return redirect(url_for('index'))
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM startups WHERE user_id = ?', (session['user_id'],))
        startup = cursor.fetchone()
        
        if request.method == 'POST':
            company_name = request.form.get('company_name', '')
            tagline = request.form.get('tagline', '')
            industry = request.form.get('industry', '')
            stage = request.form.get('stage', '')
            
            funding_amount_str = request.form.get('funding_amount_seeking', '0') or '0'
            try:
                funding_amount_seeking = float(funding_amount_str)
                if funding_amount_seeking < 0:
                    flash('Funding amount must be a positive number.', 'error')
                    conn.close()
                    user = get_current_user()
                    return render_template('startup_dashboard.html', user=user, startup=startup, matches=[], profile_completeness=0, page_title='Startup Dashboard')
            except ValueError:
                flash('Funding amount must be a valid number.', 'error')
                conn.close()
                user = get_current_user()
                return render_template('startup_dashboard.html', user=user, startup=startup, matches=[], profile_completeness=0, page_title='Startup Dashboard')
            
            description = request.form.get('description', '')
            website_url = request.form.get('website_url', '')
            location = request.form.get('location', '')
            
            team_size_str = request.form.get('team_size', '1') or '1'
            try:
                team_size = int(team_size_str)
                if team_size < 1:
                    flash('Team size must be at least 1.', 'error')
                    conn.close()
                    user = get_current_user()
                    return render_template('startup_dashboard.html', user=user, startup=startup, matches=[], profile_completeness=0, page_title='Startup Dashboard')
            except ValueError:
                flash('Team size must be a valid number.', 'error')
                conn.close()
                user = get_current_user()
                return render_template('startup_dashboard.html', user=user, startup=startup, matches=[], profile_completeness=0, page_title='Startup Dashboard')
            
            is_looking_for_investment = 'is_looking_for_investment' in request.form
            
            if startup:
                cursor.execute('''
                    UPDATE startups SET 
                        company_name=?, tagline=?, industry=?, stage=?,
                        funding_amount_seeking=?, description=?, website_url=?,
                        location=?, team_size=?, is_looking_for_investment=?
                    WHERE user_id=?
                ''', (company_name, tagline, industry, stage, funding_amount_seeking,
                      description, website_url, location, team_size, 
                      is_looking_for_investment, session['user_id']))
            else:
                cursor.execute('''
                    INSERT INTO startups (user_id, company_name, tagline, industry, stage,
                        funding_amount_seeking, description, website_url, location,
                        team_size, is_looking_for_investment)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (session['user_id'], company_name, tagline, industry, stage,
                      funding_amount_seeking, description, website_url, location,
                      team_size, is_looking_for_investment))
            
            conn.commit()
            flash('Profile updated successfully!', 'success')
            
            cursor.execute('SELECT * FROM startups WHERE user_id = ?', (session['user_id'],))
            startup = cursor.fetchone()
        
        cursor.execute('''
            SELECT m.*, i.firm_name, i.investment_thesis, i.location as investor_location
            FROM matches m
            JOIN investors i ON m.investor_id = i.id
            WHERE m.startup_id = ?
            ORDER BY m.created_at DESC
        ''', (startup['id'] if startup else None,))
        matches = cursor.fetchall()
        
        profile_completeness = calculate_profile_completeness(dict(startup) if startup else {}, 'startup') if startup else 0
        
        conn.close()
        user = get_current_user()
        return render_template('startup_dashboard.html', user=user, startup=startup, matches=matches, profile_completeness=profile_completeness, page_title='Startup Dashboard')
    except Exception:
        flash('An error occurred. Please try again.', 'error')
        user = get_current_user()
        return render_template('startup_dashboard.html', user=user, startup=None, matches=[], profile_completeness=0, page_title='Startup Dashboard')

@app.route('/investor/dashboard', methods=['GET', 'POST'])
@login_required
def investor_dashboard():
    """Investor dashboard - renders investor_dashboard.html"""
    if session.get('user_type') != 'vc':
        return redirect(url_for('index'))
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM investors WHERE user_id = ?', (session['user_id'],))
        investor = cursor.fetchone()
        
        if request.method == 'POST':
            firm_name = request.form.get('firm_name', '')
            
            fund_size_str = request.form.get('fund_size', '0') or '0'
            try:
                fund_size = float(fund_size_str)
                if fund_size < 0:
                    flash('Fund size must be a positive number.', 'error')
                    conn.close()
                    user = get_current_user()
                    return render_template('investor_dashboard.html', user=user, investor=investor, matches=[], profile_completeness=0, page_title='Investor Dashboard')
            except ValueError:
                flash('Fund size must be a valid number.', 'error')
                conn.close()
                user = get_current_user()
                return render_template('investor_dashboard.html', user=user, investor=investor, matches=[], profile_completeness=0, page_title='Investor Dashboard')
            
            preferred_stages = request.form.get('preferred_stages', '')
            preferred_industries = request.form.get('preferred_industries', '')
            
            min_investment_str = request.form.get('min_investment', '0') or '0'
            max_investment_str = request.form.get('max_investment', '0') or '0'
            try:
                min_investment = float(min_investment_str)
                max_investment = float(max_investment_str)
                if min_investment < 0:
                    flash('Minimum investment must be a positive number.', 'error')
                    conn.close()
                    user = get_current_user()
                    return render_template('investor_dashboard.html', user=user, investor=investor, matches=[], profile_completeness=0, page_title='Investor Dashboard')
                if max_investment < 0:
                    flash('Maximum investment must be a positive number.', 'error')
                    conn.close()
                    user = get_current_user()
                    return render_template('investor_dashboard.html', user=user, investor=investor, matches=[], profile_completeness=0, page_title='Investor Dashboard')
                if min_investment > max_investment:
                    flash('Minimum investment cannot be greater than maximum investment.', 'error')
                    conn.close()
                    user = get_current_user()
                    return render_template('investor_dashboard.html', user=user, investor=investor, matches=[], profile_completeness=0, page_title='Investor Dashboard')
            except ValueError:
                flash('Investment amounts must be valid numbers.', 'error')
                conn.close()
                user = get_current_user()
                return render_template('investor_dashboard.html', user=user, investor=investor, matches=[], profile_completeness=0, page_title='Investor Dashboard')
            
            portfolio_companies = request.form.get('portfolio_companies', '')
            investment_thesis = request.form.get('investment_thesis', '')
            location = request.form.get('location', '')
            is_actively_investing = 'is_actively_investing' in request.form
            
            if investor:
                cursor.execute('''
                    UPDATE investors SET 
                        firm_name=?, fund_size=?, preferred_stages=?, preferred_industries=?,
                        min_investment=?, max_investment=?, portfolio_companies=?,
                        investment_thesis=?, location=?, is_actively_investing=?
                    WHERE user_id=?
                ''', (firm_name, fund_size, preferred_stages, preferred_industries,
                      min_investment, max_investment, portfolio_companies,
                      investment_thesis, location, is_actively_investing, session['user_id']))
            else:
                cursor.execute('''
                    INSERT INTO investors (user_id, firm_name, fund_size, preferred_stages,
                        preferred_industries, min_investment, max_investment,
                        portfolio_companies, investment_thesis, location, is_actively_investing)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (session['user_id'], firm_name, fund_size, preferred_stages,
                      preferred_industries, min_investment, max_investment,
                      portfolio_companies, investment_thesis, location, is_actively_investing))
            
            conn.commit()
            flash('Profile updated successfully!', 'success')
            
            cursor.execute('SELECT * FROM investors WHERE user_id = ?', (session['user_id'],))
            investor = cursor.fetchone()
        
        cursor.execute('''
            SELECT m.*, s.company_name, s.industry, s.stage, s.description
            FROM matches m
            JOIN startups s ON m.startup_id = s.id
            WHERE m.investor_id = ?
            ORDER BY m.created_at DESC
        ''', (investor['id'] if investor else None,))
        matches = cursor.fetchall()
        
        profile_completeness = calculate_profile_completeness(dict(investor) if investor else {}, 'investor') if investor else 0
        
        conn.close()
        user = get_current_user()
        return render_template('investor_dashboard.html', user=user, investor=investor, matches=matches, profile_completeness=profile_completeness, page_title='Investor Dashboard')
    except Exception:
        flash('An error occurred. Please try again.', 'error')
        user = get_current_user()
        return render_template('investor_dashboard.html', user=user, investor=None, matches=[], profile_completeness=0, page_title='Investor Dashboard')

# ----------------------------------------------------
# DISCOVERY ROUTES
# ----------------------------------------------------

@app.route('/discover/startups')
@login_required
def discover_startups():
    """Discover startups page - for investors"""
    if session.get('user_type') != 'vc':
        return redirect(url_for('index'))
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM investors WHERE user_id = ?', (session['user_id'],))
        investor = cursor.fetchone()
        
        search_query = request.args.get('search', '').lower()
        industry_filter = request.args.get('industry', '')
        
        page = request.args.get('page', 1, type=int)
        per_page = 10
        offset = (page - 1) * per_page
        
        cursor.execute('SELECT * FROM startups WHERE is_looking_for_investment = 1')
        all_startups = cursor.fetchall()
        
        startups_with_scores = []
        for startup in all_startups:
            if investor:
                score = calculate_match_score(startup, investor)
            else:
                score = 0
            startups_with_scores.append({
                'startup': dict(startup),
                'match_score': score
            })
        
        startups_with_scores.sort(key=lambda x: x['match_score'], reverse=True)
        
        filtered_startups = []
        for item in startups_with_scores:
            startup = item['startup']
            matches_search = True
            matches_industry = True
            
            if search_query:
                matches_search = search_query in startup.get('company_name', '').lower()
            if industry_filter:
                matches_industry = startup.get('industry') == industry_filter
            
            if matches_search and matches_industry:
                filtered_startups.append({
                    'startup': startup,
                    'match_score': item['match_score']
                })
        
        total_startups = len(filtered_startups)
        total_pages = (total_startups + per_page - 1) // per_page if total_startups > 0 else 1
        paginated_startups = filtered_startups[offset:offset + per_page]
        
        conn.close()
        user = get_current_user()
        return render_template('discover_startups.html', user=user, startups=paginated_startups, investor=investor, 
                               current_page=page, total_pages=total_pages, total_items=total_startups, page_title='Discover Startups')
    except Exception:
        flash('An error occurred. Please try again.', 'error')
        user = get_current_user()
        return render_template('discover_startups.html', user=user, startups=[], investor=None,
                               current_page=1, total_pages=1, total_items=0, page_title='Discover Startups')

@app.route('/discover/investors')
@login_required
def discover_investors():
    """Discover investors page - for startups"""
    if session.get('user_type') != 'startup':
        return redirect(url_for('index'))
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM startups WHERE user_id = ?', (session['user_id'],))
        startup = cursor.fetchone()
        
        search_query = request.args.get('search', '').lower()
        fund_size_filter = request.args.get('fund_size', '')
        
        page = request.args.get('page', 1, type=int)
        per_page = 10
        offset = (page - 1) * per_page
        
        cursor.execute('SELECT * FROM investors WHERE is_actively_investing = 1')
        all_investors = cursor.fetchall()
        
        investors_with_scores = []
        for investor in all_investors:
            if startup:
                score = calculate_match_score(startup, investor)
            else:
                score = 0
            investors_with_scores.append({
                'investor': dict(investor),
                'match_score': score
            })
        
        investors_with_scores.sort(key=lambda x: x['match_score'], reverse=True)
        
        filtered_investors = []
        for item in investors_with_scores:
            investor = item['investor']
            matches_search = True
            matches_fund = True
            
            if search_query:
                matches_search = search_query in investor.get('firm_name', '').lower()
            if fund_size_filter:
                fund_size = investor.get('fund_size', 0) or 0
                if fund_size_filter == 'small':
                    matches_fund = fund_size < 10000000
                elif fund_size_filter == 'medium':
                    matches_fund = 10000000 <= fund_size < 100000000
                elif fund_size_filter == 'large':
                    matches_fund = fund_size >= 100000000
            
            if matches_search and matches_fund:
                filtered_investors.append({
                    'investor': investor,
                    'match_score': item['match_score']
                })
        
        total_investors = len(filtered_investors)
        total_pages = (total_investors + per_page - 1) // per_page if total_investors > 0 else 1
        paginated_investors = filtered_investors[offset:offset + per_page]
        
        conn.close()
        user = get_current_user()
        return render_template('discover_investors.html', user=user, investors=paginated_investors, startup=startup,
                               current_page=page, total_pages=total_pages, total_items=total_investors, page_title='Discover Investors')
    except Exception:
        flash('An error occurred. Please try again.', 'error')
        user = get_current_user()
        return render_template('discover_investors.html', user=user, investors=[], startup=None,
                               current_page=1, total_pages=1, total_items=0, page_title='Discover Investors')

# ----------------------------------------------------
# API ROUTES
# ----------------------------------------------------

@app.route('/api/match/<type>')
@api_login_required
def api_match(type):
    """Generate match suggestions based on compatibility"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        if type == 'startups' and session.get('user_type') == 'vc':
            cursor.execute('SELECT * FROM investors WHERE user_id = ?', (session['user_id'],))
            investor = cursor.fetchone()
            
            if not investor:
                conn.close()
                return jsonify([])
            
            preferred_industries = investor['preferred_industries'].split(',') if investor['preferred_industries'] else []
            
            cursor.execute('SELECT * FROM startups WHERE is_looking_for_investment = 1')
            all_startups = cursor.fetchall()
            
            matches = []
            for startup in all_startups:
                score = 0
                
                if startup['industry'] in preferred_industries or not preferred_industries:
                    score += 30
                
                if investor['min_investment'] <= startup['funding_amount_seeking'] <= investor['max_investment']:
                    score += 40
                
                if investor['preferred_stages'] and startup['stage'] in investor['preferred_stages'].split(','):
                    score += 30
                
                if score > 0:
                    matches.append({
                        'startup': dict(startup),
                        'score': score
                    })
            
            matches.sort(key=lambda x: x['score'], reverse=True)
            conn.close()
            return jsonify(matches[:10])
        
        elif type == 'investors' and session.get('user_type') == 'startup':
            cursor.execute('SELECT * FROM startups WHERE user_id = ?', (session['user_id'],))
            startup = cursor.fetchone()
            
            if not startup:
                conn.close()
                return jsonify([])
            
            cursor.execute('SELECT * FROM investors WHERE is_actively_investing = 1')
            all_investors = cursor.fetchall()
            
            matches = []
            for investor in all_investors:
                score = 0
                
                if investor['preferred_industries'] and startup['industry'] in investor['preferred_industries'].split(','):
                    score += 40
                elif not investor['preferred_industries']:
                    score += 20
                
                if investor['min_investment'] <= startup['funding_amount_seeking'] <= investor['max_investment']:
                    score += 40
                
                if investor['preferred_stages'] and startup['stage'] in investor['preferred_stages'].split(','):
                    score += 20
                
                if score > 0:
                    matches.append({
                        'investor': dict(investor),
                        'score': score
                    })
            
            matches.sort(key=lambda x: x['score'], reverse=True)
            conn.close()
            return jsonify(matches[:10])
        
        conn.close()
        return jsonify([])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/match/request', methods=['POST'])
@api_login_required
def match_request():
    """Send a match request"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON data'}), 400
    
    target_id = data.get('target_id')
    target_type = data.get('target_type')
    
    if not target_id:
        return jsonify({'success': False, 'message': 'Missing target_id'}), 400
    if not target_type:
        return jsonify({'success': False, 'message': 'Missing target_type'}), 400
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        if session.get('user_type') == 'startup':
            cursor.execute('SELECT * FROM startups WHERE user_id = ?', (session['user_id'],))
            startup = cursor.fetchone()
            
            if not startup:
                conn.close()
                return jsonify({'success': False, 'message': 'Startup profile not found'}), 404
            
            if target_type == 'investor':
                cursor.execute('SELECT * FROM investors WHERE id = ?', (target_id,))
                investor = cursor.fetchone()
                
                if not investor:
                    conn.close()
                    return jsonify({'success': False, 'message': 'Investor not found'}), 404
                
                score = calculate_match_score(startup, investor)
                
                cursor.execute('''
                    SELECT * FROM matches 
                    WHERE (startup_id = ? AND investor_id = ?)
                       OR (startup_id = ? AND investor_id = ?)
                ''', (startup['id'], investor['id'], investor['id'], startup['id']))
                existing = cursor.fetchone()
                
                if not existing:
                    cursor.execute('''
                        INSERT INTO matches (startup_id, investor_id, match_score, status)
                        VALUES (?, ?, ?, 'pending')
                    ''', (startup['id'], investor['id'], score))
                    conn.commit()
                    conn.close()
                    return jsonify({'success': True, 'message': 'Match request sent!'})
                else:
                    conn.close()
                    return jsonify({'success': False, 'message': 'A match request already exists between these parties!'})
            else:
                conn.close()
                return jsonify({'success': False, 'message': 'Invalid target_type for startup'}), 400
        else:
            cursor.execute('SELECT * FROM investors WHERE user_id = ?', (session['user_id'],))
            investor = cursor.fetchone()
            
            if not investor:
                conn.close()
                return jsonify({'success': False, 'message': 'Investor profile not found'}), 404
            
            if target_type == 'startup':
                cursor.execute('SELECT * FROM startups WHERE id = ?', (target_id,))
                startup = cursor.fetchone()
                
                if not startup:
                    conn.close()
                    return jsonify({'success': False, 'message': 'Startup not found'}), 404
                
                score = calculate_match_score(startup, investor)
                
                cursor.execute('''
                    SELECT * FROM matches 
                    WHERE (startup_id = ? AND investor_id = ?)
                       OR (startup_id = ? AND investor_id = ?)
                ''', (startup['id'], investor['id'], investor['id'], startup['id']))
                existing = cursor.fetchone()
                
                if not existing:
                    cursor.execute('''
                        INSERT INTO matches (startup_id, investor_id, match_score, status)
                        VALUES (?, ?, ?, 'pending')
                    ''', (startup['id'], investor['id'], score))
                    conn.commit()
                    conn.close()
                    return jsonify({'success': True, 'message': 'Match request sent!'})
                else:
                    conn.close()
                    return jsonify({'success': False, 'message': 'A match request already exists between these parties!'})
            else:
                conn.close()
                return jsonify({'success': False, 'message': 'Invalid target_type for investor'}), 400
        
        conn.close()
        return jsonify({'success': False, 'message': 'Could not create match request'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500

@app.route('/api/match/respond', methods=['POST'])
@api_login_required
def match_respond():
    """Respond to a match request (accept/reject)"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON data'}), 400
    
    match_id = data.get('match_id')
    action = data.get('action')
    
    if not match_id:
        return jsonify({'success': False, 'message': 'Missing match_id'}), 400
    if not action:
        return jsonify({'success': False, 'message': 'Missing action'}), 400
    if action not in ('accept', 'reject'):
        return jsonify({'success': False, 'message': 'Invalid action. Must be accept or reject'}), 400
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        if session.get('user_type') == 'startup':
            cursor.execute('SELECT id FROM startups WHERE user_id = ?', (session['user_id'],))
            startup = cursor.fetchone()
            if not startup:
                conn.close()
                return jsonify({'success': False, 'message': 'Startup profile not found'}), 404
            
            cursor.execute('SELECT * FROM matches WHERE id = ? AND startup_id = ?', (match_id, startup['id']))
            match = cursor.fetchone()
            if not match:
                conn.close()
                return jsonify({'success': False, 'message': 'Match not found or not authorized'}), 404
        else:
            cursor.execute('SELECT id FROM investors WHERE user_id = ?', (session['user_id'],))
            investor = cursor.fetchone()
            if not investor:
                conn.close()
                return jsonify({'success': False, 'message': 'Investor profile not found'}), 404
            
            cursor.execute('SELECT * FROM matches WHERE id = ? AND investor_id = ?', (match_id, investor['id']))
            match = cursor.fetchone()
            if not match:
                conn.close()
                return jsonify({'success': False, 'message': 'Match not found or not authorized'}), 404
        
        status = 'accepted' if action == 'accept' else 'rejected'
        cursor.execute('UPDATE matches SET status = ? WHERE id = ?', (status, match_id))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Match {status}!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'An error occurred: {str(e)}'}), 500
# =====================================================
# MAIN
# =====================================================

if __name__ == '__main__':
    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    app.run(host=host, port=port, debug=False)
