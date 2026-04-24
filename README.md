# Discord Brain Rot

Discord bot for soundboard playback, live voice keyword triggers, TTS/STS, sound ingestion, analytics, and an optional web dashboard. Web dashboard is optional and disabled by default in production.

This README is based on the current codebase behavior (not historical README assumptions).

## What The Bot Does Today

### Sound Playback and In-Chat UI
- Slash playback with fuzzy matching: `/toca`.
- Playback effects on demand: `speed`, `volume`, `reverse`.
- Fast playback start with deferred image/UI work.
- Image-based sound cards rendered from `templates/sound_card.html`.
- Playback card controls (expand/collapse with auto-close):
  - progress button (click to slap while playing, replay when stopped)
  - replay
  - favorite toggle
  - slap toggle
  - rename
  - assign join/leave event
  - STS character select
  - similar sounds (lazy-loaded)
  - add-to-list select
- Separate quick controls button (`⚙️`) sends an ephemeral controls panel.
- `send_message` notifications now include an inline `⚙️` button by default when no custom view is provided, and its button style matches the message accent/color when possible.

### Controls Panel (Non-Slash UI)
- Random sound
- Random favorite
- Global favorites list
- Personal favorites list
- Random slap
- Brain rot trigger
- Stats view
- Unified upload modal
- Last downloaded sounds
- 30-minute mute toggle

### Upload and Sound Ingestion
- Unified upload modal supports:
  - direct MP3 file upload
  - URL ingestion (MP3, TikTok, YouTube, Instagram)
- Filename sanitization preserves spaces and avoids collisions.
- Secure MP3 validation before insertion.
- Ingest-time loudness normalization for direct MP3 uploads and URL-ingested MP3s (compression + peak-safe gain; target `-18 dBFS` by default).
- Periodic MyInstants scraping (background task).

### Voice Connection Resilience
- `ensure_voice_connected` with per-guild locks and retry logic.
- Zombie voice client detection/recovery (websocket/socket/latency checks).
- Reconnection grace period to avoid competing reconnects.
- Voice DAVE compatibility patch for py-cord (identify payload, DAVE transitions, and MLS binary frame handling).
- Voice DAVE receive decrypt support so recording sinks can feed Vosk instead of encrypted opus.
- Auto-follow users when they switch channels.
- Auto-disconnect when bot is alone (event-based + safety loop).
- Auto-join is feature-flagged per guild (disabled by default for public hosting).

### Real-Time Keyword Detection (Vosk)
- Live keyword detection via Vosk + Discord voice sinks.
- Keywords are stored in the `keywords` table and managed with `/keyword`.
- Supported keyword actions:
  - `slap`
  - `list:<list_name>`
- Guild-level STT is controlled by `/settings feature stt_enabled`.
- Grammar + confidence filtering improves trigger precision for configured words like `diogo` or `hugo`.
- Worker and health checks restart stalled keyword detection.

### TTS, STS, and Voice Isolation
- `/tts` supports Google and ElevenLabs profiles.
- `/sts` performs ElevenLabs speech-to-speech conversion.
- `/isolate` performs ElevenLabs voice isolation.
- High-resolution timestamped filenames for generated outputs.
- Loudness normalization in TTS pipeline.
- ElevenLabs outputs are tagged (`is_elevenlabs=1`) and excluded from normal random/listing flows.

### Lists, Events, and Historical Features
- Sound list CRUD via slash commands.
- Add/remove sounds with autocomplete and ownership checks.
- Join/leave event sound assignment UI and paginated event browsing.
- `/onthisday` returns sounds from 1 month or 1 year ago.
- `/rlstore` shows the current Rocket League item shop as compact paginated image grids with item thumbnails, labeled page-jump buttons that stay active until bot restart, a Merc yes/no ping for the configured notify target, and a non-unfurled `https://rlshop.gg` source URL.

### Stats and Analytics
- `/top` leaderboard options:
  - users
  - sounds
  - voice users
  - voice channels
