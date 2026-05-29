# Web Soundboard Agent Notes

Read this when changing `web_page.py`, `bot/web/`, web repositories/services, templates/static assets for the soundboard, Flask auth, web uploads, web playback, web TTS, or the web control room.

## Architecture

- The Flask app is layered like the bot: `web_page.py` is only the entrypoint, `bot/web/app.py` builds the app, `bot/web/routes.py` registers focused route modules (`*_routes.py`), and shared route helpers live in `bot/web/route_helpers.py`.
- Flask-owned page templates and static assets live under `bot/web/templates/` and `bot/web/static/`. Root `templates/sound_card.html` and `templates/rl_store_card.html` are image-card templates used by `ImageGeneratorService`, not Flask page templates.
- SQL/business logic belongs in `bot/repositories/web_*.py` and `bot/services/web_*.py`; route modules should stay thin request/response adapters.
- Web routes should read SQLite through `app.config["DATABASE_PATH"]`, not a hardcoded `data/database.db`, so tests and alternate DB configs use the same paths.
- The web control-room panel is backed by `web_bot_status`, written by `BackgroundService.web_control_room_status_loop()` every 1 second. Flask reads it through `WebControlRoomRepository`/`WebControlRoomService`; do not inspect live Discord objects from Flask.

## Guilds And Auth

- Omitted `guild_id` is allowed only when exactly one non-null guild can be inferred from stable persisted data: `guild_settings`, `sounds`, `actions`, or `web_bot_status`. `playback_queue` is only a last-resort fallback when those tables are empty.
- Multi-guild web callers must send `guild_id` explicitly or `/api/play_sound` returns `400`.
- The soundboard has a guild selector backed by persisted guild data. Keep selected `guild_id` flowing through table endpoints, control-room status, play/control requests, and web uploads.
- Web playback requires Discord OAuth login. `web_page.py` expects `DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET`, and stable `WEB_SESSION_SECRET`; set `DISCORD_OAUTH_REDIRECT_URI` explicitly in production if Flask cannot infer the public callback URL.
- Web upload moderation should mirror `BotBehavior.is_admin_or_mod`: OAuth requests `identify guilds`, stores `DiscordWebUser.admin_guild_ids`, and treats users as web admins for a selected guild when they are owners or Discord reports Administrator / Manage Server / Manage Channels. If a known admin cannot see the inbox, have them log out/in to refresh scopes and admin guild IDs.

## Honker Integration (Required in Docker)

- Docker containers enable and require Honker via `HONKER_ENABLED=true` and `HONKER_REQUIRED=true` in `docker-compose.yml`. Local Python 3.10 development gracefully skips Honker.
- `bot/services/honker_integration.py` centralises all Honker API calls. Every public helper has a no-op fallback when Honker is absent; `HONKER_REQUIRED=true` makes failures hard errors.
- Honker connections are cached per-thread in `_thread_honker.connections` to avoid re-running `Database.__init__` schema/bootstrap DDL on every helper call. `_get_honker_connection()` returns the cached connection on subsequent calls from the same thread. A bounded retry (5 attempts, exp backoff up to 1s) handles transient `database is locked` on first open. `_close_honker_connection(db_path)` removes a cached connection for tests/clean shutdown.
- `queue_playback_request()` / `queue_control_request()` publish a Honker NOTIFY on `playback_queue` after inserting the row. `_drain_playback_queue_once()` (extracted from `check_playback_queue`) is called by both the polling loop and the Honker listener task. The drain is serialized with a module-level `asyncio.Lock` (`_playback_queue_drain_lock`) so concurrent calls from both paths cannot fetch and process the same unplayed row twice. The lock is acquired non-blocking — if it is already held, the second call returns immediately.
- `SoundImportNotificationRepository.enqueue()` publishes a Honker NOTIFY on `sound_import_notifications`. `BackgroundService._start_honker_sound_import_listener()` listens and calls `drain_sound_import_notifications_once()` immediately.
- `publish_soundboard_event()` in `bot/web/event_routes.py` publishes coarse change notifications on the `soundboard_events` Honker channel via both NOTIFY and stream publish. These drive the SSE `/api/events` endpoint.
- The SSE `/api/events` endpoint uses a background daemon thread with its own asyncio event loop to consume Honker NOTIFY events via `listen_notifications()` from the integration layer (rather than calling `honker.open()` or `stream.subscribe()` directly). This ensures the per-thread Honker connection cache is used. Event payloads are pushed to a thread-safe `queue.Queue` and consumed by the Flask SSE generator. A `threading.Event` signals the listener to stop when the generator exits.
- Web upload jobs (`_queue_web_upload_job`) are enqueued to the Honker `web_upload_jobs` durable queue when available. The web process runs background Honker worker threads that claim and process these jobs via `_run_web_upload_job`. The legacy `ThreadPoolExecutor` fallback is used only when Honker is unavailable.
- `BackgroundService` has optional Honker named-lock protection (`_run_with_honker_lock()`) around duplicate-sensitive scheduler loops (weekly wrapped, rlstore notification, backup, favourite watcher). Polling and fallback loops are preserved.
- Lock helpers use SQL functions `honker_lock_acquire(name, owner, ttl_s)` / `honker_lock_release(name, owner)` via `conn.transaction().query(...)`.
- `ensure_available(db_path)` is called during both bot and web container startup to validate Honker availability. With `HONKER_REQUIRED=true`, a missing/broken Honker fails the container with a clear RuntimeError.

## SSE / Live Updates

