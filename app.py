from flask import Flask, request, send_file, render_template, redirect, url_for, session, flash, jsonify
from functools import wraps  # Add this import
import pandas as pd
from io import BytesIO, StringIO
import csv
from db_config import get_connection,get_owl_connection
from flaskwebgui import FlaskUI
import requests
import os
import json
import hashlib  # Add this import
from datetime import datetime
from db_config import is_db_configured, save_config, test_connection, load_config

import sys
import os

# Add this near the top of your file, after imports
if getattr(sys, 'frozen', False):
    # If the application is run as a bundle
    application_path = sys._MEIPASS
else:
    # If the application is run from a Python interpreter
    application_path = os.path.dirname(os.path.abspath(__file__))

# Modify your Flask app initialization
app = Flask(__name__,
            static_folder=os.path.join(application_path, 'static'),
            template_folder=os.path.join(application_path, 'templates'))

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
        session['logged_in'] = False
        try:
            conn = get_owl_connection()
            cursor = conn.cursor()
            
            # Check user credentials
            cursor.execute("SELECT * FROM user WHERE namauser = %s AND password = PASSWORD(%s)", 
                          (username, password))
            user = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            if user:
                session['user_id'] = user[0]
                # session['username'] = user[1]
                session['logged_in'] = True
                return redirect(url_for('sync_datakaryawan'))
            else:
                flash('Invalid username or password')
                return redirect(url_for('login'))
                
        except Exception as e:
            return render_template('error.html', error_message=f'Database connection error: {str(e)}')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('upload.html')

@app.route('/pivot')
@login_required
def pivot_index():
    try:
        # Get OWL connection to fetch available options
        conn = get_owl_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get available date range
        date_range_query = """
        SELECT 
            MIN(DATE(scan_date)) as min_date,
            MAX(DATE(scan_date)) as max_date
        FROM att_log_vw
        WHERE namakaryawan IS NOT NULL
        """
        cursor.execute(date_range_query)
        date_range = cursor.fetchone() or {'min_date': None, 'max_date': None}
        
        # Get available lokasitugas options
        lokasitugas_query = """
        SELECT DISTINCT lokasitugas 
        FROM att_log_vw
        WHERE lokasitugas IS NOT NULL 
        AND namakaryawan IS NOT NULL
        ORDER BY lokasitugas
        """
        cursor.execute(lokasitugas_query)
        lokasitugas_options = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('pivot_index.html',
                             date_range=date_range,
                             lokasitugas_options=lokasitugas_options)
    except Exception as e:
        return render_template('error.html', error_message=f'Error loading pivot report page: {str(e)}')

# Add to all other routes
@app.route('/upload', methods=['POST'])
@login_required
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
@login_required
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

        try:
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
            
        except Exception as e:
            return render_template('error.html', error_message=f'Database error during CSV export: {str(e)}')

        # After getting the data, automatically process it
        df = pd.DataFrame(rows, columns=['tanggal', 'pegawai_nama', 'jammasuk', 'jamkeluar'])
        
        # Store the data in session for report view
        session['attendance_data'] = df.to_dict('records')
        session['date_range'] = {'start': start_date, 'end': end_date}

        # Redirect to report page
        return redirect(url_for('report'))

    return render_template('export_form.html')

@app.route('/report')
@login_required
def report():
    try:
        # Connect to OWL database for reporting
        conn = get_owl_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Get available lokasitugas for filter options
        try:
            cursor.execute("SELECT DISTINCT lokasitugas FROM att_log WHERE lokasitugas IS NOT NULL ORDER BY lokasitugas")
            lokasitugas_options = cursor.fetchall()
        except Exception as e:
            return render_template('error.html', error_message=f'Error fetching lokasitugas: {str(e)}')
        
        # Get date range for default values (last 30 days)
        try:
            cursor.execute("SELECT MIN(DATE(scan_date)) as min_date, MAX(DATE(scan_date)) as max_date FROM att_log")
            date_range = cursor.fetchone()
        except Exception as e:
            return render_template('error.html', error_message=f'Error fetching date range: {str(e)}')
        
        cursor.close()
        conn.close()
        
        return render_template('report.html', 
                             lokasitugas_options=lokasitugas_options,
                             date_range=date_range)
        
    except Exception as e:
        return render_template('error.html', error_message=f'Database connection error: {str(e)}')

