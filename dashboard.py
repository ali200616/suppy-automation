# dashboard.py
from flask import Flask, render_template, send_from_directory, request
import os
from datetime import datetime

app = Flask(__name__)

@app.route('/')
def index():
    logs = []
    csv_files = []

    # Create logs folder if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Read log file if it exists
    log_file = 'logs/integration-log.txt'
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            logs = [line.strip() for line in f.readlines()][-50:]

    # Get list of CSVs in logs/
    csv_files = [f for f in os.listdir('logs') if f.endswith('.csv')]
    csv_files.sort(reverse=True)

    return render_template('index.html',
        logs=logs,
        files=csv_files,
        updated=datetime.now().strftime('%Y-%m-%d %H:%M')
    )

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory('logs', filename, as_attachment=True)

# NEW ENDPOINT TO RECEIVE FILES FROM GITHUB ACTION
@app.route('/upload-log', methods=['POST'])
def upload_log():
    if not os.path.exists('logs'):
        os.makedirs('logs')

    log_text = request.form.get('log')
    filename = request.form.get('filename')
    csv_file = request.files.get('file')

    if log_text:
        with open('logs/integration-log.txt', 'a') as f:
            f.write(log_text + '\n')

    if csv_file and filename:
        csv_file.save(os.path.join('logs', filename))

    return 'OK', 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