- `/api/events` streams Server-Sent Events. When Honker is available, events are driven by Honker LISTEN on `soundboard_events`; otherwise the stream sends only periodic heartbeats.
- The frontend `soundboard.js` creates an `EventSource` to `/api/events` on load. Events trigger targeted refresh calls (`fetchActions`, `fetchAllSounds`, `refreshControlRoomStatus`, etc.).
- **SSE connection state** (`sseConnected`, `sseLastMessageAt`) is tracked client-side. The `connected` event sets both; every event/heartbeat updates `sseLastMessageAt`. On `onerror`, `sseConnected` is set to `false` but the EventSource is **not closed** — the browser auto-reconnects with backoff. When the connection resumes, a fresh `connected` event restores healthy state.
- **Debounce**: SSE event handlers use `scheduleSseRefresh(key, fn, delayMs=150)` to coalesce multiple events into a single refresh, preventing fetch storms from batched mutations.
- Tables are **strictly SSE-driven**: no passive polling occurs regardless of SSE health, and no reconnect resync happens on SSE connect/reconnect. Missed events require fixing event publication on the server, not client-side polling fallback. Control room and system monitor continue their normal polling cadence regardless of SSE health.
- SSE auto-reconnect: on error the frontend marks unhealthy but does NOT close the EventSource; the browser automatically retries with backoff. The `connected` event restores SSE health tracking but does **not** trigger table resyncs.
- Honker NOTIFY listeners use `fallback_poll_s=1.0` for important channels (`soundboard_events`, `playback_queue`, `sound_import_notifications`) so that SQLite-poll-based wake-ups have at most 1 s latency even when file-watch notifications are unavailable in Docker.
- Events are published from multiple layers:
  - **ActionRepository.insert()** and **Database.insert_action()** — both publish `actions_changed` after each new action row.
  - **SoundRepository.insert_sound()/update_sound_by_id()/update()/insert()/update_sound()** — publishes `sounds_changed` after sound mutations.
  - **playback_routes.py** — publishes `playback_queued` on play/control requests (already existed).
  - **upload_routes.py** — publishes `upload_job_changed` on initial queue (already existed).
  - **_run_web_upload_job()** — publishes `upload_job_changed` on every status transition (processing → approved/error).
  - **BackgroundService.web_control_room_status_loop()** — publishes `control_room_changed` when a per-guild signature of significant fields changes (ignoring fast-changing elapsed seconds). Signature includes: voice_connected, voice_channel_id, voice_member_count, is_playing, is_paused, current_sound, current_requester, muted.
  - **BackgroundService.drain_sound_import_notifications_once()** — publishes `sound_imported` and `sounds_changed` after each successful notification send.
- `publish_soundboard_event()` is safe to call from any Flask route, background thread, or repository; it degrades to no-op when Honker is unavailable.
- **Actions table refresh** (strictly SSE-driven — no passive polling, no reconnect resync, no local post-play fallback):
    1. **`actions_changed` event** — published by `ActionRepository.insert()` after every action row is committed. The frontend calls `_scheduleAuthoritativeActionsRefresh()`, which records a timestamp, cancels any pending delayed fallback timers, and calls `fetchActions()` with `showLoading=true`.
    2. **`playback_queued` event** — published by `playback_routes.py` immediately after queueing. The frontend checks both `data.action` (controls) and `data.play_action` (sound plays) and calls `_scheduleActionsFallbackRefresh(800)`.
    3. **`control_room_changed` event** — published by `AudioService._mark_playback_started()` for all real playback paths. The frontend parses `data.reason === 'playback_started'` and calls `_scheduleActionsFallbackRefresh(1200)`.

    The delayed fallback helpers use a shared timer and `fetchActions()` with `showLoading=false` to avoid forcing a repaint when data is unchanged. If an authoritative `actions_changed` event has arrived since the fallback was scheduled, the fallback is skipped entirely — preventing duplicate table repaints from overlapping web playback events.

## Playback Queue Transport

- `playback_queue` is an internal Flask-to-bot transport table, not a user-facing sound queue. Do not show pending queue counts or "Queue/Queued" wording in the UI.
- Rows carry `request_username` and `request_user_id`; keep migrations and bot-side selection in sync so web-triggered analytics are attributed to the logged-in Discord user.
- Web Slap and mute-toggle controls are sent through `playback_queue` using `request_type`/`control_action`, not executed directly in Flask.
- Web "Play similar" uses `request_type='play_sound'` and `playback_queue.play_action='play_similar_sound'` so analytics match the Discord similar-sound select.
- Web TTS uses control action `tts`; `sound_filename` is JSON with `message` and `profile`. Bot-side dispatch routes Google profiles to `VoiceTransformationService.tts()` and ElevenLabs character profiles to `tts_EL()`.
- Web play-button latency is dominated by the bot-side `check_playback_queue` polling loop in `personal_greeter.py`. Keep it driven by `config.PLAYBACK_QUEUE_INTERVAL` (default `0.25` seconds); avoid fixed sleeps after `process_playback_queue_request()` without a concrete Discord race or rate-limit reason.
- Web playback can hit stale renamed DB rows where `sounds.Filename` is missing on disk but `sounds.originalfilename` still exists. Keep the fallback in `WebPlaybackService.process_playback_queue_request()`.
- Web soundboard duration display has the same renamed-row issue: show `sounds.Filename` to users, but fall back to `sounds.originalfilename` when reading MP3 metadata from disk.

## Uploads

- Web uploads use the same user-facing fields as `UploadSoundWithFileModal`: URL, MP3 file, custom name, and video time limit. File upload takes priority. Supported URLs are MP3/TikTok/YouTube/Instagram.
- Uploads are approved by default and recorded in `web_uploads`. Rejected uploads should remain auditable and should blacklist the linked sound when `sounds.blacklist` exists.
- Web uploads are queued through in-process Flask background jobs. `/api/upload_sound` returns `202` with `job_id`; clients poll `/api/upload_sound/<job_id>` until `approved` or `error`. Keep request handlers fast.
- Job status is now persistent via `WebUploadJobRepository` (`web_upload_jobs` table). On restart, `_resume_pending_upload_jobs()` in `app.py` recovers queued/stale processing jobs. File-upload jobs whose temp file is gone are marked as error; URL-based jobs are re-submitted from `source_url`.
- Docker web uploads must write to the same host-mounted `sounds/` directory the bot reads (`/app/sounds` in both containers).
- Do not put `.play-button` on the web upload submit button. Soundboard JS initializes every `.play-button` as an audio control and can rewrite upload text to the play icon.

## Cross-Process Import Notifications

