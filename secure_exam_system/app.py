from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
import sqlite3
import os
from datetime import datetime, timedelta
import smtplib
from email.message import EmailMessage
import random
from pypdf import PdfReader, PdfWriter

app = Flask(__name__)
app.secret_key = "secureexam_secret_key"

# ---------------- EMAIL CONFIG ----------------
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

UNIVERSITY_EMAIL = "secureexam.university@gmail.com"
EMAIL_PASSWORD = "zyryoobjqmutcbdq"

# ---------------- PATHS ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "instance", "database.db")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads", "encrypted_papers")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------- PDF ENCRYPTION ----------------
def encrypt_pdf(input_path, output_path, new_password, old_password=None):
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(input_path)

    # 🔓 Step 1: Decrypt if PDF is protected
    if reader.is_encrypted:
        if not old_password:
            raise ValueError("Original PDF password required")

        if reader.decrypt(old_password) == 0:
            raise ValueError("Wrong original PDF password")

    # 🔐 Step 2: Re-encrypt with admin password
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    writer.encrypt(new_password)

    with open(output_path, "wb") as f:
        writer.write(f)

# ---------------- DATABASE ----------------
def get_db():
    conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS colleges (
            id INTEGER PRIMARY KEY,
            college_name TEXT NOT NULL,
            stream TEXT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            centre_code TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY,
            course_type TEXT,
            stream TEXT,
            course TEXT,
            specialization TEXT,
            semester TEXT,
            paper_name TEXT NOT NULL,
            pdf_password TEXT,
            filename TEXT NOT NULL,
            unlock_time DATETIME NOT NULL,
            centres TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS paper_centres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER,
            college_id INTEGER
        )
    """)

    # ---------------- AUDIT LOGS TABLE ----------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_type TEXT NOT NULL,
            user_id INTEGER,
            user_name TEXT,
            user_email TEXT,
            action TEXT NOT NULL,
            paper_id INTEGER,
            paper_name TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ---------------- UNIVERSITY ADMIN TABLE ----------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS university_admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # Ensure default admin exists
    cursor.execute("SELECT * FROM university_admin WHERE email=?", (UNIVERSITY_EMAIL,))
    admin = cursor.fetchone()

    if not admin:
        cursor.execute(
            "INSERT INTO university_admin (email, password) VALUES (?, ?)",
            (UNIVERSITY_EMAIL, "admin123")
        )

    db.commit()
    db.close()

init_db()

# ---------------- AUDIT LOG FUNCTION ----------------
def add_log(user_type, action, user_id=None, user_name=None, user_email=None, paper_id=None, paper_name=None):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO audit_logs (user_type, user_id, user_name, user_email, action, paper_id, paper_name, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_type,
        user_id,
        user_name,
        user_email,
        action,
        paper_id,
        paper_name,
        datetime.now().isoformat()
    ))

    db.commit()
    db.close()

# ---------------- EMAIL SENDER (PAPER UPLOAD) ----------------
def send_paper_upload_email(paper_name, unlock_time, course_type, stream, course, specialization, semester, pdf_password, selected_centres):
    if not selected_centres:
        return
    db = get_db()
    cursor = db.cursor()
    query = f"""
        SELECT college_name, email FROM colleges
        WHERE id IN ({','.join(['?']*len(selected_centres))})
    """
    cursor.execute(query, selected_centres)
    colleges = cursor.fetchall()
    db.close()

    for college in colleges:
        msg = EmailMessage()
        msg["Subject"] = "📄 New Exam Paper Uploaded"
        msg["From"] = UNIVERSITY_EMAIL
        msg["To"] = college["email"]

        msg.set_content(f"""
Dear {college['college_name']},

A new examination paper has been uploaded by the university.

Course Type: {course_type}
Stream: {stream}
Course: {course}
Specialization: {specialization}
Semester: {semester}

Paper Name: {paper_name}
Unlock Time: {unlock_time.strftime('%d %B %Y, %I:%M %p')}

📌 PDF Password: {pdf_password}

The paper will be available for download 30 minutes before the exam.

Please login to the Secure Exam System to download it once unlocked.

Regards,
University Examination Cell
""")

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(UNIVERSITY_EMAIL, EMAIL_PASSWORD)
            server.send_message(msg)

# ---------------- OTP EMAIL SENDER ----------------
def send_otp_email(to_email, otp_code, user_type="User"):
    msg = EmailMessage()
    msg["Subject"] = f"🔐 SecureExam OTP Verification ({user_type})"
    msg["From"] = UNIVERSITY_EMAIL
    msg["To"] = to_email

    msg.set_content(f"""