@app.route('/export_excel')
@login_required
def export_excel():
    try:
        if 'attendance_data' not in session:
            return redirect(url_for('export_csv'))

        df = pd.DataFrame(session['attendance_data'])
        date_range = session['date_range']
        
        # Create Excel output
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Attendance Data', index=False)
        
        output.seek(0)
        
        return send_file(
            output,
            as_attachment=True,
            download_name=f'pivot_absensi_{date_range["start"]}_to_{date_range["end"]}.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        return render_template('error.html', error_message=f'Error generating Excel file: {str(e)}')

@app.route('/sync_datakaryawan')
@login_required
def sync_datakaryawan():
    return render_template('sync_datakaryawan.html')

@app.route('/sync_att')
@login_required
def sync_att():
    return render_template('sync_att.html')

@app.route('/sync_datakaryawan/sync', methods=['POST'])
@login_required
def sync_datakaryawan_process():
    owl_conn = None
    owl_cursor = None
    local_conn = None
    local_cursor = None
    
    try:
        # Get data from OWL database
        try:
            owl_conn = get_owl_connection()
            owl_cursor = owl_conn.cursor(dictionary=True)
        except Exception as e:
            return jsonify({
                'success': False,
                'error_type': 'owl_database_connection',
                'message': f'Failed to connect to OWL database: {str(e)}',
                'total': 0,
                'updated': 0,
                'new': 0
            })
        
        # Query OWL database
        try:
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
        except Exception as e:
            return jsonify({
                'success': False,
                'error_type': 'owl_database_query',
                'message': f'Error querying OWL database: {str(e)}',
                'total': 0,
                'updated': 0,
                'new': 0
            })
        
        # Connect to local database
        try:
            local_conn = get_connection()
            local_cursor = local_conn.cursor()
        except Exception as e:
            return jsonify({
                'success': False,
                'error_type': 'local_database_connection',
                'message': f'Failed to connect to local database: {str(e)}',
                'total': 0,
                'updated': 0,
                'new': 0
            })
        
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
        
        try:
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
        except Exception as e:
            if local_conn:
                local_conn.rollback()
            return jsonify({
                'success': False,
                'error_type': 'local_database_insert',
                'message': f'Error inserting/updating records in local database: {str(e)}',
                'total': len(owl_data),
                'updated': updated_count,
                'new': new_count
            })
        
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
            'error_type': 'general',
            'message': f'Unexpected error during sync: {str(e)}',
            'total': 0,
            'updated': 0,
            'new': 0
        }
        
    finally:
        # Close all connections
        if owl_cursor:
            owl_cursor.close()
        if owl_conn:
            owl_conn.close()
        if local_cursor:
            local_cursor.close()
        if local_conn:
            local_conn.close()
    
    return jsonify(result)

@app.route('/sync_datakaryawan/check')
@login_required
def check_sync_status():
    owl_conn = None
    owl_cursor = None
    local_conn = None
    local_cursor = None
    
    try:
        # Connect to OWL database
        try:
            owl_conn = get_owl_connection()
            owl_cursor = owl_conn.cursor(dictionary=True)
        except Exception as e:
            return jsonify({
                'error_type': 'owl_database_connection',
                'error': f'Failed to connect to OWL database: {str(e)}'
            }), 500
        
        # Connect to local database
        try:
            local_conn = get_connection()
            local_cursor = local_conn.cursor(dictionary=True)
        except Exception as e:
            return jsonify({
                'error_type': 'local_database_connection',
                'error': f'Failed to connect to local database: {str(e)}'
            }), 500
        
        # Get counts from OWL database
        try:
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
        except Exception as e:
            return jsonify({
                'error_type': 'owl_database_query',
                'error': f'Error querying OWL database: {str(e)}'
            }), 500
        
        # Get counts from local database
        try:
            local_cursor.execute("SELECT COUNT(*) as count FROM datakaryawan_owl")
            local_count = local_cursor.fetchone()['count']
            
            # Get last sync time
            local_cursor.execute("SELECT MAX(last_sync) as last_sync FROM datakaryawan_owl")
            last_sync = local_cursor.fetchone()['last_sync']
        except Exception as e:
            return jsonify({
                'error_type': 'local_database_query',
                'error': f'Error querying local database: {str(e)}'
            }), 500
        
        return jsonify({
            'owl_count': owl_count,
            'local_count': local_count,
            'difference': owl_count - local_count,
            'last_sync': last_sync.isoformat() if last_sync else None
        })
        
    except Exception as e:
        return jsonify({
            'error_type': 'general',
            'error': f'Unexpected error: {str(e)}'
        }), 500
        
    finally:
        if owl_cursor:
            owl_cursor.close()
        if owl_conn:
            owl_conn.close()
        if local_cursor:
            local_cursor.close()
        if local_conn:
            local_conn.close()

@app.route('/pin_nik_settings')
@login_required
def pin_nik_settings():
    local_conn = None
    local_cursor = None
    
    try:
        # Get pegawai data
        local_conn = get_connection()
        local_cursor = local_conn.cursor(dictionary=True)
        
        # Get all employees from pegawai table
        try:
            local_cursor.execute("""
                SELECT p.pegawai_pin as pin, p.pegawai_nama, pn.nik 
                FROM pegawai p 
                LEFT JOIN pin_nik pn ON p.pegawai_pin = pn.pin
                ORDER BY p.pegawai_nama
            """)
            employees = local_cursor.fetchall()
        except Exception as e:
            return render_template('error.html', error_message=f'Error loading employee data: {str(e)}')
        
        # Get all employees from datakaryawan_owl
        try:
            local_cursor.execute("SELECT nik, namakaryawan FROM datakaryawan_owl ORDER BY namakaryawan")
            datakaryawan = local_cursor.fetchall()
        except Exception as e:
            return render_template('error.html', error_message=f'Error loading datakaryawan data: {str(e)}')
        
        return render_template('pin_nik_settings.html', 
                             employees=employees,
                             datakaryawan=datakaryawan)
    
    except Exception as e:
        return render_template('error.html', error_message=f'Database connection error: {str(e)}')
    finally:
        if local_cursor:
            local_cursor.close()
        if local_conn:
            local_conn.close()