- `/weeklywrapped` admin trigger for a weekly guild digest (top sounds/users/voice + quirky stats).
- `/yearreview` yearly wrap-up with rank, play habits, streaks, and voice metrics.
- Voice session analytics backed by `voice_activity` rows from `on_voice_state_update`.
- Web analytics dashboard includes:
  - summary cards
  - top users/sounds
  - activity heatmap
  - timeline
  - recent activity feed

### Web Soundboard
- `GET /` shows recent actions, favorites, and all sounds.
- Multi-guild web deployments expose a guild selector; soundboard tables, control-room status, play/control requests, and uploads include the selected `guild_id` instead of relying on implicit backend inference.
- A web control-room panel shows live bot status: current sound/requester, voice channel, mute state, and quick upload/Slap/mute controls.
- Authenticated users can open the web upload modal from the control-room upload icon and queue a sound with the same fields as the bot upload modal: MP3/TikTok/YouTube/Instagram URL, MP3 file, optional custom name, and optional video time limit.
- Desktop nav uses text labels for Soundboard and Analytics; mobile nav compacts those controls to emoji-only buttons.
- Web uploads clear the form after submit, show active items in the modal processing queue, run in the background, insert into the selected guild sound library when processing finishes, and are recorded in a paginated admin-only upload inbox.
- Web upload moderation is restricted to users who match the bot admin/mod rule for the selected guild (`OWNER_USER_IDS`, Administrator, Manage Server, or Manage Channels). Existing web sessions may need to log out/in after this change so Discord grants the `guilds` OAuth scope.
- Recent actions can be filtered by action/user, Favorites can be searched and filtered by favoriting user, and All Sounds can be filtered by sound list without losing server-side pagination.
- The soundboard and analytics pages include a dark mode toggle beside the Discord login/profile control that persists in browser local storage.
- Each web table lets you enter a target page directly from its pagination controls.
- The web soundboard and analytics dashboard replace matched racist/hateful usernames and sound titles with `******` unless the logged-in Discord user has prior tracked voice activity.
- Send playback requests from web via `POST /api/play_sound`; `playback_queue` remains the internal Flask-to-bot transport table.
- The web soundboard also exposes authenticated Slap and mute-toggle controls via `POST /api/web_control`; the mute-on path plays a slap before muting, the bot consumes controls through the same internal polling path, and the mute toggle icon refreshes from `/api/web_control_state`.
- Unauthenticated web play/control buttons use a red locked state to prompt Discord login before sending bot actions.
- Web sound playback now requires Discord login; web requests carry the authenticated Discord user so playback is logged as that user instead of a bot/system account.
- Web play buttons use `sound_id` under the hood so censored labels still play the real sound correctly.
- Bot-side web playback polling defaults to `PLAYBACK_QUEUE_INTERVAL=0.25` seconds for low-latency play-button response.
- If `DEFAULT_GUILD_ID` is unset, web playback now auto-resolves the guild only when exactly one known guild ID exists in stable bot data (`guild_settings`, `sounds`, `actions`, or `web_bot_status`); `playback_queue` is used only as a last-resort fallback when those tables are empty, and multi-guild callers must send `guild_id` explicitly.
- Bot background task consumes web playback/control requests from the internal transport table.

### Operations and Admin
- Daily rotating logs in `Logs/YYYY-MM-DD.log` (+ `Logs/errors.log`).
- Admin slash commands:
  - `/lastlogs`
  - `/commands`
  - `/backup`
  - `/reboot` (owner allowlist or Discord Administrator permission only)
- Backup service creates compressed project backups with exclusions and now updates the ephemeral `/backup` response with live stage/progress status while archiving.

### Background Automations
- Random periodic sound playback loop (feature-flagged per guild; disabled by default).
- MyInstants scraping loop.
- Weekly wrapped scheduler loop (UTC-based, default Friday 18:00, deduped per guild/week).
- Daily `rlstore` notification loop (UTC-based, default 19:05, mentions the configured target user, posts the paginated image-card shop view to `#botrl` when that channel exists, otherwise falls back to the configured bot channel, and includes a non-unfurled `https://rlshop.gg` source URL).
- Scraper start + completion image cards with compact run summary.
- Controls-button normalizer loop (every minute): keeps one recent inline `⚙️` on eligible bot messages by adding if missing and removing extras with safe raw-component edits.
- Keyword detection health check loop.
- Voice-activity auto-disconnect safety loop.
- High-frequency performance telemetry loop (JSON logs with CPU, memory, process/runtime, network, disk, loop lag, and bot health metrics).
- Web playback/control request bridge loop.

