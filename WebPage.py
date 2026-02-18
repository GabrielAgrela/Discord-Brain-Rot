from flask import Flask, render_template, jsonify, request
import sqlite3
import math
import datetime
import os

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

    conn = sqlite3.connect('Data/database.db')
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

    order_limit_offset = " ORDER BY a.timestamp DESC, a.id DESC LIMIT ? OFFSET ?"
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
    conn = sqlite3.connect('Data/database.db')
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
        query = "SELECT COUNT(*) FROM sounds WHERE is_elevenlabs = 0"
        if search_query:
            query += " AND (Filename LIKE ? OR originalfilename LIKE ?)"
            search_term = f"%{search_query}%"
            params.extend([search_term, search_term])
    elif table_name == 'sounds_fav':
        query = "SELECT COUNT(*) FROM sounds WHERE favorite = 1 AND is_elevenlabs = 0"
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

    conn = sqlite3.connect('Data/database.db')
    cursor = conn.cursor()

    # Use CTE to get most recent favorite action timestamp for each sound
    base_query = """
        WITH LatestFavorite AS (
            SELECT 
                CAST(target AS INTEGER) as sound_id,
                MAX(timestamp) as last_favorited
            FROM actions
            WHERE action = 'favorite_sound'
            GROUP BY CAST(target AS INTEGER)
        )
        SELECT s.Filename, s.originalfilename
        FROM sounds s
        LEFT JOIN LatestFavorite lf ON lf.sound_id = s.id
        WHERE s.favorite = 1 AND s.is_elevenlabs = 0
    """
    where_clause = ""
    params = []

    if search_query:
        where_clause = " AND (s.Filename LIKE ? OR s.originalfilename LIKE ?)"
        search_term = f"%{search_query}%"
        params.extend([search_term, search_term])

    order_limit_offset = " ORDER BY lf.last_favorited DESC, s.id DESC LIMIT ? OFFSET ?"
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

    conn = sqlite3.connect('Data/database.db')
    cursor = conn.cursor()

    base_query = "SELECT Filename, originalfilename, timestamp FROM sounds WHERE is_elevenlabs = 0"
    where_clause = ""
    params = []

    if search_query:
        where_clause = " AND (Filename LIKE ? OR originalfilename LIKE ?)"
        search_term = f"%{search_query}%"
        params.extend([search_term, search_term])

    order_limit_offset = " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?"
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
    requested_guild_id = data.get('guild_id')

    if not sound_filename:
        return jsonify({'error': 'Missing sound_filename'}), 400

    guild_id_raw = requested_guild_id or os.getenv("DEFAULT_GUILD_ID", "")
    if not guild_id_raw:
        return jsonify({'error': 'Missing guild_id'}), 400
    try:
        guild_id = int(guild_id_raw)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid guild_id'}), 400

    try:
        conn = sqlite3.connect('Data/database.db')
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO playback_queue (guild_id, sound_filename)
            VALUES (?, ?)
        """,
            (guild_id, sound_filename),
        )
        conn.commit()
        conn.close()
        return jsonify({'message': 'Playback request queued'}), 200
    except sqlite3.Error as e:
        print(f"Database error queuing playback: {e}")
        return jsonify({'error': 'Database error'}), 500
    except Exception as e:
        print(f"Error queuing playback: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ===== Analytics Dashboard =====

@app.route('/analytics')
def analytics():
    """Render the analytics dashboard page."""
    return render_template('analytics.html')


@app.route('/api/analytics/summary')
def get_analytics_summary():
    """Get summary statistics for the dashboard."""
    try:
        days = int(request.args.get('days', 0))
    except ValueError:
        days = 0
    
    conn = sqlite3.connect('Data/database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    stats = {
        'total_sounds': 0,
        'total_plays': 0,
        'active_users': 0,
        'sounds_this_week': 0
    }
    
    # Total sounds
    cursor.execute("SELECT COUNT(*) as count FROM sounds")
    row = cursor.fetchone()
    stats['total_sounds'] = row['count'] if row else 0
    
    # Build time filter
    time_filter = ""
    params = []
    if days > 0:
        from datetime import timedelta
        cutoff = (datetime.datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        time_filter = "AND timestamp >= ?"
        params.append(cutoff)
    
    # Total plays
    cursor.execute(
        f"""
        SELECT COUNT(*) as count FROM actions 
        WHERE action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                       'play_request', 'play_from_list', 'play_similar_sound', 'play_sound_periodically', 'play_sound_generic')
        {time_filter}
        """,
        tuple(params)
    )
    row = cursor.fetchone()
    stats['total_plays'] = row['count'] if row else 0
    
    # Active users
    cursor.execute(
        f"""
        SELECT COUNT(DISTINCT username) as count FROM actions 
        WHERE action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                       'play_request', 'play_from_list', 'play_similar_sound')
        {time_filter}
        """,
        tuple(params)
    )
    row = cursor.fetchone()
    stats['active_users'] = row['count'] if row else 0
    
    # Sounds added this week
    from datetime import timedelta
    week_ago = (datetime.datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("SELECT COUNT(*) as count FROM sounds WHERE timestamp >= ?", (week_ago,))
    row = cursor.fetchone()
    stats['sounds_this_week'] = row['count'] if row else 0
    
    conn.close()
    return jsonify(stats)


@app.route('/api/analytics/top_users')
def get_analytics_top_users():
    """Get top users by play count."""
    try:
        days = int(request.args.get('days', 7))
        limit = int(request.args.get('limit', 10))
    except ValueError:
        days = 7
        limit = 10
    
    conn = sqlite3.connect('Data/database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    time_filter = ""
    params = []
    if days > 0:
        from datetime import timedelta
        cutoff = (datetime.datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        time_filter = "AND timestamp >= ?"
        params.append(cutoff)
    
    params.append(limit)
    
    cursor.execute(
        f"""
        SELECT username, COUNT(*) as count
        FROM actions
        WHERE action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                        'play_request', 'play_from_list', 'play_similar_sound')
        {time_filter}
        GROUP BY username
        ORDER BY count DESC
        LIMIT ?
        """,
        tuple(params)
    )
    
    users = [{'username': row['username'], 'count': row['count']} for row in cursor.fetchall()]
    conn.close()
    return jsonify({'users': users})


@app.route('/api/analytics/top_sounds')
def get_analytics_top_sounds():
    """Get top played sounds."""
    try:
        days = int(request.args.get('days', 7))
        limit = int(request.args.get('limit', 10))
    except ValueError:
        days = 7
        limit = 10
    
    conn = sqlite3.connect('Data/database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    time_filter = ""
    params = []
    if days > 0:
        from datetime import timedelta
        cutoff = (datetime.datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        time_filter = "AND a.timestamp >= ?"
        params.append(cutoff)
    
    params.append(limit)
    
    cursor.execute(
        f"""
        SELECT s.Filename, COUNT(*) as count
        FROM actions a
        JOIN sounds s ON a.target = s.id
        WHERE a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                          'play_request', 'play_from_list', 'play_similar_sound', 'play_sound_periodically', 'play_sound_generic')
        AND s.slap = 0
        {time_filter}
        GROUP BY s.Filename
        ORDER BY count DESC
        LIMIT ?
        """,
        tuple(params)
    )
    
    sounds = [{'filename': row['Filename'], 'count': row['count']} for row in cursor.fetchall()]
    conn.close()
    return jsonify({'sounds': sounds})


@app.route('/api/analytics/activity_heatmap')
def get_analytics_heatmap():
    """Get activity heatmap data (day of week x hour)."""
    try:
        days = int(request.args.get('days', 30))
    except ValueError:
        days = 30
    
    conn = sqlite3.connect('Data/database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    time_filter = ""
    params = []
    if days > 0:
        from datetime import timedelta
        cutoff = (datetime.datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        time_filter = "AND timestamp >= ?"
        params.append(cutoff)
    
    cursor.execute(
        f"""
        SELECT 
            CAST(strftime('%w', timestamp) AS INTEGER) as day_of_week,
            CAST(strftime('%H', timestamp) AS INTEGER) as hour,
            COUNT(*) as count
        FROM actions
        WHERE action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                        'play_request', 'play_from_list', 'play_similar_sound', 'play_sound_periodically', 'play_sound_generic')
        {time_filter}
        GROUP BY day_of_week, hour
        ORDER BY day_of_week, hour
        """,
        tuple(params)
    )
    
    heatmap = [{'day': row['day_of_week'], 'hour': row['hour'], 'count': row['count']} for row in cursor.fetchall()]
    conn.close()
    return jsonify({'heatmap': heatmap})


@app.route('/api/analytics/activity_timeline')
def get_analytics_timeline():
    """Get activity for timeline chart. Groups by week for all-time, by day otherwise."""
    try:
        days = int(request.args.get('days', 30))
    except ValueError:
        days = 30
    
    conn = sqlite3.connect('Data/database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    from datetime import timedelta
    
    if days == 0:
        # All time: group by week for readability
        cursor.execute(
            """
            SELECT 
                strftime('%Y-W%W', timestamp) as period,
                MIN(date(timestamp)) as date,
                COUNT(*) as count
            FROM actions
            WHERE action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                           'play_request', 'play_from_list', 'play_similar_sound', 'play_sound_periodically',
                           'play_sound_generic')
            GROUP BY period
            ORDER BY period ASC
            """
        )
    else:
        # Limited time: group by day
        cutoff = (datetime.datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        cursor.execute(
            """
            SELECT 
                date(timestamp) as date,
                COUNT(*) as count
            FROM actions
            WHERE action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                           'play_request', 'play_from_list', 'play_similar_sound', 'play_sound_periodically',
                           'play_sound_generic')
            AND date(timestamp) >= ?
            GROUP BY date(timestamp)
            ORDER BY date(timestamp) ASC
            """,
            (cutoff,)
        )
    
    timeline = [{'date': row['date'], 'count': row['count']} for row in cursor.fetchall()]
    conn.close()
    return jsonify({'timeline': timeline})


@app.route('/api/analytics/recent_activity')
def get_analytics_recent():
    """Get recent activity feed."""
    try:
        limit = int(request.args.get('limit', 20))
    except ValueError:
        limit = 20
    
    conn = sqlite3.connect('Data/database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT a.username, a.action, a.timestamp, s.Filename
        FROM actions a
        LEFT JOIN sounds s ON a.target = s.id
        WHERE a.action IN ('play_random_sound', 'replay_sound', 'play_random_favorite_sound', 
                          'play_request', 'play_from_list', 'play_similar_sound', 'play_sound_periodically',
                          'favorite_sound', 'unfavorite_sound', 'join', 'leave')
        ORDER BY a.id DESC
        LIMIT ?
        """,
        (limit,)
    )
    
    activities = []
    for row in cursor.fetchall():
        activities.append({
            'username': row['username'],
            'action': row['action'],
            'timestamp': row['timestamp'],
            'sound': row['Filename'] if row['Filename'] else None
        })
    
    conn.close()
    return jsonify({'activities': activities})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