Hello,

Your OTP for SecureExam login is:

OTP: {otp_code}

This OTP is valid for 2 minutes.

If you did not request this login, please ignore this email.

Regards,
SecureExam System
""")

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(UNIVERSITY_EMAIL, EMAIL_PASSWORD)
        server.send_message(msg)

# ---------------- HOME ----------------
@app.route("/")
def home():
    return render_template("landing.html")

# =========================================================
#                 COLLEGE LOGIN + OTP
# =========================================================

# ---------------- COLLEGE AUTH ----------------
@app.route("/college-auth", methods=["GET", "POST"])
def college_auth():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "SELECT * FROM colleges WHERE email=? AND password=?",
            (email, password)
        )
        college = cursor.fetchone()
        db.close()

        if college:
            # Store pending login data in session
            session["pending_college_id"] = college["id"]
            session["pending_college_email"] = college["email"]
            session["pending_college_name"] = college["college_name"]
            session["pending_college_stream"] = college["stream"]
            session["pending_centre_code"] = college["centre_code"]

            # Generate OTP
            otp = str(random.randint(100000, 999999))
            session["college_otp"] = otp
            session["college_otp_expiry"] = (datetime.now() + timedelta(minutes=2)).isoformat()

            # Send OTP
            send_otp_email(college["email"], otp, user_type="College")

            return redirect(url_for("college_otp_verify"))

        return render_template("college_login.html", error="Invalid credentials")

    return render_template("college_login.html")

# ---------------- COLLEGE OTP VERIFY ----------------
@app.route("/college-otp", methods=["GET", "POST"])
def college_otp_verify():
    if "pending_college_id" not in session:
        return redirect(url_for("college_auth"))

    if request.method == "POST":
        entered_otp = request.form["otp"]

        saved_otp = session.get("college_otp")
        expiry_time = session.get("college_otp_expiry")

        if not saved_otp or not expiry_time:
            return render_template("college_otp.html", error="OTP expired. Please login again.")

        if datetime.now() > datetime.fromisoformat(expiry_time):
            return render_template("college_otp.html", error="OTP expired. Please login again.")

        if entered_otp != saved_otp:
            return render_template("college_otp.html", error="Invalid OTP. Try again.")

        college_email = session.get("pending_college_email")

        # OTP correct → Final login success
        session["college_id"] = session["pending_college_id"]
        session["college_name"] = session["pending_college_name"]
        session["college_stream"] = session["pending_college_stream"]
        session["centre_code"] = session["pending_centre_code"]

        # ADD THIS
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT centre_code FROM colleges WHERE id=?", (session["pending_college_id"],))
        result = cursor.fetchone()
        db.close()

        if result:
            session["centre_code"] = result["centre_code"]

        # LOG: College login
        add_log(
            user_type="College",
            action="College Login Successful",
            user_id=session["college_id"],
            user_name=session["college_name"],
            user_email=college_email
        )

        # Remove pending session data
        session.pop("pending_college_id", None)
        session.pop("pending_college_email", None)
        session.pop("pending_college_name", None)
        session.pop("pending_college_stream", None)
        session.pop("pending_centre_code", None)
        session.pop("college_otp", None)
        session.pop("college_otp_expiry", None)

        return redirect(url_for("college_dashboard"))

    return render_template("college_otp.html")

# ---------------- RESEND COLLEGE OTP ----------------
@app.route("/resend-college-otp")
def resend_college_otp():
    if "pending_college_email" not in session:
        return redirect(url_for("college_auth"))

    otp = str(random.randint(100000, 999999))
    session["college_otp"] = otp
    session["college_otp_expiry"] = (datetime.now() + timedelta(minutes=2)).isoformat()

    send_otp_email(session["pending_college_email"], otp, user_type="College")

    return redirect(url_for("college_otp_verify"))

@app.route("/college-forgot-password", methods=["GET", "POST"])
def college_forgot_password():
    if request.method == "POST":
        email = request.form["email"]

        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM colleges WHERE email=?", (email,))
        college = cursor.fetchone()
        db.close()

        if not college:
            return render_template("college_forgot_password.html", error="Email not found")

        session["reset_college_email"] = email
        session["reset_college_id"] = college["id"]

        otp = str(random.randint(100000, 999999))
        session["reset_college_otp"] = otp
        session["reset_college_otp_expiry"] = (datetime.now() + timedelta(minutes=2)).isoformat()

        send_otp_email(email, otp, user_type="College Password Reset")

        return redirect(url_for("college_reset_otp"))

    return render_template("college_forgot_password.html")

@app.route("/college-reset-otp", methods=["GET", "POST"])
def college_reset_otp():
    if "reset_college_email" not in session:
        return redirect(url_for("college_forgot_password"))

    if request.method == "POST":
        entered_otp = request.form["otp"]

        saved_otp = session.get("reset_college_otp")
        expiry_time = session.get("reset_college_otp_expiry")

        if not saved_otp or not expiry_time:
            return render_template("college_reset_otp.html", error="OTP expired. Try again.")

        if datetime.now() > datetime.fromisoformat(expiry_time):
            return render_template("college_reset_otp.html", error="OTP expired. Try again.")

        if entered_otp != saved_otp:
            return render_template("college_reset_otp.html", error="Invalid OTP")

        session["college_reset_verified"] = True
        return redirect(url_for("college_set_new_password"))

    return render_template("college_reset_otp.html")

@app.route("/college-set-new-password", methods=["GET", "POST"])
def college_set_new_password():
    if "college_reset_verified" not in session:
        return redirect(url_for("college_forgot_password"))

    if request.method == "POST":
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if new_password != confirm_password:
            return render_template("college_set_new_password.html", error="Passwords do not match")

        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE colleges SET password=? WHERE id=?",
            (new_password, session.get("reset_college_id"))
        )
        db.commit()
        db.close()

        # LOG
        add_log(
            user_type="College",
            action="College Password Reset Successful",
            user_id=session.get("reset_college_id"),
            user_email=session.get("reset_college_email")
        )

        # Clear reset session
        session.pop("reset_college_email", None)
        session.pop("reset_college_id", None)
        session.pop("reset_college_otp", None)
        session.pop("reset_college_otp_expiry", None)
        session.pop("college_reset_verified", None)

        return render_template("college_set_new_password.html", success="Password updated successfully")

    return render_template("college_set_new_password.html")

# ---------------- COLLEGE REGISTER ----------------
@app.route("/college-register", methods=["POST"])
def college_register():
    college_name = request.form["college_name"]
    stream = request.form["stream"]
    email = request.form["email"]
    password = request.form["password"]
    centre_code = request.form["centre_code"]

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute("""
            INSERT INTO colleges (college_name, stream, email, password, centre_code)
            VALUES (?, ?, ?, ?, ?)
        """, (college_name, stream, email, password, centre_code))

        db.commit()

    except sqlite3.IntegrityError:
        return render_template("college_login.html", error="College already registered")

    except Exception as e:
        return str(e)

    finally:
        db.close()

    return redirect(url_for("college_auth"))

# ---------------- COLLEGE DASHBOARD ----------------
@app.route("/college-dashboard")
def college_dashboard():
    if "college_id" not in session:
        return redirect(url_for("college_auth"))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, paper_name, filename, unlock_time, pdf_password, centres
        FROM papers
        WHERE stream = ?
        ORDER BY unlock_time DESC
    """, (session.get("college_stream"),))
    papers = cursor.fetchall()
    db.close()

    formatted_papers = []

    for paper in papers:
        paper = dict(paper)

    # CHECK USING paper_centres
        db2 = get_db()
        cursor2 = db2.cursor()

        cursor2.execute("""
            SELECT 1 FROM paper_centres
            WHERE paper_id=? AND college_id=?
        """, (paper["id"], session.get("college_id")))

        allowed = cursor2.fetchone()
        db2.close()

        if not allowed:
            if paper.get("centres"):
                allowed_centres = [c.strip() for c in paper["centres"].split(",")]
                college_centre = str(session.get("centre_code")).strip()

                if college_centre not in allowed_centres:
                    continue
            else:
                continue

        paper["unlock_time"] = datetime.fromisoformat(paper["unlock_time"])
        formatted_papers.append(paper)

    return render_template(
        "college_dashboard.html",
        papers=formatted_papers,
        now=datetime.now(),
        college_name=session.get("college_name")
    )

