from flask import Flask, render_template, jsonify, request
import math
import os
from src.common.database import Database
from src.common.config import Config

app = Flask(__name__,
            template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates')),
            static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), 'static')))

db = Database()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/actions')
def get_actions():
    page = max(1, int(request.args.get('page', 1)))
    per_page = int(request.args.get('per_page', 10))
    offset = (page - 1) * per_page
    search_query = request.args.get('search', '').strip()

    base_query = """
        SELECT s.Filename, a.username, a.action, a.target, a.timestamp
        FROM actions a
        LEFT JOIN sounds s ON a.target = s.id
    """
    where_clause = ""
    params = []

    if search_query:
        where_clause = " WHERE (a.username LIKE ? OR a.action LIKE ? OR a.target LIKE ? OR (s.Filename IS NOT NULL AND s.Filename LIKE ?))"
        search_term = f"%{search_query}%"
        params.extend([search_term, search_term, search_term, search_term])

    query = base_query + where_clause + " ORDER BY a.id DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    rows = db.fetch_all(query, tuple(params))

    actions = [
        {
            'filename': row['Filename'] if row['Filename'] else row['target'],
            'username': row['username'],
            'action': row['action'],
            'timestamp': row['timestamp']
        }
        for row in rows
    ]

    count_query = "SELECT COUNT(*) as count FROM actions a LEFT JOIN sounds s ON a.target = s.id" + where_clause
    count_result = db.fetch_one(count_query, tuple(params[:-2]))
    total_count = count_result['count'] if count_result else 0
    total_pages = math.ceil(total_count / per_page)

    return jsonify({
        'items': actions,
        'total_pages': total_pages
    })

@app.route('/api/favorites')
def get_favorites():
    page = max(1, int(request.args.get('page', 1)))
    per_page = int(request.args.get('per_page', 10))
    offset = (page - 1) * per_page
    search_query = request.args.get('search', '').strip()

    base_query = "SELECT Filename, originalfilename FROM sounds WHERE favorite = 1"
    where_clause = ""
    params = []

    if search_query:
        where_clause = " AND (Filename LIKE ? OR originalfilename LIKE ?)"
        search_term = f"%{search_query}%"
        params.extend([search_term, search_term])

    query = base_query + where_clause + " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    rows = db.fetch_all(query, tuple(params))
    favorites = [{'filename': row['Filename']} for row in rows]

    count_query = "SELECT COUNT(*) as count FROM sounds WHERE favorite = 1" + where_clause
    count_result = db.fetch_one(count_query, tuple(params[:-2]))
    total_count = count_result['count'] if count_result else 0
    total_pages = math.ceil(total_count / per_page)

    return jsonify({'items': favorites, 'total_pages': total_pages})

@app.route('/api/all_sounds')
def get_all_sounds():
    page = max(1, int(request.args.get('page', 1)))
    per_page = int(request.args.get('per_page', 10))
    offset = (page - 1) * per_page
    search_query = request.args.get('search', '').strip()

    base_query = "SELECT Filename, originalfilename, timestamp FROM sounds"
    where_clause = ""
    params = []

    if search_query:
        where_clause = " WHERE (Filename LIKE ? OR originalfilename LIKE ?)"
        search_term = f"%{search_query}%"
        params.extend([search_term, search_term])

    query = base_query + where_clause + " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    rows = db.fetch_all(query, tuple(params))
    all_sounds = [{'filename': row['Filename'], 'timestamp': row['timestamp']} for row in rows]

    count_query = "SELECT COUNT(*) as count FROM sounds" + (where_clause.replace("WHERE", "AND") if where_clause else "")
    if not where_clause: count_query = "SELECT COUNT(*) as count FROM sounds"
    elif where_clause: count_query = "SELECT COUNT(*) as count FROM sounds" + where_clause

    count_result = db.fetch_one(count_query, tuple(params[:-2]))
    total_count = count_result['count'] if count_result else 0
    total_pages = math.ceil(total_count / per_page)

    return jsonify({'items': all_sounds, 'total_pages': total_pages})

@app.route('/api/play_sound', methods=['POST'])
def request_play_sound():
    data = request.get_json()
    sound_filename = data.get('sound_filename')
    if not sound_filename:
        return jsonify({'error': 'Missing sound_filename'}), 400

    guild_id = 359077662742020107 # TODO: Move to config

    try:
        db.execute_update(
            "INSERT INTO playback_queue (guild_id, sound_filename) VALUES (?, ?)",
            (guild_id, sound_filename)
        )
        return jsonify({'message': 'Playback request queued'}), 200
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': 'Internal error'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
