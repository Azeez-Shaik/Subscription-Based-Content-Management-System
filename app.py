from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import mysql.connector
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
import io

app = Flask(__name__)
app.secret_key = "your_secret_key"

bcrypt = Bcrypt(app)
login_manager = LoginManager()
login_manager.init_app(app)

# Database Connection
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="subscription_db"
    )

# User Model
class User(UserMixin):
    def __init__(self, id, username, email, subscription_type, expiry_date, role, age=None, phone=None):
        self.id = id
        self.username = username
        self.email = email
        self.subscription_type = subscription_type
        self.expiry_date = expiry_date if expiry_date else None
        self.role = role
        self.age = age  
        self.phone = phone  


@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if user:
        return User(
            user["id"], user["username"], user["email"],
            user["subscription_type"], user["expiry_date"],
            user["role"], user.get("age"), user.get("phone")
        )
    return None



# ---------------------- EXISTING ROUTES ----------------------
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        role = request.form['role']

        if role not in ['user', 'admin']:
            flash("Invalid role selected.", 'danger')
            return redirect(url_for('signup'))

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)", 
                       (username, email, password, role))
        conn.commit()
        cursor.close()
        conn.close()

        flash("Registration successful! Please log in.", 'success')
        return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and bcrypt.check_password_hash(user["password"], password):
            user_obj = User(user["id"], user["username"], user["email"], user["subscription_type"], user["expiry_date"], user["role"])
            login_user(user_obj)
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid login credentials, please try again.", 'danger')

    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch user details along with the assigned trainer's details
    cursor.execute("""
        SELECT users.id, users.username, users.subscription_type, users.expiry_date, 
               trainers.name AS trainer_name, trainers.contact AS trainer_contact, 
               trainers.specialization AS trainer_specialization  -- Get specialization from trainers table
        FROM users 
        LEFT JOIN trainers ON users.trainer_id = trainers.id
        WHERE users.id = %s
    """, (current_user.id,))
    
    user = cursor.fetchone()

    if not user:
        return "User not found", 404

    # Debugging: Print user dictionary to check if trainer_specialization is available
    print("User Data:", user)

    # Fetch content matching the user's subscription type and the trainer's specialization
    cursor.execute("""
        SELECT * FROM content 
        WHERE subscription_type = %s AND specialization = %s
    """, (user['subscription_type'], user['trainer_specialization']))  # Use trainer's specialization

    content = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('user_dashboard.html', 
                           username=user['username'], 
                           subscription_type=user['subscription_type'], 
                           expiry_date=user['expiry_date'],
                           trainer_name=user['trainer_name'],
                           trainer_contact=user['trainer_contact'],
                           trainer_specialization=user['trainer_specialization'],
                           content=content)  # Pass filtered content to template

@app.route('/admin_dashboard', methods=['GET', 'POST'])
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch users along with their assigned trainer details
    cursor.execute("""
        SELECT users.*, trainers.name AS trainer_name 
        FROM users 
        LEFT JOIN trainers ON users.trainer_id = trainers.id
        WHERE users.role = 'user'
    """)
    users = cursor.fetchall()

    cursor.execute("SELECT * FROM trainers")
    trainers = cursor.fetchall()

    # Fetch subscription types and specializations for filter dropdowns
    cursor.execute("SELECT DISTINCT subscription_type FROM content")
    subscription_types = [row['subscription_type'] for row in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT specialization FROM content")
    specializations = [row['specialization'] for row in cursor.fetchall()]

    # Handle content filtering
    filter_subscription = request.form.get('filter_subscription')
    filter_specialization = request.form.get('filter_specialization')

    query = "SELECT * FROM content WHERE 1=1"
    params = []

    if filter_subscription:
        query += " AND subscription_type = %s"
        params.append(filter_subscription)

    if filter_specialization:
        query += " AND specialization = %s"
        params.append(filter_specialization)

    cursor.execute(query, params)
    uploaded_content = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('admin_dashboard.html', users=users, trainers=trainers, 
                           subscription_types=subscription_types, specializations=specializations,
                           uploaded_content=uploaded_content)


@app.route('/update_subscription', methods=['POST'])
@login_required
def update_subscription():
    user_id = request.form['user_id']
    new_subscription_type = request.form['subscription_type']
    expiry_date = datetime.now() + timedelta(days=30)  # Extend for 30 days

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET subscription_type = %s, expiry_date = %s WHERE id = %s",
                   (new_subscription_type, expiry_date, user_id))
    conn.commit()
    cursor.close()
    conn.close()

    # Update current_user session
    current_user.subscription_type = new_subscription_type
    current_user.expiry_date = expiry_date

    flash("Your subscription has been updated successfully!", 'success')
    return redirect(url_for('dashboard'))