- Web upload background workers cannot use BotBehavior directly (Flask vs bot process). After a successful upload, `_run_web_upload_job` enqueues a row in the `sound_import_notifications` table via `SoundImportNotificationRepository`.
- `BackgroundService.sound_import_notification_drain_loop` polls this table every 3 seconds and dispatches the Discord image-card notification using `SoundImportNotificationService.send_notification()`.
- All import paths (scraper `move_sounds`, favorite watcher, web upload, manual Discord upload) use the same `SoundImportNotificationService` so notifications are consistent. Each source has a default title template, requester label, and accent colour — see `SoundImportNotificationService` docstring.
- The repository/fixture combines `ensure_schema()` (safe for both bot and web processes) with `Database._run_schema_migrations()` so the table always exists.

## Sound Rows And Options

- All-sounds rows include `favorite`; keep `WebContentRepository.get_all_sounds_page()`, `WebContentService.get_all_sounds()`, and row `data-favorite` rendering in sync.
- Favorites and all-sounds rows include `slap`; web slap changes should mirror Discord `SlapButton` semantics, require web admin/mod access, and log `slap_sound`.
- Web event assignment uses the same `users` table and `EventRepository.toggle()` path as Discord controls. The modal posts `target_user`, `event` (`join`/`leave`), and `sound_id`.
- The event user dropdown is backed by persisted data (`users`, `actions`, `voice_activity`) plus the logged-in user because Flask lacks a live Discord member list.
- When a web label may be censored or transformed for display, send `sound_id` to `/api/play_sound` and resolve the real filename server-side.
- Do not embed raw sound filenames in inline `onclick` handlers. Many filenames contain apostrophes/quotes; use `data-*` attributes plus JS event listeners.

## TTS

- Web TTS should mirror Discord `/tts`: default modal profile `ventura`, send a loading GIF/card to the bot channel before generation, pass it as `loading_message`, and pass ElevenLabs profile thumbnails as `sts_thumbnail_url`.
- `AudioService.play_audio()` deletes the loading message and sends the final character card.
- Web TTS enhancement is a pre-send transform, not playback queue execution. Keep `/api/tts/enhance` authenticated, route OpenRouter calls through `WebTtsEnhancerService`, and treat `OPENROUTER_API_KEY` as optional.

- LLM settings (OpenRouter model ID and provider) are stored in the ``app_settings`` DB table under both ``ventura_chat_*`` keys (primary, written by the UI) and legacy ``web_tts_enhancer_*`` keys (fallback, written together with the new keys for backward compat).  The admin UI label is "Ventura Chat LLM" because the settings primarily control the bot-side Ventura voice chat LLM; the web TTS enhancer also reads these same DB settings at request time.  Admins can read/write them via ``GET/POST /api/tts/enhancer-settings``.  ``WebTtsSettingsService`` provides ``get/set/clear_ventura_chat_settings()`` (with fallback to legacy keys) and ``get/set/clear_enhancer_settings()`` (legacy).  Both ``VenturaChatService`` and ``WebTtsEnhancerService`` read the DB settings at request time.  When a provider is configured, it is sent to OpenRouter as ``{"order": [provider], "allow_fallbacks": false}`` — never as ``{"sort": ...}``.
- `WebTtsEnhancerService` uses DeepSeek v4 flash with reasoning enabled by default (unlike Ventura chat which keeps reasoning disabled for speed), and no default provider routing unless set via DB override or ``WEB_TTS_ENHANCER_PROVIDER`` env var. Keep the model in sync with `VenturaChatService` in `voice_command.py` when changing OpenRouter model defaults. The reasoning default divergence is intentional: web TTS enhancement benefits from reasoning quality while Ventura voice chat prioritizes low latency.

## Soundboard Layout

- After webpage UI changes, open the rendered page and inspect screenshots before finalizing. Use only a 1920x1080 desktop browser-window check and a 1440x3120 mobile check unless the user asks for another size.
- Treat the 1920x1080 desktop check as the full Windows browser window, not the page viewport. Leave enough vertical room for browser chrome and the Windows taskbar; headless screenshots that use the full 1080px as content height can miss bottom clipping.
- Desktop layout should use the viewport as a maximum, not stretch tables to fill it. Keep rows at natural CSS height, `.table-container` as `flex: 0 1 auto` with a max-height, and `per_page` fixed to the safe value.
- Keep desktop soundboard page size at 7 rows unless the card layout is redesigned.
- Do not reintroduce click-time auto-shrink for `per_page`; it caused pagination to shrink after Next/Prev clicks.
- Keep control areas vertically balanced across cards. If one card has `.library-controls`, match its reserved bottom spacing to the normal search/filter footprint.
- Rounded-bottom padding (`--table-bottom-inset`) is visual only. Clip detection should compare the last row against the actual `.table-container` bottom.
- First paint must stay layout-stable. Render the first page of actions/favorites/all-sounds and visible action filters server-side in `bot/web/templates/index.html`, seed JS cache through the `soundboard-config` JSON script tag, and do not immediately refetch/repaint on load.
- Refresh calls use `include_filters=0` for actions, favorites, and all-sounds. Treat missing/empty `filters` as "no filter update", not as an empty option list.
- Do not poll all-sounds with full filters; production sound/date filter metadata is hundreds of KB.
- Favorites user filtering is based on the latest per-user `favorite_sound`/`unfavorite_sound` action for each sound. Keep page, count, and filter queries in sync.
- Soundboard pagination should support direct `touchend` handling and make exactly one fetch per tap/click.

## Control Room

- `GET /api/control_room/status` combines `web_bot_status` and mute state and intentionally does not expose pending `playback_queue` summary data.
- Keep `web_bot_status` in the stable guild discovery set so single-guild deployments can load the control room without explicit `guild_id`.
- Web slap/mute controls belong inside the control-room panel, not the nav header.
- Keep control-room metrics as a flat status strip, not boxed cards inside the rounded banner.
- Verify desktop control-room/table rhythm in the 1920x1080 browser-window check; the 7-row tables rely on compact desktop header/row heights.
- On mobile, the control room should be a compact two-row controller: row one has status, row two has voice and system (compact CPU/RAM), and a single ⚡ action-dock trigger spans both rows on the right side. Hover/tap on the trigger opens a popup menu for Upload, TTS, Slap, and Mute.
- Mobile play/slap/mute buttons need direct `touchend` handlers with duplicate-click suppression.
- On mobile, nav intentionally scrolls away and the control-room panel is the sticky top element. Do not make both sticky.