@app.route('/pin_nik_settings/update', methods=['POST'])
@login_required
def update_pin_nik():
    local_conn = None
    local_cursor = None
    
    try:
        data = request.get_json()
        pin = data.get('pin')
        nik = data.get('nik')
        
        if not pin:
            return jsonify({'success': False, 'message': 'PIN is required'})
        
        try:
            local_conn = get_connection()
            local_cursor = local_conn.cursor()
            
            if nik is None or nik == '':
                # Delete the PIN-NIK mapping if NIK is null or empty
                local_cursor.execute("DELETE FROM pin_nik WHERE pin = %s", (pin,))
            else:
                # Update or insert PIN-NIK mapping
                local_cursor.execute("""
                    INSERT INTO pin_nik (pin, nik) 
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE nik = VALUES(nik)
                """, (pin, nik))
            
            local_conn.commit()
            return jsonify({'success': True})
            
        except Exception as e:
            if local_conn:
                local_conn.rollback()
            return jsonify({'success': False, 'message': f'Database error: {str(e)}'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Request processing error: {str(e)}'})
    finally:
        if local_cursor:
            local_cursor.close()
        if local_conn:
            local_conn.close()

@app.route('/check_updates')
@login_required
def check_updates():
    try:
        config = load_config()
        server_url = f"{config['server_url']}/version"
        response = requests.get(server_url)
        
        if response.status_code == 200:
            server_version = response.json().get('version')
            
            # Read local version
            version_file = os.path.join(os.path.dirname(__file__), 'version.json')
            local_version = "1.0.0"  # Default version
            
            if os.path.exists(version_file):
                with open(version_file, 'r') as f:
                    local_version = json.load(f).get('version', "1.0.0")
            
            if server_version > local_version:
                return jsonify({
                    'update_available': True,
                    'current_version': local_version,
                    'server_version': server_version
                })
            
        return jsonify({
            'update_available': False,
            'current_version': local_version
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'update_available': False
        })

# Add route for performing update
@app.route('/perform_update')
@login_required
def perform_update():
    try:
        # Replace with your actual update server endpoint
        update_url = "YOUR_SERVER_URL/update"
        response = requests.get(update_url)
        
        if response.status_code == 200:
            update_data = response.json()
            
            # Process the update - this is a simplified example
            # You should implement proper update logic based on your needs
            version_file = os.path.join(os.path.dirname(__file__), 'version.json')
            with open(version_file, 'w') as f:
                json.dump({
                    'version': update_data['version'],
                    'last_updated': datetime.now().isoformat()
                }, f)
            
            return jsonify({
                'success': True,
                'message': 'Update completed successfully'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.before_request
def check_db_setup():
    if not is_db_configured() and request.endpoint not in ['setup_database', 'static', 'login']:
        return redirect(url_for('setup_database'))

@app.route('/sync_data', methods=['POST'])
@login_required
def sync_data():
    local_conn = None
    owl_conn = None
    local_cursor = None
    owl_cursor = None
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'status': 'error',
                'error_type': 'invalid_request',
                'message': 'No JSON data provided'
            })
            
        if 'start_date' not in data or 'end_date' not in data:
            return jsonify({
                'status': 'error',
                'error_type': 'missing_parameters',
                'message': 'start_date and end_date parameters are required'
            })
            
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d')  # Get end date from request data

        # Try to connect to local database first
        try:
            local_conn = get_connection()
            local_cursor = local_conn.cursor()
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error_type': 'local_database_connection',
                'message': str(e)
            })

        # Try to connect to OWL database
        try:
            owl_conn = get_owl_connection()
            owl_cursor = owl_conn.cursor()  # Remove dictionary=True to get tuples like local database
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error_type': 'owl_database_connection',
                'message': str(e)
            })

        # Query data dalam range tanggal from local database
        try:
            # First check if the view exists
            local_cursor.execute("SHOW TABLES LIKE 'att_log_vw'")
            view_exists = local_cursor.fetchone()
            
            if not view_exists:
                return jsonify({
                    'status': 'error',
                    'error_type': 'missing_view',
                    'message': 'att_log_vw view does not exist in local database'
                })
            
            local_cursor.execute(
                "SELECT * FROM att_log_vw WHERE scan_date >= %s AND scan_date < %s AND pin IS NOT NULL AND pin > 0",
                (start_date, end_date)
            )
            rows_a = local_cursor.fetchall()
            
            if not rows_a:
                return jsonify({
                    'status': 'success',
                    'message': 'No data found in the specified date range',
                    'rows_synced': 0,
                    'total_source_rows': 0,
                    'total_target_rows': 0,
                    'last_sync': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error_type': 'local_database_query',
                'message': f"Error querying local database: {str(e)}"
            })

        # Ambil data existing dari target untuk perbandingan
        try:
            owl_cursor.execute(
                "SELECT * FROM att_log WHERE scan_date >= %s AND scan_date < %s",
                (start_date, end_date)
            )
            rows_b = owl_cursor.fetchall()
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error_type': 'owl_database_query',
                'message': f"Error querying OWL database: {str(e)}"
            })

        # Debug: Check data structure
        debug_info = {
            'local_sample': rows_a[0] if rows_a else None,
            'owl_sample': rows_b[0] if rows_b else None,
            'local_type': type(rows_a[0]).__name__ if rows_a else None,
            'owl_type': type(rows_b[0]).__name__ if rows_b else None,
            'local_length': len(rows_a[0]) if rows_a else None,
            'owl_length': len(rows_b[0]) if rows_b else None
        }

        # Hash function untuk perbandingan data
        def hash_row(row):
            try:
                # Both databases now return tuples
                # Map column indices based on the SELECT * order
                indices = {
                    'sn': 0,
                    'scan_date': 1,
                    'pin': 2,
                    'verifymode': 3,
                    'inoutmode': 4,
                    'reserved': 5,
                    'work_code': 6,
                    'att_id': 7
                }
                
                # Validate row has enough columns
                if len(row) < 8:
                    raise ValueError(f"Row has insufficient columns: {len(row)} < 8")
                
                # Create data string for hashing
                data_string = "|".join([str(row[indices[k]]) for k in ['sn', 'scan_date', 'pin', 'verifymode', 'inoutmode', 'reserved', 'work_code', 'att_id']])
                return hashlib.md5(data_string.encode()).hexdigest()
            except Exception as e:
                raise Exception(f"Error hashing row: {str(e)}, Row data: {row}")

        try:
            hashes_b = {hash_row(row) for row in rows_b}
            rows_to_push = [row for row in rows_a if hash_row(row) not in hashes_b]
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error_type': 'data_processing',
                'message': f"Error processing data for comparison: {str(e)}"
            })

        # Push data ke table target
        try:
            if not rows_to_push:
                return jsonify({
                    'status': 'success',
                    'message': 'No new data to sync',
                    'rows_synced': 0,
                    'total_source_rows': len(rows_a),
                    'total_target_rows': len(rows_b),
                    'last_sync': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'debug_info': debug_info
                })
                
            for i, row in enumerate(rows_to_push):
                try:
                    keys = ['sn', 'scan_date', 'pin', 'verifymode', 'inoutmode', 'reserved', 'work_code', 'att_id']
                    cols = ", ".join(keys)
                    vals = ", ".join(["%s"] * len(keys))
                    # Use INSERT ... ON DUPLICATE KEY UPDATE to handle existing primary keys (sn, scan_date, pin)
                    update_clause = ", ".join([f"{key} = VALUES({key})" for key in keys if key not in ['sn', 'scan_date', 'pin']])
                    sql = f"INSERT INTO att_log ({cols}) VALUES ({vals}) ON DUPLICATE KEY UPDATE {update_clause}"
                    owl_cursor.execute(sql, row)  # Pass the tuple directly since it's already in the correct order
                except Exception as row_error:
                    raise Exception(f"Error inserting row {i+1}: {str(row_error)}, Row data: {row}")

            owl_conn.commit()
        except Exception as e:
            if owl_conn:
                owl_conn.rollback()
            return jsonify({
                'status': 'error',
                'error_type': 'owl_database_insert',
                'message': f"Error inserting data into OWL database: {str(e)}"
            })

        return jsonify({
            'status': 'success',
            'rows_synced': len(rows_to_push),
            'total_source_rows': len(rows_a),
            'total_target_rows': len(rows_b),
            'last_sync': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'debug_info': debug_info
        })

    except ValueError as e:
        return jsonify({
            'status': 'error',
            'error_type': 'date_format',
            'message': f"Invalid date format: {str(e)}"
        })
    except Exception as e:
        # Enhanced error reporting
        error_msg = str(e) if str(e) else f"Unknown error occurred - Exception type: {type(e).__name__}"
        return jsonify({
            'status': 'error',
            'error_type': 'general',
            'message': f"Unexpected error: {error_msg}",
            'exception_type': type(e).__name__
        })
    finally:
        # Clean up connections
        if local_cursor:
            local_cursor.close()
        if owl_cursor:
            owl_cursor.close()
        if local_conn:
            local_conn.close()
        if owl_conn:
            owl_conn.close()

