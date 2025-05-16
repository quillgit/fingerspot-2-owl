from flask import Flask, request, send_file, render_template, redirect, url_for, session, flash, jsonify
from functools import wraps  # Add this import
import pandas as pd
from io import BytesIO, StringIO
import datetime
import csv
from db_config import get_connection,get_owl_connection

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this to a secure secret key

# Login decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_connection()
        cursor = conn.cursor()
        
        # Check user credentials
        cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", 
                      (username, password))
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['username'] = user[1]
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password')
            return redirect(url_for('login'))
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    return render_template('upload.html')

# Add to all other routes
@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['file']
    df = pd.read_csv(file, sep=';')
    
    # Clean jammasuk and jamkeluar columns by removing spaces
    # df['jammasuk'] = df['jammasuk'].str.strip()
    # df['jamkeluar'] = df['jamkeluar'].str.strip()
    
    # Parse tanggal to datetime
    df['tanggal'] = pd.to_datetime(df['tanggal'])
    
    # Sort tanggal
    tanggal_sorted = sorted(df['tanggal'].unique())

    # Pivot masuk & keluar using pivot_table to handle duplicates
    masuk = df.pivot_table(index='pegawai_nama', columns='tanggal', 
                          values='jammasuk', aggfunc='first')
    keluar = df.pivot_table(index='pegawai_nama', columns='tanggal', 
                           values='jamkeluar', aggfunc='last')

    # MultiIndex Columns
    col_tuples = []
    for t in tanggal_sorted:
        t_str = t.strftime('%Y-%m-%d')
        col_tuples.append((t_str, 'jammasuk'))
        col_tuples.append((t_str, 'jamkeluar'))
    multi_cols = pd.MultiIndex.from_tuples(col_tuples)

    # Combine into one DataFrame
    combined = pd.DataFrame(index=masuk.index, columns=multi_cols)
    for t in tanggal_sorted:
        t_str = t.strftime('%Y-%m-%d')
        # Fix the swapped values by correcting the assignment
        combined[(t_str, 'jamkeluar')] = masuk[t]
        combined[(t_str, 'jammasuk')] = keluar[t]

    # Summary hadir
    hadir_count = masuk.notna().sum(axis=1)
    combined[('Summary', 'Total Hadir')] = hadir_count

    # Sort columns
    combined = combined.sort_index(axis=1, level=0)

    # --- Excel Output ---
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        sheetname = 'Pivot Absensi'
        combined.to_excel(writer, sheet_name=sheetname, startrow=2, merge_cells=False)
        worksheet = writer.sheets[sheetname]

        # Styles
        header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1})
        jam_fmt = workbook.add_format({'align': 'center'})
        red_late_fmt = workbook.add_format({'bg_color': 'red', 'align': 'center'})
        weekend_fmt = workbook.add_format({'bg_color': '#D9D9D9', 'align': 'center'})

        # Write merged headers manually
        worksheet.write(0, 0, 'pegawai_nama', header_fmt)

        col_idx = 1
        for t in tanggal_sorted:
            t_str = t.strftime('%Y-%m-%d')
            worksheet.merge_range(0, col_idx, 0, col_idx + 1, t_str, header_fmt)
            worksheet.write(1, col_idx, 'jammasuk', header_fmt)
            worksheet.write(1, col_idx + 1, 'jamkeluar', header_fmt)
            col_idx += 2

        # Write summary header
        worksheet.merge_range(0, col_idx, 1, col_idx, 'Total Hadir', header_fmt)

        # Freeze headers
        worksheet.freeze_panes(2, 1)

        # Column width
        worksheet.set_column(0, 0, 20)
        worksheet.set_column(1, col_idx, 12)

        # Conditional formatting (Red for late jammasuk)
        for i, t in enumerate(tanggal_sorted):
            col_letter = chr(66 + i*2)  # Get column letter (B, D, F, etc.)
            
            if t.weekday() >= 5:  # Weekend: Saturday(5), Sunday(6)
                worksheet.conditional_format(2, 1 + i * 2, 2 + len(combined), 1 + i * 2 + 1,
                                          {'type': 'no_blanks', 
                                           'format': weekend_fmt})

            # Late if after 09:00 - Using formula-based conditional formatting
            worksheet.conditional_format(2, 1 + i * 2, 2 + len(combined), 1 + i * 2,
                                      {'type': 'formula',
                                       'criteria': f'=AND(NOT(ISBLANK({col_letter}3)),TIME(9,0,0)<TIMEVALUE({col_letter}3))',
                                       'format': red_late_fmt})

    # Get first and last date from tanggal_sorted
    start_date = tanggal_sorted[0].strftime('%Y%m%d')
    end_date = tanggal_sorted[-1].strftime('%Y%m%d')
    
    output.seek(0)
    return send_file(output, 
                    as_attachment=True, 
                    download_name=f'pivot_absensi_{start_date}_to_{end_date}.xlsx',
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/export_csv', methods=['GET', 'POST'])
def export_csv():
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']

        query = """
        SELECT 
            LEFT(al.scan_date,10) AS tanggal,
            pegawai_nama,
            MIN(RIGHT(scan_date,9)) AS jammasuk,
            MAX(RIGHT(scan_date,9)) AS jamkeluar
        FROM att_log al
        LEFT JOIN pegawai p ON p.pegawai_pin = al.pin
        WHERE LEFT(scan_date,10) BETWEEN %s AND %s
        GROUP BY al.pin, tanggal
        """

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(query, (start_date, end_date))
        rows = cursor.fetchall()

        # Create output in text mode instead of binary
        output = StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(['tanggal', 'pegawai_nama', 'jammasuk', 'jamkeluar'])
        writer.writerows(rows)
        
        # Convert to bytes for response
        output_bytes = BytesIO()
        output_bytes.write(output.getvalue().encode('utf-8-sig'))  # utf-8-sig includes BOM
        output_bytes.seek(0)
        
        cursor.close()
        conn.close()

        return send_file(
            output_bytes,
            as_attachment=True,
            download_name=f"absensi_{start_date}_to_{end_date}.csv",
            mimetype='text/csv'
        )

        # After getting the data, automatically process it
        df = pd.DataFrame(rows, columns=['tanggal', 'pegawai_nama', 'jammasuk', 'jamkeluar'])
        
        # Store the data in session for report view
        session['attendance_data'] = df.to_dict('records')
        session['date_range'] = {'start': start_date, 'end': end_date}

        # Redirect to report page
        return redirect(url_for('report'))

    return render_template('export_form.html')

@app.route('/report')
def report():
    if 'attendance_data' not in session:
        return redirect(url_for('export_csv'))

    df = pd.DataFrame(session['attendance_data'])
    
    # Process data for template
    dates = sorted(df['tanggal'].unique())
    employees = df['pegawai_nama'].unique()
    
    data = []
    for emp in employees:
        emp_data = {
            'name': emp,
            'attendance': [],
            'total_present': 0
        }
        
        for date in dates:
            day_data = df[(df['pegawai_nama'] == emp) & (df['tanggal'] == date)].iloc[0] if len(df[(df['pegawai_nama'] == emp) & (df['tanggal'] == date)]) > 0 else {'jammasuk': '', 'jamkeluar': ''}
            
            is_late = False
            if day_data['jammasuk']:
                is_late = pd.to_datetime(day_data['jammasuk']).time() > pd.to_datetime('09:00').time()
                emp_data['total_present'] += 1
            
            emp_data['attendance'].append({
                'in': day_data['jammasuk'],
                'out': day_data['jamkeluar'],
                'is_late': is_late
            })
        
        data.append(emp_data)

    return render_template('report.html', data=data, dates=dates)

@app.route('/export_excel')
def export_excel():
    if 'attendance_data' not in session:
        return redirect(url_for('export_csv'))

    df = pd.DataFrame(session['attendance_data'])
    date_range = session['date_range']
    
    # Process the data similar to upload route
    return send_file(
        output,
        as_attachment=True,
        download_name=f'pivot_absensi_{date_range["start"]}_to_{date_range["end"]}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/sync_datakaryawan')
def sync_datakaryawan():
    return render_template('sync_datakaryawan.html')

@app.route('/sync_datakaryawan/sync', methods=['POST'])
def sync_datakaryawan_process():
    try:
        # Get data from OWL database
        owl_conn = get_owl_connection()
        owl_cursor = owl_conn.cursor(dictionary=True)
        
        owl_query = """
        SELECT * FROM datakaryawan 
        WHERE lokasitugas IN (
            SELECT kodeorganisasi 
            FROM organisasi 
            WHERE tipe = 'HOLDING'
        )
        """
        owl_cursor.execute(owl_query)
        owl_data = owl_cursor.fetchall()
        
        # Connect to local database
        local_conn = get_connection()
        local_cursor = local_conn.cursor()
        
        # Insert or update records
        update_query = """
        INSERT INTO datakaryawan_owl (karyawanid, nik, namakaryawan)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            karyawanid = VALUES(karyawanid),
            nik = VALUES(nik),
            namakaryawan = VALUES(namakaryawan)
        """
        
        updated_count = 0
        new_count = 0
        
        for record in owl_data:
            # Check if record exists
            check_query = "SELECT karyawanid FROM datakaryawan_owl WHERE karyawanid = %s"
            local_cursor.execute(check_query, (record['karyawanid'],))
            exists = local_cursor.fetchone()
            
            # Insert/update record
            local_cursor.execute(update_query, (
                record['karyawanid'],
                record['nik'],
                record['namakaryawan']
            ))
            
            if exists:
                updated_count += 1
            else:
                new_count += 1
        
        local_conn.commit()
        
        result = {
            'success': True,
            'message': 'Sync completed successfully',
            'total': len(owl_data),
            'updated': updated_count,
            'new': new_count
        }
        
    except Exception as e:
        result = {
            'success': False,
            'message': f'Error during sync: {str(e)}',
            'total': 0,
            'updated': 0,
            'new': 0
        }
        
    finally:
        # Close all connections
        if 'owl_cursor' in locals(): owl_cursor.close()
        if 'owl_conn' in locals(): owl_conn.close()
        if 'local_cursor' in locals(): local_cursor.close()
        if 'local_conn' in locals(): local_conn.close()
    
    return jsonify(result)

@app.route('/sync_datakaryawan/check')
def check_sync_status():
    try:
        owl_conn = get_owl_connection()
        local_conn = get_connection()
        
        owl_cursor = owl_conn.cursor(dictionary=True)
        local_cursor = local_conn.cursor(dictionary=True)
        
        # Get counts from both databases
        owl_query = """
        SELECT COUNT(*) as count FROM datakaryawan 
        WHERE lokasitugas IN (
            SELECT kodeorganisasi 
            FROM organisasi 
            WHERE tipe = 'HOLDING'
        )
        """
        owl_cursor.execute(owl_query)
        owl_count = owl_cursor.fetchone()['count']
        
        local_cursor.execute("SELECT COUNT(*) as count FROM datakaryawan_owl")
        local_count = local_cursor.fetchone()['count']
        
        # Get last sync time
        local_cursor.execute("SELECT MAX(last_sync) as last_sync FROM datakaryawan_owl")
        last_sync = local_cursor.fetchone()['last_sync']
        
        return jsonify({
            'owl_count': owl_count,
            'local_count': local_count,
            'difference': owl_count - local_count,
            'last_sync': last_sync.isoformat() if last_sync else None
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500
        
    finally:
        owl_cursor.close()
        owl_conn.close()
        local_cursor.close()
        local_conn.close()

@app.route('/pin_nik_settings')
# @login_required
def pin_nik_settings():
    try:
        # Get pegawai data
        local_conn = get_connection()
        local_cursor = local_conn.cursor(dictionary=True)
        
        # Get all employees from pegawai table
        local_cursor.execute("""
            SELECT p.pegawai_pin as pin, p.pegawai_nama, pn.nik 
            FROM pegawai p 
            LEFT JOIN pin_nik pn ON p.pegawai_pin = pn.pin
            ORDER BY p.pegawai_nama
        """)
        employees = local_cursor.fetchall()
        
        # Get all employees from datakaryawan_owl
        local_cursor.execute("SELECT nik, namakaryawan FROM datakaryawan_owl ORDER BY namakaryawan")
        datakaryawan = local_cursor.fetchall()
        
        return render_template('pin_nik_settings.html', 
                             employees=employees,
                             datakaryawan=datakaryawan)
    
    except Exception as e:
        flash(f'Error loading data: {str(e)}', 'error')
        return redirect(url_for('index'))
    finally:
        if 'local_cursor' in locals(): local_cursor.close()
        if 'local_conn' in locals(): local_conn.close()

@app.route('/pin_nik_settings/update', methods=['POST'])
# @login_required
def update_pin_nik():
    try:
        data = request.get_json()
        pin = data.get('pin')
        nik = data.get('nik')
        
        if not pin or not nik:
            return jsonify({'success': False, 'message': 'PIN and NIK are required'})
        
        local_conn = get_connection()
        local_cursor = local_conn.cursor()
        
        # Update or insert PIN-NIK mapping
        local_cursor.execute("""
            INSERT INTO pin_nik (pin, nik) 
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE nik = VALUES(nik)
        """, (pin, nik))
        
        local_conn.commit()
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        if 'local_cursor' in locals(): local_cursor.close()
        if 'local_conn' in locals(): local_conn.close()

if __name__ == '__main__':
    app.run(debug=True)
