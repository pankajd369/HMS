from flask import Flask, render_template, request, redirect, session, flash, g, url_for
import sqlite3
from functools import wraps
import datetime
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
DATABASE = 'hms.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to access this page.')
                return redirect(url_for('login'))
            
            if role and session.get('role') != role:
                flash('Access denied.')
                return redirect(url_for('home'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def home():
    user = None
    if 'user_id' in session:
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    return render_template('base.html', user=user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user and user['password_hash'] == password:
             session['user_id'] = user['id']
             session['role'] = user['role']
             session['name'] = user['name']
             return redirect(url_for(f"{user['role']}_dashboard"))
        else:
             flash('Invalid credentials')
             
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        name = request.form['name']
        contact = request.form['contact']
        
        db = get_db()
        try:
            cur = db.execute('INSERT INTO users (username, password_hash, role, name, contact_info) VALUES (?, ?, ?, ?, ?)',
                       (username, password, 'patient', name, contact))
            user_id = cur.lastrowid
            
            db.execute('INSERT INTO patients (user_id, medical_history) VALUES (?, ?)', (user_id, ''))
            db.commit()
            flash('Registration successful')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists')
            
    return render_template('register.html')

# Admin Routes
@app.route('/admin/dashboard')
@login_required('admin')
def admin_dashboard():
    db = get_db()
    doctor_count = db.execute('SELECT COUNT(*) FROM doctors').fetchone()[0]
    patient_count = db.execute('SELECT COUNT(*) FROM patients').fetchone()[0]
    appointment_count = db.execute('SELECT COUNT(*) FROM appointments').fetchone()[0]
    return render_template('admin_dashboard.html', 
                         doctor_count=doctor_count, 
                         patient_count=patient_count, 
                         appointment_count=appointment_count)

@app.route('/admin/doctors', methods=['GET', 'POST'])
@login_required('admin')
def manage_doctors():
    db = get_db()
    if request.method == 'POST':
        username = request.form['username']
        name = request.form['name']
        contact = request.form['contact']
        specialization = request.form['specialization']
        password = request.form['password']
        
        try:
            cur = db.execute('INSERT INTO users (username, password_hash, role, name, contact_info) VALUES (?, ?, ?, ?, ?)',
                       (username, password, 'doctor', name, contact))
            user_id = cur.lastrowid
            cur_doc = db.execute('INSERT INTO doctors (user_id, specialization) VALUES (?, ?)', (user_id, specialization))
            doctor_id = cur_doc.lastrowid
            
            # Handle default shift if provided
            start_time = request.form.get('start_time')
            end_time = request.form.get('end_time')
            if start_time and end_time:
                today = datetime.date.today()
                for i in range(7):
                    date_str = (today + datetime.timedelta(days=i)).isoformat()
                    db.execute('INSERT INTO availability (doctor_id, date, start_time, end_time) VALUES (?, ?, ?, ?)',
                               (doctor_id, date_str, start_time, end_time))
            
            db.commit()
        except sqlite3.IntegrityError:
            flash('Username exists')
            
    specialization = request.args.get('specialization')
    if specialization:
        doctors = db.execute('SELECT d.id, u.name, u.username, d.specialization FROM doctors d JOIN users u ON d.user_id = u.id WHERE d.specialization LIKE ?', (f'%{specialization}%',)).fetchall()
    else:
        doctors = db.execute('SELECT d.id, u.name, u.username, d.specialization FROM doctors d JOIN users u ON d.user_id = u.id').fetchall()
    return render_template('manage_doctors.html', doctors=doctors)

@app.route('/admin/doctor/edit/<int:doctor_id>', methods=['GET', 'POST'])
@login_required('admin')
def edit_doctor(doctor_id):
    db = get_db()
    if request.method == 'POST':
        if 'update_details' in request.form:
            name = request.form['name']
            contact = request.form['contact']
            specialization = request.form['specialization']
            
            doctor = db.execute('SELECT user_id FROM doctors WHERE id = ?', (doctor_id,)).fetchone()
            db.execute('UPDATE users SET name = ?, contact_info = ? WHERE id = ?', (name, contact, doctor['user_id']))
            db.execute('UPDATE doctors SET specialization = ? WHERE id = ?', (specialization, doctor_id))
            db.commit()
            flash('Doctor details updated')
        
        elif 'update_availability' in request.form:
            today = datetime.date.today()
            db.execute('DELETE FROM availability WHERE doctor_id = ? AND date >= ?', (doctor_id, today))
            
            for i in range(7):
                date_str = (today + datetime.timedelta(days=i)).isoformat()
                start_time = request.form.get(f'start_time_{i}')
                end_time = request.form.get(f'end_time_{i}')
                
                if start_time and end_time:
                    db.execute('INSERT INTO availability (doctor_id, date, start_time, end_time) VALUES (?, ?, ?, ?)',
                               (doctor_id, date_str, start_time, end_time))
            db.commit()
            flash('Availability updated')
            
        return redirect(url_for('edit_doctor', doctor_id=doctor_id))
        
    doctor = db.execute('SELECT d.id, u.name, u.contact_info, d.specialization FROM doctors d JOIN users u ON d.user_id = u.id WHERE d.id = ?', (doctor_id,)).fetchone()
    
    # Get availability for editing
    today = datetime.date.today()
    dates = []
    for i in range(7):
        date = today + datetime.timedelta(days=i)
        dates.append(date)
        
    availability = db.execute('SELECT * FROM availability WHERE doctor_id = ? AND date >= ?', (doctor_id, today)).fetchall()
    avail_dict = {row['date']: row for row in availability}
    
    return render_template('edit_doctor.html', doctor=doctor, dates=dates, avail_dict=avail_dict)

@app.route('/admin/doctor/delete/<int:doctor_id>')
@login_required('admin')
def delete_doctor(doctor_id):
    db = get_db()
    # Get user_id to delete from users table too
    doctor = db.execute('SELECT user_id FROM doctors WHERE id = ?', (doctor_id,)).fetchone()
    if doctor:
        db.execute('DELETE FROM doctors WHERE id = ?', (doctor_id,))
        db.execute('DELETE FROM users WHERE id = ?', (doctor['user_id'],))
        db.commit()
    return redirect(url_for('manage_doctors'))

@app.route('/admin/patients', methods=['GET'])
@login_required('admin')
def manage_patients():
    db = get_db()
    search = request.args.get('search')
    if search:
        patients = db.execute('''
            SELECT p.id, u.name, u.username, u.contact_info 
            FROM patients p JOIN users u ON p.user_id = u.id 
            WHERE u.name LIKE ? OR u.contact_info LIKE ? OR u.id LIKE ?
        ''', (f'%{search}%', f'%{search}%', f'%{search}%')).fetchall()
    else:
        patients = db.execute('SELECT p.id, u.name, u.username, u.contact_info FROM patients p JOIN users u ON p.user_id = u.id').fetchall()
    return render_template('manage_patients.html', patients=patients)

@app.route('/admin/patient/edit/<int:patient_id>', methods=['GET', 'POST'])
@login_required('admin')
def edit_patient(patient_id):
    db = get_db()
    if request.method == 'POST':
        name = request.form['name']
        contact = request.form['contact']
        medical_history = request.form['medical_history']
        
        patient = db.execute('SELECT user_id FROM patients WHERE id = ?', (patient_id,)).fetchone()
        db.execute('UPDATE users SET name = ?, contact_info = ? WHERE id = ?', (name, contact, patient['user_id']))
        db.execute('UPDATE patients SET medical_history = ? WHERE id = ?', (medical_history, patient_id))
        db.commit()
        return redirect(url_for('manage_patients'))
        
    patient = db.execute('SELECT p.id, u.name, u.contact_info, p.medical_history FROM patients p JOIN users u ON p.user_id = u.id WHERE p.id = ?', (patient_id,)).fetchone()
    return render_template('edit_patient.html', patient=patient)

@app.route('/admin/patient/delete/<int:patient_id>')
@login_required('admin')
def delete_patient(patient_id):
    db = get_db()
    patient = db.execute('SELECT user_id FROM patients WHERE id = ?', (patient_id,)).fetchone()
    if patient:
        db.execute('DELETE FROM patients WHERE id = ?', (patient_id,))
        db.execute('DELETE FROM users WHERE id = ?', (patient['user_id'],))
        db.commit()
    return redirect(url_for('manage_patients'))

@app.route('/admin/appointments')
@login_required('admin')
def manage_appointments():
    db = get_db()
    appointments = db.execute('''
        SELECT a.id, a.date, a.time, a.status, p_u.name as patient_name, d_u.name as doctor_name
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        JOIN users p_u ON p.user_id = p_u.id
        JOIN doctors d ON a.doctor_id = d.id
        JOIN users d_u ON d.user_id = d_u.id
        ORDER BY a.date DESC
    ''').fetchall()
    
    return render_template('manage_appointments.html', appointments=appointments)

@app.route('/admin/appointment/<int:appointment_id>/cancel')
@login_required('admin')
def admin_cancel_appointment(appointment_id):
    db = get_db()
    db.execute("UPDATE appointments SET status = 'Cancelled' WHERE id = ?", (appointment_id,))
    db.commit()
    flash('Appointment cancelled successfully')
    return redirect(url_for('manage_appointments'))

# Doctor Routes
@app.route('/doctor/dashboard')
@login_required('doctor')
def doctor_dashboard():
    db = get_db()
    doctor = db.execute('SELECT d.id, u.name FROM doctors d JOIN users u ON d.user_id = u.id WHERE u.id = ?', (session['user_id'],)).fetchone()
    
    # Get today's appointments
    today = datetime.date.today().isoformat()
    appointments = db.execute('''
        SELECT a.id, a.date, a.time, a.status, u.name as patient_name, p.id as patient_id
        FROM appointments a 
        JOIN patients p ON a.patient_id = p.id 
        JOIN users u ON p.user_id = u.id 
        WHERE a.doctor_id = ? AND a.date = ?
        ORDER BY a.time
    ''', (doctor['id'], today)).fetchall()
    
    return render_template('doctor_dashboard.html', doctor=doctor, appointments=appointments)

@app.route('/doctor/appointments')
@login_required('doctor')
def doctor_appointments():
    db = get_db()
    doctor = db.execute('SELECT d.id, u.name FROM doctors d JOIN users u ON d.user_id = u.id WHERE u.id = ?', (session['user_id'],)).fetchone()
    
    appointments = db.execute('''
        SELECT a.id, a.date, a.time, a.status, a.treatment_type, u.name as patient_name, p.id as patient_id
        FROM appointments a 
        JOIN patients p ON a.patient_id = p.id 
        JOIN users u ON p.user_id = u.id 
        WHERE a.doctor_id = ?
        ORDER BY a.date DESC, a.time ASC
    ''', (doctor['id'],)).fetchall()
    
    return render_template('doctor_appointments.html', doctor=doctor, appointments=appointments)

@app.route('/doctor/appointment/<int:appointment_id>/status', methods=['POST'])
@login_required('doctor')
def update_appointment_status(appointment_id):
    status = request.form['status']
    db = get_db()
    db.execute('UPDATE appointments SET status = ? WHERE id = ?', (status, appointment_id))
    db.commit()
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/appointment/<int:appointment_id>/treatment', methods=['GET', 'POST'])
@login_required('doctor')
def add_treatment(appointment_id):
    db = get_db()
    if request.method == 'POST':
        treatment_name = request.form.get('treatment_name', '')
        diagnosis = request.form['diagnosis']
        prescription = request.form['prescription']
        notes = request.form['notes']
        
        exists = db.execute('SELECT id FROM treatments WHERE appointment_id = ?', (appointment_id,)).fetchone()
        if exists:
            db.execute('UPDATE treatments SET treatment_name=?, diagnosis=?, prescription=?, notes=? WHERE appointment_id=?',
                       (treatment_name, diagnosis, prescription, notes, appointment_id))
        else:
            db.execute('INSERT INTO treatments (appointment_id, treatment_name, diagnosis, prescription, notes) VALUES (?, ?, ?, ?, ?)',
                       (appointment_id, treatment_name, diagnosis, prescription, notes))
        
        db.execute("UPDATE appointments SET status = 'Completed' WHERE id = ?", (appointment_id,))
        db.commit()
        return redirect(url_for('doctor_dashboard'))
        
    appointment = db.execute('''
        SELECT a.id, a.date, a.time, p_u.name as patient_name, t.treatment_name, t.diagnosis, t.prescription, t.notes
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        JOIN users p_u ON p.user_id = p_u.id
        LEFT JOIN treatments t ON a.id = t.appointment_id
        WHERE a.id = ?
    ''', (appointment_id,)).fetchone()
    
    return render_template('view_treatments.html', appointment=appointment)

@app.route('/doctor/availability', methods=['GET', 'POST'])
@login_required('doctor')
def manage_availability():
    db = get_db()
    doctor = db.execute('SELECT id FROM doctors WHERE user_id = ?', (session['user_id'],)).fetchone()
    
    if request.method == 'POST':
        # Clear existing availability for future dates to avoid complexity for now, or just upsert
        # For simplicity, we'll delete future availability and re-insert
        today = datetime.date.today()
        db.execute('DELETE FROM availability WHERE doctor_id = ? AND date >= ?', (doctor['id'], today))
        
        for i in range(7):
            date_str = (today + datetime.timedelta(days=i)).isoformat()
            start_time = request.form.get(f'start_time_{i}')
            end_time = request.form.get(f'end_time_{i}')
            
            if start_time and end_time:
                db.execute('INSERT INTO availability (doctor_id, date, start_time, end_time) VALUES (?, ?, ?, ?)',
                           (doctor['id'], date_str, start_time, end_time))
        db.commit()
        flash('Availability updated')
        return redirect(url_for('doctor_dashboard'))
        
    # Get current availability
    today = datetime.date.today()
    dates = []
    for i in range(7):
        date = today + datetime.timedelta(days=i)
        dates.append(date)
        
    availability = db.execute('SELECT * FROM availability WHERE doctor_id = ? AND date >= ?', (doctor['id'], today)).fetchall()
    # Convert to dict for easier lookup in template
    avail_dict = {row['date']: row for row in availability}
    
    return render_template('manage_availability.html', dates=dates, avail_dict=avail_dict)

@app.route('/doctor/patient/<int:patient_id>/history')
@login_required('doctor')
def view_patient_history(patient_id):
    db = get_db()
    patient = db.execute('SELECT p.id, u.name, u.contact_info, p.medical_history FROM patients p JOIN users u ON p.user_id = u.id WHERE p.id = ?', (patient_id,)).fetchone()
    
    history = db.execute('''
        SELECT a.date, a.time, a.status, t.treatment_name, t.diagnosis, t.prescription, t.notes, d_u.name as doctor_name
        FROM appointments a
        JOIN doctors d ON a.doctor_id = d.id
        JOIN users d_u ON d.user_id = d_u.id
        LEFT JOIN treatments t ON a.id = t.appointment_id
        WHERE a.patient_id = ? AND a.status = 'Completed'
        ORDER BY a.date DESC
    ''', (patient_id,)).fetchall()
    
    return render_template('patient_history.html', patient=patient, history=history)

# Patient Routes
@app.route('/patient/dashboard')
@login_required('patient')
def patient_dashboard():
    db = get_db()
    patient = db.execute('SELECT p.id, u.name FROM patients p JOIN users u ON p.user_id = u.id WHERE u.id = ?', (session['user_id'],)).fetchone()
    
    appointments = db.execute('''
        SELECT a.id, a.date, a.time, a.status, d_u.name as doctor_name, t.treatment_name, t.diagnosis, t.prescription
        FROM appointments a
        JOIN doctors d ON a.doctor_id = d.id
        JOIN users d_u ON d.user_id = d_u.id
        LEFT JOIN treatments t ON a.id = t.appointment_id
        WHERE a.patient_id = ?
        ORDER BY a.date DESC
    ''', (patient['id'],)).fetchall()
    
    return render_template('patient_dashboard.html', patient=patient, appointments=appointments)

@app.route('/patient/profile', methods=['GET', 'POST'])
@login_required('patient')
def edit_profile():
    db = get_db()
    if request.method == 'POST':
        name = request.form['name']
        contact = request.form['contact']
        medical_history = request.form['medical_history']
        
        patient = db.execute('SELECT id FROM patients WHERE user_id = ?', (session['user_id'],)).fetchone()
        db.execute('UPDATE users SET name = ?, contact_info = ? WHERE id = ?', (name, contact, session['user_id']))
        db.execute('UPDATE patients SET medical_history = ? WHERE id = ?', (medical_history, patient['id']))
        db.commit()
        flash('Profile updated')
        return redirect(url_for('patient_dashboard'))
        
    patient = db.execute('SELECT p.id, u.name, u.contact_info, p.medical_history FROM patients p JOIN users u ON p.user_id = u.id WHERE u.id = ?', (session['user_id'],)).fetchone()
    return render_template('edit_profile.html', patient=patient)

    return render_template('edit_profile.html', patient=patient)

@app.route('/get_availability/<int:doctor_id>')
@login_required()
def get_availability(doctor_id):
    db = get_db()
    today = datetime.date.today()
    availability = db.execute('SELECT date, start_time, end_time FROM availability WHERE doctor_id = ? AND date >= ?', (doctor_id, today)).fetchall()
    return {'availability': [dict(row) for row in availability]}

@app.route('/patient/book', methods=['GET', 'POST'])
@login_required('patient')
def book_appointment():
    db = get_db()
    if request.method == 'POST':
        doctor_id = request.form['doctor_id']
        date = request.form['date']
        time = request.form['time']
        treatment_type = request.form.get('treatment_type', '')
        
        # Check availability
        availability = db.execute('SELECT start_time, end_time FROM availability WHERE doctor_id = ? AND date = ?', (doctor_id, date)).fetchone()
        
        if availability:
            if time < availability['start_time'] or time > availability['end_time']:
                flash(f"Doctor is only available between {availability['start_time']} and {availability['end_time']}")
                return redirect(url_for('book_appointment'))
        # If no availability set, we allow booking (loose check) or could block. 
        # For now, we proceed.

        patient = db.execute('SELECT id FROM patients WHERE user_id = ?', (session['user_id'],)).fetchone()
        
        try:
            db.execute('INSERT INTO appointments (patient_id, doctor_id, date, time, treatment_type) VALUES (?, ?, ?, ?, ?)',
                       (patient['id'], doctor_id, date, time, treatment_type))
            db.commit()
            return redirect(url_for('patient_dashboard'))
        except sqlite3.IntegrityError:
            flash('Slot already booked')
            
    specialization = request.args.get('specialization')
    if specialization:
        doctors = db.execute('SELECT d.id, u.name, d.specialization FROM doctors d JOIN users u ON d.user_id = u.id WHERE d.specialization LIKE ?', (f'%{specialization}%',)).fetchall()
    else:
        doctors = db.execute('SELECT d.id, u.name, d.specialization FROM doctors d JOIN users u ON d.user_id = u.id').fetchall()
    return render_template('book_appointment.html', doctors=doctors, now_date=datetime.date.today())

@app.route('/patient/appointment/<int:appointment_id>/cancel')
@login_required('patient')
def cancel_appointment(appointment_id):
    db = get_db()
    db.execute("UPDATE appointments SET status = 'Cancelled' WHERE id = ?", (appointment_id,))
    db.commit()
    return redirect(url_for('patient_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
