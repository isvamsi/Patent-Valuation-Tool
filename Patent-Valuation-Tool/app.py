from flask import Flask, render_template, request, redirect, url_for, jsonify, current_app, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
import io
import numpy as np
import pandas as pd
import os
import json
from sqlalchemy import desc
from dotenv import load_dotenv # Import dotenv

# Load environment variables from .env file (for local testing)
load_dotenv() 

# --- APP SETUP ---
app = Flask(__name__)
# CRITICAL FIX: Use the environment variable for the database URI
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///site.db') 
# Fallback to sqlite is for very initial setup or local debugging without a .env file
app.config['SQLALCHEMY_TRACK_MODELS'] = False
# Configure secret key from environment (CRITICAL!)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_default_secret_key_change_me_in_prod') 

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# Define the Super Admin's unique identifier for security
SUPER_ADMIN_USERNAME = 'Grid.Thoma'

# --- HELPER FUNCTIONS & DECORATORS ---

# Custom decorator to ensure only admins can access a route
def admin_required(f):
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('dashboard')) 
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- DATABASE MODELS ---

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)
    is_super_admin = db.Column(db.Boolean, default=False)
    # Ensure cascade="all, delete-orphan" and passive_deletes=True 
    calculations = db.relationship(
        'Calculation', 
        backref='author', 
        lazy='dynamic', 
        order_by='Calculation.timestamp.asc()',
        cascade="all, delete-orphan", 
        passive_deletes=True
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f"User('{self.username}', '{self.email}', Admin: {self.is_admin}, Super: {self.is_super_admin})"

class Calculation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.now())
    # Store inputs and results as JSON strings
    input_params_json = db.Column(db.Text, nullable=False)
    output_summary_json = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f"Calculation('{self.timestamp}', UserID: {self.user_id})"

# --- INITIAL SETUP ---

def create_default_admin():
    with app.app_context():
        # NOTE: db.create_all() will create tables in the DATABASE_URL connection
        db.create_all()
        
        # Super Admin check (Grid.Thoma)
        if User.query.filter_by(username=SUPER_ADMIN_USERNAME).first() is None:
            admin_user = User(
                username=SUPER_ADMIN_USERNAME, 
                email='grid.thoma@unicam.it', 
                is_admin=True,
                is_super_admin=True
            )
            admin_user.set_password('gridthoma123')
            db.session.add(admin_user)
            db.session.commit()
            print(f"Super Admin '{SUPER_ADMIN_USERNAME}' created!")
        else:
            print("Super Admin already exists.")

# --- ORIGINAL CALCULATION HELPER FUNCTIONS (Assuming correct) ---

def binomial_parameters(sigma, r, delta, dt):
    u = np.exp(sigma * np.sqrt(dt))
    d = 1 / u
    p = (np.exp((r - delta) * dt) - d) / (u - d)
    return u, d, p

def calculate_lattices(V, K, T, sigma, delta, r, n, deltas_manual=None):
    dt = T / n
    sigma_effective = sigma
    u = np.exp(sigma_effective * np.sqrt(dt))
    d = 1 / u

    A = [[V * (u**(j-i)) * (d**i) for j in range(n+1)] for i in range(n+1)]
    N = [[max(A[i][j] - K, 0) for j in range(n+1)] for i in range(n+1)]

    C = [[0.0]*(n+1) for _ in range(n+1)]

    for i in range(n+1):
        C[i][n] = N[i][n]

    discount = np.exp(-r * dt)

    times = list(range(n + 1))
    
    if deltas_manual is not None and len(deltas_manual) == n:
        deltas = deltas_manual + [1.0]
    else:
        deltas = [0.0] * (n + 1)
        if n > 0 and delta > 0:
            g = (1.0 / delta)**(1/n) - 1
            deltas = [delta * ((1 + g)**t) for t in times]
            deltas[n] = 1.0 
        elif n == 0:
            deltas = [delta]
    
    ps_for_export = [(np.exp((r - deltas[t]) * dt) - d) / (u - d) if u != d else 0 for t in times]
    ps_for_induction = ps_for_export[:-1]

    for j in range(n - 1, -1, -1):
        p = ps_for_induction[j] 

        for i in range(j + 1):
            intrinsic_value = N[i][j]
            hold = discount * (p * C[i][j+1] + (1-p) * C[i+1][j+1])
            C[i][j] = max(hold, intrinsic_value)

    return A, N, C, times, deltas, ps_for_export

