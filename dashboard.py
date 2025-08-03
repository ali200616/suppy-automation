import os
from flask import Flask, render_template, request, send_from_directory, abort
from datetime import datetime

app = Flask(__name__)
LOGS_DIR = os.path.join(os.getcwd(), 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

@app.route('/')
def index():
    # Load integration log (last 50 lines)
    log_path = os.path.join(LOGS_DIR, 'integration-log.txt')
    logs = []
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            logs = lines[-50:][::-1]  # newest first

    # List CSV files in logs/ folder
    csvs = sorted(
        [f for f in os.listdir(LOGS_DIR) if f.lower().endswith('.csv')],
        key=lambda x: os.path.getmtime(os.path.join(LOGS_DIR, x)),
        reverse=True
    )

    last_updated = datetime.now().strftime('%Y-%m-%d %H:%M')
    return render_template(
        'index.html',
        logs=logs,
        csvs=csvs,
        last_updated=last_updated
    )

@app.route('/download/<filename>')
def download(filename):
    try:
        return send_from_directory(LOGS_DIR, filename, as_attachment=True)
    except FileNotFoundError:
        abort(404)

@app.route('/upload-log', methods=['POST'])
def upload_log():
    log = request.form.get('log')
    filename = request.form.get('filename')
    file = request.files.get('file')

    # Validate form input
    if not filename or not file:
        return "Missing filename or file", 400

    # Save CSV file
    csv_path = os.path.join(LOGS_DIR, filename)
    file.save(csv_path)

    # Save log line
    if log:
        log_path = os.path.join(LOGS_DIR, 'integration-log.txt')
        with open(log_path, 'a', encoding='utf-8') as flog:
            flog.write(log + '\n')

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
