from flask import Flask, render_template, jsonify, request
import sqlite3

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
    cursor.execute("SELECT * FROM actions ORDER BY id DESC LIMIT ? OFFSET ?", (per_page, offset))
    actions = [
        {
            'id': row[0],
            'username': row[1],
            'action': row[2],
            'target': row[3],
            'timestamp': row[4]
        }
        for row in cursor.fetchall()
    ]
    conn.close()
    return jsonify(actions)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)