#-----------------UNIVERSITY LOGIN--------------------
@app.route("/university-login", methods=["GET", "POST"])
def university_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        db = get_db()
        cursor = db.cursor()

        cursor.execute("SELECT * FROM university_admin WHERE email=? AND password=?", (email, password))
        admin = cursor.fetchone()
        db.close()

        if admin:
            session["pending_university_email"] = email

            otp = str(random.randint(100000, 999999))
            session["university_otp"] = otp
            session["university_otp_expiry"] = (datetime.now() + timedelta(minutes=2)).isoformat()

            send_otp_email(email, otp, user_type="University Admin")

            return redirect(url_for("university_otp_verify"))

        return render_template("university_login.html", error="Invalid credentials")

    return render_template("university_login.html")

#--------------------- Verify OTP ----------------
@app.route("/university-otp", methods=["GET", "POST"])
def university_otp_verify():
    if "pending_university_email" not in session:
        return redirect(url_for("university_login"))

    if request.method == "POST":
        entered_otp = request.form["otp"]

        saved_otp = session.get("university_otp")
        expiry_time = session.get("university_otp_expiry")

        if not saved_otp or not expiry_time:
            return render_template("university_otp.html", error="OTP expired. Please login again.")

        if datetime.now() > datetime.fromisoformat(expiry_time):
            return render_template("university_otp.html", error="OTP expired. Please login again.")

        if entered_otp != saved_otp:
            return render_template("university_otp.html", error="Invalid OTP. Try again.")

        # OTP correct → Final login success
        session["university_admin"] = True

        # LOG: University login
        add_log(
            user_type="University",
            action="University Login Successful",
            user_email=session.get("pending_university_email")
        )

        session.pop("pending_university_email", None)
        session.pop("university_otp", None)
        session.pop("university_otp_expiry", None)

        return redirect(url_for("university_dashboard"))

    return render_template("university_otp.html")

