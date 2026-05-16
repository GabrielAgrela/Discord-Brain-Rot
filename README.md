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

### Voice Commands (Wake Word + Groq Whisper + Ventura Chat)
- When Vosk detects the configured wake word, the bot plays a **start prompt clip** from `Sounds/` (no DB lookup), then **records fresh per-user PCM audio after the prompt** (not a rolling buffer). Recording stops when the user stops talking (silence timeout) or a max duration is reached. The captured audio is wrapped as WAV and sent to Groq Whisper (`whisper-large-v3`) for transcription. This avoids sending pre-wake conversation/silence.
- **Two-way branching** after transcription:
   1. **Play command** (e.g. "ventura play air horn"): the bot plays a **done prompt clip** (acknowledgment), then fuzzy-matches and plays the requested sound, like `/toca`.
   2. **No command** (e.g. "ventura, you are useless"): the bot routes the transcript to **OpenRouter** (Qwen Coder model) which generates an angry André Ventura parody reply in European Portuguese with ElevenLabs square-bracket performance tags. The reply is sent to **ElevenLabs Ventura TTS** and played back.
- **Default wake word**: `ventura` — directly in-vocabulary for the bundled Portuguese Vosk model (`vosk-model-small-pt-0.3`). The same default is used for both the human-facing wake word and the Vosk grammar injection, so no phonetic aliases are needed by default.
- **Historical note**: The prior default was `bot`, which was out of vocabulary. It required Portuguese phonetic aliases (`bote,bota,boto`) configured via `VOICE_COMMAND_WAKE_ALIASES`. The two-layer env override mechanism remains for custom models or backward compatibility.
- **Mixed-language support**: The wake word may appear **anywhere** in the transcript (not only at the start), so English preamble such as "What the fuck was that? Ventura, play das páginas." is handled correctly. Both English (`play`) and Portuguese (`toca`, `tocar`, `mete`, `meter`, `põe`, `poe`, `reproduz`, `reproduzir`) command verbs are recognised and normalised to `"play"`.
- Supported voice commands:
   - `<wake word/alias> play/toca/mete/põe/reproduz <sound name>` — fuzzy-matches and plays the requested sound, like `/toca` but with an important difference: if the exact name match is blacklisted/rejected, voice commands **skip it and fall back** to the nearest non-blacklisted fuzzy match (since voice has no autocomplete).
- Pre-decoded prompt MP3 clips from `Sounds/` (no FFmpeg, no DB lookup) are played as wake acknowledgement (start prompt) and capture-complete indication (done prompt, play path only) without interrupting current audio playback. Both prompts randomly select from a configurable pool of filenames (single or comma-separated). The done prompt is only played **after** Groq transcription when a play command is detected.
- Voice-command-initiated playback includes a "Heard: play <sound>" note on the generated sound card image (and in the embed fallback).
- Requires `GROQ_API_KEY` for transcription. Additionally requires `OPENROUTER_API_KEY` for the non-play Ventura chat branch (OpenRouter Qwen Coder model, default `qwen/qwen3-coder-next`) and `EL_key`/`EL_voice_id_pt` for ElevenLabs Ventura TTS playback.
- Configurable capture duration, silence timeout, cooldown, model, wake words, Vosk aliases, confidence threshold, prompt clips, and prompt enable/disable via environment variables.
- Debug save of the exact WAV bytes sent to Groq is enabled by default (``GROQ_WHISPER_DEBUG_SAVE_AUDIO=true``). Files land in ``Debug/groq_whisper/`` with timestamped names plus a ``latest.wav`` overwrite for quick inspection. Set ``GROQ_WHISPER_DEBUG_SAVE_AUDIO=false`` to disable. With the fresh post-prompt capture, debug WAV files contain only the command speech (e.g., "play despacito"), not several pre-wake seconds.

