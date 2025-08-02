from flask import Flask, render_template, send_from_directory, request
import os
from datetime import datetime

app = Flask(__name__)

@app.route('/')
def index():
    logs_dir = 'logs'
    log_file = os.path.join(logs_dir, 'integration-log.txt')
    uploads = []

    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            lines = f.readlines()
        for line in reversed(lines[-50:]):
            uploads.append(line.strip())

    csv_files = []
    if os.path.exists(logs_dir):
        for file in sorted(os.listdir(logs_dir), reverse=True):
            if file.endswith('.csv'):
                csv_files.append(file)

    return render_template(
        'index.html',
        logs=uploads,
        files=csv_files,
        updated=datetime.now().strftime('%Y-%m-%d %H:%M')
    )

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory('logs', filename, as_attachment=True)

@app.route('/upload-log', methods=['POST'])
def upload_log():
    logs_dir = 'logs'
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    log_text = request.form.get('log')
    filename = request.form.get('filename')
    csv_file = request.files.get('file')

    if log_text:
        with open(os.path.join(logs_dir, 'integration-log.txt'), 'a') as f:
            f.write(log_text + '\n')

    if csv_file and filename:
        csv_path = os.path.join(logs_dir, filename)
        csv_file.save(csv_path)

    return 'OK', 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
