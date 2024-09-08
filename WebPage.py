from flask import Flask, render_template, jsonify, request
import sqlite3
from flask import Flask, render_template
import sqlite3
from waitress import serve
from paste.translogger import TransLogger
import ssl
import threading

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/actions')
def get_actions():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))
    offset = (page - 1) * per_page

    conn = sqlite3.connect('/home/sopqos/github/Discord-Brain-Rot/database.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.Filename, a.username, a.action, a.target, a.timestamp
        FROM actions a
        LEFT JOIN sounds s ON a.target = s.id
        ORDER BY a.id DESC
        LIMIT ? OFFSET ?
    """, (per_page, offset))
    actions = [
        {
            'filename': row[0] if row[0] else 'N/A',
            'username': row[1],
            'action': row[2],
            'target': row[3],
            'timestamp': row[4]
        }
        for row in cursor.fetchall()
    ]
    conn.close()
    return jsonify(actions)

def run_http_server():
    app.run(host='0.0.0.0', port=80)

def run_https_server():
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(
        '/etc/letsencrypt/live/gabrielagrela.com/fullchain.pem', 
        '/etc/letsencrypt/live/gabrielagrela.com/privkey.pem'
    )
    app.run(host='0.0.0.0', port=443, ssl_context=ssl_context)

if __name__ == '__main__':
    http_thread = threading.Thread(target=run_http_server)
    https_thread = threading.Thread(target=run_https_server)
    
    http_thread.start()
    https_thread.start()
    
    http_thread.join()
    https_thread.join()