### Voice Connection Resilience
- `ensure_voice_connected` with per-guild locks and retry logic.
- Zombie voice client detection/recovery (websocket/socket/latency checks).
- Reconnection grace period to avoid competing reconnects.
- Voice DAVE compatibility patch for py-cord (identify payload, DAVE transitions, and MLS binary frame handling).
- Voice DAVE receive decrypt support so recording sinks can feed Vosk instead of encrypted opus.
- Auto-follow users when they switch channels (never auto-follows into AFK channels).
- Auto-disconnect when bot is alone (event-based + safety loop).
- Auto-join is feature-flagged per guild (disabled by default for public hosting).
- AFK auto-moves are treated as leave events from the previous channel: the bot plays the user's leave sound in the channel they left, then disconnects if empty. The bot never connects to or follows users into AFK channels.

### Real-Time Keyword Detection (Vosk) + Voice Commands
- Live keyword detection via Vosk + Discord voice sinks.
- Keywords are stored in the `keywords` table and managed with `/keyword`.
- Supported keyword actions:
  - `slap`
  - `list:<list_name>`
- **Voice commands** are built on top of keyword detection: the `VOICE_COMMAND_WAKE_ALIASES` (default `ventura`) are injected into the Vosk grammar.
  - The human-facing wake word (`VOICE_COMMAND_WAKE_WORDS`, default `ventura`) is also used for transcript parsing. Since the default is in-vocabulary, both values default to `ventura` and work identically.
  - When a wake word is detected, recent audio from the speaking user is sent to **Groq Whisper** (`whisper-large-v3`) for transcription.
  - If the transcript contains a recognised command verb (`play`, `toca`, `tocar`, `mete`, `meter`, `põe`, `poe`, `reproduz`, `reproduzir`), the same fuzzy-matching playback path as `/toca` is executed via `SoundService.play_request`.
  - Voice commands are rate-limited per user (default 5 s cooldown) and require `GROQ_API_KEY` to be set.
- Guild-level STT is controlled by `/settings feature stt_enabled`.
- Grammar + confidence filtering improves trigger precision: normal keywords use 0.95 confidence threshold, voice-command wake words use a configurable threshold (`VOICE_COMMAND_WAKE_CONFIDENCE_THRESHOLD`, default 0.85).
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
- `/weeklywrapped` admin trigger for a weekly guild digest, sent as a Remotion-rendered GIF when there is activity.
- `/yearreview` yearly wrap-up as a Remotion-rendered animated GIF that replaces its progress message with the final file.
- Voice session analytics backed by `voice_activity` rows from `on_voice_state_update`.
- Web analytics dashboard includes:
  - summary cards
  - top users/sounds
  - activity heatmap
  - timeline
  - recent activity feed

