import os
from flask import Flask, render_template, request, send_from_directory, redirect, url_for
from datetime import datetime

app = Flask(__name__)
LOGS_DIR = os.path.join(os.getcwd(), 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

@app.route('/')
def index():
    # Get integration log (last 50 lines)
    log_path = os.path.join(LOGS_DIR, 'integration-log.txt')
    logs = []
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            logs = lines[-50:][::-1]  # newest first
    # List CSVs, newest first
    csvs = sorted(
        [f for f in os.listdir(LOGS_DIR) if f.endswith('.csv')],
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
    return send_from_directory(LOGS_DIR, filename, as_attachment=True)

@app.route('/upload-log', methods=['POST'])
def upload_log():
    log = request.form.get('log', '')
    filename = request.form.get('filename', '')
    # Save log line
    with open(os.path.join(LOGS_DIR, 'integration-log.txt'), 'a', encoding='utf-8') as flog:
        flog.write(log + '\n')
    # Save uploaded file
    if 'file' in request.files and filename:
        file = request.files['file']
        save_path = os.path.join(LOGS_DIR, filename)
        file.save(save_path)
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
