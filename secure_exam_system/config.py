import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = "secure_exam_secret"

    # ✅ FORCE DB INTO instance/
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "instance", "database.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

    GOOGLE_CLIENT_ID = "YOUR_GOOGLE_CLIENT_ID"
    GOOGLE_CLIENT_SECRET = "YOUR_GOOGLE_CLIENT_SECRET"