### Web Soundboard
- `GET /` shows the web soundboard with All Sounds as the primary library, plus recent actions and favorites.
- Multi-guild web deployments expose a guild selector; soundboard tables, control-room status, play/control requests, and uploads include the selected `guild_id` instead of relying on implicit backend inference.
- A web control-room panel shows live bot status: current sound/requester with a playback progress bar and elapsed/total time, voice channel, mute state, and quick upload/TTS/Slap/mute controls; clicking the voice channel opens the current user/avatar list.
- Favorites and All Sounds rows show MP3 duration under the sound name when the file is available on disk; hovering a sound also shows Discord-card-style `Added` date and uploader.
- Authenticated users can open the web upload modal from the control-room upload icon and queue a sound with the same fields as the bot upload modal: MP3/TikTok/YouTube/Instagram URL, MP3 file, optional custom name, and optional video time limit.
- Desktop nav uses text labels for Soundboard and Analytics; mobile nav compacts those controls to emoji-only buttons.
- Web uploads clear the form after submit, show active items in the modal processing queue, run in the background, insert into the selected guild sound library when processing finishes, and are recorded in a paginated admin-only upload inbox opened from the profile control.
- The profile moderation control shows an exclamation alert only while uploads are still unreviewed by a moderator.
- Rejected web uploads stay in the moderation audit trail, but their linked sounds are hidden from soundboard tables and blocked from web and Discord playback.
- Web upload moderation is restricted to users who match the bot admin/mod rule for the selected guild (`OWNER_USER_IDS`, Administrator, Manage Server, or Manage Channels). Existing web sessions may need to log out/in after this change so Discord grants the `guilds` OAuth scope.
- Recent actions, Favorites, and All Sounds support search with visible result counts and clear buttons; Recent actions can also be filtered by action/user, Favorites by favoriting user, and All Sounds by sound list or slap sounds without losing server-side pagination.
- The soundboard and analytics pages include a dark mode toggle beside the Discord login/profile control that persists in browser local storage.
- Each web table lets you enter a target page directly from its pagination controls.
- The web soundboard and analytics dashboard replace matched racist/hateful usernames and sound titles with `******` unless the logged-in Discord user has prior tracked voice activity.
- Send playback requests from web via `POST /api/play_sound`; `playback_queue` remains the internal Flask-to-bot transport table.
- The web soundboard also exposes authenticated TTS, Slap, and mute-toggle controls via `POST /api/web_control`; TTS opens a modal with the same voice/language profile choices as `/tts`, includes an Enhance button that can add ElevenLabs audio tags through OpenRouter, the mute-on path plays a slap before muting, the bot consumes controls through the same internal polling path, and the mute toggle icon refreshes from `/api/web_control_state`.
- Unauthenticated web play/control buttons use a red locked state to prompt Discord login before sending bot actions.
- Web sound playback now requires Discord login; web requests carry the authenticated Discord user so playback is logged as that user instead of a bot/system account.
- Web play buttons use `sound_id` under the hood so censored labels still play the real sound correctly.
- Web sound rows include play and visible options buttons. The options button, right-click, or long-press opens rename, add-to-list, play-similar, set-event, favorite/unfavorite, and make/unmake slap actions; rename, add-to-list, play-similar, and set-event each use their own modal, and slap changes require a web admin/mod user.
- The set-event modal shows existing join/leave assignments for the selected sound, uses a known-user dropdown, and labels the submit action as Add Event or Remove Event for the selected user/event pair.
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
- Sound watcher slash commands:
  - `/favoritewatcher add url:<TikTok collection URL>` seeds the current collection as a baseline and imports only future additions.
  - `/favoritewatcher list`
  - `/favoritewatcher remove watcher_id:<id>`
- Backup service creates compressed project backups with exclusions and now updates the ephemeral `/backup` response with live stage/progress status while archiving.