@app.route('/setup', methods=['GET', 'POST'])
def setup_database():
    try:
        if request.method == 'POST':
            config = {
                'local_host': request.form['local_host'],
                'local_port': int(request.form['local_port']),
                'local_database': request.form['local_database'],
                'local_user': request.form['local_user'],
                'local_password': request.form['local_password'],
                'owl_host': request.form['owl_host'],
                'owl_port': int(request.form['owl_port']),
                'owl_database': request.form['owl_database'],
                'owl_user': request.form['owl_user'],
                'owl_password': request.form['owl_password'],
                'server_url': request.form['server_url'].rstrip('/')  # Remove trailing slash if present
            }
            
            success, error = test_connection(config)
            if success:
                save_config(config)
                flash('Database configuration saved successfully!', 'success')
                return redirect(url_for('index'))
            else:
                flash(f'Connection test failed: {error}', 'danger')
                return redirect(url_for('setup_database'))
                
        return render_template('db_setup.html')
    except Exception as e:
        return render_template('error.html', error_message=f'Error in database setup: {str(e)}')

# Add error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', 
                         error_title='404 - Page Not Found',
                         error_message='The page you are looking for does not exist.'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('error.html',
                         error_title='500 - Internal Server Error',
                         error_message='Something went wrong on our end.'), 500

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html',
                         error_title='403 - Forbidden',
                         error_message='You do not have permission to access this resource.'), 403