## System Monitor (`WebSystemMonitorService` / `HostSystemMonitorService`)

### Invariant — host process collection belongs in the bot container

Only the bot container has ``pid: host`` in ``docker-compose.yml``, so **all host-level per-process data collection must happen in the bot**, not the web container. The web container sees only its own Python worker processes when enumerating ``/proc/[pid]/``.

### Architecture

1. **``HostSystemMonitorService``** (``bot/services/system_monitor.py``) — reads ``/proc/stat``, ``/proc/meminfo``, ``/proc/diskstats``, ``/proc/[pid]/stat``, ``/proc/[pid]/status``, and ``/proc/[pid]/cmdline`` from the **bot's** perspective (which shows real host processes because of ``pid: host``). It is two-sample: the first call warms, subsequent calls compute CPU-percent and disk-I/O deltas. It also resolves descriptive display names via cmdline analysis (e.g. "web_page.py" instead of "python"). Instantiated and used by ``BackgroundService.web_system_monitor_status_loop``.

2. **``WebSystemStatusRepository``** (``bot/repositories/web_system_status.py``) — lightweight singleton table ``web_system_status`` with columns ``id`` (always 1), ``snapshot_json`` (TEXT), and ``updated_at`` (TEXT). The bot background loop writes a snapshot every 1 s. The web endpoint reads it.

3. **``WebSystemMonitorService``** (``bot/services/web_system_monitor.py``) — the Flask-side service. It now reads the persisted snapshot from ``WebSystemStatusRepository`` instead of directly reading ``/proc``. If the snapshot is missing or stale (>5 s), it returns ``"available": false`` with ``"status_label": "Waiting for host monitor"``.

### Dev fallback

Set ``WEB_SYSTEM_MONITOR_ALLOW_WEB_PROC_FALLBACK=1`` to fall back to reading ``/proc`` from the web container (two-sample, container-local processes only). This is **not** the recommended configuration; use only for local testing without the bot.

### CPU temperature

``HostSystemMonitorService.get_snapshot()`` includes a ``cpu_temperature_celsius`` key (``float | None``). The bot-side service reads CPU temperature from sysfs: first ``/sys/class/thermal/thermal_zone*/`` (preferring zones with CPU-related ``type`` labels such as ``x86_pkg_temp``), then ``/sys/class/hwmon/hwmon*/`` (matching by device ``name`` or sensor ``temp*_label``). A constructor param ``sys_root`` is available for test overrides (no env var needed for production). When no sensor is available or readable the value is ``None``.

### CPU fan speed

``HostSystemMonitorService.get_snapshot()`` also includes a ``cpu_fan_rpm`` key (``int | None``). The bot-side service reads CPU fan RPM from sysfs ``/sys/class/hwmon/hwmon*/fan*_input`` values. It prefers sensors whose ``fan*_label`` contains CPU-related keywords (``cpu``, ``processor``, ``package``, ``core``, ``soc``, ``tctl``, ``tdie``), then falls back to fans on known hwmon devices (common motherboard/sensor chip names), then to the first valid fan input. A value of ``0`` RPM is valid — it means a readable (but stopped/idle) fan — and is reported as ``0``. Invalid values (negative, outlandish > 99999 RPM, or unreadable/non-numeric) are ignored. When no fan sensor is available or readable the value is ``None``. Unavailable/fallback/error payloads in ``WebSystemMonitorService`` and route handlers include ``"cpu_fan_rpm": None``.

### Disk I/O

``HostSystemMonitorService.get_snapshot()`` includes ``disk_active_percent`` (``float | None``), ``disk_read_bytes_per_second`` (``float``), and ``disk_write_bytes_per_second`` (``float``). These are two-sample values from ``/proc/diskstats`` and should be collected in the bot container, like CPU/process data. ``disk_active_percent`` is based on ``io_ms`` delta and is capped at 100; read/write speeds use 512-byte sector deltas. First samples and unavailable/error payloads report ``disk_active_percent: None`` and zero read/write rates.

### Env vars

- ``WEB_SYSTEM_MONITOR_PROCFS_ROOT`` — override `/proc` for ``WebSystemMonitorService`` fallback (testing).
- ``HOST_SYSTEM_MONITOR_PROCFS_ROOT`` — override `/proc` for ``HostSystemMonitorService`` (testing).

### In-process cache (WebSystemMonitorService)

``WebSystemMonitorService.get_snapshot()`` has an optional in-memory cache (TTL defaults to 1 s, configurable via the ``cache_ttl`` constructor parameter). Only valid ``available: true`` snapshots are cached; unavailable responses always re-query the repository. This reduces redundant SQLite reads when multiple browser tabs or rapid polling hit the endpoint within the TTL window. Set ``cache_ttl=0`` to disable.

The ``/api/system_monitor/status`` route also sets ``Cache-Control: private, max-age=1`` so the browser itself can serve cached responses for up to 1 s without a network round-trip.

### Browser polling policy

The control-room page never uses setInterval. Instead it uses staggered setTimeout chains. Tables are strictly SSE-driven — no passive polling, no reconnect resync fallback. Control room polls on a fixed 1 s cadence regardless of SSE health. SSE events provide fast-path acceleration atop active polling for control room and system monitor. The paths are:

1. **Control room network poll** — `/api/control_room/status` is fetched every 1 s regardless of SSE health. A local client-side progress tick updates the elapsed time between fetches for smooth progress display. SSE events (`control_room_changed`, `playback_queued`) trigger immediate refreshes with `forceNetwork: true`.
2. **Tables (actions, favorites, all-sounds)** — strictly SSE-driven. No passive polling occurs regardless of SSE health. No reconnect resync happens on SSE connect/reconnect. SSE events (`actions_changed`, `sounds_changed`) trigger immediate targeted fetches. Missed events must be fixed by publishing the correct event server-side.
3. **Web control state** — SSE-driven with a 5 s health-check fallback. When SSE is healthy, only the health-check timer runs. When SSE is unhealthy, full state polling resumes.
4. **System monitor** — host telemetry has no event-driven path, so it always polls at 1 s when visible (20 s when hidden), regardless of SSE health.
5. **Upload jobs** — SSE-driven with 1.2 s network polling fallback when SSE is unhealthy.