def calculate_sensitivity_data(base_params, n):
    V, K, T, sigma, delta, r = base_params['V_calc'], base_params['K_calc'], base_params['T'], \
                               base_params['sigma'], base_params['delta_val'], base_params['r']
    
    def get_C0(V, K, T, sigma, delta, r, n):
        new_n = max(1, int(T))
        return calculate_lattices(V, K, T, sigma, delta, r, new_n)[2][0][0] / 1000

    base_option_value = get_C0(V, K, T, sigma, delta, r, n)
    
    # 1. Tornado and Spider Data (Varying each input by +/- 10%)
    tornado_data = {}
    spider_data = {}
    params_to_test = {
        'Asset Value (V)': V,
        'Volatility': sigma,
        'Time to Maturity (T)': T,
        'Exercise Cost (K)': K,
        'Cost of Delay': delta,
        'Risk-free Rate (r)': r,
    }
    
    for name, base_val in params_to_test.items():
        results = []
        
        for factor in [0.9, 1.1]:
            if name == 'Asset Value (V)':
                new_C = get_C0(V * factor, K, T, sigma, delta, r, n)
            elif name == 'Volatility':
                new_C = get_C0(V, K, T, sigma * factor, delta, r, n)
            elif name == 'Time to Maturity (T)':
                new_T = T * factor
                new_C = get_C0(V, K, new_T, sigma, delta, r, new_T)
            elif name == 'Exercise Cost (K)':
                new_C = get_C0(V, K * factor, T, sigma, delta, r, n)
            elif name == 'Cost of Delay':
                new_C = get_C0(V, K, T, sigma, delta * factor, r, n)
            elif name == 'Risk-free Rate (r)':
                new_C = get_C0(V, K, T, sigma, delta, r * factor, n)
            
            results.append(new_C)
            
        min_C = min(results)
            
        max_C = max(results)
        
        tornado_data[name] = {
            'min': min_C,
            'max': max_C,
            'base_value': base_option_value
        }

        # Handle base_option_value == 0
        if base_option_value == 0:
            percent_change = 0.0
        else:
            abs_change = max(abs(max_C - base_option_value), abs(min_C - base_option_value))
            percent_change = abs_change / base_option_value * 100
        
        spider_data[name] = round(percent_change, 2)
        
    # 2. Line Chart 1 Data: Volatility (X) vs. Asset Value (Series)
    sigma_line_range = np.linspace(sigma * 0.5, sigma * 1.5, 7).tolist()
    v_series_factors = [0.8, 1.0, 1.2]
    
    sigma_v_data = {}
    for factor in v_series_factors:
        series_v = V * factor
        series_name = f'V={round(series_v/1000)}k'
        c_values = [round(get_C0(series_v, K, T, s, delta, r, n), 2) for s in sigma_line_range]
        sigma_v_data[series_name] = c_values

    # 3. Line Chart 2 Data: Volatility (X) vs. Cost of Delay (Series)
    delta_series_factors = [0.5, 1.0, 1.5]
    
    sigma_delta_data = {}
    for factor in delta_series_factors:
        series_delta = delta * factor
        series_name = f'Cost of Delay={round(series_delta*100, 1)}%'
        c_values = [round(get_C0(V, K, T, s, series_delta, r, n), 2) for s in sigma_line_range]
        sigma_delta_data[series_name] = c_values

    return {
        'tornado': tornado_data,
        'spider': spider_data,
        'line_chart_v_sigma': {
            'x_labels': [round(s, 3) for s in sigma_line_range],
            'data': sigma_v_data
        },
        'line_chart_delta_sigma': {
            'x_labels': [round(s, 3) for s in sigma_line_range],
            'data': sigma_delta_data
        },
        'base_option_value': base_option_value
    }

