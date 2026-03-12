# ===================== IMPORTS =====================
import os
import sqlite3
import uuid
import pathlib
import torch
from datetime import datetime
import yaml
import smtplib
import numpy as np

from PIL import Image
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, emit, join_room
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    import cv2
except:
    cv2 = None

app = Flask(__name__)
app = Flask(__name__)

# Allow larger uploads (important for mobile photos)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024
app.secret_key = 'wverihdfuvuwi2482'

app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True

EMAIL_ADDRESS = "c9074hai@gmail.com"
EMAIL_PASSWORD = "dnhd qnaf dklq jshy"  
ADMIN_EMAIL = "deeplearning251@gmail.com"


BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app.config['DATABASE'] = os.path.join(BASE_DIR, 'database.db')

app.config['COMPLAINT_UPLOAD_FOLDER'] = os.path.join(
    BASE_DIR, 'static', 'uploads', 'complaints'
)

app.config['PROFILE_UPLOAD_FOLDER'] = os.path.join(
    BASE_DIR, 'static', 'profiles'
)

app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0


os.makedirs(app.config['COMPLAINT_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROFILE_UPLOAD_FOLDER'], exist_ok=True)


def load_class_names():
    with open("data.yaml", "r") as f:
        data = yaml.safe_load(f)
    return data["names"]



def get_db_connection():
   
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    with conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                number TEXT,
                password TEXT NOT NULL,
                image_path TEXT,
                role TEXT DEFAULT 'user'
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS complients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                image_path TEXT,
                result TEXT,
                user_email TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    conn.close()

def allowed_file(filename, filetype):
    if filetype == 'image':
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions
    return False



@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}


@app.route('/')
def index():
   
    return render_template('index.html',  title="Home")



@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        number = request.form['number']
        password = request.form['password']
        profile_image = request.files['profile_image']
        role = request.form['role']

        filename = None
        if profile_image and allowed_file(profile_image.filename, 'image'):
            filename = secure_filename(profile_image.filename)
            image_path = os.path.join(app.config['PROFILE_UPLOAD_FOLDER'], filename)
            profile_image.save(image_path)
        else:
            flash('Invalid image file.', 'danger')
            return redirect(request.url)

        hashed_password = generate_password_hash(password)
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO users (name, email, number, password, image_path, role) VALUES (?, ?, ?, ?, ?, ?)',
                (name, email, number, hashed_password, filename, role)
            )
            conn.commit()
            flash('Registration successful. Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already exists.', 'danger')
        finally:
            conn.close()

    return render_template('register.html', title="Register")


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
    
        if user and check_password_hash(user['password'], password):
            session['email'] = user['email']
            session['name'] = user['name']
            session['role'] = user['role']

            flash('Login successful!', 'success')
            return redirect(url_for('admin_dashboard' if user['role'] == 'admin' else 'index'))
        else:
            flash('Invalid email or password', 'danger')

    return render_template('login.html', title="Login")



@app.route('/contact', methods=['GET', 'POST'])
def contact():
    return render_template('contact.html')



@app.route('/profile')
def profile():
    if 'email' not in session:
        flash('Please login to view your profile.', 'warning')
        return redirect(url_for('login'))

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (session['email'],)).fetchone()
    conn.close()

    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('login'))

    return render_template('profile.html', user=user)



# Load model once
model = None

def get_model():
    global model

    if model is None:

        model_path = os.path.join(os.getcwd(), "best.pt")

        print("Current directory:", os.getcwd())
        print("Looking for model at:", model_path)

        if not os.path.exists(model_path):
            print("best.pt not found")
            return None

        print("Loading YOLO model...")

        model = torch.hub.load(
            "ultralytics/yolov5",
            "custom",
            path=model_path,
            source="github"
        )

        model.conf = 0.15
        model.iou = 0.45

    return model

from PIL import Image
import numpy as np

