# Discord Brain Rot

Discord bot for soundboard playback, live voice keyword triggers, TTS/STS, sound ingestion, analytics, and an optional web dashboard. The web dashboard is opt-in (disabled by default in production).

## Features

- **Sound playback** — `/toca` with fuzzy matching, speed/volume/reverse effects, image-based sound cards with inline controls (progress, replay, favorite, slap, rename, join/leave events, STS character, similar sounds, add-to-list). Random/random-favorite/random-slap via the controls panel. Slash commands for `/subwaysurfers`, `/familyguy`, `/slice`.
- **Upload & sound ingestion** — Unified modal for MP3 file upload and URL ingestion (MP3, TikTok, YouTube, Instagram). Automatic loudness normalization on save. Filename sanitization with collision avoidance. Periodic MyInstants scraping.
- **Voice commands (wake word + Groq Whisper + Ventura chat)** — Vosk detects the configured wake word (default `ventura`), plays a start prompt, records fresh command audio, and sends it to Groq Whisper for transcription. Three-way branching: play a sound, activate 30-minute mute, or route to an OpenRouter LLM (DeepSeek) for an angry André Ventura parody reply with ElevenLabs TTS playback. Wake words, capture duration, silence timeout, cooldown, confidence thresholds, and prompt clips are all configurable via environment variables.
- **Real-time keyword detection (Vosk)** — Live keyword triggers (slap or list playback) managed via `/keyword add|remove|list`. Voice commands build on top of the same Vosk grammar.
- **TTS / STS / Voice isolation** — `/tts` (Google or ElevenLabs), `/sts` (ElevenLabs speech-to-speech), `/isolate` (ElevenLabs voice isolation). All outputs are loudness-normalized.
- **Sound lists & events** — CRUD for sound lists via slash commands. Join/leave event sound assignment with paginated browsing.
- **Analytics & wrapped** — `/top` leaderboards (users, sounds, voice users, voice channels), `/weeklywrapped` and `/yearreview` as Remotion-rendered GIF digests, `/sendyearreview` admin DM flow. Voice session analytics from `voice_activity` rows.
- **On This Day** — `/onthisday` shows sounds popular on this day 1 month or 1 year ago.
- **Rocket League store** — `/rlstore` shows the daily Rocket League item shop with paginated image cards and a configurable notification.
- **Web dashboard (optional)** — Flask-based web soundboard, analytics dashboard, control room (live bot status, CPU/RAM, playback progress), and upload moderation. Requires Discord OAuth login. See [Web Dashboard & API](#web-dashboard--api) below.
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
| `OPENROUTER_API_KEY` | — | Required for Ventura chat LLM branch and web TTS enhancer |
| `EL_key` | — | ElevenLabs API key |
| `EL_voice_id_pt` | — | ElevenLabs Portuguese voice ID |
| `EL_voice_id_en` | — | ElevenLabs English voice ID |
| `EL_voice_id_costa` | — | ElevenLabs "costa" voice ID |
| `EL_TTS_QUOTA_COOLDOWN_SECONDS` | `3600` | Cooldown (seconds) after ElevenLabs quota_exceeded before retrying TTS |

### Voice Commands & STT

| Variable | Default | Description |
|---|---|---|
| `VOICE_COMMAND_ENABLED` | `true` | Set `false` to keep STT but disable wake-word voice commands |
| `VOICE_COMMAND_WAKE_WORDS` | `ventura` | Comma-separated human-facing wake words |
| `VOICE_COMMAND_WAKE_ALIASES` | `ventura` | Comma-separated Vosk grammar words (injected into keyword map) |
| `VOICE_COMMAND_WAKE_CONFIDENCE_THRESHOLD` | `0.85` | Wake-word confidence (range `0.0`–`1.0`); normal keywords use `0.95` |
| `VOICE_COMMAND_CAPTURE_SECONDS` | `6` | Max post-prompt recording duration (max `15`) |
| `VOICE_COMMAND_COOLDOWN_SECONDS` | `5` | Per-user rate limit between commands |
| `VOICE_COMMAND_QUOTA_COOLDOWN_SECONDS` | `3600` | Per-user cooldown for Ventura chat+ElevenLabs TTS when quota is blocked (does not affect `toca`/`mute` voice commands) |
| `VOICE_COMMAND_SILENCE_SECONDS` | `1.0` | Silence timeout after prompt (range `0.5`–`5.0`) |
| `VOICE_COMMAND_BEEP_ENABLED` | `true` | Set `false` to disable prompt clips |
| `GROQ_WHISPER_MODEL` | `whisper-large-v3` | Groq Whisper model |
| `GROQ_WHISPER_LANGUAGE` | `pt` | Language hint for Whisper; empty for auto-detect |
| `GROQ_WHISPER_TIMEOUT_SECONDS` | `20` | Groq API timeout |
| `VOICE_MAX_DAVE_PROTOCOL_VERSION` | auto | Set `0` to force-disable DAVE negotiation |

### Ventura Chat (LLM Branch)

| Variable | Default | Description |
|---|---|---|
| `VENTURA_CHAT_MODEL` | `deepseek/deepseek-v4-flash` | OpenRouter model for Ventura replies |
| `VENTURA_CHAT_PROVIDER` | — | OpenRouter provider to pin (e.g. `crucible` or `parasail/fp8`); unset = no routing |
| `VENTURA_CHAT_REASONING_ENABLED` | `false` | Enable model reasoning |
| `VENTURA_CHAT_TIMEOUT_SECONDS` | `20` | API timeout |
| `VENTURA_CHAT_MAX_TOKENS` | `250` | Max reply tokens |
| `VENTURA_CHAT_TEMPERATURE` | `0.7` | Temperature (range `0.0`–`2.0`) |
| `VENTURA_CHAT_HISTORY_RETENTION_SECONDS` | `300` | Per-user context lifetime (`0` disables history) |
| `VENTURA_CHAT_LOG_PAYLOAD` | `true` | Log full request payload; `false` for compact summary |

### Audio & Playback

| Variable | Default | Description |
|---|---|---|
| `AUDIO_LATENCY_MODE` | `low_latency` | Options: `low_latency`, `balanced`, `high_quality` |
| `PLAYBACK_START_PREROLL_MS` | `180` | Baseline startup pre-roll |
| `LOW_LATENCY_MP3_START_PREROLL_MS` | `650` | Minimum MP3 pre-roll floor in low-latency mode |
| `SOUND_PLAYBACK_EAR_PROTECTION_ENABLED` | `true` | Anti-earrape filtering during playback |
| `TTS_LOUDNORM_MODE` | `off` | Options: `off`, `single`, `double` |
| `FFMPEG_MAX_CONCURRENT_JOBS` | — | Global FFmpeg concurrency cap |
| `TTS_MAX_CONCURRENT_JOBS` | — | Global TTS/STS concurrency cap |
| `PLAYBACK_QUEUE_INTERVAL` | `0.25` | Web request bridge polling interval (seconds) |

### Scheduler & Admin

| Variable | Default | Description |
|---|---|---|
| `WEEKLY_WRAPPED_ENABLED` | `true` | Enable weekly digest scheduler |
| `WEEKLY_WRAPPED_DAY_UTC` | `4` (Friday) | Day of week (0=Monday) |
| `WEEKLY_WRAPPED_HOUR_UTC` | `18` | Hour |
| `WEEKLY_WRAPPED_LOOKBACK_DAYS` | `7` | Activity window |
| `WEEKLY_WRAPPED_GIF_MAX_MB` | — | Upload cap override for weekly GIF |
| `YEAR_REVIEW_GIF_MAX_MB` | — | Upload cap override for year-review GIF |
| `BACKUP_SCHEDULER_ENABLED` | `true` | Enable weekly backup |
| `BACKUP_SCHEDULER_DAY_UTC` | `4` (Friday) | Day of week |
| `BACKUP_SCHEDULER_HOUR_UTC` | `18` | Hour |
| `RLSTORE_NOTIFY_ENABLED` | `true` | Daily RL store notification |
| `RLSTORE_NOTIFY_HOUR_UTC` | `19` | Notification hour |
| `RLSTORE_NOTIFY_MINUTE_UTC` | `5` | Notification minute |
| `RLSTORE_NOTIFY_TARGET_USERNAME` | `sopustos` | User to mention |
| `BOT_SELF_HEAL_RESTART_ENABLED` | `true` | Let Docker restart after unrecoverable failures |
| `BOT_GATEWAY_UNREADY_RESTART_SECONDS` | `300` | Gateway unready restart threshold |
| `BOT_VOICE_RECOVERY_FAILURE_RESTARTS` | `3` | Voice recovery failure restart threshold |

### Advanced Tuning

| Variable | Default | Description |
|---|---|---|
| `SOUND_INGEST_NORMALIZE_ENABLED` | `true` | Normalize uploaded/ingested MP3s |
| `SOUND_INGEST_TARGET_DBFS` | `-18.0` | Target loudness for ingest normalization |
| `SOUND_EARRAPE_KEYWORDS` | `earrape,bassboost,bass boost` | Filename markers for stronger protection |
| `FAVORITE_WATCHER_SCAN_LIMIT` | `50` | Max TikTok collection entries per poll |
| `KEYWORD_SILENCE_FLUSH_SECONDS` | `0.35` | Vosk final detection flush delay |
| `PERFORMANCE_MONITOR_TICK_SECONDS` | `0.5` | Telemetry interval (min `0.1`) |
| `WEB_TTS_ENHANCER_MODEL` | `deepseek/deepseek-v4-flash` | OpenRouter model for web TTS enhancer |
| `WEB_TTS_ENHANCER_PROVIDER` | — | OpenRouter provider for web TTS enhancer |
| `WEB_TTS_ENHANCER_MAX_TOKENS` | `8192` | Max tokens for enhance response |
| `WEB_TTS_ENHANCER_REASONING_ENABLED` | `true` | Enable reasoning for web TTS enhancer |

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
| `GET /api/control_room/status` | Live bot status, progress, CPU/RAM |
| `GET /api/system_monitor/status` | Host process & resource data |
| `POST /api/upload_sound` | Queue a sound upload |
| `GET /api/upload_sound/<job_id>` | Poll upload progress |
| `GET /api/uploads` | Upload inbox (admin/mod) |
| `POST /api/uploads/<id>/moderation` | Approve/reject upload (admin/mod) |
| `GET /api/analytics/summary\|top_users\|top_sounds\|activity_heatmap\|activity_timeline\|recent_activity` | Analytics data |

Unauthenticated buttons show a locked state prompting Discord login. Web playback requires authentication so actions are logged as the real user.

## Data & Storage

- **Database:** SQLite at `config.DATABASE_PATH` (`data/database.db` by default).
- **Sounds:** `sounds/` — MP3 files referenced by the database.
- **Uploads/downloads:** `downloads/` — temporary ingestion workspace.
- **Logs:** `logs/YYYY-MM-DD.log` plus `logs/errors.log`.
- **Debug:** `debug/` — Vosk/Groq debug WAVs when enabled.
- **Vosk model:** Expected at `data/models/vosk-model-small-pt-0.3`.
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
