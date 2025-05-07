from flask import Flask, request, send_file, render_template
import pandas as pd
from io import BytesIO, StringIO
import datetime
import csv
from db_config import get_connection

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('upload.html')

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

    return render_template('export_form.html')

if __name__ == '__main__':
    app.run(debug=True)