# --- AUTHENTICATION & MANAGEMENT ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard')) 

    if request.method == 'POST':
        identifier = request.form.get('identifier').strip()
        password = request.form.get('password')
        
        user = User.query.filter((User.username == identifier) | (User.email == identifier)).first()

        if user and user.check_password(password):
            login_user(user, remember=True)
            return redirect(url_for('dashboard')) 
        else:
            flash('Login Failed. Check username/email and password.', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    # Explicitly get the User object to avoid 'LocalProxy' error
    user = User.query.get(current_user.id)
    
    # CRITICAL FIX: Enforce Super Admin transfer protection for the specific account.
    if user.is_super_admin and user.username == SUPER_ADMIN_USERNAME:
        # Check if any other user has the super admin role
        if User.query.filter(User.is_super_admin == True, User.id != user.id).count() == 0:
            flash('CRITICAL: You are the last Super Admin. Transfer the Super Admin role before deleting your account.', 'danger')
            return redirect(url_for('dashboard'))

    # User deletion success path
    logout_user() 
    try:
        db.session.delete(user)
        db.session.commit()
        flash('Your account has been successfully deleted.', 'success')
        return redirect(url_for('login'))
    except Exception as e:
        # Fallback in case of database error after logout
        flash(f'An error occurred during account deletion: {e}', 'danger')
        return redirect(url_for('login'))


@app.route('/admin/manage_users', methods=['GET', 'POST'])
@admin_required
def admin_manage_users():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_user':
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
            is_admin = request.form.get('is_admin') == 'on'
            is_super_admin = request.form.get('is_super_admin') == 'on' # Only present if current_user is super admin

            if not all([username, email, password]):
                flash('All fields are required.', 'danger')
            elif User.query.filter((User.username == username) | (User.email == email)).first():
                flash('Username or Email already exists.', 'danger')
            elif is_super_admin and not current_user.is_super_admin:
                flash('Only the Super Admin can create another Super Admin.', 'danger')
            else:
                # If promoting to Super Admin, make sure they are also marked as admin
                if is_super_admin:
                    is_admin = True 

                new_user = User(username=username, email=email, is_admin=is_admin, is_super_admin=is_super_admin)
                new_user.set_password(password)
                try:
                    db.session.add(new_user)
                    db.session.commit()
                    flash(f'User "{username}" created successfully (Admin: {is_admin})!', 'success')
                except Exception as e:
                    db.session.rollback()
                    flash(f'An error occurred while creating the user: {e}', 'danger')

        elif action == 'delete_user':
            user_id = request.form.get('user_id')
            user_to_delete = User.query.get(user_id)
            
            if user_to_delete:
                # Super Admin Deletion Protection (Admin Portal)
                if user_to_delete.is_super_admin:
                    if user_to_delete.username == SUPER_ADMIN_USERNAME:
                        # Cannot delete the primary Super Admin through the portal if they are the last one.
                        if User.query.filter_by(is_super_admin=True).count() <= 1:
                            flash('Cannot delete the last remaining primary Super Admin.', 'danger')
                            return redirect(url_for('admin_manage_users'))

                    if not current_user.is_super_admin:
                        flash('Only the Super Admin can delete Super Admin accounts.', 'danger')
                        return redirect(url_for('admin_manage_users'))
                
                try:
                    # If admin deletes themselves, log them out first
                    if user_to_delete.id == current_user.id:
                        logout_user() 
                        flash(f'Your admin account was deleted.', 'success')
                        db.session.delete(user_to_delete)
                        db.session.commit()
                        return redirect(url_for('login'))

                    db.session.delete(user_to_delete)
                    db.session.commit()
                    flash(f'User {user_to_delete.username} deleted.', 'success')
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error deleting user: {e}', 'danger')
            else:
                flash('User not found.', 'danger')

        elif action == 'toggle_admin':
            user_id = request.form.get('user_id')
            user_to_toggle = User.query.get(user_id)

            if user_to_toggle and current_user.is_admin:
                
                # Prevent non-Super Admin from modifying Super Admins
                if user_to_toggle.is_super_admin and not current_user.is_super_admin:
                    flash('Only the Super Admin can modify Super Admin roles.', 'danger')
                
                # Prevent removal of primary Super Admin role via toggle
                elif user_to_toggle.username == SUPER_ADMIN_USERNAME and user_to_toggle.is_admin:
                    flash('The primary Super Admin role cannot be modified via this toggle.', 'danger')
                
                else:
                    user_to_toggle.is_admin = not user_to_toggle.is_admin
                    
                    # If we remove admin, ensure super_admin is also false (safety)
                    if not user_to_toggle.is_admin:
                        user_to_toggle.is_super_admin = False 
                    
                    try:
                        db.session.commit()
                        flash(f'Role for {user_to_toggle.username} updated. Super Admin role revoked if admin privileges were removed.', 'success')
                    except Exception as e:
                        db.session.rollback()
                        flash(f'Error updating role: {e}', 'danger')

        # Corrected 'set_super_admin' logic for transferring the role
        elif action == 'set_super_admin':
            user_id = request.form.get('user_id')
            user_to_promote = User.query.get(user_id)
            
            if not current_user.is_super_admin:
                 flash('Only the Super Admin can assign the Super Admin role.', 'danger')
            elif user_to_promote and current_user.is_super_admin:
                
                # Ensure the current user isn't promoting themselves (shouldn't happen via form but for safety)
                if user_to_promote.id == current_user.id:
                    flash('Cannot transfer the role to yourself.', 'danger')
                    return redirect(url_for('admin_manage_users'))

                # Demote current super admin
                current_user.is_super_admin = False
                
                # Promote target user (must be admin to be super admin)
                user_to_promote.is_admin = True
                user_to_promote.is_super_admin = True

                try:
                    db.session.commit()
                    flash(f'Super Admin role transferred from {current_user.username} to {user_to_promote.username}. You are now a regular admin/user. Please log in again.', 'success')
                    # Log out current user to force re-login with new permissions
                    logout_user()
                    return redirect(url_for('login'))

                except Exception as e:
                    db.session.rollback()
                    flash(f'Error transferring Super Admin role: {e}', 'danger')
            else:
                flash('User not found for promotion.', 'danger')


    # GET request: list all users for the admin portal view
    users = User.query.all()
    return render_template('admin_add_user.html', users=users, current_user=current_user)

@app.route('/')
def index():
    # Force redirection to login page for persistent session environments
    if current_user.is_authenticated:
        logout_user()
        
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    # This is the actual main page content route, which requires login.
    return render_template('main.html')

@app.route('/api/user/history')
@login_required
def get_user_history():
    # Fetch calculations belonging to the current user (Max 15 is enforced in /calculate)
    history = Calculation.query.filter_by(user_id=current_user.id).order_by(desc(Calculation.timestamp)).all()
    
    history_data = []
    for calc in history:
        inputs = json.loads(calc.input_params_json)
        outputs = json.loads(calc.output_summary_json)
        
        history_data.append({
            'id': calc.id,
            'timestamp': calc.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'input_params': inputs, 
            'initial_option_value': outputs.get('initial_option_value', 'N/A')
        })
        
    return jsonify(history_data)

@app.route('/calculate', methods=['POST'])
@login_required 
def calculate():
    try:
        data  = request.get_json(force=True)
        V_input_thousands = float(data['V'])
        K_input_thousands = float(data['K'])

        delta_mode = data.get('delta-mode', 'auto') 
        delta_input = data['delta'] 
        deltas_manual = None
        
        if delta_mode == 'auto':
            delta_val = float(delta_input)
            delta_t0 = delta_val
        else:
            try:
                if delta_input:
                    deltas_manual = [float(d.strip()) for d in delta_input.split(',')]
                else:
                    deltas_manual = []
            except ValueError:
                return jsonify({'error': 'Manual Cost of Delay values must be valid numbers.'}), 400
            
            delta_val = deltas_manual[0] if deltas_manual else 0.0
            delta_t0 = delta_val
            
        V_calc = V_input_thousands * 1000
        K_calc = K_input_thousands * 1000
        T     = float(data['T'])
        sigma = float(data['sigma'])
        r     = float(data['r'])

        n = int(T)
        if n == 0:
            n = 1

        # NOTE: calculate_lattices returns 6 values: A, N, C, times(n+1), deltas(n+1), ps_for_export(n+1)
        A, N, C, times, deltas, ps_for_export = calculate_lattices(V_calc, K_calc, T, sigma, delta_val, r, n, deltas_manual) 

        # CRITICAL FIX: Ensure the probability array used for DataFrame creation is the full length (n+1)
        # The ps_for_export returned by the helper function (6th value) already has the correct length (n+1).
        
        initial_option_value_actual_units = C[0][0]
        initial_option_value_thousands = initial_option_value_actual_units / 1000

        # Data to save for history (inputs) - Using desired full names for history display
        input_params = {
            'Asset Value V': V_input_thousands, 
            'Exercise Cost K': K_input_thousands, 
            'Time to Maturity T': T, 
            'Volatility': sigma, 
            'Risk-free Rate r': r, 
            'Delta Mode': delta_mode, 
            'Cost of Delay (t=0)': delta_t0,
            'Cost of Delay (Manual Mode)': deltas_manual 
        }
        
        A_thousands = [[int(round(val / 1000)) for val in row_a] for row_a in A]
        N_thousands = [[int(round(val / 1000)) for val in row_n] for row_n in N]
        C_thousands = [[int(round(val / 1000)) for val in row_c] for row_c in C]

        base_params = {
            'V_calc': V_calc, 'K_calc': K_calc, 'T': T, 'sigma': sigma, 
            'delta_val': delta_val, 'r': r, 'delta_t0': delta_t0, 
            'deltas_manual': deltas_manual
        }
        sensitivity_data = calculate_sensitivity_data(base_params, n)

        # Data to save for history (output summary)
        output_summary = {
            'initial_option_value': round(initial_option_value_thousands, 4),
            'sensitivity_summary': sensitivity_data.get('base_option_value', 'N/A') 
        }

        # --- SAVE CALCULATION TO DB & MANAGE LIMIT (MAX 15) ---
        if current_user.is_authenticated:
            # Check the count
            calc_count = Calculation.query.filter_by(user_id=current_user.id).count()
            
            # If count exceeds 14 (will become 15 when new one is added), delete the oldest one (ASCENDING order in model relationship)
            if calc_count >= 15:
                # The relationship is ordered by asc, so .first() is the oldest
                oldest_calc = current_user.calculations.first()
                if oldest_calc:
                    db.session.delete(oldest_calc)
            
            # Add the new calculation
            new_calc = Calculation(
                user_id=current_user.id,
                input_params_json=json.dumps(input_params),
                output_summary_json=json.dumps(output_summary)
            )
            db.session.add(new_calc)
            db.session.commit()
        # --- END SAVE CALCULATION ---
        
        if data.get('export') == 'excel':
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                wb = writer.book
                ws = wb.add_worksheet('tree')
                writer.sheets['tree'] = ws

                hdr_fmt = wb.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1})
                float_fmt = wb.add_format({'num_format': '0.0000'})
                int_fmt = wb.add_format({'num_format': '0'})
                section_hdr = wb.add_format({'bold': True, 'bg_color': '#d9ead3', 'align': 'left'})

                row = 0
                ws.merge_range(row, 0, row, 1, 'Input Parameters', section_hdr)
                row += 1
                ws.write_row(row, 0, ['Parameter', 'Value'], hdr_fmt)
                row += 1
                
                delta_label = 'Cost of delay $\delta$ (t=0, Auto Model)' if delta_mode == 'auto' else 'Cost of delay $\delta$ (t=0, Manual Input)'

                params = [
                    ['Asset Value V (€1000s)', V_input_thousands],
                    ['Exercise Cost K (€1000s)', K_input_thousands],
                    ['Time to Maturity T (years)', T],
                    ['Volatility $\sigma$', sigma],
                    [delta_label, delta_t0],
                    ['Risk-free Rate r', r],
                    ['Initial option value C₀ (€1000s)', initial_option_value_thousands],
                ]
                for label, val in params:
                    ws.write_row(row, 0, [label, val], float_fmt)
                    row += 1

                row += 2
                ws.merge_range(row, 0, row, 2, 'Time-Variant Inputs', section_hdr)
                row += 1
                
                tv_data = {
                    't':              times,
                    '$\delta$ (delay cost)':   deltas,
                    # Using the ps_for_export list (length n+1) 
                    'p (up-move prob)': ps_for_export
                }
                # This line should now succeed because all lists (times, deltas, ps_for_export) are length n+1
                tv = pd.DataFrame(tv_data)
                
                ws.write_row(row + 1, 0, ['t', '$\delta$ (delay cost)', 'p (up-move prob)'], hdr_fmt)
                
                for r_idx in range(len(tv)):
                    ws.write_number(row + 2 + r_idx, 0, tv.loc[r_idx, 't'], int_fmt)
                    ws.write_number(row + 2 + r_idx, 1, tv.loc[r_idx, '$\delta$ (delay cost)'], float_fmt)
                    
                    p_val = tv.loc[r_idx, 'p (up-move prob)']
                    ws.write_number(row + 2 + r_idx, 2, p_val, float_fmt)
                        
                row += len(tv) + 3

                def write_lattice(df, title, start_row):
                    ws.merge_range(start_row, 0, start_row, n+1, title, section_hdr)
                    df.to_excel(writer, sheet_name='tree', startrow=start_row+2, startcol=0, header=True, index=True, float_format='0')
                    return start_row + len(df) + 4

                dfA = pd.DataFrame(A_thousands, index=[f'i={i}' for i in times], columns=[f't={t}' for t in times])
                dfN = pd.DataFrame(N_thousands, index=[f'i={i}' for i in times], columns=[f't={t}' for t in times])
                dfC = pd.DataFrame(C_thousands, index=[f'i={i}' for i in times], columns=[f't={t}' for t in times])

                row = write_lattice(dfA, 'Asset-Value Lattice (A)', row)
                row = write_lattice(dfN, 'Net-Value Lattice (N)', row)
                write_lattice(dfC, 'Option-Value Lattice (C)', row)

            buf.seek(0)
            return send_file(
                buf,
                as_attachment=True,
                download_name='tree.xlsx',
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

        return jsonify({
            'summary': {'initial_option_value': round(initial_option_value_thousands, 4)},
            'asset':  A_thousands,
            'net':    N_thousands,
            'option': C_thousands,
            'sensitivity': sensitivity_data
        })

    except Exception as e:
        # Ensures that errors during calculation or export are visible in the console
        current_app.logger.exception("Calculation or export failed")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    create_default_admin() 
    app.run(debug=True)