# Generic error handler
@app.errorhandler(Exception)
def handle_exception(e):
    error_message = str(e) if app.debug else 'An unexpected error occurred.'
    return render_template('error.html',
                         error_title='Error',
                         error_message=error_message), 500


# if __name__ == '__main__':
    # try:
    #     # Try to ensure service is running
    #     from service import ensure_service_running
    #     ensure_service_running()
    # except Exception as e:
    #     print(f"Warning: Could not start service: {e}")
    
# Main block moved to end of file - see bottom of file

@app.route('/debug_sync', methods=['GET'])
@login_required
def debug_sync():
    """Debug endpoint to test sync functionality"""
    try:
        # Test local database connection
        local_conn = get_connection()
        local_cursor = local_conn.cursor()
        
        # Test OWL database connection
        owl_conn = get_owl_connection()
        owl_cursor = owl_conn.cursor()
        
        # Check if att_log_vw exists
        local_cursor.execute("SHOW TABLES LIKE 'att_log_vw'")
        view_exists = local_cursor.fetchone()
        
        # Get sample data
        local_cursor.execute("SELECT * FROM att_log_vw LIMIT 1")
        sample_row = local_cursor.fetchone()
        
        # Get table structure
        local_cursor.execute("DESCRIBE att_log_vw")
        table_structure = local_cursor.fetchall()
        
        # Clean up
        local_cursor.close()
        local_conn.close()
        owl_cursor.close()
        owl_conn.close()
        
        return jsonify({
            'status': 'success',
            'local_db_connected': True,
            'owl_db_connected': True,
            'att_log_vw_exists': bool(view_exists),
            'sample_row': sample_row,
            'table_structure': table_structure
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f"Debug error: {str(e)}",
            'exception_type': type(e).__name__
        })

@app.route('/debug_hash', methods=['POST'])
@login_required
def debug_hash():
    """Debug endpoint to test hash function"""
    try:
        data = request.get_json()
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d')
        
        # Test connections
        local_conn = get_connection()
        local_cursor = local_conn.cursor()
        owl_conn = get_owl_connection()
        owl_cursor = owl_conn.cursor()
        
        # Get sample data from both databases
        local_cursor.execute(
            "SELECT * FROM att_log_vw WHERE scan_date >= %s AND scan_date < %s AND pin IS NOT NULL AND pin > 0 LIMIT 1",
            (start_date, end_date)
        )
        local_sample = local_cursor.fetchone()
        
        owl_cursor.execute(
            "SELECT * FROM att_log WHERE scan_date >= %s AND scan_date < %s LIMIT 1",
            (start_date, end_date)
        )
        owl_sample = owl_cursor.fetchone()
        
        # Test hash function
        def hash_row(row):
            try:
                # Both databases now return tuples
                indices = {
                    'sn': 0,
                    'scan_date': 1,
                    'pin': 2,
                    'verifymode': 3,
                    'inoutmode': 4,
                    'reserved': 5,
                    'work_code': 6,
                    'att_id': 7
                }
                
                if len(row) < 8:
                    raise ValueError(f"Row has insufficient columns: {len(row)} < 8")
                
                data_string = "|".join([str(row[indices[k]]) for k in ['sn', 'scan_date', 'pin', 'verifymode', 'inoutmode', 'reserved', 'work_code', 'att_id']])
                return hashlib.md5(data_string.encode()).hexdigest()
            except Exception as e:
                raise Exception(f"Error hashing row: {str(e)}, Row data: {row}")
        
        result = {
            'local_sample': local_sample,
            'owl_sample': owl_sample,
            'local_type': type(local_sample).__name__ if local_sample else None,
            'owl_type': type(owl_sample).__name__ if owl_sample else None,
            'local_length': len(local_sample) if local_sample else None,
            'owl_length': len(owl_sample) if owl_sample else None
        }
        
        # Try to hash both samples
        if local_sample:
            try:
                result['local_hash'] = hash_row(local_sample)
            except Exception as e:
                result['local_hash_error'] = str(e)
        
        if owl_sample:
            try:
                result['owl_hash'] = hash_row(owl_sample)
            except Exception as e:
                result['owl_hash_error'] = str(e)
        
        # Clean up
        local_cursor.close()
        local_conn.close()
        owl_cursor.close()
        owl_conn.close()
        
        return jsonify({
            'status': 'success',
            'result': result
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f"Debug hash error: {str(e)}",
            'exception_type': type(e).__name__
        })

