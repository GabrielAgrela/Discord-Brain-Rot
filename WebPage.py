from flask import Flask, render_template, jsonify, request
import sqlite3
import math
import datetime

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
    search_query = request.args.get('search', '').strip()

    conn = sqlite3.connect('/home/gabi/github/Discord-Brain-Rot/database.db')
    cursor = conn.cursor()
    
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

    order_limit_offset = " ORDER BY a.id DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    final_query = base_query + where_clause + order_limit_offset
    cursor.execute(final_query, tuple(params))
    
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

    total_count = get_total_count('actions', search_query)
    total_pages = math.ceil(total_count / per_page)

    return jsonify({
        'items': actions,
        'total_pages': total_pages
    })

def get_total_count(table_name, search_query=None):
    conn = sqlite3.connect('/home/gabi/github/Discord-Brain-Rot/database.db')
    cursor = conn.cursor()
    params = []
    where_clause = ""

    if table_name == 'actions':
        base_query = "SELECT COUNT(*) FROM actions a LEFT JOIN sounds s ON a.target = s.id"
        if search_query:
             where_clause = " WHERE (a.username LIKE ? OR a.action LIKE ? OR a.target LIKE ? OR (s.Filename IS NOT NULL AND s.Filename LIKE ?))"
             search_term = f"%{search_query}%"
             params.extend([search_term, search_term, search_term, search_term])
        query = base_query + where_clause
    elif table_name == 'sounds':
        query = "SELECT COUNT(*) FROM sounds"
        if search_query:
            query += " WHERE (Filename LIKE ? OR originalfilename LIKE ?)"
            search_term = f"%{search_query}%"
            params.extend([search_term, search_term])
    elif table_name == 'sounds_fav':
        query = "SELECT COUNT(*) FROM sounds WHERE favorite = 1"
        if search_query:
            query += " AND (Filename LIKE ? OR originalfilename LIKE ?)"
            search_term = f"%{search_query}%"
            params.extend([search_term, search_term])
    else:
        query = f"SELECT COUNT(*) FROM {table_name}" 

    cursor.execute(query, tuple(params))
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
    search_query = request.args.get('search', '').strip()

    conn = sqlite3.connect('/home/gabi/github/Discord-Brain-Rot/database.db')
    cursor = conn.cursor()

    base_query = "SELECT Filename, originalfilename FROM sounds WHERE favorite = 1"
    where_clause = ""
    params = []

    if search_query:
        where_clause = " AND (Filename LIKE ? OR originalfilename LIKE ?)"
        search_term = f"%{search_query}%"
        params.extend([search_term, search_term])

    order_limit_offset = " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    final_query = base_query + where_clause + order_limit_offset
    cursor.execute(final_query, tuple(params))

    favorites = [
        {
            'filename': row[0]
        }
        for row in cursor.fetchall()
    ]
    conn.close()

    total_count = get_total_count('sounds_fav', search_query)
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
    search_query = request.args.get('search', '').strip()

    conn = sqlite3.connect('/home/gabi/github/Discord-Brain-Rot/database.db')
    cursor = conn.cursor()

    base_query = "SELECT Filename, originalfilename, timestamp FROM sounds"
    where_clause = ""
    params = []

    if search_query:
        where_clause = " WHERE (Filename LIKE ? OR originalfilename LIKE ?)"
        search_term = f"%{search_query}%"
        params.extend([search_term, search_term])

    order_limit_offset = " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    final_query = base_query + where_clause + order_limit_offset
    cursor.execute(final_query, tuple(params))

    all_sounds = [
        {
            'filename': row[0],
            'timestamp': row[2]
        }
        for row in cursor.fetchall()
    ]
    conn.close()

    total_count = get_total_count('sounds', search_query)
    total_pages = math.ceil(total_count / per_page)

    return jsonify({
        'items': all_sounds,
        'total_pages': total_pages
    })

# New endpoint to request sound playback
@app.route('/api/play_sound', methods=['POST'])
def request_play_sound():
    data = request.get_json()
    sound_filename = data.get('sound_filename')

    if not sound_filename:
        return jsonify({'error': 'Missing sound_filename'}), 400

    # --- IMPORTANT: Replace YOUR_DEFAULT_GUILD_ID with the actual server ID ---
    guild_id = 359077662742020107 # YOUR_DEFAULT_GUILD_ID 
    # ----------------------------------------------------------------------

    try:
        conn = sqlite3.connect('/home/gabi/github/Discord-Brain-Rot/database.db')
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO playback_queue (guild_id, sound_filename)
            VALUES (?, ?)
        """, (guild_id, sound_filename))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Playback request queued'}), 200
    except sqlite3.Error as e:
        print(f"Database error queuing playback: {e}")
        return jsonify({'error': 'Database error'}), 500
    except Exception as e:
        print(f"Error queuing playback: {e}")
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