## Recent Updates (Last Months)

### Sep-Oct 2025
- Secure MP3 upload flow added and expanded.
- Mute feature introduced and evolved to the current 30-minute toggle behavior.
- TTS voice/profile and thumbnail improvements.

### Dec 2025 to Jan 2026
- Major architecture refactor into `commands/`, `services/`, `repositories/`, and `ui/` layers.
- Repository pattern rollout + larger pytest coverage.
- Real-time Vosk keyword detection and keyword management.
- On This Day feature and yearly review flow added.
- Dockerized runtime and deployment workflow consolidation.
- Multi-guild and voice-connection resilience improvements.
- Analytics dashboard and backup command added.

### Feb 2026
- Image-first playback/message cards and startup announcement cards.
- Persistent Selenium renderer, image caching, and parallel avatar downloads.
- Faster audio startup by deferring heavy card/UI operations.
- Clickable progress button behavior (slap while playing, replay when stopped).
- Auto-hide/expand playback controls and lazy similar-sounds loading.
- Voice session analytics (`voice_activity`) integrated into `/top` and `/yearreview`.
- Accent border color support for generated image cards.

## Slash Commands (Current)

### Sound
- `/toca message:<sound|random> speed:<0.5-3.0> volume:<0.1-5.0> reverse:<bool>`
- `/change current:<name> new:<name>`
- `/lastsounds number:<int>`
- `/subwaysurfers`
- `/familyguy`
- `/slice`

### TTS / Voice
- `/tts message:<text> language:<profile>`
- `/sts sound:<sound> char:<ventura|tyson|costa>`
- `/isolate sound:<sound>`

### Lists
- `/createlist list_name:<name>`
- `/addtolist sound:<sound> list_name:<list>`
- `/removefromlist sound:<sound> list_name:<list>`
- `/deletelist list_name:<list>`
- `/showlist list_name:<list>`

### Events
- `/addevent username:<user> event:<join|leave> sound:<sound>`
- `/listevents username:<optional>`

### Keywords
- `/keyword add keyword:<word> action:<slap|list> list_name:<optional>`
- `/keyword remove keyword:<word>`
- `/keyword list`

### Stats
- `/top option:<users|sounds|voice users|voice channels> number:<int> numberdays:<int>`
- `/weeklywrapped days:<optional>` (admin/mod-gated; sends digest to configured bot channel)
- `/yearreview user:<optional> year:<optional>`
- `/sendyearreview user:<required> year:<optional>` (admin-gated placeholder DM flow)

### Admin
- `/lastlogs lines:<int> service:<optional>`
- `/commands`
- `/backup`

### Setup / Settings
- `/setup text_channel:<optional> voice_channel:<optional>`
- `/settings channel channel_type:<text|voice> action:<set|clear> text_channel:<optional> voice_channel:<optional>`
- `/settings feature feature:<autojoin_enabled|periodic_enabled|stt_enabled> enabled:<bool>`
- `/settings audio_policy policy:<low_latency|balanced|high_quality>`

### Historical
- `/onthisday period:<1 year ago|1 month ago>`

### External
- `/rlstore`

## Web Routes (Optional `web` Profile)

- `GET /`
- `GET /login`
- `GET /auth/discord/callback`
- `GET /logout`
- `GET /analytics`
- `GET /api/actions`
- `GET /api/favorites`
- `GET /api/all_sounds`
- `GET /api/guilds`
- `POST /api/play_sound`
- `POST /api/upload_sound`
- `GET /api/upload_sound/<job_id>`
- `GET /api/uploads` (owner/admin web users only)
- `POST /api/uploads/<upload_id>/moderation` (owner/admin web users only)
- `POST /api/web_control`
- `GET /api/web_control_state`
- `GET /api/control_room/status`
- `GET /api/analytics/summary`
- `GET /api/analytics/top_users`
- `GET /api/analytics/top_sounds`
- `GET /api/analytics/activity_heatmap`
- `GET /api/analytics/activity_timeline`
- `GET /api/analytics/recent_activity`

