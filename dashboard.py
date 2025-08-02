from flask import Flask, render_template, send_from_directory, request
import os
from datetime import datetime

app = Flask(__name__)

@app.route('/')
def index():
    log_file = 'logs/integration-log.txt'
    uploads = []

    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            lines = f.readlines()
        for line in reversed(lines[-50:]):
            uploads.append(line.strip())

    if not os.path.exists('logs'):
        os.makedirs('logs')

    csv_files = sorted(
        [f for f in os.listdir('logs') if f.endswith('.csv')],
        reverse=True
    )

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
    print("📥 Received upload")

    if not os.path.exists('logs'):
        os.makedirs('logs')
        print("📁 Created logs/ folder")

    log_text = request.form.get('log')
    filename = request.form.get('filename')
    csv_file = request.files.get('file')

    if log_text:
        with open('logs/integration-log.txt', 'a') as f:
            f.write(log_text + '\n')
        print("📝 Log saved")

    if csv_file and filename:
        path = os.path.join('logs', filename)
        csv_file.save(path)
        print(f"✅ Saved file: {filename}")
    else:
        print("❌ Missing CSV or filename")

    return 'OK', 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