**When SSE is unhealthy / unavailable**:

| What | Cadence (visible) | Hidden tab |
|---|---|---|
| Table data (actions/favorites/all_sounds) | **No fetch** — strictly SSE-driven | Same |
| Control room status | 1 s network poll | N/A |
| Web control (mute) state | 5 s | N/A |
| System monitor | 1 s | 20 s |
| Upload job polling | 1.2 s | Same |

**When SSE is healthy** — tables are strictly SSE-driven; control room continues polling at 1 s. SSE events provide fast-path acceleration. Web control and upload jobs rely on SSE with fallback:

| What | Cadence (visible) | Hidden tab | Why |
|---|---|---|---|
| Table data (actions/favorites/all_sounds) | **No fetch** — strictly SSE-driven | Same | SSE events (`actions_changed`, `sounds_changed`) drive updates; no reconnect resync or polling fallback |
| Control room status | 1 s network poll + local progress tick | N/A | SSE events provide immediate refresh; 1 s polling ensures correctness even if events are missed |
| Web control (mute) state | **No fetch** — health check only (~5 s) | N/A | Events (`control_room_changed`, `actions_changed`) drive state; low priority |
| System monitor | **1 s** (unchanged, no event path) | 20 s | Host telemetry is NOT event-driven |
| Upload job polling | Event-driven, 1.2 s fallback when SSE unhealthy | Same | `upload_job_changed` event triggers the next poll |

- **Control room local progress tick**: When SSE is healthy, the 1 s `_scheduleStatusPoll` timer runs `_controlRoomProgressTick()` instead of fetching. This function increments a local elapsed counter and re-renders the progress bar. On the next SSE event or visibility change, `refreshControlRoomStatus()` fetches fresh server data and resets the local counter. When SSE becomes unhealthy (detected by the health-check tick), polling resumes with a full network fetch every 1 s.
- **System monitor 1 s cadence**: Unlike previous behaviour where system monitor slowed down during SSE health (paranoia intervals up to 15 s/60 s), it now always polls at 1 s when the tab is visible and 20 s when hidden. There is no event-driven path for host telemetry.
- **Health-check tick**: The web-control loop schedules a 5 s health-check tick that calls `isSseHealthy()`. When SSE is healthy, web-control state is not fetched (events drive updates). When SSE is unhealthy, the next tick starts polling web-control state. This ensures automatic recovery without network overhead for the lowest-priority data.
- **Upload job fallback**: After submitting an upload, the initial `pollUploadJob()` call fetches status once. If the job is still processing and SSE is healthy, no timeout is scheduled — the next `upload_job_changed` SSE event drives the check. When SSE is unhealthy, polling resumes at 1.2 s.
- **SSE health check**: `isSseHealthy()` returns true when `sseConnected` is true AND the last event/heartbeat was received within `SSE_HEALTHY_TIMEOUT_MS` (45 s). If `sseConnected` is true but no event arrives for >45 s, SSE is considered unhealthy. The health-check tick (5 s) detects this faster.
- Each loop uses `setTimeout` chains so the next tick is scheduled only after the previous tick fires (``setInterval`` would pile up if a fetch stalls).
- Table data has no passive polling loop — tables are strictly SSE-driven. Missed events must be fixed by publishing the correct event server-side.
- Opening the system monitor dropdown triggers an immediate refresh. The cadence is 1 s regardless of dropdown state.
- ``visibilitychange`` triggers an immediate refresh of all key state when the tab becomes visible.
- User-triggered fetches (search, pagination, play response, mutation response) are always immediate with `forceNetwork: true` and are **not** affected by SSE health or paranoia intervals.

### Cross-tab request deduplication

Since every open tab runs its own polling loops, 10 tabs could fire 10 identical network requests within seconds. A browser-side shared-fetch cache in ``soundboard.js`` deduplicates GET requests across tabs:

1. **BroadcastChannel** — primary cross-tab communication. The first tab to need fresh data fetches from the server, then posts the result (``{ type: 'cache-update', key, payload, ttlMs }``) on the ``soundboard-shared-fetch`` channel. Other tabs receive the broadcast and resolve their pending fetch with the shared result.

2. **localStorage fallback** — used both as the persistent cache store (with ``expiresAt`` timestamps) and as a fallback when BroadcastChannel is unavailable. A per-URL lock key (``{ tabId, expiresAt }``, 2.5 s TTL) prevents thundering herds even across tabs that do not share a BroadcastChannel.

3. **TTL policy** — cached entries live slightly less than their poll interval so the next scheduled poll gets fresh data:

   | Endpoint | Shared-cache TTL |
   |---|---|
   | System monitor | 1200 ms |
   | Control room status | 900 ms |
   | Web control (mute) state | 1800 ms |
   | Table data (actions/favorites/all_sounds) | 3000 ms |

4. **Fallback** — when a lock is held by another tab and no result arrives via BroadcastChannel or localStorage within 2 s (or the TTL, whichever is smaller), the waiting tab does its own fetch. This guarantees forward progress when the locking tab crashes or its page is closed.

5. **Failure handling** — non-ok HTTP responses are never cached. Failed fetches silently fall through (the calling function already handled errors gracefully).

6. **Server-side headers** — JSON endpoints set ``Cache-Control`` so the browser can serve a cached response within the same tab without a network round-trip:
   - ``/api/system_monitor/status`` — ``Cache-Control: private, max-age=1``
   - ``/api/control_room/status`` — ``Cache-Control: private, max-age=0, must-revalidate`` (1s browser polling, server-side 0.9s cache; this header prevents the browser HTTP cache from masking the 1s cadence)
   - ``/api/web_control_state`` — ``Cache-Control: private, max-age=1``
   - ``/api/actions``, ``/api/favorites``, ``/api/all_sounds`` — ``Cache-Control: private, max-age=1``