## Runtime Requirements

- Docker + Docker Compose (recommended)
- FFmpeg
- Chromium + chromedriver (image rendering/scraping)
- Vosk model at `Data/models/vosk-model-small-pt-0.3`

## Environment Variables

### Required
- `DISCORD_BOT_TOKEN`

### Core Optional
- `FFMPEG_PATH` (local run default: `ffmpeg`; Docker sets `/usr/bin/ffmpeg`)
- `CHROMEDRIVER_PATH` (Docker sets `/usr/bin/chromedriver`)
- `WEB_SESSION_SECRET` (Flask session secret for Discord web login; set this in production)
- `WEB_SESSION_LIFETIME_DAYS` (optional; how long the Discord web login cookie persists across browser/PC restarts, defaults to `30`)
- `DISCORD_OAUTH_CLIENT_ID` (required to enable Discord login on the web UI)
- `DISCORD_OAUTH_CLIENT_SECRET` (required to enable Discord login on the web UI)
- `DISCORD_OAUTH_REDIRECT_URI` (recommended public callback URL for Discord OAuth; falls back to Flask external URL generation if unset)
- `PLAYBACK_QUEUE_INTERVAL` (internal web request bridge polling interval in seconds, default `0.25`)
- `OWNER_USER_IDS` (comma-separated Discord user IDs allowed to run admin-only commands)
- `AUDIO_LATENCY_MODE` (`low_latency` default, or `balanced` / `high_quality`)
- `RLSTORE_NOTIFY_ENABLED` (`true` default; enables the daily Rocket League store notification scheduler)
- `RLSTORE_NOTIFY_HOUR_UTC` (default `19`; current store-reset follow-up hour in UTC)
- `RLSTORE_NOTIFY_MINUTE_UTC` (default `5`; notification minute after the reset hour)
- `RLSTORE_NOTIFY_TARGET_USERNAME` (default `sopustos`; exact username/display name or Discord user ID to mention)
- `PLAYBACK_START_PREROLL_MS` (default `180`; baseline startup pre-roll for low-latency playback)
- `LOW_LATENCY_MP3_START_PREROLL_MS` (default `650`; minimum startup pre-roll floor for MP3 in low-latency mode)
- `TTS_LOUDNORM_MODE` (`off` default, or `single` / `double`)
- `FFMPEG_MAX_CONCURRENT_JOBS` (global ffmpeg concurrency cap)
- `TTS_MAX_CONCURRENT_JOBS` (global TTS/STS concurrency cap)
- `SOUND_PLAYBACK_EAR_PROTECTION_ENABLED` (`true` default; enables playback-time anti-earrape filtering)
- `SOUND_PLAYBACK_EAR_PROTECTION_GAIN_DB` (default `-3.0`; baseline playback attenuation)
- `SOUND_PLAYBACK_EAR_PROTECTION_THRESHOLD_DBFS` (default `-16.0`; playback compressor threshold)
- `SOUND_PLAYBACK_EAR_PROTECTION_RATIO` (default `6.0`; playback compressor ratio)
- `SOUND_PLAYBACK_EAR_PROTECTION_LOWPASS_HZ` (default `12000`; playback high-frequency smoothing)
- Low-fidelity MP3 sources (<=24kHz or <=96kbps) auto-relax ear-protection (skip compressor/lowpass, keep attenuation) unless filename matches earrape keywords.
- `SOUND_EARRAPE_KEYWORDS` (default `earrape,bassboost,bass boost`; filename markers for stronger protection)
- `SOUND_EARRAPE_EXTRA_ATTENUATION_DB` (default `-6.0`; extra attenuation for matched filenames)
- `SOUND_EARRAPE_LOWPASS_HZ` (default `9000`; stronger lowpass for matched filenames)
- `SOUND_EARRAPE_COMPRESS_THRESHOLD_DBFS` (default `-20.0`; stronger compressor threshold for matched filenames)
- `SOUND_EARRAPE_COMPRESS_RATIO` (default `12.0`; stronger compressor ratio for matched filenames)
- `SOUND_INGEST_NORMALIZE_ENABLED` (`true` default; normalize direct uploads/URL MP3s on save)
- `SOUND_INGEST_TARGET_DBFS` (default `-18.0`; target loudness for ingest normalization)
- `SOUND_INGEST_PEAK_CEILING_DBFS` (default `-2.0`; prevents clipping/earrape peaks after normalization)
- `SOUND_INGEST_COMPRESS_ENABLED` (`true` default; applies dynamic compression before gain)
- `SOUND_INGEST_COMPRESS_THRESHOLD_DBFS` (default `-14.0`; compressor threshold)
- `SOUND_INGEST_COMPRESS_RATIO` (default `6.0`; compressor ratio)
- `AUTOJOIN_DEFAULT` (`false` default for new guilds)
- `PERIODIC_DEFAULT` (`false` default for new guilds)
- `STT_DEFAULT` (`false` default for new guilds)
- `KEYWORD_SILENCE_FLUSH_SECONDS` (`0.35` default; pause after speech before Vosk final keyword detection is forced)
- `VOICE_MAX_DAVE_PROTOCOL_VERSION` (default auto-detected from `davey` protocol version, currently `1`; set `0` only to force-disable DAVE negotiation)
- `PERFORMANCE_MONITOR_TICK_SECONDS` (performance monitor interval in seconds, default `0.5`, minimum `0.1`)
- `WEEKLY_WRAPPED_ENABLED` (`true` default; enables weekly digest scheduler)
- `WEEKLY_WRAPPED_DAY_UTC` (0-6, Monday=0, default `4` for Friday)
- `WEEKLY_WRAPPED_HOUR_UTC` (0-23, default `18`)
- `WEEKLY_WRAPPED_MINUTE_UTC` (0-59, default `0`)
- `WEEKLY_WRAPPED_LOOKBACK_DAYS` (1-30, default `7`)

