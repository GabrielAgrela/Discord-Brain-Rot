import datetime
import math
import os
import sqlite3
from collections.abc import Sequence
from functools import wraps
from urllib.parse import urlencode, urlparse

import requests
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from bot.repositories.sound import SoundRepository
from bot.services.text_censor import TextCensorService
from bot.services.web_playback import queue_playback_request

app = Flask(__name__)
app.config.setdefault("DATABASE_PATH", "Data/database.db")
app.config.setdefault("SECRET_KEY", os.getenv("WEB_SESSION_SECRET", "discord-brain-rot-web-dev"))
app.config.setdefault("DISCORD_API_BASE_URL", "https://discord.com/api")
text_censor_service = TextCensorService()


def _get_db_connection(*, row_factory: sqlite3.Row | None = None) -> sqlite3.Connection:
    """Create a SQLite connection using the configured database path."""
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    if row_factory is not None:
        conn.row_factory = row_factory
    return conn


def _censor_text(value: str | None) -> str | None:
    """Censor hateful text for web responses."""
    return text_censor_service.censor_text(value)


def _parse_positive_int_arg(name: str, default: int) -> int:
    """Return a positive integer query arg or the provided default."""
    try:
        return max(1, int(request.args.get(name, default)))
    except (TypeError, ValueError):
        return default


def _build_in_clause(column: str, values: Sequence[str]) -> tuple[str, list[str]]:
    """Build a parameterized IN clause for SQLite."""
    placeholders = ", ".join("?" for _ in values)
    return f"{column} IN ({placeholders})", list(values)


def _get_filter_values(param_name: str) -> list[str]:
    """Return normalized multi-value filters from the query string."""
    return [value.strip() for value in request.args.getlist(param_name) if value.strip()]


def _fetch_distinct_values(
    cursor: sqlite3.Cursor,
    query: str,
    params: Sequence[object],
) -> list[str]:
    """Fetch a distinct string column list, excluding empty values."""
    cursor.execute(query, tuple(params))
    values: list[str] = []
    for (value,) in cursor.fetchall():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            values.append(text)
    return values


