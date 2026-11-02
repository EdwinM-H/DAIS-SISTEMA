import os
from datetime import timedelta

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

CLAVE_DESARROLLO = "clave-solo-para-desarrollo"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or CLAVE_DESARROLLO
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///dais.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")          # temporales de importacion
    GENERATED_FOLDER = os.path.join(BASE_DIR, "generated")     # fichas Word generadas
    STORAGE_FOLDER = os.path.join(BASE_DIR, "storage")         # archivos de docentes/tesis
    DATA_FOLDER = os.path.join(BASE_DIR, "data")               # plantilla y Excel oficial
    MAX_CONTENT_LENGTH = 15 * 1024 * 1024

    EXTENSIONES_IMPORTACION = {"xlsx", "csv"}
    EXTENSIONES_DOCUMENTOS = {"pdf", "doc", "docx", "jpg", "jpeg", "png"}

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_TIME_LIMIT = None

    # Contrasena inicial de la cuenta 'admin' creada por `flask init-db`.
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test"


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