### ElevenLabs
- `EL_key`
- `EL_voice_id_pt`
- `EL_voice_id_en`
- `EL_voice_id_costa`

### Optional TTS Loudness Tuning
- `TTS_LUFS_TARGET`
- `TTS_TP_LIMIT`
- `TTS_LRA_TARGET`

## Quick Start (Docker)

```bash
git clone https://github.com/GabrielAgrela/Discord-Brain-Rot.git
cd Discord-Brain-Rot

# Create .env with at least DISCORD_BOT_TOKEN
docker-compose up --build -d bot
```

Useful commands:

```bash
# Follow bot logs
docker-compose logs -f bot

# Follow web logs
docker-compose --profile web logs -f web

# Restart services
docker-compose restart

# Stop everything
docker-compose down
```

The optional web service shares the same `Sounds/` and `Data/` mounts as the bot, so web uploads are written where bot playback can read them.

## Verify, Test, Deploy

Preferred one-shot command:

```bash
./scripts/verify_and_deploy.sh
```

It runs:
1. `pytest`
2. `docker-compose restart`
3. `docker-compose ps`
4. recent bot logs

## Local Development (Without Docker)

```bash
./venv/bin/python -m pytest -q tests/
./venv/bin/python PersonalGreeter.py
# Optional web dashboard:
./venv/bin/python WebPage.py
```

## Project Layout

```text
Discord-Brain-Rot/
├── PersonalGreeter.py
├── WebPage.py
├── config.py
├── bot/
│   ├── commands/
│   ├── services/
│   ├── repositories/
│   ├── models/
│   ├── ui/
│   └── downloaders/
├── templates/
├── static/
├── Data/
├── Sounds/
├── Downloads/
├── Logs/
├── Debug/
└── tests/
```

## Notes

- Public invite/install scopes: `bot` and `applications.commands`.
- Recommended bot permissions: `Send Messages`, `Embed Links`, `Read Message History`, `Connect`, `Speak`, `Use Voice Activity`, `Manage Messages`.
- Slash command propagation note: global commands can take up to about 1 hour to appear in newly invited guilds.
- Bot auto-messaging falls back to a text channel named `bot` when `/setup` has not configured a text channel.
- Web dashboard routes are not started unless the `web` profile is enabled.
- `templates/sound_card.html` is runtime-critical and tracked in git.

## License

MIT
