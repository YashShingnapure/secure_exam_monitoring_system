from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin / college
    college_name = db.Column(db.String(200), nullable=True)


class Paper(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(200), nullable=False)
    exam_date = db.Column(db.Date, nullable=False)
    exam_time = db.Column(db.String(50), nullable=False)
    file_name = db.Column(db.String(300))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