### Background Automations
- Random periodic sound playback loop (feature-flagged per guild; disabled by default).
- MyInstants scraping loop.
- TikTok collection favorite watcher loop (every 10 seconds; imports only videos added after a watcher URL was configured and posts an image-card notification with a play button).
- Weekly wrapped scheduler loop (UTC-based, default Friday 18:00, deduped per guild/week).
- Daily `rlstore` notification loop (UTC-based, default 19:05, mentions the configured target user, posts the paginated image-card shop view to `#botrl` when that channel exists, otherwise falls back to the configured bot channel, and includes a non-unfurled `https://rlshop.gg` source URL).
- Scraper start + completion image cards with compact run summary.
- Controls-button normalizer loop (every minute): keeps one recent inline `⚙️` on eligible bot messages by adding if missing and removing extras with safe raw-component edits.
- Keyword detection health check loop.
- Self-heal watchdog: exits the bot process after prolonged Discord gateway loss or repeated unrecoverable voice cleanup failures so Docker restarts it cleanly.
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
- `/weeklywrapped days:<optional>` (admin/mod-gated; sends a Remotion GIF digest to the configured bot channel)
- `/yearreview user:<optional> year:<optional>` (renders a Remotion recap and edits the progress response into a compact animated GIF)
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
- `GET /api/sounds/<sound_id>/options`
- `POST /api/sounds/<sound_id>/rename`
- `POST /api/sounds/<sound_id>/favorite`
- `POST /api/sounds/<sound_id>/slap`
- `POST /api/sounds/<sound_id>/lists`
- `POST /api/sounds/<sound_id>/events`
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
- Node.js/npm (for Remotion year-review and weekly-wrapped rendering)
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
- `OPENROUTER_API_KEY` (optional; enables the web TTS Enhance button)
- `WEB_TTS_ENHANCER_MODEL` (optional; OpenRouter model for web TTS enhancement, default `qwen/qwen3-coder-next`)
- `OPENROUTER_API_URL` (optional; OpenRouter-compatible chat completions endpoint)
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
- `YEAR_REVIEW_GIF_MAX_MB` (optional upload cap override for generated `/yearreview` GIFs; also used by `/weeklywrapped` unless overridden)
- `WEEKLY_WRAPPED_GIF_MAX_MB` (optional upload cap override for generated `/weeklywrapped` GIFs)
- `YEAR_REVIEW_RENDER_TIMEOUT_SECONDS` (optional timeout for Remotion MP4 rendering before GIF conversion, default `180`)
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
- `FAVORITE_WATCHER_SCAN_LIMIT` (default `50`; max TikTok collection entries checked per watcher poll)
- `AUTOJOIN_DEFAULT` (`false` default for new guilds)
- `PERIODIC_DEFAULT` (`false` default for new guilds)
- `STT_DEFAULT` (`false` default for new guilds)
- `KEYWORD_SILENCE_FLUSH_SECONDS` (`0.35` default; pause after speech before Vosk final keyword detection is forced)
- `GROQ_API_KEY` (required for voice commands; enables Groq Whisper transcription of wake-word audio)
- `GROQ_WHISPER_MODEL` (optional; Groq Whisper model name, default `whisper-large-v3` — more accurate; override to `whisper-large-v3-turbo` if speed is preferred)
- `GROQ_WHISPER_PROMPT` (optional; prompt sent to guide Whisper transcription, default empty to reduce short/noisy-clip prompt hallucinations)
- `GROQ_WHISPER_TEMPERATURE` (optional; transcription temperature, default `0` for deterministic output)
- `GROQ_WHISPER_LANGUAGE` (optional; language hint for Whisper transcription, default `pt` — prevents Whisper from translating Portuguese utterances to English; set to empty string to restore auto-detect for strongly mixed-language deployments)
- `GROQ_WHISPER_TIMEOUT_SECONDS` (optional; Groq API timeout, default `20`)
- `GROQ_WHISPER_DEBUG_SAVE_AUDIO` (optional; set `false` to disable saving WAV files sent to Groq Whisper for debugging, default `true`)
- `GROQ_WHISPER_DEBUG_AUDIO_DIR` (optional; directory for saved debug WAVs; default `Debug/groq_whisper/` under the project root; absolute paths are used as-is)
- `GROQ_WHISPER_DEBUG_AUDIO_KEEP` (optional; max number of timestamped debug WAVs to retain, default `25`; `latest.wav` is not counted)
- `VOICE_COMMAND_ENABLED` (optional; set `false` to disable wake-word voice commands while keeping STT enabled, default `true`)
- `VOICE_COMMAND_WAKE_WORDS` (optional; comma-separated wake words for voice commands, default `ventura`)
 - `VOICE_COMMAND_CAPTURE_SECONDS` (optional; max duration of post-prompt command recording sent to Whisper, default `6`, max `15`)