@app.route('/generate_pivot_report', methods=['POST'])
@login_required
def generate_pivot_report():
    try:
        # Get form data
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        lokasitugas_list = request.form.getlist('lokasitugas')
        
        if not start_date or not end_date:
            flash('Start date and end date are required', 'error')
            return redirect(url_for('pivot_index'))
        
        if not lokasitugas_list:
            flash('Please select at least one lokasitugas', 'error')
            return redirect(url_for('pivot_index'))
        
        # Connect to OWL database
        conn = get_owl_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Create placeholders for IN clause
        lokasitugas_placeholders = ','.join(['%s'] * len(lokasitugas_list))
        
        # Build the pivot query
        pivot_query = f"""
        SELECT 
            namakaryawan,
            DATE(scan_date) as tanggal,
            TIME(MIN(scan_date)) as jammasuk,
            TIME(MAX(scan_date)) as jamkeluar
        FROM att_log 
        WHERE DATE(scan_date) BETWEEN %s AND %s
        AND lokasitugas IN ({lokasitugas_placeholders})
        AND namakaryawan IS NOT NULL
        GROUP BY namakaryawan, DATE(scan_date)
        ORDER BY namakaryawan, DATE(scan_date)
        """
        
        # Execute query with parameters
        params = [start_date, end_date] + lokasitugas_list
        cursor.execute(pivot_query, params)
        raw_data = cursor.fetchall()
        
        # Get unique dates for column headers
        date_query = f"""
        SELECT DISTINCT DATE(scan_date) as tanggal
        FROM att_log 
        WHERE DATE(scan_date) BETWEEN %s AND %s
        AND lokasitugas IN ({lokasitugas_placeholders})
        ORDER BY DATE(scan_date)
        """
        cursor.execute(date_query, params)
        dates = cursor.fetchall()
        
        # Get unique employees
        employee_query = f"""
        SELECT DISTINCT namakaryawan
        FROM att_log 
        WHERE DATE(scan_date) BETWEEN %s AND %s
        AND lokasitugas IN ({lokasitugas_placeholders})
        AND namakaryawan IS NOT NULL
        ORDER BY namakaryawan
        """
        cursor.execute(employee_query, params)
        employees = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # Process data into pivot format
        pivot_data = {}
        for employee in employees:
            pivot_data[employee['namakaryawan']] = {}
            for date in dates:
                pivot_data[employee['namakaryawan']][str(date['tanggal'])] = {
                    'jammasuk': None,
                    'jamkeluar': None
                }
        
        # Fill in the actual data
        for row in raw_data:
            employee_name = row['namakaryawan']
            date_str = str(row['tanggal'])
            if employee_name in pivot_data and date_str in pivot_data[employee_name]:
                pivot_data[employee_name][date_str]['jammasuk'] = row['jammasuk']
                pivot_data[employee_name][date_str]['jamkeluar'] = row['jamkeluar']
        
        # Calculate summary statistics
        for employee_name in pivot_data:
            total_hadir = sum(1 for date_data in pivot_data[employee_name].values() 
                            if date_data['jammasuk'] is not None)
            pivot_data[employee_name]['total_hadir'] = total_hadir
        
        return render_template('pivot_report.html', 
                             pivot_data=pivot_data,
                             dates=dates,
                             start_date=start_date,
                             end_date=end_date,
                             selected_lokasitugas=lokasitugas_list)
        
    except Exception as e:
        flash(f'Error generating pivot report: {str(e)}', 'error')
        return redirect(url_for('pivot_index'))

