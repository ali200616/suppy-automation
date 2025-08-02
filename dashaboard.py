from flask import Flask, render_template, send_from_directory
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

    csv_files = sorted(os.listdir('logs'), reverse=True)
    csv_files = [f for f in csv_files if f.endswith('.csv')]

    return render_template('index.html',
        logs=uploads,
        files=csv_files,
        updated=datetime.now().strftime('%Y-%m-%d %H:%M')
    )

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory('logs', filename, as_attachment=True)

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
