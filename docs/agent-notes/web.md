# Web Soundboard Agent Notes

Read this when changing `web_page.py`, `bot/web/`, web repositories/services, templates/static assets for the soundboard, Flask auth, web uploads, web playback, web TTS, or the web control room.

## Architecture

- The Flask app is layered like the bot: `web_page.py` is only the entrypoint, `bot/web/app.py` builds the app, `bot/web/routes.py` registers focused route modules (`*_routes.py`), and shared route helpers live in `bot/web/route_helpers.py`.
- Flask-owned page templates and static assets live under `bot/web/templates/` and `bot/web/static/`. Root `templates/sound_card.html` and `templates/rl_store_card.html` are image-card templates used by `ImageGeneratorService`, not Flask page templates.
- SQL/business logic belongs in `bot/repositories/web_*.py` and `bot/services/web_*.py`; route modules should stay thin request/response adapters.
- Web routes should read SQLite through `app.config["DATABASE_PATH"]`, not a hardcoded `data/database.db`, so tests and alternate DB configs use the same paths.
- The web control-room panel is backed by `web_bot_status`, written by `BackgroundService.web_control_room_status_loop()` every 2 seconds. Flask reads it through `WebControlRoomRepository`/`WebControlRoomService`; do not inspect live Discord objects from Flask.

## Guilds And Auth

- Omitted `guild_id` is allowed only when exactly one non-null guild can be inferred from stable persisted data: `guild_settings`, `sounds`, `actions`, or `web_bot_status`. `playback_queue` is only a last-resort fallback when those tables are empty.
- Multi-guild web callers must send `guild_id` explicitly or `/api/play_sound` returns `400`.
- The soundboard has a guild selector backed by persisted guild data. Keep selected `guild_id` flowing through table endpoints, control-room status, play/control requests, and web uploads.
- Web playback requires Discord OAuth login. `web_page.py` expects `DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET`, and stable `WEB_SESSION_SECRET`; set `DISCORD_OAUTH_REDIRECT_URI` explicitly in production if Flask cannot infer the public callback URL.
- Web upload moderation should mirror `BotBehavior.is_admin_or_mod`: OAuth requests `identify guilds`, stores `DiscordWebUser.admin_guild_ids`, and treats users as web admins for a selected guild when they are owners or Discord reports Administrator / Manage Server / Manage Channels. If a known admin cannot see the inbox, have them log out/in to refresh scopes and admin guild IDs.

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
- Job status is in-memory; a web restart can drop active status polling even when already-started processing completed or failed.
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
- On mobile, the control room should be a compact two-row controller: row one has status plus slap/mute, row two has voice, system (compact CPU/RAM), upload, and TTS.
- Mobile play/slap/mute buttons need direct `touchend` handlers with duplicate-click suppression.
- On mobile, nav intentionally scrolls away and the control-room panel is the sticky top element. Do not make both sticky.

## System Monitor (`WebSystemMonitorService` / `HostSystemMonitorService`)

### Invariant — host process collection belongs in the bot container

Only the bot container has ``pid: host`` in ``docker-compose.yml``, so **all host-level per-process data collection must happen in the bot**, not the web container. The web container sees only its own Python worker processes when enumerating ``/proc/[pid]/``.

### Architecture

1. **``HostSystemMonitorService``** (``bot/services/system_monitor.py``) — reads ``/proc/stat``, ``/proc/meminfo``, ``/proc/[pid]/stat``, ``/proc/[pid]/status``, and ``/proc/[pid]/cmdline`` from the **bot's** perspective (which shows real host processes because of ``pid: host``). It is two-sample: the first call warms, subsequent calls compute CPU-percent deltas. It also resolves descriptive display names via cmdline analysis (e.g. "web_page.py" instead of "python"). Instantiated and used by ``BackgroundService.web_system_monitor_status_loop``.

2. **``WebSystemStatusRepository``** (``bot/repositories/web_system_status.py``) — lightweight singleton table ``web_system_status`` with columns ``id`` (always 1), ``snapshot_json`` (TEXT), and ``updated_at`` (TEXT). The bot background loop writes a snapshot every 1 s. The web endpoint reads it.

