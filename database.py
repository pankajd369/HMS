# database.py
import os
import sqlite3
from contextlib import contextmanager

# Path to SQLite DB file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hms.db")


def dict_factory(cursor, row):
    """Return rows as dictionaries instead of tuples."""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def get_connection():
    """Create a new DB connection with foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def get_db():
    """
    Context manager for DB connection.

    Usage:
        with get_db() as conn:
            cur = conn.execute(...)
            rows = cur.fetchall()
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create all tables and insert default admin user if needed."""
    with get_db() as conn:
        cur = conn.cursor()

        # USERS TABLE (for Admin/Doctor/Patient login)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin','doctor','patient')),
                name TEXT,
                contact_info TEXT
            );
            """
        )

        # DEPARTMENT TABLE
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                reg_doctor_count INTEGER DEFAULT 0
            );
            """
        )

        # DOCTOR TABLE
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                specialization TEXT NOT NULL,
                department_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL
            );
            """
        )

        # PATIENT TABLE
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                medical_history TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )

        # APPOINTMENT TABLE
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                date TEXT NOT NULL,  -- ISO format YYYY-MM-DD
                time TEXT NOT NULL,  -- HH:MM
                status TEXT NOT NULL DEFAULT 'Scheduled'
                    CHECK (status IN ('Scheduled','Completed','Cancelled')),
                FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
                FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE,
            "SELECT id FROM users WHERE username = ? AND role = 'admin';",
            ("admin",),
        )
        admin = cur.fetchone()

        if not admin:
            # NOTE: set actual hash from your app (Werkzeug, etc.)
            # For now, using plain text as per app.py logic
            default_admin_hash = "admin123"
            cur.execute(
                """
                INSERT INTO users (username, password_hash, role, name, contact_info)
                VALUES (?, ?, 'admin', ?, ?);
                """,
                ("admin", default_admin_hash, "System Admin", "admin@hospital.com"),
            )


# --------- OPTIONAL HELPER FUNCTIONS (You can use or delete) --------- #

def get_user_by_username(username: str):
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM users WHERE username = ?;",
            (username,),
        )
        return cur.fetchone()


def get_user_by_id(user_id: int):
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM users WHERE id = ?;",
            (user_id,),
        )
        return cur.fetchone()


def create_patient_user(username, password_hash, name, contact_info=""):
    """
    Create user with role='patient' and related entry in patients table.
    Returns patient_id.
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (username, password_hash, role, name, contact_info)
            VALUES (?, ?, 'patient', ?, ?);
            """,
            (username, password_hash, name, contact_info),
        )
        user_id = cur.lastrowid

        cur.execute(
            "INSERT INTO patients (user_id, medical_history) VALUES (?, ?);",
            (user_id, ""),
        )
        patient_id = cur.lastrowid
        return patient_id


def create_doctor_user(username, password_hash, name, contact_info, specialization, department_id=None):
    """
    Create user with role='doctor' and related entry in doctors table.
    Returns doctor_id.
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (username, password_hash, role, name, contact_info)
            VALUES (?, ?, 'doctor', ?, ?);
            """,
            (username, password_hash, name, contact_info),
        )
        user_id = cur.lastrowid

        cur.execute(
            """
            INSERT INTO doctors (user_id, specialization, department_id)
            VALUES (?, ?, ?);
            """,
            (user_id, specialization, department_id),
        )
        doctor_id = cur.lastrowid
        return doctor_id


def create_appointment(patient_id, doctor_id, date_str, time_str):
    """
    Create a new appointment if not duplicate.
    Duplicate rule enforced by UNIQUE constraint.
    """
    with get_db() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO appointments (patient_id, doctor_id, date, time, status)
                VALUES (?, ?, ?, ?, 'Scheduled');
                """,
                (patient_id, doctor_id, date_str, time_str),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError as e:
            # could be duplicate (unique constraint) or FK error
            raise e


def update_appointment_status(appointment_id, status):
    with get_db() as conn:
        conn.execute(
            "UPDATE appointments SET status = ? WHERE id = ?;",
            (status, appointment_id),
        )


def add_or_update_treatment(appointment_id, diagnosis, prescription, notes=""):
    """
    Insert or update treatment for a given appointment.
    Also can be used to store diagnosis/prescription after completion.
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM treatments WHERE appointment_id = ?;",
            (appointment_id,),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE treatments
                SET diagnosis = ?, prescription = ?, notes = ?
                WHERE appointment_id = ?;
                """,
                (diagnosis, prescription, notes, appointment_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO treatments (appointment_id, diagnosis, prescription, notes)
                VALUES (?, ?, ?, ?);
                """,
                (appointment_id, diagnosis, prescription, notes),
            )

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
