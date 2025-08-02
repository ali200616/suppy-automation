from flask import Flask, render_template, send_from_directory, request
import os
from datetime import datetime

app = Flask(__name__, static_folder='static')

@app.route('/')
def index():
    logs_dir = 'logs'
    log_file = os.path.join(logs_dir, 'integration-log.txt')
    uploads = []

    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
        print("📁 Created logs folder")

    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            lines = f.readlines()
        for line in reversed(lines[-50:]):
            uploads.append(line.strip())
        print(f"📄 Loaded {len(uploads)} log lines")
    else:
        print("⚠️ No integration-log.txt found")

    csv_files = []
    for file in sorted(os.listdir(logs_dir), reverse=True):
        if file.endswith('.csv'):
            csv_files.append(file)
    print(f"🧾 Found {len(csv_files)} CSV files")

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
        print("📁 Created logs folder in upload")

    log_text = request.form.get('log')
    filename = request.form.get('filename')
    csv_file = request.files.get('file')

    if log_text:
        log_path = os.path.join(logs_dir, 'integration-log.txt')
        with open(log_path, 'a') as f:
            f.write(log_text + '\n')
        print("📝 Log appended")
    else:
        print("⚠️ No log text received")

    if csv_file and filename:
        path = os.path.join(logs_dir, filename)
        csv_file.save(path)
        print(f"✅ Saved CSV to {path}")
    else:
        print("❌ Missing CSV file or filename in upload")

    return 'OK', 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
