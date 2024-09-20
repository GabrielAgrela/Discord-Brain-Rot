from flask import Flask, render_template, jsonify, request
import sqlite3

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/actions')
def get_actions():
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1

    per_page = int(request.args.get('per_page', 10))
    offset = (page - 1) * per_page

    conn = sqlite3.connect('/home/gabi/github/Discord-Brain-Rot/database.db')
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
            'timestamp': row[4]
        }
        for row in cursor.fetchall()
    ]
    conn.close()
    return jsonify(actions)

@app.route('/api/favorites')
def get_favorites():
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1

    per_page = int(request.args.get('per_page', 10))
    offset = (page - 1) * per_page

    conn = sqlite3.connect('/home/gabi/github/Discord-Brain-Rot/database.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT Filename, originalfilename
        FROM sounds
        WHERE favorite = 1
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """, (per_page, offset))
    favorites = [
        {
            'filename': row[0]
        }
        for row in cursor.fetchall()
    ]
    conn.close()
    return jsonify(favorites)

@app.route('/api/all_sounds')
def get_all_sounds():
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1

    per_page = int(request.args.get('per_page', 10))
    offset = (page - 1) * per_page

    conn = sqlite3.connect('/home/gabi/github/Discord-Brain-Rot/database.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT Filename, originalfilename
        FROM sounds
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """, (per_page, offset))
    all_sounds = [
        {
            'filename': row[0]
        }
        for row in cursor.fetchall()
    ]
    conn.close()
    return jsonify(all_sounds)
