import sqlite3

def migrate():
    conn = sqlite3.connect('hms.db')
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE appointments ADD COLUMN treatment_type TEXT")
        print("Successfully added treatment_type column to appointments table.")
    except sqlite3.OperationalError as e:
        print(f"Error (column might already exist): {e}")
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    migrate()