#---------------- Resend University OTP -----------------
@app.route("/resend-university-otp")
def resend_university_otp():
    if "pending_university_email" not in session:
        return redirect(url_for("university_login"))

    otp = str(random.randint(100000, 999999))
    session["university_otp"] = otp
    session["university_otp_expiry"] = (datetime.now() + timedelta(minutes=2)).isoformat()

    send_otp_email(session["pending_university_email"], otp, user_type="University Admin")

    return redirect(url_for("university_otp_verify"))

# =========================================================
#       UNIVERSITY CHANGE PASSWORD + FORGOT PASSWORD
# =========================================================

@app.route("/university-change-password", methods=["GET", "POST"])
def university_change_password():
    if "university_admin" not in session:
        return redirect(url_for("university_login"))

    db = get_db()
    cursor = db.cursor()

    if request.method == "POST":
        current_password = request.form["current_password"]
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        cursor.execute("SELECT * FROM university_admin WHERE email=?", (UNIVERSITY_EMAIL,))
        admin = cursor.fetchone()

        if not admin:
            db.close()
            return render_template("university_change_password.html", error="Admin account not found.")

        if current_password != admin["password"]:
            db.close()
            return render_template("university_change_password.html", error="Current password is incorrect.")

        if new_password != confirm_password:
            db.close()
            return render_template("university_change_password.html", error="Passwords do not match.")

        cursor.execute(
            "UPDATE university_admin SET password=? WHERE email=?",
            (new_password, UNIVERSITY_EMAIL)
        )
        db.commit()
        db.close()

        add_log(
            user_type="University",
            action="University Password Changed",
            user_email=UNIVERSITY_EMAIL
        )

        return render_template("university_change_password.html", success="Password updated successfully!")

    db.close()
    return render_template("university_change_password.html")


@app.route("/university-forgot-password", methods=["GET", "POST"])
def university_forgot_password():
    if request.method == "POST":
        email = request.form["email"]

        if email != UNIVERSITY_EMAIL:
            return render_template("university_forgot_password.html", error="Invalid university admin email.")

        session["forgot_university_email"] = email

        otp = str(random.randint(100000, 999999))
        session["forgot_university_otp"] = otp
        session["forgot_university_otp_expiry"] = (datetime.now() + timedelta(minutes=2)).isoformat()

        send_otp_email(email, otp, user_type="University Forgot Password")

        return redirect(url_for("university_reset_otp"))

    return render_template("university_forgot_password.html")


