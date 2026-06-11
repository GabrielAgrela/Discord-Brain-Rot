# Discord Brain Rot

Discord bot for soundboard playback, live voice keyword triggers, TTS/STS, sound ingestion, analytics, and an optional web dashboard. The web dashboard is opt-in (disabled by default in production).

## Features

- **Sound playback** — `/toca` with fuzzy matching, speed/volume/reverse effects, image-based sound cards with inline controls (progress, replay, favorite, slap, rename, join/leave events, STS character, similar sounds, add-to-list). Random/random-favorite/random-slap via the controls panel. Slash commands for `/subwaysurfers`, `/familyguy`, `/slice`.
- **Upload & sound ingestion** — Unified modal for MP3 file upload and URL ingestion (MP3, TikTok, YouTube, Instagram). Automatic loudness normalization on save. Filename sanitization with collision avoidance. Periodic MyInstants scraping.
- **Voice commands (wake word + Groq Whisper + Ventura chat)** — Vosk detects the configured wake word (default `ventura`), plays a start prompt, records fresh command audio, and sends it to Groq Whisper for transcription. Three-way branching: play a sound, activate 30-minute mute, or route to a chat LLM (DeepSeek by default) for an angry André Ventura parody reply with ElevenLabs TTS playback. Wake words, capture duration, silence timeout, cooldown, confidence thresholds, and prompt clips are all configurable via environment variables.
- **Real-time keyword detection (Vosk)** — Live keyword triggers (slap or list playback) managed via `/keyword add|remove|list`. Voice commands build on top of the same Vosk grammar.
- **Speech training dataset (opt-in)** — Persistent voice capture for building a labeled speech dataset with Madeiran Portuguese accents. Clips are segmented by silence, saved as MP3, and can be labeled via the web labeling UI. Requires `SPEECH_TRAINING_RECORDING_ENABLED=true`.
- **TTS / STS / Voice isolation** — `/tts` (Google or ElevenLabs), `/sts` (ElevenLabs speech-to-speech), `/isolate` (ElevenLabs voice isolation). All outputs are loudness-normalized.
- **Sound lists & events** — CRUD for sound lists via slash commands. Join/leave event sound assignment with paginated browsing.
- **Analytics & wrapped** — `/top` leaderboards (users, sounds, voice users, voice channels), `/weeklywrapped` and `/yearreview` as Remotion-rendered GIF digests, `/sendyearreview` admin DM flow. Voice session analytics from `voice_activity` rows.
- **On This Day** — `/onthisday` shows sounds popular on this day 1 month or 1 year ago.
- **Rocket League store** — `/rlstore` shows the daily Rocket League item shop with paginated image cards and a configurable notification.
- **Web dashboard (optional)** — Flask-based web soundboard, analytics dashboard, control room (live bot status, CPU/RAM/disk and laptop battery with hover history graphs and sample readouts, playback progress), and upload moderation. Requires Discord OAuth login. See [Web Dashboard & API](#web-dashboard--api) below.
- **Voice connection resilience** — Per-guild locks, zombie detection/recovery, DAVE compatibility patch, auto-follow (never into AFK), auto-disconnect, configurable auto-join.
- **Background automations** — Periodic sound playback loop, MyInstants scraping, TikTok favorite watcher, weekly wrapped/guild digest scheduler, weekly backup scheduler, daily RL store notification, keyword health check, self-heal watchdog, performance telemetry.

## Quick Start (Docker)

```bash
git clone https://github.com/GabrielAgrela/Discord-Brain-Rot.git
cd Discord-Brain-Rot

# Create .env with at least DISCORD_BOT_TOKEN
docker compose up --build -d bot

# Optional web dashboard
docker compose --profile web up --build -d web
```

> **Note:** `docker-compose.yml` uses absolute host bind mounts (`/home/gabi/github/Discord-Brain-Rot/...`). Edit the paths or use `docker compose config` before deploying elsewhere.

```bash
# Follow bot logs
docker compose logs -f bot

# Follow web logs
docker compose --profile web logs -f web

# Restart all services
docker compose restart

# Stop everything
docker compose down
```

The optional `web` service shares the same `sounds/` and `data/` volumes as the bot, so web uploads are written where the bot can read them.

## Configuration

Create a `.env` file in the project root. Only `DISCORD_BOT_TOKEN` is strictly required.

### Required

| Variable | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | Discord bot token |

### Audio Playback

| Variable | Default | Description |
|---|---|---|
| `AUDIO_SUPPRESS_RECORDING_WHILE_PLAYING` | `true` | Skip recent-audio recording and speech-training work while the bot is actively playing audio; Vosk keyword detection still runs |
| `AUDIO_PLAYBACK_READ_GAP_WARNING_SECONDS` | `0.08` | Log `[PLAY-STUTTER] audio_source_read_gap` when the Discord audio player is delayed between source reads |
| `AUDIO_PLAYBACK_READ_DURATION_WARNING_SECONDS` | `0.04` | Log `[PLAY-STUTTER] audio_source_read_slow` when a source read blocks |
| `AUDIO_DEFER_SHORT_CLIP_UI_UNTIL_AFTER_PLAYBACK_SECONDS` | `0.0` | Optional threshold for deferring bot-channel UI/card generation until short clips finish; `0.0` keeps normal immediate messages |

### Discord OAuth & Web

| Variable | Default | Description |
|---|---|---|
| `WEB_SESSION_SECRET` | — | Flask session secret for Discord web login (set in production) |
| `WEB_SESSION_LIFETIME_DAYS` | `30` | Discord web login cookie lifetime |
| `DISCORD_OAUTH_CLIENT_ID` | — | Required to enable Discord login on the web UI |
| `DISCORD_OAUTH_CLIENT_SECRET` | — | Required to enable Discord login on the web UI |
| `DISCORD_OAUTH_REDIRECT_URI` | Flask external URL | Public callback URL for Discord OAuth |
| `OWNER_USER_IDS` | — | Comma-separated Discord user IDs allowed to run admin-only commands |

### External APIs

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | Required for voice commands (Groq Whisper) |
| `DEEPSEEK_API_KEY` | — | Required for the default Ventura chat LLM backend |
| `OPENROUTER_API_KEY` | — | Required for Ventura chat only when `VENTURA_CHAT_LLM_PROVIDER=openrouter`; always required for web TTS enhancer |
| `EL_key` | — | ElevenLabs API key |
| `EL_voice_id_pt` | — | ElevenLabs Portuguese voice ID |
| `EL_voice_id_en` | — | ElevenLabs English voice ID |
| `EL_voice_id_costa` | — | ElevenLabs "costa" voice ID |
| `EL_TTS_QUOTA_COOLDOWN_SECONDS` | `3600` | Cooldown (seconds) after ElevenLabs quota_exceeded before retrying TTS |

### Honker (Required in Docker — Cross-Process Notifications and Locks)

The **Honker** SQLite extension provides fast cross-process NOTIFY/LISTEN,
durable queues, and named locks. **Docker containers enable and require Honker
by default.** When Honker is missing or broken in a container, the process fails
at startup with a clear error.

For local Python 3.10 development, Honker is not available (it requires
Python >= 3.11). All features degrade gracefully to their original
polling/fallback behaviour in that case.

| Variable | Default | Description |
|---|---|---|
| `HONKER_ENABLED` | `true` (Docker) / `auto` (local) | When `true` or `auto` with available module, Honker features are active |
| `HONKER_REQUIRED` | `true` (Docker) / `false` (local) | When `true`, startup hard-fails if Honker cannot be loaded |
| `HONKER_WORKER_ID` | `hostname-pid` | Worker identifier for queue claim groups and lock identity |

**What uses Honker when available:**

- **Playback queue fast path:** After `queue_playback_request()` / `queue_control_request()`
  inserts a row, a Honker NOTIFY wakes the bot drain listener immediately.
  Existing polling (`PLAYBACK_QUEUE_INTERVAL`, default 0.25s) remains as
  fallback. See `bot/services/honker_integration.py`.
- **Sound import notifications:** After
  `SoundImportNotificationRepository.enqueue()` inserts a row, a Honker NOTIFY
  wakes the bot's notification drain loop immediately instead of waiting for the
  3-second poll.
- **Web upload jobs:** Job status is persisted to the `web_upload_jobs` table.
  When Honker is available, jobs are enqueued to a Honker durable queue and
  processed by Honker-backed workers in the web container. The direct
  `ThreadPoolExecutor` fallback is used only when Honker is unavailable.
  On container restart, queued or stale-processing jobs are recovered.
- **SSE live updates:** The `/api/events` Server-Sent Events endpoint is driven
  by a background Honker stream listener (using an async-to-sync daemon thread
  and queue bridge) when available; otherwise it sends only keep-alive
  heartbeats and the frontend falls back to staggered polling.
- **Scheduled-work locking:** Named-lock guards around duplicate-sensitive
  scheduler loops (weekly wrapped, RL store notification, backup, favourite
  watcher) prevent double execution when multiple bot processes are running.
  When Honker is unavailable, the locks are no-ops (original behaviour).

### Voice Commands & STT

| Variable | Default | Description |
|---|---|---|
| `VOICE_COMMAND_ENABLED` | `true` | Set `false` to keep STT but disable wake-word voice commands |
| `VOICE_COMMAND_WAKE_WORDS` | `ventura` | Comma-separated human-facing wake words |
| `VOICE_COMMAND_WAKE_ALIASES` | `ventura` | Comma-separated Vosk grammar words (injected into keyword map) |
| `VOICE_COMMAND_WAKE_CONFIDENCE_THRESHOLD` | `0.85` | Wake-word confidence (range `0.0`–`1.0`); normal keywords use `0.95` |
| `VOICE_COMMAND_CAPTURE_SECONDS` | `6` | Max post-prompt recording duration (max `15`) |
| `VOICE_COMMAND_COOLDOWN_SECONDS` | `5` | Per-user rate limit between commands |
| `VOICE_COMMAND_QUOTA_COOLDOWN_SECONDS` | `3600` | Per-user cooldown for Ventura chat+ElevenLabs TTS when quota is blocked (does not affect `play`/`toca`/`mute` voice commands) |
| `VOICE_COMMAND_SILENCE_SECONDS` | `1.0` | Silence timeout after prompt (range `0.5`–`5.0`) |
| `VOICE_COMMAND_BEEP_ENABLED` | `true` | Set `false` to disable prompt clips |
| `VOICE_COMMAND_THINKING_SOUND` | `09-06-26-21-14-35-796406-contemplating hmmmmmmmmm.mp3` | Non-blocking clip played while Ventura chat/TTS is being generated for non-play voice commands |
| `GROQ_WHISPER_MODEL` | `whisper-large-v3` | Groq Whisper model |
| `GROQ_WHISPER_LANGUAGE` | `pt` | Language hint for Whisper; empty for auto-detect |
| `GROQ_WHISPER_TIMEOUT_SECONDS` | `20` | Groq API timeout |
| `WEB_TRANSCRIPT_REQUEST_DELAY_SECONDS` | `1.0` | Inter-request delay (s) between Groq API calls during auto-transcript (max `60`) |
| `WEB_TRANSCRIPT_429_MAX_RETRIES` | `3` | Max retries per clip on HTTP 429 rate-limit (max `10`, `0` to disable retry) |
| `WEB_TRANSCRIPT_429_BACKOFF_SECONDS` | `15` | Base backoff (s) for 429 retry when no Retry-After header (max `300`) |
| `WEB_TRANSCRIPT_429_BACKOFF_MAX_SECONDS` | `120` | Exponential-backoff ceiling (s) for 429 retries (max `600`) |
| `VOICE_MAX_DAVE_PROTOCOL_VERSION` | auto | Set `0` to force-disable DAVE negotiation |

### Ventura Chat (LLM Branch)

| Variable | Default | Description |
|---|---|---|
| `VENTURA_CHAT_LLM_PROVIDER` | `deepseek` | Chat backend for Ventura replies (`deepseek`, `groq`, or `openrouter`) |
| `VENTURA_CHAT_MODEL` | `deepseek-v4-flash` | Model for Ventura replies |
| `VENTURA_CHAT_PROVIDER` | — | OpenRouter provider to pin when `VENTURA_CHAT_LLM_PROVIDER=openrouter` (e.g. `crucible` or `parasail/fp8`); unset = no routing |
| `VENTURA_CHAT_REASONING_ENABLED` | `false` | Enable model reasoning/thinking where supported |
| `VENTURA_CHAT_REASONING_EFFORT` | `none` | Reasoning effort for supported providers (`high`/`max` for DeepSeek thinking) |
| `VENTURA_CHAT_TIMEOUT_SECONDS` | `20` | API timeout |
| `VENTURA_CHAT_MAX_TOKENS` | `250` | Max reply tokens |
| `VENTURA_CHAT_TEMPERATURE` | `0.95` | Temperature (range `0.0`–`2.0`) |
| `VENTURA_CHAT_HISTORY_RETENTION_SECONDS` | `300` | Per-user context lifetime (`0` disables history) |
| `VENTURA_CHAT_LOG_PAYLOAD` | `false` | Log full request payload; `false` for compact summary |

### Audio & Playback

| Variable | Default | Description |
|---|---|---|---|
| `KEYWORD_SILENCE_FLUSH_SECONDS` | `0.35` | Vosk final detection flush delay |
| `SPEECH_TRAINING_RECORDING_ENABLED` | `false` | Enable persistent voice capture for dataset (privacy-sensitive — opt-in only) |
| `SPEECH_TRAINING_DATA_DIR` | `data/speech_training` | Root directory for captured MP3 clips |
| `SPEECH_TRAINING_SILENCE_SECONDS` | `0.35` | Silence gap to split speech segments (range `0.15`–`3.0`) |
| `SPEECH_TRAINING_MIN_DURATION_SECONDS` | `0.25` | Minimum segment duration to save |
| `SPEECH_TRAINING_MAX_DURATION_SECONDS` | `10.0` | Max segment duration before forced split |
| `SPEECH_TRAINING_MIN_RMS` | `120` | Minimum RMS amplitude to skip near-silent artifacts |
| `SPEECH_TRAINING_SPEECH_RMS_THRESHOLD` | `250` | Per-chunk RMS threshold to detect voiced frames; segments only start on voiced audio (range `50`–`5000`; lower = more sensitive) |
| `SPEECH_TRAINING_PREROLL_SECONDS` | `0.08` | Seconds of pre-voiced context included when a segment starts (range `0.0`–`0.5`) |
| `SPEECH_TRAINING_TRIM_SILENCE` | `true` | Remove trailing low-energy frames from captured segments before enqueue |
| `SPEECH_TRAINING_MP3_BITRATE` | `64k` | MP3 export bitrate for captured clips |
| `SPEECH_TRAINING_QUEUE_SIZE` | `200` | Max pending export jobs before dropping |
| `PERFORMANCE_MONITOR_TICK_SECONDS` | `0.5` | Telemetry interval (min `0.1`) |
| `WEB_TTS_ENHANCER_MODEL` | `deepseek/deepseek-v4-flash` | OpenRouter model for web TTS enhancer |
| `WEB_TTS_ENHANCER_PROVIDER` | — | OpenRouter provider for web TTS enhancer |
| `WEB_TTS_ENHANCER_MAX_TOKENS` | `8192` | Max tokens for enhance response |
| `WEB_TTS_ENHANCER_REASONING_ENABLED` | `true` | Enable reasoning for web TTS enhancer |
| `SPEECH_TRAINING_KEYWORD_SCAN_ENABLED` | `true` | Enable daily (24h) scheduled keyword scan of unlabeled speech training clips via the bot (labels non-matches as `none`, labels matches as `potential`; Discord image-card progress shows percentage only and completion shows detected count only) |
| `SPEECH_TRAINING_KEYWORD_SCAN_INTERVAL_SECONDS` | `86400` | Interval for the scheduled keyword scan, default 24h (range `300`–`86400`) |
| `SPEECH_TRAINING_KEYWORD_SCAN_WORKERS` | `4` | Worker count for the automatic bot-side keyword scan (range `1`–`8`; manual web scans keep their own worker setting) |
| `SPEECH_TRAINING_KEYWORD_SCAN_STARTUP_DELAY_SECONDS` | `120` | Delay scheduled keyword scans after bot startup so voice autojoin/state can settle (range `0`–`3600`) |
| `SPEECH_TRAINING_KEYWORD_SCAN_DEFER_WHILE_VOICE_ACTIVE` | `true` | Defer scheduled keyword scans while the bot is connected to an occupied voice channel |
| `SPEECH_TRAINING_KEYWORD_SCAN_ACTIVE_VOICE_RETRY_SECONDS` | `300` | Retry delay after deferring a scheduled keyword scan because voice is active (range `60`–`3600`) |

## Slash Commands

### Sound
| Command | Description |
|---|---|
| `/toca` | Play a sound with fuzzy matching; optional speed/volume/reverse |
| `/change` | Rename a sound |
| `/lastsounds` | List last downloaded sounds |
| `/subwaysurfers` | Play Subway Surfers gameplay |
| `/familyguy` | Play Family Guy clip |
| `/slice` | Play Slice All gameplay |

### TTS / Voice
| Command | Description |
|---|---|
| `/tts` | Text-to-speech (Google or ElevenLabs) |
| `/sts` | ElevenLabs speech-to-speech conversion |
| `/isolate` | ElevenLabs voice isolation |

### Lists
| Command | Description |
|---|---|
| `/createlist` | Create a sound list |
| `/addtolist` | Add a sound to a list |
| `/removefromlist` | Remove a sound from a list |
| `/deletelist` | Delete a sound list |
| `/showlist` | Display a sound list |

### Events
| Command | Description |
|---|---|
| `/addevent` | Assign a join/leave sound to a user |
| `/listevents` | List event sounds for a user |

### Keywords
| Command | Description |
|---|---|
| `/keyword add` | Add a trigger keyword (slap or list action) |
| `/keyword remove` | Remove a trigger keyword |
| `/keyword list` | List all trigger keywords |

### Stats & Analytics
| Command | Description |
|---|---|
| `/top` | Leaderboards (users, sounds, voice users, voice channels) |
| `/weeklywrapped` | Send weekly guild digest GIF (admin/mod) |
| `/yearreview` | Show yearly wrapped GIF |
| `/sendyearreview` | Send year review as DM (admin) |
| `/onthisday` | Show sounds popular on this day in the past |

### Operations / Admin
| Command | Description |
|---|---|
| `/reboot` | Reboot the host machine (owner/Administrator) |
| `/lastlogs` | Show recent service logs |
| `/commands` | Show recent bot commands |
| `/backup` | Create a full project backup |

### Setup / Settings
| Command | Description |
|---|---|
| `/setup` | Initial guild channel configuration |
| `/settings channel` | Set/clear text or voice channel |
| `/settings feature` | Toggle features (autojoin, periodic playback, STT) |
| `/settings audio_policy` | Set audio latency policy |

### External
| Command | Description |
|---|---|
| `/rlstore` | Show today's Rocket League item shop |
| `/favoritewatcher add\|list\|remove` | Manage TikTok collection watchers |

## Web Dashboard & API

The optional web dashboard is served by a separate `web` container (Docker profile `web`). It requires Discord OAuth (`DISCORD_OAUTH_CLIENT_ID`/`SECRET`) for authenticated actions. Routes:

| Route | Description |
|---|---|
| `GET /` | Soundboard with All Sounds, recent actions, favorites |
| `GET /analytics` | Analytics dashboard |
| `GET /login` / `/auth/discord/callback` / `/logout` | Discord OAuth flow |
| `GET /api/guilds` | Guild list |
| `GET /api/actions` | Recent actions |
| `GET /api/favorites` | Favorites |
| `GET /api/all_sounds` | All sounds (paginated, searchable) |
| `GET /api/sounds/<id>/options` | Sound row options (right-click/long-press) |
| `POST /api/sounds/<id>/rename\|favorite\|slap\|lists\|events` | Sound actions |
| `POST /api/play_sound` | Request playback |
| `POST /api/web_control` | TTS, slap, mute controls |
| `GET /api/web_control_state` | Current mute state |
| `POST /api/tts/enhance` | TTS message enhancement via OpenRouter |
| `GET /api/tts/enhancer-settings` | Read enhancer model/provider (admin) |
| `POST /api/tts/enhancer-settings` | Update enhancer model/provider (admin) |
| `GET /api/control_room/status` | Live bot status, progress, CPU/RAM summary |
| `GET /api/system_monitor/status` | Host CPU, RAM, disk I/O, battery, and process resource data |
| `POST /api/upload_sound` | Queue a sound upload |
| `GET /api/upload_sound/<job_id>` | Poll upload progress |
| `GET /api/uploads` | Upload inbox (admin/mod) |
| `POST /api/uploads/<id>/moderation` | Approve/reject upload (admin/mod) |
| `GET /api/analytics/summary\|top_users\|top_sounds\|activity_heatmap\|activity_timeline\|recent_activity` | Analytics data |
| `GET /speech-training` | Speech training dataset labeling page (admin-only, auto-refreshes every 5 s). Shows the automatic keyword scan schedule (last run, next run, status) as a compact tip inside the Find Keywords button. |
| `GET /api/speech_training/storage` | MP3 dataset usage + machine disk free/total capacity (admin-only) |
| `GET /api/speech_training/users` | Per-user clip aggregation (admin-only) |
| `GET /api/speech_training/clips` | Paginated clip list with filters (admin-only) |
| `GET /api/speech_training/clips/<id>/audio` | Stream a captured MP3 (admin-only) |
| `POST /api/speech_training/clips/<id>/label` | Update label/transcript/notes (admin-only) |
| `DELETE /api/speech_training/clips/<id>` | Delete a single clip (admin-only) |
| `POST /api/speech_training/clips/<id>/trim_to_keyword` | Trim a clip's audio in-place to the detected keyword region (admin-only). Reads persisted scan timing (`detected_start_seconds` / `detected_end_seconds`) or accepts explicit `start_seconds`/`end_seconds`/`padding_seconds` in the JSON body. Returns updated `duration_seconds`, `byte_size`, `keyword_start_seconds`, `keyword_end_seconds`, `trim_start_seconds`, `trim_end_seconds`. Matched clips are auto-trimmed by default during scan via `trim_matches_to_keyword`; this manual endpoint is available for further adjustments. |
| `POST /api/speech_training/clips/bulk` | Bulk label or delete clips (admin-only) |
| `POST /api/speech_training/keyword_scan` | Start async keyword scan (admin-only, returns `202` + `job_id`; poll with GET below). Only unlabeled clips ≤30s are eligible. Supports `all_keywords: true` to scan all configured trigger keywords from the `keywords` table, or a specific `keyword`. When `label_matches_as_potential` (default `true`) matches are bulk-labeled as `potential`; when `label_non_matches_as_none` (default `true`) non-matches are labeled as `none`. When `trim_matches_to_keyword` (default `true`) matched clips with valid Vosk word timing are auto-trimmed to the detected keyword region. |
| `GET /api/speech_training/keyword_scan/<job_id>` | Poll keyword scan progress & results (admin-only). Response includes `max_duration_seconds`. When multiple keywords were scanned, includes `keywords` (list) and `keyword_count`. Job result includes `trim_matches_to_keyword`, `trimmed_matches`, and `failed_trim_matches` counts. |
| `GET /api/speech_training/keyword_scan/schedule` | Automatic keyword scan schedule metadata (admin-only). Returns `enabled`, `interval_seconds`, `last_started_at`, `last_finished_at`, `last_status`, `last_summary`, `next_run_at`, `updated_at`. The Dataset page shows this info inline. |
| `POST /api/speech_training/transcribe_empty` | Start async auto-transcript job (admin-only, returns `202` + `job_id`). Transcribes empty-transcript clips via Groq Whisper (`GROQ_API_KEY` required). Poll with GET below. |
| `GET /api/events` | Server-Sent Events stream for live UI updates. Driven by Honker LISTEN when available; otherwise sends keep-alive heartbeats. |
| `GET /api/speech_training/transcribe_empty/<job_id>` | Poll auto-transcript progress & results (admin-only). Response includes `total`, `processed`, `updated`, `empty_marked`, `skipped`. |

Unauthenticated buttons show a locked state prompting Discord login. Web playback requires authentication so actions are logged as the real user.

## Data & Storage

- **Database:** SQLite at `config.DATABASE_PATH` (`data/database.db` by default).
- **Sounds:** `sounds/` — MP3 files referenced by the database.
- **Uploads/downloads:** `downloads/` — temporary ingestion workspace.
- **Logs:** `logs/YYYY-MM-DD.log` plus `logs/errors.log`.
- **Debug:** `debug/` — Vosk/Groq debug WAVs when enabled.
- **Vosk model:** Expected at `data/models/vosk-model-small-pt-0.3`.
- **Speech training data:** `data/speech_training/<guild_id>/<username>_<user_id>/<timestamp>_<dur-ms>ms.mp3` — optional captured voice clips for dataset labeling.
- **Remotion:** Year-review and weekly-wrapped GIF rendering requires Node.js/npm and a local Remotion CLI under `trailer/node_modules/.bin/remotion` (setup not included in this repo).

## Project Layout

```
Discord-Brain-Rot/
├── personal_greeter.py          # Bot entry point
├── web_page.py                  # Web dashboard entry point
├── config.py
├── docker-compose.yml
├── bot/
│   ├── commands/                # Slash command cogs
│   ├── services/                # Business logic
│   ├── repositories/            # Database access
│   ├── models/                  # Domain entities
│   ├── ui/                      # Discord views/modals
│   ├── web/                     # Flask routes & templates
│   └── downloaders/             # External content fetch
├── templates/                   # Image-card HTML templates
├── sounds/                      # MP3 library
├── downloads/                   # Ingestion workspace
├── data/                        # SQLite DB & models
├── logs/
├── debug/
└── tests/
```

## Local Development

```bash
./venv/bin/python -m pytest -q tests/
./venv/bin/python personal_greeter.py
./venv/bin/python web_page.py   # web dashboard (optional)
```

## Verify, Test, Deploy

```bash
./scripts/verify_and_deploy.sh   # pytest -> restart -> health check
./scripts/clean_browser_artifacts.sh  # remove browser/test artifacts
./scripts/clean_browser_artifacts.sh --dry-run  # preview only
```

## Notes

- Public invite scopes: `bot` + `applications.commands`.
- Recommended permissions: Send Messages, Embed Links, Read Message History, Connect, Speak, Use Voice Activity, Manage Messages.
- Global slash commands can take up to ~1 hour to propagate to new guilds.
- Bot auto-messaging falls back to a channel named `bot` when no text channel is configured via `/setup`.
- Web routes are only started with the `web` Docker profile.
- `templates/sound_card.html` and `templates/rl_store_card.html` are runtime-critical image-card templates tracked in git.
- `requirements.txt` is UTF-16 LE with BOM — preserve that encoding if editing.

## License

MIT