def run_yolo_detection(image_path, detection_folder, filename):

    try:
        # Load image using Pillow instead of cv2
        img = Image.open(image_path).convert("RGB")
        img_np = np.array(img)

        model = get_model()

        if model is None:
            print("Model load failed")
            return None, "Model load failed"

        results = model(img_np)

        detected_classes = []

        for *box, conf, cls in results.xyxy[0]:
            class_name = model.names[int(cls)]
            detected_classes.append(class_name)

        detected_classes = list(set(detected_classes))

        if not detected_classes:
            result_text = "No object detected"
        else:
            result_text = ", ".join(detected_classes)

        save_path = os.path.join(detection_folder, filename)

        # Save result image
        img.save(save_path, format="JPEG")

        return f"/static/detections/{filename}", result_text

    except Exception as e:
        print("Detection error:", e)
        return None, "Detection failed"

import uuid

@app.route('/complaint', methods=['GET', 'POST'])
def complaint():

    if 'email' not in session:
        flash('Please login to file a complaint.', 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':

        title = request.form.get('title')
        description = request.form.get('description')
        complaint_image = request.files.get('complaint_image')

        if not title or not description:
            flash('All fields are required.', 'danger')
            return redirect(request.url)

        if not complaint_image or not allowed_file(complaint_image.filename, 'image'):
            flash('Please upload a valid image file.', 'danger')
            return redirect(request.url)

        ext = complaint_image.filename.rsplit('.', 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex}.{ext}"

        upload_folder = app.config['COMPLAINT_UPLOAD_FOLDER']

        detection_folder = os.path.join(BASE_DIR, "static", "detections")

        os.makedirs(upload_folder, exist_ok=True)
        os.makedirs(detection_folder, exist_ok=True)

        original_path = os.path.join(upload_folder, unique_name)

        complaint_image.save(original_path)

        detected_relative_path, result_text = run_yolo_detection(
            original_path,
            detection_folder,
            unique_name
        )
        if detected_relative_path is None:
            print("Image detection failed, saving original image only")
            detected_relative_path = f"uploads/complaints/{unique_name}"
            result_text = "Detection failed"

        conn = get_db_connection()

        conn.execute("""
            INSERT INTO complients
            (title, description, image_path, result, user_email)
            VALUES (?, ?, ?, ?, ?)
        """, (
            title,
            description,
            detected_relative_path,
            result_text,
            session['email']
        ))

        conn.commit()
        conn.close()

        flash('Complaint filed & analyzed successfully.', 'success')

        return redirect(url_for('my_complaints'))

    return render_template('complaint.html', title="File Complaint")

@app.route('/my_complaints')
def my_complaints():
    if 'email' not in session or 'role' not in session:
        flash('Please login to view your complaints.', 'warning')
        return redirect(url_for('login'))

    conn = get_db_connection()
    complaints = conn.execute(
    "SELECT * FROM complients WHERE user_email = ?",
    (session['email'],)
).fetchall()

    conn.close()

    return render_template('my_complaints.html', complaints=complaints, title="My Complaints")


## Admin Routes
@app.route('/admin_dashboard')
def admin_dashboard():
    if 'email' not in session or session.get('role') != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    
    total_users = conn.execute("SELECT COUNT(*) FROM users ").fetchone()[0]
    
    total_complaints = conn.execute("SELECT COUNT(*) FROM complients").fetchone()[0]
    conn.close()

    return render_template('admin_dashboard.html',
                           total_users=total_users,
                           total_complaints=total_complaints,
                          
                           title="Admin Dashboard")


@app.route('/admin/users')
def admin_users():
    if 'email' not in session or session.get('role') != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    users = conn.execute("SELECT * FROM users").fetchall()
    conn.close()

    return render_template('admin_users.html', users=users, title="Admin Users")


@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if 'email' not in session or session.get('role') != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()

   
    user = conn.execute(
        "SELECT role FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not user or user['role'] in ('admin'):
        conn.close()
        flash('You cannot delete this user.', 'danger')
        return redirect(url_for('admin_users'))

    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/complaints')
def admin_complaints():
    if 'email' not in session or session.get('role') != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    complaints = conn.execute("SELECT * FROM complients").fetchall()
    conn.close()

    return render_template('admin_complaints.html', complaints=complaints, title="Admin Complaints")

@app.route('/admin/complaint/edit/<int:complaint_id>', methods=['GET', 'POST'])
def admin_complaint_edit(complaint_id):
    if 'email' not in session or session.get('role') != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    complaint = conn.execute("SELECT * FROM complients WHERE id = ?", (complaint_id,)).fetchone()

    if not complaint:
        conn.close()
        flash('Complaint not found.', 'danger')
        return redirect(url_for('admin_complaints'))

    if request.method == 'POST':
        result = request.form['result']
        status = request.form['status']

        conn.execute(
            "UPDATE complients SET result = ?, status = ? WHERE id = ?",
            (result, status, complaint_id)
        )
        conn.commit()
        conn.close()

        flash('Complaint updated successfully.', 'success')
        return redirect(url_for('admin_complaints'))

    conn.close()
    return render_template('admin_complaint_edit.html', complaint=complaint, title="Edit Complaint")


@app.route('/admin/complaint/delete/<int:complaint_id>', methods=['POST'])
def delete_complaint(complaint_id):
    if 'email' not in session or session.get('role') != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    conn.execute("DELETE FROM complients WHERE id = ?", (complaint_id,))
    conn.commit()
    conn.close()

    flash('Complaint deleted successfully.', 'success')
    return redirect(url_for('admin_complaints'))



@app.template_filter('time_ago')
def time_ago(value):
    """
    Converts datetime or datetime-string to 'x minutes ago'
    """
    if not value:
        return ''

  
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value 
    now = datetime.now()
    diff = now - value

    seconds = diff.total_seconds()

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    elif seconds < 86400:
        return f"{int(seconds // 3600)} hours ago"
    elif seconds < 604800:
        return f"{int(seconds // 86400)} days ago"
    else:
        return value.strftime("%b %d, %Y")


def send_chat_start_email(sender_name, sender_email):
    try:
        subject = "New User Started Chat"

        body = f"""
A user has started a chat.

Name: {sender_name}
Email: {sender_email}

Please check admin dashboard.
        """

        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = ADMIN_EMAIL
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, ADMIN_EMAIL, msg.as_string())
        server.quit()

        print("Chat start notification sent.")

    except Exception as e:
        print("Chat start email failed:", str(e))


@app.route('/chat')
def user_chat():
    if 'email' not in session:
        flash('Please login first.', 'warning')
        return redirect(url_for('login'))

    # Send notification only once per session
    if not session.get("chat_started_notified") and session.get("role") != "admin":

        send_chat_start_email(
            session.get("name"),
            session.get("email")
        )

        session["chat_started_notified"] = True

    return render_template(
        'user_chat.html',
        room_id=session['email'],
        user_name=session['name']
    )


socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)