7. **What is NOT cached** — POST/mutation requests (play, mute, TTS, slap, upload, sound-options) bypass the shared cache entirely. ``forceNetwork: true`` is passed for user-triggered searches, pagination clicks, and mutation-response refreshes.

### Server-side multi-client route cache

The browser cross-tab dedupe (BroadcastChannel + localStorage) only helps within a single browser profile.  It does **not** reduce duplicate network requests from different users, devices, or separate browser profiles.  To handle multi-client polling, a per-process, thread-safe TTL cache sits in front of read-only JSON endpoints.

#### Implementation

- ``bot/web/response_cache.py`` — ``ResponseCache`` class: per-process, thread-safe TTL JSON payload cache.
  - Double-checked locking with per-key locks so simultaneous identical misses do not all run the producer.
  - Opportunistic purge of expired entries; hard cap of 256 entries prevents unbounded growth from arbitrary query strings.
  - ``get_or_set(key, ttl, producer)`` returns the cached payload or calls *producer* at most once per TTL window.
  - In-memory only; **not** shared across Gunicorn workers or separate containers (Redis would be needed for cross-worker caching).

- ``bot/web/route_helpers.py`` exposes:
  - ``_get_response_cache()`` — returns the shared ``ResponseCache`` from ``current_app.extensions["web_response_cache"]``.
  - ``_build_read_cache_key(endpoint_name, *, visibility=None)`` — builds a deterministic key from endpoint path plus sorted ``request.args`` and an optional visibility scope.
  - ``_get_content_visibility_scope(current_user)`` — returns ``anon``, ``auth_censored``, or ``auth_uncensored`` depending on authentication and voice-activity presence.  This prevents username/sound-label leaks across visibility boundaries.

#### Cached endpoints

| Endpoint | TTL | Visibility scope | Notes |
|---|---|---|---|
| ``/api/actions`` | 1.5 s | anon / auth_censored / auth_uncensored | Full query (page, filters, search) + scope in key |
| ``/api/favorites`` | 1.5 s | anon / auth_censored / auth_uncensored | Same keying as actions |
| ``/api/all_sounds`` | 1.5 s | anon / auth_censored / auth_uncensored | Same keying as actions |
| ``/api/control_room/status`` | 0.9 s | anon / auth | ``current_user is None`` vs authenticated (only username censorship differs) |
| ``/api/web_control_state`` | 1.0 s | auth | Already requires login; share across all authenticated users for same guild |

The TTLs are intentionally short (0.9–1.5 s) so that user-triggered searches, pagination clicks, and mutations do not see stale data for long.

**Not cached**: POST/mutation/upload/TTS/play/sound-options endpoints.  Error responses are never cached (the producer is simply not called when the service raises).

#### Safety checks

- **Visibility isolation**: Anonymous ``anon`` payloads never leak to authenticated users and vice versa (different scope strings produce different cache keys).
- **Authenticated censorship**: Users with no voice activity see censored ``auth_censored`` payloads; users with activity see ``auth_uncensored``.  These scopes never share a cache entry.
- **Query isolation**: Different page numbers, search queries, filters, or guild IDs produce different cache keys.
- **Per-key locking**: Multiple concurrent requests for the same uncached key do not all run the producer — only one wins and the rest read the cached result.

#### Limitations

- The cache lives **per Flask process/worker**.  With multiple Gunicorn workers, each has its own independent cache.  For true global multi-worker caching, add a Redis layer or redesign endpoints to use SSE/server-push.
- Cache entries are evicted when the entry count exceeds 256 (oldest are removed first).
- The cache does not persist across web container restarts.

## Speech Training Labeling UI