def _resolve_sound_filename_for_request(payload: dict) -> str:
    """Resolve a playback request payload into a real sound filename."""
    sound_filename = str(payload.get("sound_filename", "")).strip()
    if sound_filename:
        return sound_filename

    sound_id = payload.get("sound_id")
    if sound_id in (None, ""):
        raise ValueError("Missing sound_filename")

    try:
        sound_id_int = int(sound_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid sound_id") from exc

    sound = SoundRepository(
        db_path=app.config["DATABASE_PATH"],
        use_shared=False,
    ).get_by_id(sound_id_int)
    if sound is None:
        raise ValueError("Unknown sound_id")
    return sound.filename


def _get_discord_oauth_config() -> dict[str, str]:
    """Return Discord OAuth configuration from the environment."""
    return {
        "client_id": os.getenv("DISCORD_OAUTH_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("DISCORD_OAUTH_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv("DISCORD_OAUTH_REDIRECT_URI", "").strip(),
    }


def _discord_oauth_is_configured() -> bool:
    """Return True when the required Discord OAuth env vars are configured."""
    config = _get_discord_oauth_config()
    return bool(config["client_id"] and config["client_secret"])


def _build_discord_redirect_uri() -> str:
    """Return the Discord OAuth callback URL."""
    redirect_uri = _get_discord_oauth_config()["redirect_uri"]
    if redirect_uri:
        return redirect_uri
    return url_for("discord_callback", _external=True)


def _sanitize_next_path(next_path: str | None) -> str:
    """Allow only local relative redirect targets."""
    if not next_path:
        return url_for("index")
    parsed = urlparse(next_path)
    if parsed.scheme or parsed.netloc:
        return url_for("index")
    if not next_path.startswith("/"):
        return url_for("index")
    return next_path


def _get_current_discord_user() -> dict[str, str] | None:
    """Return the logged-in Discord user payload stored in session."""
    user = session.get("discord_user")
    if not isinstance(user, dict):
        return None
    if not user.get("id") or not user.get("username"):
        return None
    return user


def _require_discord_login_api(view_func):
    """Require an authenticated Discord user for JSON API access."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if _get_current_discord_user() is None:
            return jsonify(
                {
                    "error": "Discord login required",
                    "login_url": url_for("login", next=request.path),
                }
            ), 401
        return view_func(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_auth_context():
    """Expose Discord auth state to templates."""
    return {
        "discord_user": _get_current_discord_user(),
        "discord_oauth_configured": _discord_oauth_is_configured(),
        "discord_login_url": url_for("login", next=request.path),
    }


@app.route("/login")
def login():
    """Start Discord OAuth login."""
    if not _discord_oauth_is_configured():
        return "Discord OAuth is not configured on this server.", 503

    next_path = _sanitize_next_path(request.args.get("next"))
    session["oauth_next_path"] = next_path
    state = os.urandom(24).hex()
    session["discord_oauth_state"] = state

    query = urlencode(
        {
            "client_id": _get_discord_oauth_config()["client_id"],
            "redirect_uri": _build_discord_redirect_uri(),
            "response_type": "code",
            "scope": "identify",
            "state": state,
            "prompt": "none",
        }
    )
    return redirect(f"https://discord.com/oauth2/authorize?{query}")


@app.route("/auth/discord/callback")
def discord_callback():
    """Handle Discord OAuth callback and persist the user in session."""
    if not _discord_oauth_is_configured():
        return "Discord OAuth is not configured on this server.", 503

    if request.args.get("error"):
        return f"Discord login failed: {request.args['error']}", 400

    expected_state = session.pop("discord_oauth_state", None)
    returned_state = request.args.get("state", "")
    if not expected_state or expected_state != returned_state:
        return "Discord login failed: invalid state", 400

    code = request.args.get("code", "").strip()
    if not code:
        return "Discord login failed: missing code", 400

    oauth_config = _get_discord_oauth_config()
    token_response = requests.post(
        f"{app.config['DISCORD_API_BASE_URL']}/oauth2/token",
        data={
            "client_id": oauth_config["client_id"],
            "client_secret": oauth_config["client_secret"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _build_discord_redirect_uri(),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if not token_response.ok:
        return "Discord login failed during token exchange", 502

    access_token = token_response.json().get("access_token", "").strip()
    if not access_token:
        return "Discord login failed: missing access token", 502

    user_response = requests.get(
        f"{app.config['DISCORD_API_BASE_URL']}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if not user_response.ok:
        return "Discord login failed while loading user profile", 502

    user_payload = user_response.json()
    session["discord_user"] = {
        "id": str(user_payload["id"]),
        "username": str(user_payload["username"]),
        "global_name": str(user_payload.get("global_name") or user_payload["username"]),
        "avatar": str(user_payload.get("avatar") or ""),
    }
    return redirect(_sanitize_next_path(session.pop("oauth_next_path", None)))


@app.route("/logout")
def logout():
    """Clear the current Discord web session."""
    session.pop("discord_user", None)
    session.pop("discord_oauth_state", None)
    return redirect(_sanitize_next_path(request.args.get("next") or url_for("index")))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/actions')
def get_actions():
    page = _parse_positive_int_arg('page', 1)
    per_page = _parse_positive_int_arg('per_page', 10)
    offset = (page - 1) * per_page
    search_query = request.args.get('search', '').strip()
    action_filters = _get_filter_values('action')
    user_filters = _get_filter_values('user')
    sound_filters = _get_filter_values('sound')

    conn = _get_db_connection()
    cursor = conn.cursor()
    
    base_query = """
        SELECT s.Filename, a.username, a.action, a.target, a.timestamp
        FROM actions a
        LEFT JOIN sounds s ON a.target = s.id
    """
    conditions = []
    params: list[object] = []
    if search_query:
        search_term = f"%{search_query}%"
        conditions.append("(a.username LIKE ? OR a.action LIKE ? OR a.target LIKE ? OR (s.Filename IS NOT NULL AND s.Filename LIKE ?))")
        params.extend([search_term, search_term, search_term, search_term])

    if action_filters:
        clause, clause_params = _build_in_clause("a.action", action_filters)
        conditions.append(clause)
        params.extend(clause_params)

    if user_filters:
        clause, clause_params = _build_in_clause("a.username", user_filters)
        conditions.append(clause)
        params.extend(clause_params)

    if sound_filters:
        clause, clause_params = _build_in_clause("COALESCE(s.Filename, a.target)", sound_filters)
        conditions.append(clause)
        params.extend(clause_params)

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    order_limit_offset = " ORDER BY a.timestamp DESC, a.id DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    final_query = base_query + where_clause + order_limit_offset
    cursor.execute(final_query, tuple(params))
    
    actions = [
        {
            'display_filename': _censor_text(row[0] if row[0] else row[3]),
            'display_username': _censor_text(row[1]),
            'action': row[2],
            'timestamp': row[4]
        }
        for row in cursor.fetchall()
    ]

    total_count = get_total_count(
        'actions',
        search_query,
        filters={
            'action': action_filters,
            'user': user_filters,
            'sound': sound_filters,
        },
    )
    total_pages = math.ceil(total_count / per_page)

    filter_options = {
        'action': _fetch_distinct_values(
            cursor,
            """
            SELECT DISTINCT action
            FROM actions
            WHERE action IS NOT NULL AND TRIM(action) != ''
            ORDER BY action COLLATE NOCASE ASC
            """,
            (),
        ),
        'user': _fetch_distinct_values(
            cursor,
            """
            SELECT DISTINCT username
            FROM actions
            WHERE username IS NOT NULL AND TRIM(username) != ''
            ORDER BY username COLLATE NOCASE ASC
            """,
            (),
        ),
        'sound': _fetch_distinct_values(
            cursor,
            """
            SELECT DISTINCT COALESCE(s.Filename, a.target) AS sound_value
            FROM actions a
            LEFT JOIN sounds s ON a.target = s.id
            WHERE COALESCE(s.Filename, a.target) IS NOT NULL
              AND TRIM(COALESCE(s.Filename, a.target)) != ''
            ORDER BY sound_value COLLATE NOCASE ASC
            """,
            (),
        ),
    }
    conn.close()

    return jsonify({
        'items': actions,
        'total_pages': total_pages,
        'filters': filter_options,
    })

def get_total_count(table_name, search_query=None, filters: dict[str, list[str]] | None = None):
    conn = _get_db_connection()
    cursor = conn.cursor()
    params: list[object] = []
    filters = filters or {}

    if table_name == 'actions':
        base_query = "SELECT COUNT(*) FROM actions a LEFT JOIN sounds s ON a.target = s.id"
        conditions = []
        if search_query:
            search_term = f"%{search_query}%"
            conditions.append("(a.username LIKE ? OR a.action LIKE ? OR a.target LIKE ? OR (s.Filename IS NOT NULL AND s.Filename LIKE ?))")
            params.extend([search_term, search_term, search_term, search_term])
        if filters.get('action'):
            clause, clause_params = _build_in_clause("a.action", filters['action'])
            conditions.append(clause)
            params.extend(clause_params)
        if filters.get('user'):
            clause, clause_params = _build_in_clause("a.username", filters['user'])
            conditions.append(clause)
            params.extend(clause_params)
        if filters.get('sound'):
            clause, clause_params = _build_in_clause("COALESCE(s.Filename, a.target)", filters['sound'])
            conditions.append(clause)
            params.extend(clause_params)
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = base_query + where_clause
    elif table_name == 'sounds':
        query = "SELECT COUNT(*) FROM sounds WHERE is_elevenlabs = 0"
        if search_query:
            query += " AND (Filename LIKE ? OR originalfilename LIKE ?)"
            search_term = f"%{search_query}%"
            params.extend([search_term, search_term])
        if filters.get('sound'):
            clause, clause_params = _build_in_clause("Filename", filters['sound'])
            query += f" AND {clause}"
            params.extend(clause_params)
        if filters.get('date'):
            clause, clause_params = _build_in_clause("date(timestamp)", filters['date'])
            query += f" AND {clause}"
            params.extend(clause_params)
    elif table_name == 'sounds_fav':
        query = "SELECT COUNT(*) FROM sounds WHERE favorite = 1 AND is_elevenlabs = 0"
        if search_query:
            query += " AND (Filename LIKE ? OR originalfilename LIKE ?)"
            search_term = f"%{search_query}%"
            params.extend([search_term, search_term])
        if filters.get('sound'):
            clause, clause_params = _build_in_clause("Filename", filters['sound'])
            query += f" AND {clause}"
            params.extend(clause_params)
    else:
        query = f"SELECT COUNT(*) FROM {table_name}" 

    cursor.execute(query, tuple(params))
    count = cursor.fetchone()[0]
    conn.close()
    return count

@app.route('/api/favorites')
def get_favorites():
    page = _parse_positive_int_arg('page', 1)
    per_page = _parse_positive_int_arg('per_page', 10)
    offset = (page - 1) * per_page
    search_query = request.args.get('search', '').strip()
    sound_filters = _get_filter_values('sound')

    conn = _get_db_connection()
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
        SELECT s.id, s.Filename, s.originalfilename
        FROM sounds s
        LEFT JOIN LatestFavorite lf ON lf.sound_id = s.id
        WHERE s.favorite = 1 AND s.is_elevenlabs = 0
    """
    params: list[object] = []

    if search_query:
        search_term = f"%{search_query}%"
        where_clause = " AND (s.Filename LIKE ? OR s.originalfilename LIKE ?)"
        params.extend([search_term, search_term])
    else:
        where_clause = ""

    if sound_filters:
        clause, clause_params = _build_in_clause("s.Filename", sound_filters)
        where_clause += f" AND {clause}"
        params.extend(clause_params)

    order_limit_offset = " ORDER BY lf.last_favorited DESC, s.id DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    final_query = base_query + where_clause + order_limit_offset
    cursor.execute(final_query, tuple(params))

    favorites = [
        {
            'sound_id': row[0],
            'display_filename': _censor_text(row[1]),
        }
        for row in cursor.fetchall()
    ]

    total_count = get_total_count('sounds_fav', search_query, filters={'sound': sound_filters})
    total_pages = math.ceil(total_count / per_page)

    filter_options = {
        'sound': _fetch_distinct_values(
            cursor,
            """
            SELECT DISTINCT Filename
            FROM sounds
            WHERE favorite = 1 AND is_elevenlabs = 0 AND Filename IS NOT NULL AND TRIM(Filename) != ''
            ORDER BY Filename COLLATE NOCASE ASC
            """,
            (),
        ),
    }
    conn.close()

    return jsonify({
        'items': favorites,
        'total_pages': total_pages,
        'filters': filter_options,
    })

@app.route('/api/all_sounds')
def get_all_sounds():
    page = _parse_positive_int_arg('page', 1)
    per_page = _parse_positive_int_arg('per_page', 10)
    offset = (page - 1) * per_page
    search_query = request.args.get('search', '').strip()
    sound_filters = _get_filter_values('sound')
    date_filters = _get_filter_values('date')

    conn = _get_db_connection()
    cursor = conn.cursor()

    base_query = "SELECT id, Filename, originalfilename, timestamp FROM sounds WHERE is_elevenlabs = 0"
    where_clause = ""
    params: list[object] = []

    if search_query:
        where_clause = " AND (Filename LIKE ? OR originalfilename LIKE ?)"
        search_term = f"%{search_query}%"
        params.extend([search_term, search_term])

    if sound_filters:
        clause, clause_params = _build_in_clause("Filename", sound_filters)
        where_clause += f" AND {clause}"
        params.extend(clause_params)

    if date_filters:
        clause, clause_params = _build_in_clause("date(timestamp)", date_filters)
        where_clause += f" AND {clause}"
        params.extend(clause_params)

    order_limit_offset = " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    final_query = base_query + where_clause + order_limit_offset
    cursor.execute(final_query, tuple(params))

    all_sounds = [
        {
            'sound_id': row[0],
            'display_filename': _censor_text(row[1]),
            'timestamp': row[3]
        }
        for row in cursor.fetchall()
    ]

    total_count = get_total_count(
        'sounds',
        search_query,
        filters={
            'sound': sound_filters,
            'date': date_filters,
        },
    )
    total_pages = math.ceil(total_count / per_page)

    filter_options = {
        'sound': _fetch_distinct_values(
            cursor,
            """
            SELECT DISTINCT Filename
            FROM sounds
            WHERE is_elevenlabs = 0 AND Filename IS NOT NULL AND TRIM(Filename) != ''
            ORDER BY Filename COLLATE NOCASE ASC
            """,
            (),
        ),
        'date': _fetch_distinct_values(
            cursor,
            """
            SELECT DISTINCT date(timestamp) AS sound_date
            FROM sounds
            WHERE is_elevenlabs = 0 AND timestamp IS NOT NULL AND TRIM(timestamp) != ''
            ORDER BY sound_date DESC
            """,
            (),
        ),
    }
    conn.close()

    return jsonify({
        'items': all_sounds,
        'total_pages': total_pages,
        'filters': filter_options,
    })

# New endpoint to request sound playback
@app.route('/api/play_sound', methods=['POST'])
@_require_discord_login_api
def request_play_sound():
    data = request.get_json(silent=True) or {}
    current_user = _get_current_discord_user()

    try:
        sound_filename = _resolve_sound_filename_for_request(data)
        queue_playback_request(
            sound_filename=sound_filename,
            requested_guild_id=data.get('guild_id'),
            db_path=app.config["DATABASE_PATH"],
            request_username=current_user["global_name"],
            request_user_id=current_user["id"],
        )
        return jsonify({'message': 'Playback request queued'}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
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
    
    conn = _get_db_connection(row_factory=sqlite3.Row)
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
    
    conn = _get_db_connection(row_factory=sqlite3.Row)
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
    
    users = [
        {'display_username': _censor_text(row['username']), 'count': row['count']}
        for row in cursor.fetchall()
    ]
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
    
    conn = _get_db_connection(row_factory=sqlite3.Row)
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
        SELECT MIN(s.id) as sound_id, s.Filename, COUNT(*) as count
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
    
    sounds = [
        {
            'sound_id': row['sound_id'],
            'display_filename': _censor_text(row['Filename']),
            'count': row['count'],
        }
        for row in cursor.fetchall()
    ]
    conn.close()
    return jsonify({'sounds': sounds})


@app.route('/api/analytics/activity_heatmap')
def get_analytics_heatmap():
    """Get activity heatmap data (day of week x hour)."""
    try:
        days = int(request.args.get('days', 30))
    except ValueError:
        days = 30
    
    conn = _get_db_connection(row_factory=sqlite3.Row)
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
    
    conn = _get_db_connection(row_factory=sqlite3.Row)
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
    
    conn = _get_db_connection(row_factory=sqlite3.Row)
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
            'display_username': _censor_text(row['username']),
            'action': row['action'],
            'timestamp': row['timestamp'],
            'display_sound': _censor_text(row['Filename']) if row['Filename'] else None
        })
    
    conn.close()
    return jsonify({'activities': activities})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