3. **``WebSystemMonitorService``** (``bot/services/web_system_monitor.py``) — the Flask-side service. It now reads the persisted snapshot from ``WebSystemStatusRepository`` instead of directly reading ``/proc``. If the snapshot is missing or stale (>5 s), it returns ``"available": false`` with ``"status_label": "Waiting for host monitor"``.

### Dev fallback

Set ``WEB_SYSTEM_MONITOR_ALLOW_WEB_PROC_FALLBACK=1`` to fall back to reading ``/proc`` from the web container (two-sample, container-local processes only). This is **not** the recommended configuration; use only for local testing without the bot.

### CPU temperature

``HostSystemMonitorService.get_snapshot()`` includes a ``cpu_temperature_celsius`` key (``float | None``). The bot-side service reads CPU temperature from sysfs: first ``/sys/class/thermal/thermal_zone*/`` (preferring zones with CPU-related ``type`` labels such as ``x86_pkg_temp``), then ``/sys/class/hwmon/hwmon*/`` (matching by device ``name`` or sensor ``temp*_label``). A constructor param ``sys_root`` is available for test overrides (no env var needed for production). When no sensor is available or readable the value is ``None``.

### CPU fan speed

``HostSystemMonitorService.get_snapshot()`` also includes a ``cpu_fan_rpm`` key (``int | None``). The bot-side service reads CPU fan RPM from sysfs ``/sys/class/hwmon/hwmon*/fan*_input`` values. It prefers sensors whose ``fan*_label`` contains CPU-related keywords (``cpu``, ``processor``, ``package``, ``core``, ``soc``, ``tctl``, ``tdie``), then falls back to fans on known hwmon devices (common motherboard/sensor chip names), then to the first valid fan input. A value of ``0`` RPM is valid — it means a readable (but stopped/idle) fan — and is reported as ``0``. Invalid values (negative, outlandish > 99999 RPM, or unreadable/non-numeric) are ignored. When no fan sensor is available or readable the value is ``None``. Unavailable/fallback/error payloads in ``WebSystemMonitorService`` and route handlers include ``"cpu_fan_rpm": None``.

### Env vars

- ``WEB_SYSTEM_MONITOR_PROCFS_ROOT`` — override `/proc` for ``WebSystemMonitorService`` fallback (testing).
- ``HOST_SYSTEM_MONITOR_PROCFS_ROOT`` — override `/proc` for ``HostSystemMonitorService`` (testing).

### In-process cache (WebSystemMonitorService)

``WebSystemMonitorService.get_snapshot()`` has an optional in-memory cache (TTL defaults to 1 s, configurable via the ``cache_ttl`` constructor parameter). Only valid ``available: true`` snapshots are cached; unavailable responses always re-query the repository. This reduces redundant SQLite reads when multiple browser tabs or rapid polling hit the endpoint within the TTL window. Set ``cache_ttl=0`` to disable.

The ``/api/system_monitor/status`` route also sets ``Cache-Control: private, max-age=1`` so the browser itself can serve cached responses for up to 1 s without a network round-trip.

### Browser polling policy

The control-room page no longer uses setInterval bursts. Instead it uses staggered setTimeout chains with adaptive cadences:

| What | Cadence (dropdown closed) | Cadence (dropdown open) | Hidden tab |
|---|---|---|---|
| Table data (actions/favorites/all_sounds) | One table every 3.5 s, round-robin | Same | Same (no additional slowdown) |
| Control room status | 4 s | 4 s | N/A |
| Web control (mute) state | 5 s | 5 s | N/A |
| System monitor | 4 s | 1.5 s | 20 s |

- Each loop uses `setTimeout` chains so the next tick is scheduled only after the previous tick fires (``setInterval`` would pile up if a fetch stalls).
- Passive table refresh skips while a filter select or pagination input is focused.
- Opening the system monitor dropdown triggers an immediate refresh and switches to the faster cadence. Closing it resets to the slow cadence.
- ``visibilitychange`` triggers an immediate refresh of all key state when the tab becomes visible.

### Cross-tab request deduplication

Since every open tab runs its own polling loops, 10 tabs could fire 10 identical network requests within seconds. A browser-side shared-fetch cache in ``soundboard.js`` deduplicates GET requests across tabs:

1. **BroadcastChannel** — primary cross-tab communication. The first tab to need fresh data fetches from the server, then posts the result (``{ type: 'cache-update', key, payload, ttlMs }``) on the ``soundboard-shared-fetch`` channel. Other tabs receive the broadcast and resolve their pending fetch with the shared result.

2. **localStorage fallback** — used both as the persistent cache store (with ``expiresAt`` timestamps) and as a fallback when BroadcastChannel is unavailable. A per-URL lock key (``{ tabId, expiresAt }``, 2.5 s TTL) prevents thundering herds even across tabs that do not share a BroadcastChannel.

3. **TTL policy** — cached entries live slightly less than their poll interval so the next scheduled poll gets fresh data:

   | Endpoint | Shared-cache TTL |
   |---|---|
   | System monitor | 1200 ms |
   | Control room status | 1800 ms |
   | Web control (mute) state | 1800 ms |
   | Table data (actions/favorites/all_sounds) | 3000 ms |

4. **Fallback** — when a lock is held by another tab and no result arrives via BroadcastChannel or localStorage within 2 s (or the TTL, whichever is smaller), the waiting tab does its own fetch. This guarantees forward progress when the locking tab crashes or its page is closed.

5. **Failure handling** — non-ok HTTP responses are never cached. Failed fetches silently fall through (the calling function already handled errors gracefully).

6. **Server-side headers** — the following JSON endpoints also set ``Cache-Control: private, max-age=1`` so the browser can serve a cached response within the same tab without a network round-trip:
   - ``/api/system_monitor/status``
   - ``/api/control_room/status``
   - ``/api/web_control_state``
   - ``/api/actions``, ``/api/favorites``, ``/api/all_sounds``

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
| ``/api/control_room/status`` | 1.5 s | anon / auth | ``current_user is None`` vs authenticated (only username censorship differs) |
| ``/api/web_control_state`` | 1.0 s | auth | Already requires login; share across all authenticated users for same guild |

The TTLs are intentionally short (1.0–1.5 s) so that user-triggered searches, pagination clicks, and mutations do not see stale data for long.

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

A shared nav partial lives at ``bot/web/templates/shared/nav.html``.  All pages (soundboard, analytics, dataset) include it.  The including template sets ``active_page`` (``"soundboard"``, ``"analytics"``, or ``"dataset"``), ``nav_subtitle`` (e.g. ``"Web Sound Desk"``, ``"Signal Report"``, ``"Dataset"``), ``logout_next`` (logout redirect path), and ``show_upload_inbox`` (bool for the admin inbox button).

``bot/web/templates/soundboard/nav.html`` is a compatibility wrapper that defaults ``active_page='soundboard'``, ``nav_subtitle='Web Sound Desk'``, ``show_upload_inbox=true``, and ``logout_next='/'``, then includes ``shared/nav.html``.

When adding a new page, include ``shared/nav.html`` with the correct ``active_page`` so the appropriate nav link is highlighted.  If the new page should show the Dataset link, the page route must also inject ``web_user_is_admin`` (already available from the global context processor).

### Speech Training APIs

The following admin-only APIs support quick labeling and bulk operations:

- ``DELETE /api/speech_training/clips/<id>`` — delete a single clip and its audio file.
- ``POST /api/speech_training/clips/bulk`` — body ``{"action": "label", "ids": [...], "label": "chapada"}`` or ``{"action": "delete", "ids": [...]}``.  Max 200 ids.

The ``GET /api/speech_training/clips`` endpoint now accepts a ``sort`` parameter (values: ``newest``, ``oldest``, ``longest``, ``shortest``, ``unlabeled_first``, ``label_asc``, ``label_desc``, ``speaker_asc``, ``speaker_desc``, ``reviewed_desc``).

### Page UI

The control-room host metric shows ``Host CPU, Temp & RAM`` with a dropdown. CPU fan speed appears in parentheses on the CPU total row (e.g. ``CPU 12.3% (2,500 RPM)`` or ``CPU sampling… (2,500 RPM)``) when available; if fan speed is unavailable, the parentheses are omitted. The process section is labelled ``Top CPU`` (reflecting that these are the top host-wide CPU consumers). The footnote shows the bot-side sample interval (~1 s). When no snapshot is available the dropdown shows "Waiting for host monitor".