- ``GET /speech-training`` and its API routes (``/api/speech_training/*``) are admin-only. Unauthenticated visitors are redirected to Discord login with ``next``; authenticated non-admins receive a 403 error page.
- Audio files are served through the protected ``/api/speech_training/clips/<id>/audio`` route (via ``send_file(mimetype="audio/mpeg", conditional=True)``), **never** as static file paths.
- ``WebSpeechTrainingService.resolve_audio_path()`` validates that the resolved path is within ``SPEECH_TRAINING_DATA_DIR`` and the file exists — rejecting path traversal.
- The repository table ``speech_training_clips`` is created by both ``Database._run_schema_migrations()`` (bot startup) and ``SpeechTrainingRepository.ensure_schema()`` (web service factory) so both processes can read/write without a strict startup order.

### Tests

- ``tests/services/test_system_monitor_service.py`` — covers ``HostSystemMonitorService`` with fake ``/proc`` trees and ``WebSystemMonitorService`` with a mocked repository, plus in-process cache hit/miss/TTL behavior.
- ``tests/repositories/test_web_system_status_repository.py`` — covers upsert, read, staleness, and edge cases.
- ``tests/test_webpage.py`` — system-monitor endpoint tests replace the service with fakes and verify route behaviour; cache tests verify producer-count reduction, scope isolation, query-param isolation, and TTL invalidation for the five cached endpoints.

### Shared navigation

A shared nav partial lives at ``bot/web/templates/shared/nav.html``.  All pages (soundboard, analytics, dataset) include it.  The including template sets ``active_page`` (``"soundboard"``, ``"analytics"``, or ``"dataset"``), ``nav_subtitle`` (e.g. ``"Web Sound Desk"``, ``"Analytics"``, ``"Dataset"``), ``logout_next`` (logout redirect path), and ``show_upload_inbox`` (bool for the admin inbox button).

``bot/web/templates/soundboard/nav.html`` is a compatibility wrapper that defaults ``active_page='soundboard'``, ``nav_subtitle='Web Sound Desk'``, ``show_upload_inbox=true``, and ``logout_next='/'``, then includes ``shared/nav.html``.

When adding a new page, include ``shared/nav.html`` with the correct ``active_page`` so the appropriate nav link is highlighted.  If the new page should show the Dataset link, the page route must also inject ``web_user_is_admin`` (already available from the global context processor).

### Speech Training APIs

The following admin-only APIs support quick labeling, bulk operations, keyword scanning, and trimming:

- ``DELETE /api/speech_training/clips/<id>`` — delete a single clip and its audio file.
- ``POST /api/speech_training/clips/<id>/trim_to_keyword`` — trim a clip's audio file in‑place to the detected keyword region. The JSON body may include ``start_seconds`` and ``end_seconds`` (optional — falls back to persisted ``detected_start_seconds`` / ``detected_end_seconds`` from the latest scan) and ``padding_seconds`` (default ``0.30``, clamped ``0–2``). Returns ``{"status":"ok", "duration_seconds": ..., "byte_size": ..., "keyword_start_seconds": ..., "keyword_end_seconds": ..., "trim_start_seconds": ..., "trim_end_seconds": ...}``. Errors return an ``error`` string with ``400`` (invalid timing) or ``404`` (clip not found). The UI shows a ``Trim kw`` button on any clip with valid keyword timing — from scan results, persisted detection metadata, or after a scan with ``trim_matches_to_keyword`` (which already auto-trimmed the clip). The manual button remains available for clips with persisted timing to allow re-trimming or adjusting the window. After trimming, the row updates in‑place without a full page refresh: the duration label refreshes, the audio source uses a cache‑busting query parameter so the browser loads the trimmed file, and any currently‑playing audio is paused.
- ``POST /api/speech_training/clips/bulk`` — body ``{"action": "label", "ids": [...], "label": "chapada"}`` or ``{"action": "delete", "ids": [...]}``.  Max 200 ids.
- ``POST /api/speech_training/keyword_scan`` — start an **async** keyword scan job using offline Vosk.  Accepts JSON body with optional ``keyword`` (default ``"chapada"``), ``min_confidence`` (default ``0.5``), ``guild_id``, ``user_id``, ``delete_non_matches`` (default ``false``), ``label_matches_as_potential`` (default ``true``), and ``trim_matches_to_keyword`` (default ``true``).  When ``delete_non_matches`` is ``true``, scanned non-matching clips are deleted after the scan completes.  When ``label_matches_as_potential`` is ``true``, scanned matching clips are bulk-labeled as ``potential``.  When ``trim_matches_to_keyword`` is ``true``, scanned matching clips with valid Vosk word timing are automatically trimmed to the detected keyword region in-place.  Returns ``202 {"job_id": ..., "status": "queued"}``.  Poll ``GET /api/speech_training/keyword_scan/<job_id>`` for progress and results.  Only unlabeled clips with ``duration_seconds <= 30`` are eligible; the response includes ``max_duration_seconds`` (always 30.0).
- ``GET /api/speech_training/keyword_scan/<job_id>`` — poll a keyword scan job.  Terminal states are ``done`` (includes ``matches[]``, ``scanned``, ``matched``, ``skipped``, ``max_duration_seconds``, ``delete_non_matches``, ``deleted_non_matches``, ``label_matches_as_potential``, ``labeled_matches``, ``trim_matches_to_keyword``, ``trimmed_matches``, and ``failed_trim_matches``) and ``error`` (includes ``error`` message).  During processing the response includes ``total``, ``scanned``, ``matched``, ``skipped``, and ``max_duration_seconds`` for progress display.  Each match includes optional ``keyword_start_seconds`` and ``keyword_end_seconds`` when Vosk word-level timing was available.  Responsive ``trim_matches_to_keyword`` matches have their ``duration_seconds``/``byte_size``/timing updated in-place to reflect the trimmed audio.
- ``POST /api/speech_training/transcribe_empty`` — start an **async** auto-transcript job using Groq Whisper.  Accepts optional JSON body fields ``guild_id`` and ``user_id`` to scope the empty-transcript clips.  Requires ``GROQ_API_KEY``.  Returns ``202 {"job_id": ..., "status": "queued"}``.  Poll ``GET /api/speech_training/transcribe_empty/<job_id>`` for progress and results.
- ``GET /api/speech_training/transcribe_empty/<job_id>`` — poll an auto-transcript job.  Terminal states are ``done`` (includes ``total``, ``processed``, ``updated``, ``empty_marked``, ``skipped``, ``errors[]``) and ``error`` (includes ``error`` message).  During processing the response includes ``total``, ``processed``, ``updated``, ``empty_marked``, ``skipped`` for progress display.
- ``GET /api/speech_training/clips`` — parameter ``sort`` one of ``newest``, ``oldest``, ``longest``, ``shortest``, ``unlabeled_first``, ``label_asc``, ``label_desc``, ``speaker_asc``, ``speaker_desc``, ``reviewed_desc``.
- ``GET /api/speech_training/clips/ids`` — returns **all** clip IDs matching the current scope/filter/search/sort, without pagination.  Accepts the same parameters as ``/api/speech_training/clips`` (``guild_id``, ``user_id``, ``label``, ``search``, ``sort``) but **not** ``page``/``per_page``.  Response: ``{"ids": [1, 2, ...], "total": 42}``.  Used by the "Select all" button to select every clip in the current filter scope.

The keyword scan persists Vosk word-level timing (``detected_start_seconds``, ``detected_end_seconds``) via the existing detection metadata columns. These are also returned as ``keyword_start_seconds`` / ``keyword_end_seconds`` on scan-match clips. When ``trim_matches_to_keyword`` is enabled (default ``true`` for Find Keywords and scheduled scans), matched clips with valid timing are automatically trimmed in-place after the scan completes. The match dicts returned to the UI reflect the post-trim ``duration_seconds``, ``byte_size``, and adjusted ``keyword_start_seconds`` / ``keyword_end_seconds``. The manual ``Trim kw`` button remains available on any clip with persisted timing.

### Passive Refresh

- Passive polling in `speech_training.js` runs every 5 seconds and calls `renderClips()` which rebuilds the entire clip list DOM. This collapses any expanded `.dataset-clip-details` panels.
- `shouldSkipPassiveClipRefresh()` must return `true` when any clip details panel is expanded, when a form field is focused inside the clip area, when audio is playing, when clips are selected, or during scan mode.
- If a passive refresh would disrupt an active labeling workflow (expanded details, focused text input, playing audio), it is skipped until the next cycle.

### Page UI

- The dataset page toolbar has a ``Find Keywords`` button.  Keyword scans always use a fixed confidence threshold of ``0.5`` (50%).  Clicking the button starts an **async** keyword scan via ``POST /api/speech_training/keyword_scan`` with ``all_keywords: true``, ``min_confidence: 0.5``, ``label_non_matches_as_none: true``, ``label_matches_as_potential: true`` and ``trim_matches_to_keyword: true``. Instead of scanning for a hardcoded ``chapada`` keyword, it fetches all configured trigger keywords from the ``keywords`` table. Matching clips are bulk-labeled ``potential``, non-matches are labeled ``none``, and matched clips with valid Vosk word timing are automatically trimmed to the detected keyword region.
- The JS polls ``GET /api/speech_training/keyword_scan/<job_id>`` every 500 ms and updates a persistent toast notification with a progress bar and detail text (e.g. ``Sound 12/83 · 4 matches · 1 skipped``).  On completion, matching clips populate the clip list in scan mode (showing matches only, with a ``Show all clips`` button).  If non-matches were deleted, the toast appends e.g. ``· 72 non-matches deleted``.  If matches were labeled ``potential``, the toast appends e.g. ``· 5 matches labeled potential``.  If matches were auto-trimmed, the toast appends e.g. ``· 3 trimmed``.  After deletion, the user list and storage summary are refreshed immediately.  Network errors during polling show a distinct "Network error while checking scan progress" message.
- Scan mode is cleared when the user changes any filter (label, search, sort, speaker, or guild).  While in scan mode, passive clip refresh is paused.
- The "Select all" button now selects all clips matching the current filters (not just the visible page).  It fetches IDs from ``GET /api/speech_training/clips/ids`` with the current filter/sort scope.  In scan mode, it selects all rendered scan-match clips locally.
- Each scan-match clip shows a confidence percentage chip (e.g. ``87%``) styled with ``--accent-olive`` colors. The chip title shows the specific matched keyword (e.g. ``ventura certainty: 87%``).
- Scan jobs run in a background thread pool (``WEB_KEYWORD_SCAN_WORKERS`` env var, default 2, bounded 1–8).  Job state is in-memory and lost on web restart.
- The bot also runs a scheduled daily keyword scan (``SPEECH_TRAINING_KEYWORD_SCAN_ENABLED``, default ``true``) every 24 h that scans all guilds' unlabeled clips with configured trigger keywords, labels non-matches as ``none``, labels matches as ``potential``, and auto‑trims matched clips to their detected keyword region (same as the web Find Keywords workflow). The interval defaults to 86400 s and is configurable via ``SPEECH_TRAINING_KEYWORD_SCAN_INTERVAL_SECONDS`` (range 300–86400). Progress is reported via a standard image-card notification (the same style as import notifications) that is edited in-place with updated progress, not a plain self-editing text message.
- Schedule metadata (enabled, interval, last started/finished timestamps, status, summary) is persisted to the ``app_settings`` table by ``BackgroundService`` after each scheduled scan run. The Dataset UI reads it via ``GET /api/speech_training/keyword_scan/schedule`` and displays a compact schedule tip inside the Find Keywords button (e.g. ``last May 26, 14:03 · next May 27, 14:03``). The schedule ``span#keywordScanSchedule`` sits inside ``button#scanKeywordBtn`` as a small second line; full details are available via ``title`` on both the span and the button. The endpoint falls back to env defaults for enabled/interval when settings have not been written yet. Do not try to inspect in-memory Discord task state from Flask for this data.

### Auto-Transcript

- The dataset page toolbar has an ``Auto transcript`` button alongside ``Find Keywords``.  Clicking it starts an **async** job via ``POST /api/speech_training/transcribe_empty`` that transcribes all clips with empty/missing ``transcript`` via Groq Whisper.
- The JS polls ``GET /api/speech_training/transcribe_empty/<job_id>`` every 500 ms and updates a persistent toast notification with a progress bar and detail text (e.g. ``Sound 5/20 · 3 updated · 1 empty · 1 skipped``).
- Audio files are converted from MP3 to WAV in memory using ``pydub.AudioSegment`` before sending to Groq Whisper.
- Processing is **sequential** (one clip at a time) to avoid rate limiting.  A safety cap of 500 clips per job is enforced.
- When Whisper returns a successful 200 response but the transcribed text is empty/blank, the transcript is stored as ``"-"``.  API failures (HTTP errors, timeouts, network errors) are skipped — they are not written as ``"-"``.
- Only ``transcript``, ``reviewed_by_username`` (set to ``"(auto-transcript)"``), and ``reviewed_at`` are updated; existing ``label`` and ``notes`` are preserved.
- The operation requires ``GROQ_API_KEY`` to be configured.  If missing, the job immediately transitions to ``error`` with a descriptive message.
- Transcript jobs run in a dedicated background thread pool (``WEB_TRANSCRIPT_WORKERS`` env var, default 1, bounded 1–4).  Job state is in-memory and lost on web restart.
- While a transcript job is running, passive clip refresh is paused and both the scan and transcript buttons are disabled.

The control-room host metric shows ``Host CPU, Disk & RAM`` with a dropdown. CPU fan speed appears in parentheses on the CPU total row (e.g. ``CPU 12.3% (2,500 RPM)`` or ``CPU sampling… (2,500 RPM)``) when available; if fan speed is unavailable, the parentheses are omitted. Disk is shown as active percentage plus read/write speeds. Hovering/focusing CPU, RAM, DISK, TEMP, or a ``Top CPU`` process row shows one inline last-minute graph for that row; hovering the graph itself shows the nearest sample time and value. The graph uses the history arrays persisted in the bot-side system monitor snapshot. The process section is labelled ``Top CPU`` (reflecting that these are the top host-wide CPU consumers). The footnote shows the bot-side sample interval (~1 s). When no snapshot is available the dropdown shows "Waiting for host monitor".