@app.route('/update_age', methods=['POST'])
@login_required
def update_age():
    if 'age' not in request.form:
        flash("Age is required.", 'danger')
        return redirect(url_for('dashboard'))

    new_age = request.form['age']

    try:
        new_age = int(new_age)
        if new_age < 0:
            flash("Invalid age entered.", 'danger')
            return redirect(url_for('dashboard'))
    except ValueError:
        flash("Please enter a valid number for age.", 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET age = %s WHERE id = %s", (new_age, current_user.id))
    conn.commit()
    cursor.close()
    conn.close()

    # Update session with new age
    current_user.age = new_age

    flash("Your age has been updated successfully!", 'success')
    return redirect(url_for('dashboard'))

@app.route('/update_phone', methods=['POST'])
@login_required
def update_phone():
    if 'phone' not in request.form:
        flash("Phone number is required.", 'danger')
        return redirect(url_for('dashboard'))

    new_phone = request.form['phone']

    # Validate phone number format (digits only and length check)
    if not new_phone.isdigit() or not (10 <= len(new_phone) <= 15):
        flash("Invalid phone number. Enter 10-15 digits only.", 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET phone = %s WHERE id = %s", (new_phone, current_user.id))
    conn.commit()
    cursor.close()
    conn.close()

    # Update session with new phone number
    current_user.phone = new_phone

    flash("Your phone number has been updated successfully!", 'success')
    return redirect(url_for('dashboard'))


@app.route('/edit_user_subscription/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user_subscription(user_id):
    if current_user.role != 'admin':
        flash("You do not have permission to edit subscriptions.", 'danger')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        new_subscription_type = request.form['subscription_type']
        expiry_date = datetime.now() + timedelta(days=30)  # Example for 1-month subscription
        
        cursor.execute(
            "UPDATE users SET subscription_type = %s, expiry_date = %s WHERE id = %s",
            (new_subscription_type, expiry_date, user_id)
        )
        conn.commit()
        flash("User's subscription has been updated.", 'success')
        return redirect(url_for('admin_dashboard'))

    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template('edit_user_subscription.html', user=user)

@app.route('/delete_user_subscription/<int:user_id>', methods=['POST'])
@login_required
def delete_user_subscription(user_id):
    if current_user.role != 'admin':
        flash("You do not have permission to delete users.", 'danger')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()

    cursor.close()
    conn.close()

    flash("User deleted successfully.", 'success')
    return redirect(url_for('admin_dashboard'))



# ---------------------- TRAINER MANAGEMENT ----------------------

@app.route('/add_trainer', methods=['POST'])
@login_required
def add_trainer():
    if current_user.role != 'admin':
        flash("Unauthorized access.", 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        name = request.form['name']
        specialization = request.form['specialization']
        contact = request.form['contact']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO trainers (name, specialization, contact) VALUES (%s, %s, %s)",
                       (name, specialization, contact))
        conn.commit()
        cursor.close()
        conn.close()

        flash("Trainer added successfully!", 'success')
        return redirect(url_for('admin_dashboard'))

@app.route('/assign_trainer/<int:user_id>', methods=['POST'])
@login_required
def assign_trainer(user_id):
    if current_user.role != 'admin':
        flash("Unauthorized access.", 'danger')
        return redirect(url_for('admin_dashboard'))

    trainer_id = request.form.get('trainer_id')  # Safely get form data
    trainer_id = int(trainer_id) if trainer_id else None  # Convert to int or None

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if trainer exists
    if trainer_id:
        cursor.execute("SELECT id FROM trainers WHERE id = %s", (trainer_id,))
        trainer_exists = cursor.fetchone()
        if not trainer_exists:
            flash("Invalid trainer selected.", 'danger')
            return redirect(url_for('admin_dashboard'))

    # Update user with assigned trainer
    cursor.execute("UPDATE users SET trainer_id = %s WHERE id = %s", (trainer_id, user_id))
    conn.commit()

    cursor.close()
    conn.close()

    flash("Trainer assigned successfully.", 'success')
    return redirect(url_for('admin_dashboard'))

    

@app.route('/edit_trainer/<int:trainer_id>', methods=['GET', 'POST'])
@login_required
def edit_trainer(trainer_id):
    print(f"Editing trainer ID: {trainer_id}")  # Debugging Line

    if current_user.role != 'admin':
        flash("Unauthorized access.", 'danger')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        name = request.form['name']
        specialization = request.form['specialization']
        contact = request.form['contact']

        cursor.execute("UPDATE trainers SET name = %s, specialization = %s, contact = %s WHERE id = %s",
                       (name, specialization, contact, trainer_id))
        conn.commit()
        cursor.close()
        conn.close()

        flash("Trainer updated successfully.", 'success')
        return redirect(url_for('admin_dashboard'))

    cursor.execute("SELECT * FROM trainers WHERE id = %s", (trainer_id,))
    trainer = cursor.fetchone()
    cursor.close()
    conn.close()

    if not trainer:
        flash("Trainer not found.", 'danger')
        return redirect(url_for('admin_dashboard'))

    return render_template('edit_trainer.html', trainer=trainer)


@app.route('/delete_trainer/<int:trainer_id>', methods=['POST'])
@login_required
def delete_trainer(trainer_id):
    if current_user.role != 'admin':
        flash("Unauthorized access.", 'danger')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trainers WHERE id = %s", (trainer_id,))
    conn.commit()
    cursor.close()
    conn.close()

    flash("Trainer deleted successfully.", 'warning')
    return redirect(url_for('admin_dashboard'))

@app.route('/process_payment', methods=['POST'])
@login_required
def process_payment():
    user_id = request.form.get('user_id')
    subscription_type = request.form.get('subscription_type')
    payment_type = request.form.get('payment_type')
    amount = request.form.get('amount')

    if not subscription_type or not amount:
        flash("Invalid subscription details!", "danger")
        return redirect(url_for('dashboard'))

    # Update user's subscription in the database
    conn = get_db_connection()
    cursor = conn.cursor()
    
    expiry_date = datetime.utcnow() + timedelta(days=30)  # Set 30 days from today
    cursor.execute("UPDATE users SET subscription_type = %s, expiry_date = %s WHERE id = %s",
                   (subscription_type, expiry_date, user_id))
    
    # Insert payment details
    cursor.execute("INSERT INTO payments (user_id, amount, payment_date, payment_method) VALUES (%s, %s, NOW(), %s)",
                   (user_id, amount, payment_type))
    
    conn.commit()
    cursor.close()
    conn.close()

    # Update the session with new subscription data
    current_user.subscription_type = subscription_type
    current_user.expiry_date = expiry_date

    flash("Subscription upgraded successfully!", "success")
    return redirect(url_for('dashboard'))

# ---------------------- CONTENT ----------------------
@app.route('/admin/upload_content', methods=['POST'])
@login_required
def upload_content():
    if current_user.role != 'admin':
        flash("You do not have permission to add content.", 'danger')
        return redirect(url_for('admin_dashboard'))

    title = request.form['title']
    description = request.form['description']
    subscription_type = request.form['subscription_type']
    specialization = request.form['specialization']
    file = request.files.get('file')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    if file:
        file_data = file.read()
        cursor.execute("""
            INSERT INTO content (title, description, subscription_type, specialization, file_data)
            VALUES (%s, %s, %s, %s, %s)
        """, (title, description, subscription_type, specialization, file_data))
    else:
        cursor.execute("""
            INSERT INTO content (title, description, subscription_type, specialization)
            VALUES (%s, %s, %s, %s)
        """, (title, description, subscription_type, specialization))

    conn.commit()
    cursor.close()
    conn.close()
    
    flash("Content added successfully!", 'success')
    return redirect(url_for('admin_dashboard'))



import io
from flask import Response, send_file

@app.route('/get_content/<int:content_id>')
@login_required
def get_content(content_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT content, content_type, filename FROM content WHERE id = %s", (content_id,))
    file = cursor.fetchone()
    cursor.close()
    conn.close()

    if file:
        # Check content type and return appropriate response
        if file['content_type'] == 'text':
            return Response(file['content'].decode('utf-8'), mimetype='text/plain')
        elif file['content_type'] == 'image':
            return Response(io.BytesIO(file['content']).read(), mimetype='image/jpeg')  # Change type if needed
        elif file['content_type'] == 'video':
            return Response(io.BytesIO(file['content']).read(), mimetype='video/mp4')  # Change type if needed
        else:
            return send_file(
                io.BytesIO(file['content']),
                as_attachment=True,
                download_name=file['filename']
            )
    
    flash("Content not found.", 'danger')
    return redirect(url_for('dashboard'))


@app.route('/delete_content/<int:content_id>', methods=['POST'])
@login_required
def delete_content(content_id):
    if current_user.role != 'admin':
        flash("Unauthorized access.", 'danger')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if content exists
    cursor.execute("SELECT * FROM content WHERE id = %s", (content_id,))
    content = cursor.fetchone()

    if not content:
        flash("Content not found.", 'danger')
        cursor.close()
        conn.close()
        return redirect(url_for('admin_dashboard'))

    # Delete the content
    cursor.execute("DELETE FROM content WHERE id = %s", (content_id,))
    conn.commit()

    cursor.close()
    conn.close()

    flash("Content deleted successfully!", 'success')
    return redirect(url_for('admin_dashboard'))


# ---------------------- LOGOUT ----------------------
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