@app.route("/university-reset-otp", methods=["GET", "POST"])
def university_reset_otp():
    if "forgot_university_email" not in session:
        return redirect(url_for("university_forgot_password"))

    if request.method == "POST":
        entered_otp = request.form["otp"]

        saved_otp = session.get("forgot_university_otp")
        expiry_time = session.get("forgot_university_otp_expiry")

        if not saved_otp or not expiry_time:
            return render_template("university_reset_otp.html", error="OTP expired. Please try again.")

        if datetime.now() > datetime.fromisoformat(expiry_time):
            return render_template("university_reset_otp.html", error="OTP expired. Please try again.")

        if entered_otp != saved_otp:
            return render_template("university_reset_otp.html", error="Invalid OTP.")

        session["forgot_university_verified"] = True
        return redirect(url_for("university_set_new_password"))

    return render_template("university_reset_otp.html")


@app.route("/university-set-new-password", methods=["GET", "POST"])
def university_set_new_password():
    if not session.get("forgot_university_verified"):
        return redirect(url_for("university_forgot_password"))

    if request.method == "POST":
        new_password = request.form["new_password"]
        confirm_password = request.form["confirm_password"]

        if new_password != confirm_password:
            return render_template("university_set_new_password.html", error="Passwords do not match.")

        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            "UPDATE university_admin SET password=? WHERE email=?",
            (new_password, UNIVERSITY_EMAIL)
        )
        db.commit()
        db.close()

        add_log(
            user_type="University",
            action="University Password Reset (Forgot Password)",
            user_email=UNIVERSITY_EMAIL
        )

        session.pop("forgot_university_email", None)
        session.pop("forgot_university_otp", None)
        session.pop("forgot_university_otp_expiry", None)
        session.pop("forgot_university_verified", None)

        return redirect(url_for("university_login"))

    return render_template("university_set_new_password.html")


@app.route("/resend-forgot-university-otp")
def resend_forgot_university_otp():
    if "forgot_university_email" not in session:
        return redirect(url_for("university_forgot_password"))

    otp = str(random.randint(100000, 999999))
    session["forgot_university_otp"] = otp
    session["forgot_university_otp_expiry"] = (datetime.now() + timedelta(minutes=2)).isoformat()

    send_otp_email(session["forgot_university_email"], otp, user_type="University Forgot Password")

    return redirect(url_for("university_reset_otp"))

