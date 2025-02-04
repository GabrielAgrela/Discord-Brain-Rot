from flask import Flask, render_template, jsonify, request
import sqlite3
import math

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
            'filename': row[0] if row[0] else row[3],
            'username': row[1],
            'action': row[2],
            'timestamp': row[4]
        }
        for row in cursor.fetchall()
    ]
    conn.close()

    total_count = get_total_count('actions')
    total_pages = math.ceil(total_count / per_page)

    return jsonify({
        'items': actions,
        'total_pages': total_pages
    })

def get_total_count(table_name):
    conn = sqlite3.connect('/home/gabi/github/Discord-Brain-Rot/database.db')
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    conn.close()
    return count

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

    total_count = get_total_count('sounds WHERE favorite = 1')
    total_pages = math.ceil(total_count / per_page)

    return jsonify({
        'items': favorites,
        'total_pages': total_pages
    })

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
        SELECT Filename, originalfilename, timestamp
        FROM sounds
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """, (per_page, offset))
    all_sounds = [
        {
            'filename': row[0],
            'timestamp': row[2]
        }
        for row in cursor.fetchall()
    ]
    conn.close()

    total_count = get_total_count('sounds')
    total_pages = math.ceil(total_count / per_page)

    return jsonify({
        'items': all_sounds,
        'total_pages': total_pages
    })