@app.route('/export_pivot_excel', methods=['POST'])
@login_required
def export_pivot_excel():
    try:
        # Get form data
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        lokasitugas_list = request.form.getlist('lokasitugas')
        
        if not start_date or not end_date or not lokasitugas_list:
            flash('Missing required parameters', 'error')
            return redirect(url_for('pivot_index'))
        
        # Connect to OWL database
        conn = get_owl_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Create placeholders for IN clause
        lokasitugas_placeholders = ','.join(['%s'] * len(lokasitugas_list))
        
        # Build the pivot query
        pivot_query = f"""
        SELECT 
            namakaryawan,
            DATE(scan_date) as tanggal,
            TIME(MIN(scan_date)) as jammasuk,
            TIME(MAX(scan_date)) as jamkeluar
        FROM att_log_vw
        WHERE DATE(scan_date) BETWEEN %s AND %s
        AND lokasitugas IN ({lokasitugas_placeholders})
        AND namakaryawan IS NOT NULL
        GROUP BY namakaryawan, DATE(scan_date)
        ORDER BY namakaryawan, DATE(scan_date)
        """
        
        # Execute query with parameters
        params = [start_date, end_date] + lokasitugas_list
        cursor.execute(pivot_query, params)
        raw_data = cursor.fetchall()
        
        # Get unique dates for column headers
        date_query = f"""
        SELECT DISTINCT DATE(scan_date) as tanggal
        FROM att_log_vw
        WHERE DATE(scan_date) BETWEEN %s AND %s
        AND lokasitugas IN ({lokasitugas_placeholders})
        ORDER BY DATE(scan_date)
        """
        cursor.execute(date_query, params)
        dates = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # Convert to pandas DataFrame for Excel export
        import pandas as pd
        from datetime import datetime as dt
        
        # Create pivot table using pandas
        df = pd.DataFrame(raw_data)
        if not df.empty:
            # Convert to proper pivot format
            df['tanggal'] = pd.to_datetime(df['tanggal'])
            
            # Create pivot for jammasuk
            pivot_masuk = df.pivot_table(
                index='namakaryawan',
                columns='tanggal',
                values='jammasuk',
                aggfunc='first'
            )
            
            # Create pivot for jamkeluar
            pivot_keluar = df.pivot_table(
                index='namakaryawan',
                columns='tanggal',
                values='jamkeluar',
                aggfunc='first'
            )
            
            # Create MultiIndex columns
            date_list = sorted(df['tanggal'].unique())
            col_tuples = []
            for date in date_list:
                date_str = date.strftime('%Y-%m-%d')
                col_tuples.append((date_str, 'jammasuk'))
                col_tuples.append((date_str, 'jamkeluar'))
            
            multi_cols = pd.MultiIndex.from_tuples(col_tuples)
            
            # Combine into one DataFrame
            combined = pd.DataFrame(index=pivot_masuk.index, columns=multi_cols)
            for date in date_list:
                date_str = date.strftime('%Y-%m-%d')
                if date in pivot_masuk.columns:
                    combined[(date_str, 'jammasuk')] = pivot_masuk[date]
                if date in pivot_keluar.columns:
                    combined[(date_str, 'jamkeluar')] = pivot_keluar[date]
            
            # Add summary column
            hadir_count = pivot_masuk.notna().sum(axis=1)
            combined[('Summary', 'Total Hadir')] = hadir_count
            
            # Sort columns
            combined = combined.sort_index(axis=1, level=0)
            
            # Create Excel file
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                workbook = writer.book
                sheetname = 'Pivot Absensi'
                combined.to_excel(writer, sheet_name=sheetname, startrow=2, merge_cells=False)
                worksheet = writer.sheets[sheetname]
                
                # Styles
                header_fmt = workbook.add_format({
                    'bold': True, 
                    'align': 'center', 
                    'valign': 'vcenter', 
                    'border': 1
                })
                weekend_fmt = workbook.add_format({
                    'bg_color': '#D9D9D9', 
                    'align': 'center'
                })
                red_late_fmt = workbook.add_format({
                    'bg_color': 'red', 
                    'align': 'center'
                })
                
                # Write merged headers manually
                worksheet.write(0, 0, 'Nama Karyawan', header_fmt)
                
                col_idx = 1
                for date in date_list:
                    date_str = date.strftime('%Y-%m-%d')
                    worksheet.merge_range(0, col_idx, 0, col_idx + 1, date_str, header_fmt)
                    worksheet.write(1, col_idx, 'Jam Masuk', header_fmt)
                    worksheet.write(1, col_idx + 1, 'Jam Keluar', header_fmt)
                    col_idx += 2
                
                # Write summary header
                worksheet.merge_range(0, col_idx, 1, col_idx, 'Total Hadir', header_fmt)
                
                # Freeze headers
                worksheet.freeze_panes(2, 1)
                
                # Column width
                worksheet.set_column(0, 0, 25)
                worksheet.set_column(1, col_idx, 12)
                
                # Weekend formatting
                for i, date in enumerate(date_list):
                    if date.weekday() >= 5:  # Saturday(5), Sunday(6)
                        worksheet.conditional_format(
                            2, 1 + i * 2, 2 + len(combined), 1 + i * 2 + 1,
                            {'type': 'no_blanks', 'format': weekend_fmt}
                        )
                
                # Late arrival formatting (after 09:00)
                for i, date in enumerate(date_list):
                    col_letter = chr(66 + i*2)  # B, D, F, etc.
                    worksheet.conditional_format(
                        2, 1 + i * 2, 2 + len(combined), 1 + i * 2,
                        {
                            'type': 'formula',
                            'criteria': f'=AND(NOT(ISBLANK({col_letter}3)),TIME(9,0,0)<TIMEVALUE({col_letter}3))',
                            'format': red_late_fmt
                        }
                    )
            
            output.seek(0)
            
            # Generate filename
            start_str = start_date.replace('-', '')
            end_str = end_date.replace('-', '')
            filename = f'pivot_absensi_{start_str}_to_{end_str}.xlsx'
            
            return send_file(
                output,
                as_attachment=True,
                download_name=filename,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        else:
            flash('No data found for the selected criteria', 'warning')
            return redirect(url_for('pivot_index'))
            
    except Exception as e:
        flash(f'Error exporting to Excel: {str(e)}', 'error')
        return redirect(url_for('pivot_index'))

@app.route('/api/pivot_report', methods=['POST'])
@login_required
def api_pivot_report():
    """API endpoint for generating pivot report data via AJAX"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No data provided'
            })
        
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        lokasitugas_list = data.get('lokasitugas', [])
        
        if not start_date or not end_date:
            return jsonify({
                'status': 'error',
                'message': 'Start date and end date are required'
            })
        
        if not lokasitugas_list:
            return jsonify({
                'status': 'error',
                'message': 'Please select at least one lokasitugas'
            })
        
        # Connect to OWL database
        conn = get_owl_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Create placeholders for IN clause
        lokasitugas_placeholders = ','.join(['%s'] * len(lokasitugas_list))
        
        # Build the pivot query
        pivot_query = f"""
        SELECT 
            namakaryawan,
            lokasitugas,
            DATE(scan_date) as tanggal,
            TIME(MIN(scan_date)) as jammasuk,
            TIME(MAX(scan_date)) as jamkeluar,
            COUNT(*) as total_scan
        FROM att_log_vw
        WHERE DATE(scan_date) BETWEEN %s AND %s
        AND lokasitugas IN ({lokasitugas_placeholders})
        AND namakaryawan IS NOT NULL
        GROUP BY namakaryawan, lokasitugas, DATE(scan_date)
        ORDER BY namakaryawan, DATE(scan_date)
        """
        
        # Execute query with parameters
        params = [start_date, end_date] + lokasitugas_list
        cursor.execute(pivot_query, params)
        raw_data = cursor.fetchall()
        
        # Get unique dates for column headers
        date_query = f"""
        SELECT DISTINCT DATE(scan_date) as tanggal
        FROM att_log_vw
        WHERE DATE(scan_date) BETWEEN %s AND %s
        AND lokasitugas IN ({lokasitugas_placeholders})
        ORDER BY DATE(scan_date)
        """
        cursor.execute(date_query, params)
        dates = cursor.fetchall()
        
        # Get unique employees with their lokasitugas
        employee_query = f"""
        SELECT DISTINCT namakaryawan, lokasitugas
        FROM att_log_vw
        WHERE DATE(scan_date) BETWEEN %s AND %s
        AND lokasitugas IN ({lokasitugas_placeholders})
        AND namakaryawan IS NOT NULL
        ORDER BY namakaryawan
        """
        cursor.execute(employee_query, params)
        employees = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # Process data into pivot format
        pivot_data = {}
        employee_info = {}
        
        for employee in employees:
            emp_name = employee['namakaryawan']
            if emp_name not in pivot_data:
                pivot_data[emp_name] = {}
                employee_info[emp_name] = {
                    'lokasitugas': employee['lokasitugas']
                }
            
            for date in dates:
                date_str = str(date['tanggal'])
                if date_str not in pivot_data[emp_name]:
                    pivot_data[emp_name][date_str] = {
                        'jammasuk': None,
                        'jamkeluar': None,
                        'total_scan': 0
                    }
        
        # Fill in the actual data
        for row in raw_data:
            employee_name = row['namakaryawan']
            date_str = str(row['tanggal'])
            if employee_name in pivot_data and date_str in pivot_data[employee_name]:
                pivot_data[employee_name][date_str]['jammasuk'] = str(row['jammasuk']) if row['jammasuk'] else None
                pivot_data[employee_name][date_str]['jamkeluar'] = str(row['jamkeluar']) if row['jamkeluar'] else None
                pivot_data[employee_name][date_str]['total_scan'] = row['total_scan']
        
        # Calculate summary statistics
        for employee_name in pivot_data:
            total_hadir = sum(1 for date_data in pivot_data[employee_name].values() 
                            if isinstance(date_data, dict) and date_data.get('jammasuk') is not None)
            pivot_data[employee_name]['total_hadir'] = total_hadir
        
        # Convert dates to string format for JSON serialization
        dates_formatted = [str(date['tanggal']) for date in dates]
        
        return jsonify({
            'status': 'success',
            'data': {
                'pivot_data': pivot_data,
                'employee_info': employee_info,
                'dates': dates_formatted,
                'start_date': start_date,
                'end_date': end_date,
                'selected_lokasitugas': lokasitugas_list,
                'total_employees': len(employees),
                'total_records': len(raw_data)
            }
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error generating pivot report: {str(e)}',
            'exception_type': type(e).__name__
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