# ---------------- UNIVERSITY DASHBOARD ----------------
@app.route("/university-dashboard", methods=["GET", "POST"])
def university_dashboard():
    if "university_admin" not in session:
        return redirect(url_for("university_login"))

    db = get_db()
    cursor = db.cursor()

    if request.method == "POST":
        paper_name = request.form["paper_name"]
        course_type = request.form["course_type"]
        stream = request.form["stream"]
        course = request.form["course"]
        specialization = request.form["specialization"]
        semester = request.form["semester"]
        pdf_password = request.form["pdf_password"]
        original_password = request.form.get("original_pdf_password")

        selected_centres = request.form.getlist("centres")

        #convert college IDs → centre codes
        centres_list = []

        for cid in selected_centres:
            cursor.execute("SELECT centre_code FROM colleges WHERE id=?", (int(cid),))
            result = cursor.fetchone()

            print("CID:", cid, "→ DB Result:", result)   # DEBUG

            if result and result["centre_code"]:
                centres_list.append(str(result["centre_code"]))

        centres_str = ",".join(centres_list)

        # DEBUG
        print("Selected IDs:", selected_centres)
        print("Converted Centre Codes:", centres_list)
        print("Final centres_str:", centres_str)

        files = request.files.getlist("paper")
        exam_time = request.form["exam_time"]

        exam_datetime = datetime.fromisoformat(exam_time)
        if exam_datetime <= datetime.now():
            return "Exam date must be in the future.", 400

        if not files or len(files) < 1:
            return "Please upload at least 1 PDF", 400

        if len(files) > 5:
            return "Maximum 5 PDFs allowed", 400

        unlock_time = exam_datetime - timedelta(minutes=30)

        for file in files:
            if file and file.filename.lower().endswith(".pdf"):

                temp_path = os.path.join(UPLOAD_FOLDER, file.filename)
                file.save(temp_path)

                encrypted_filename = f"encrypted_{file.filename}"
                encrypted_path = os.path.join(UPLOAD_FOLDER, encrypted_filename)

                try:
                    encrypt_pdf(temp_path, encrypted_path, pdf_password, original_password)
                except Exception as e:
                    return f"PDF Error: {str(e)}", 400

                if os.path.exists(temp_path):
                    os.remove(temp_path)

                cursor.execute("""
                    INSERT INTO papers (
                        paper_name, pdf_password, filename, unlock_time,
                        course_type, stream, course, specialization, semester, centres
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    paper_name,
                    pdf_password,
                    encrypted_filename,
                    unlock_time,
                    course_type,
                    stream,
                    course,
                    specialization,
                    semester,
                    centres_str 
                ))

        db.commit()

        add_log(
            user_type="University",
            action="Paper Uploaded",
            user_email=UNIVERSITY_EMAIL,
            paper_name=paper_name
        )

        send_paper_upload_email(
            paper_name, unlock_time,
            course_type, stream, course, specialization, semester,
            pdf_password,
            selected_centres
        )

    cursor.execute("SELECT * FROM papers ORDER BY id DESC")
    papers = cursor.fetchall()

    cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC")
    logs = cursor.fetchall()

    cursor.execute("SELECT id, college_name, centre_code FROM colleges")
    colleges = cursor.fetchall()

    db.close()

    return render_template(
        "university_dashboard.html",
        papers=papers,
        logs=logs,
        colleges=colleges
    )

# ---------------- DELETE PAPER ----------------
@app.route("/delete-paper/<int:paper_id>", methods=["POST"])
def delete_paper(paper_id):
    if "university_admin" not in session:
        return redirect(url_for("university_login"))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT filename, paper_name FROM papers WHERE id=?", (paper_id,))
    paper = cursor.fetchone()

    if paper:
        file_path = os.path.join(UPLOAD_FOLDER, paper["filename"])
        if os.path.exists(file_path):
            os.remove(file_path)

        cursor.execute("DELETE FROM papers WHERE id=?", (paper_id,))
        db.commit()

        # LOG: Paper deleted
        add_log(
            user_type="University",
            action="Paper Deleted",
            user_email=UNIVERSITY_EMAIL,
            paper_id=paper_id,
            paper_name=paper["paper_name"]
        )

    db.close()
    return redirect(url_for("university_dashboard"))

# ---------------- DOWNLOAD PAPER ----------------
@app.route("/download/<int:paper_id>")
def download_paper(paper_id):
    if "college_id" not in session:
        return redirect(url_for("college_auth"))

    db = get_db()
    cursor = db.cursor()

    # Get paper
    cursor.execute("""
        SELECT filename, unlock_time, stream, paper_name
        FROM papers
        WHERE id=?
    """, (paper_id,))
    paper = cursor.fetchone()

    if not paper:
        db.close()
        return "Paper not found", 404

    # 🔥CHECK ACCESS USING paper_centres TABLE
    cursor.execute("""
        SELECT * FROM paper_centres
        WHERE paper_id=? AND college_id=?
    """, (paper_id, session.get("college_id")))

    allowed = cursor.fetchone()

    if not allowed:
        cursor.execute("SELECT centres FROM papers WHERE id=?", (paper_id,))
        centres_data = cursor.fetchone()

        if centres_data and centres_data["centres"]:
            allowed_centres = [c.strip() for c in centres_data["centres"].split(",")]
            college_centre = str(session.get("centre_code")).strip()

            if college_centre not in allowed_centres:
                db.close()
                return "Unauthorized access (Not assigned to your college)", 403
        else:
            db.close()
            return "No centres assigned to this paper", 403

    db.close()

    # Check unlock time
    if datetime.now() < datetime.fromisoformat(paper["unlock_time"]):
        return "Paper is locked", 403

    # LOG
    add_log(
        user_type="College",
        action="Paper Downloaded",
        user_id=session.get("college_id"),
        user_name=session.get("college_name"),
        paper_id=paper_id,
        paper_name=paper["paper_name"]
    )

    return send_from_directory(
        UPLOAD_FOLDER,
        paper["filename"],
        as_attachment=True
    )
# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    # LOG: Logout
    if session.get("college_id"):
        add_log(
            user_type="College",
            action="College Logout",
            user_id=session.get("college_id"),
            user_name=session.get("college_name")
        )

    if session.get("university_admin"):
        add_log(
            user_type="University",
            action="University Logout",
            user_email=UNIVERSITY_EMAIL
        )

    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)