init_db()

# Admin Chat Route
@app.route('/admin/chat/<user_email>')
def admin_chat(user_email):
    if 'email' not in session or session.get('role') != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))
    
    # room_id is user_email because it's unique
    return render_template(
     'admin_chat.html',
     room_id=user_email,
     user_name=session['name']
)
# Online Users Page (Admin)
@app.route('/admin/online-users')
def admin_online_users():

    if 'email' not in session or session.get('role') != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    return render_template('online_users.html')

@app.route('/admin/chat-list')
def admin_chat_list():

    if 'email' not in session or session.get('role') != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()

    users = conn.execute("""
        SELECT name, email
        FROM users
        WHERE role != 'admin'
    """).fetchall()

    conn.close()

    return render_template(
        'admin_chat_list.html',
        users=users
    )

@socketio.on('join')
def on_join(data):
    room = data['room']
    user = data['user']

    join_room(room)

    print(f"{user} joined room: {room}")

    emit(
        'status',
        {'msg': f"{user} joined"},
        room=room
    )

@socketio.on('send_message')
def handle_message(data):
    room = data['room']
    sender_name = data['user']
    message = data['message']

    emit('receive_message', {
        'user': sender_name,
        'msg': message
    }, room=room)


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

if __name__ == "__main__":
    init_db()