- `VOICE_COMMAND_COOLDOWN_SECONDS` (optional; per-user rate limit between voice command transcriptions, default `5`)
 - `VOICE_COMMAND_SILENCE_SECONDS` (optional; silence timeout after start prompt before voice command is considered complete, default `1.0`, range `0.5`-`5.0`)

 - `VOICE_COMMAND_BEEP_ENABLED` (optional; set `false` to disable voice command prompt clips entirely, default `true`)

 - `VOICE_COMMAND_START_SOUND` (optional; comma-separated prompt MP3 filenames under `Sounds/` — one is chosen at random when wake word is accepted. A single filename also works for backward compatibility. Default: `"16-05-26-19-52-51-637928-Sim.mp3,16-05-26-20-11-24-672100-Diz.mp3,16-05-26-20-12-44-779160-whispers O que que queres.mp3,16-05-26-20-13-18-557980-Frustrated sharp Foda-se q.mp3"`)

 - `VOICE_COMMAND_DONE_SOUND` (optional; comma-separated prompt MP3 filenames under `Sounds/` — one is chosen at random after command audio capture completes. A single filename also works for backward compatibility. Default: `"16-05-26-19-54-41-416014-Ok fica bem.mp3,16-05-26-20-14-36-595803-Sim senhor.mp3,16-05-26-20-15-00-686598-Ok já toco essa merda.mp3,16-05-26-20-15-34-525805-shouts aggressive Ok já ag.mp3"`)
- `VOICE_COMMAND_WAKE_ALIASES` (optional; comma-separated Vosk grammar words injected into the keyword map, default `ventura`; overrides `VOICE_COMMAND_WAKE_WORDS` for Vosk injection; falls back to wake words when empty, range `0.0`-`1.0`)
- `VOICE_COMMAND_WAKE_CONFIDENCE_THRESHOLD` (optional; confidence threshold for voice-command wake detection, default `0.85`, range `0.0`-`1.0`; normal keywords still use `0.95`)
- `OPENROUTER_API_KEY` (required for non-play Ventura voice command chat branch; enables OpenRouter Qwen Coder model)
- `VENTURA_CHAT_MODEL` (optional; OpenRouter model for Ventura chat replies, default `qwen/qwen3-coder-next`)
- `VENTURA_CHAT_TIMEOUT_SECONDS` (optional; Ventura Chat API timeout, default `20`)
- `VENTURA_CHAT_MAX_TOKENS` (optional; max tokens for Ventura reply, default `250`)
- `VENTURA_CHAT_TEMPERATURE` (optional; model temperature for Ventura chat, default `0.7`, range `0.0`-`2.0`)
- `VOICE_MAX_DAVE_PROTOCOL_VERSION` (default auto-detected from `davey` protocol version, currently `1`; set `0` only to force-disable DAVE negotiation)
- `PERFORMANCE_MONITOR_TICK_SECONDS` (performance monitor interval in seconds, default `0.5`, minimum `0.1`)
- `BOT_SELF_HEAL_RESTART_ENABLED` (`true` default; lets Docker restart the bot after unrecoverable gateway/voice health failures)
- `BOT_GATEWAY_UNREADY_RESTART_SECONDS` (default `300`; restart threshold while Discord gateway remains unready)
- `BOT_VOICE_RECOVERY_FAILURE_RESTARTS` (default `3`; restart threshold for repeated failed zombie voice cleanup)
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

#### ElevenLabs TTS Performance Options (since Ventura chat generates via this path)
- `EL_TTS_STREAMING_ENABLED` (optional; use the streaming TTS endpoint for lower latency, default `true`)
- `EL_TTS_OPTIMIZE_STREAMING_LATENCY` (optional; streaming latency optimisation level `0`-`4`, default `3`; higher values reduce latency but may reduce quality; set empty to omit the parameter; **only applied for models that support it** — automatically omitted for `eleven_v3` which does not accept this parameter)
- `EL_TTS_OUTPUT_FORMAT` (optional; output audio format, default `mp3_44100_128`; other ElevenLabs formats such as `mp3_44100_64` or `pcm_16000` are possible)
- `EL_TTS_MODEL_ID` (optional; ElevenLabs TTS model, default `eleven_v3`)
- `EL_TTS_TIMEOUT_SECONDS` (optional; HTTP timeout for ElevenLabs TTS API calls, default `30`)

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
│   ├── web/
│   └── downloaders/
├── templates/
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
- Web dashboard routes are not started unless the `web` profile is enabled. Flask page templates/static assets live under `bot/web/`.
- `templates/sound_card.html` and `templates/rl_store_card.html` are runtime-critical image-card templates and tracked in git.

## License

MIT
