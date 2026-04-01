# config.py
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Base de datos
    DB_SERVER = os.getenv('DB_SERVER')
    DB_NAME = os.getenv('DB_NAME')
    DB_USER = os.getenv('DB_USER')
    DB_PASS = os.getenv('DB_PASS')

    # Seguridad
    SECRET_KEY = os.getenv('SECRET_KEY', 'clave_temporal_cambiar')
    SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', 30))
    MAX_LOGIN_ATTEMPTS = int(os.getenv('MAX_LOGIN_ATTEMPTS', 5))

    # Rutas
    BASE_INVENTARIO = os.path.join(os.getcwd(), 'Inventario')

    # Conexión SQL Server
    CONN_STR = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        f"UID={DB_USER};"
        f"PWD={DB_PASS};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
        "Connection Timeout=60;"
    )