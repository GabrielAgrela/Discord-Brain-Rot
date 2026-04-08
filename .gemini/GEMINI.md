# Discord Brain Rot - Project Guidelines

> **Note for AI agents**: This file is located at `.gemini/GEMINI.md` (hidden directory). Standard file searches may not find it - look in `.gemini/` directly.

This project follows strict architectural patterns and coding standards. All contributions must adhere to these guidelines.

## Architecture Patterns

### Repository Pattern
- All database access MUST go through repository classes in `bot/repositories/`
- Repositories extend `BaseRepository` from `bot/repositories/base.py`
- Repositories handle ONLY data access, no business logic
- Use `_execute`, `_execute_one`, `_execute_write` methods from base class
- Implement abstract methods: `get_by_id`, `get_all`, `_row_to_entity`

### Service Layer
- Business logic lives in service classes in `bot/services/`
- Services receive dependencies through constructor injection
- Services coordinate between repositories, external APIs, and Discord interactions
- Services should NOT directly access the database - use repositories instead

### Models
- Data models/entities live in `bot/models/`
- Models are simple data classes representing domain entities

### UI Layer
- Discord UI components (Views, Buttons, Modals) live in `bot/ui/`
- UI components should delegate to services for business logic

## SOLID Principles

### Single Responsibility
- Each class should have one clear responsibility
- Don't mix database access with business logic
- Don't mix UI handling with data processing

### Open/Closed
- Extend behavior through new classes, not modifying existing ones
- Use base classes and inheritance (like `BaseRepository`)

### Liskov Substitution
- Subclasses must be substitutable for their base classes
- Repository implementations must fulfill the `BaseRepository` contract

### Interface Segregation
- Keep interfaces focused and specific
- Don't force classes to depend on methods they don't use

### Dependency Inversion
- High-level modules should not depend on low-level modules
- Both should depend on abstractions
- Inject dependencies (repositories into services, services into commands)

## Code Style

### Docstrings
- All public methods must have docstrings explaining purpose
- Use triple-quoted strings with Args/Returns sections for complex methods
- See `bot/repositories/base.py` as the reference example

### Type Hints
- Use type hints for all function parameters and return values
- Import from `typing` module when needed (Optional, List, Dict, etc.)

### Async/Await
- Discord operations and I/O-bound operations should be async
- Use `async def` and `await` appropriately
- Don't mix sync and async patterns

## File Organization

```
bot/
├── commands/      # Discord slash commands
├── downloaders/   # External content downloaders
├── models/        # Data models/entities
├── repositories/  # Database access layer
├── services/      # Business logic layer
├── ui/            # Discord UI components (Views, Buttons, etc.)
```

## When Adding New Features

1. Create models in `bot/models/` if new entities are needed
2. Create or extend repositories in `bot/repositories/` for data access
3. Create or extend services in `bot/services/` for business logic
4. Create commands in `bot/commands/` for Discord interaction
5. Create UI components in `bot/ui/` if interactive elements are needed
6. **Write tests** in `tests/` for new code when it makes sense:
   - Model tests in `tests/models/`
   - Repository tests in `tests/repositories/`
   - Service tests in `tests/services/`
   - Use existing fixtures from `tests/conftest.py`
7. **Update `.gitignore`** if the new feature generates artifacts that shouldn't be tracked (cache files, build outputs, logs, etc.)
8. **Update this file (GEMINI.md)** if you discover patterns, gotchas, or fixes that future agents should know about - this prevents the same mistakes from recurring
9. **Update `README.md` whenever needed** if user-facing behavior changed:
   - slash commands, command options, or UI controls
   - setup/deployment/runtime requirements
   - environment variables or external integrations (LLM/TTS/APIs)
   - web routes, dashboards, or operational workflows
   - If no README update is required, explicitly state why in the final response

## Testing

- Tests are located in `tests/` and use pytest
- Run tests with `pytest tests/ -v`
- Preferred local command: `./venv/bin/python -m pytest -q tests/`
- Run with coverage: `pytest tests/ --cov=bot --cov-report=term`
- Use in-memory SQLite for repository tests (see `conftest.py` fixtures)
- Mock Discord dependencies for service tests
- Follow existing test patterns when adding new tests
- Testing artifacts (`.pytest_cache/`, `.coverage`, `htmlcov/`) are in `.gitignore`

## Agent Definition Of Done (Mandatory)

This section is mandatory for AI agents working in this repository.

- After code changes, agents must run `./scripts/verify_and_deploy.sh` unless the user explicitly says to skip tests or skip deployment.
- Agents must execute deployment themselves when tool permissions allow it. Do not ask the user to run deploy commands on the agent's behalf.
- If a step fails, agents must report the exact failing command and error summary, and stop claiming completion.
- For any implemented change (feature, bugfix, refactor, or behavior tweak), agents must explicitly perform a test-gap analysis before finishing.
- Test-gap analysis must consider: regression risk, edge cases, affected service/repository/UI boundaries, and whether existing tests already cover the changed behavior.
- If tests are missing or coverage is weak, agents must add/update tests in the same task when feasible.
- If agents choose not to add tests, they must provide a concrete reason in the final response (not just "not needed").
- Before finalizing any task, agents must explicitly reflect on whether they learned anything that should be added to this file (`AGENTS.md` / `.gemini/GEMINI.md`) for future agents.
- If such guidance exists (pattern, pitfall, fix, workflow note), agents must update this file in the same task.
- Final response must include:
  - test result summary
  - test-gap analysis summary and why tests were added or not added
  - deploy/restart result summary
  - post-restart bot log health summary
  - whether an `AGENTS.md` knowledge update was made (and why, if not)

Canonical completion command:

```bash
./scripts/verify_and_deploy.sh
```

## Logging
- Use the project's logger from `bot/logger.py`
- All significant operations should be logged
- Logs go to daily files in `Logs/`

## Don't
- Don't put business logic in repository classes
- Don't access the database directly from commands or UI
- Don't create god classes that do everything
- Don't ignore existing patterns - follow what's already established

## Important Notes

### BotBehavior Attribute Naming
- Services in `BotBehavior` are stored with underscore prefix (private attributes)
- Use `behavior._audio_service`, `behavior._sound_service`, etc. (NOT `behavior.audio_service`)
- This pattern keeps services encapsulated while allowing access when needed

### Service Access Patterns
- `SoundService` has `sound_repo` attribute for repository access (e.g., `sound_service.sound_repo.get_sound_by_name()`)
- Services don't expose repository methods directly - access via `.sound_repo`, `.action_repo`, etc.
- Repository method names may differ from service methods - always verify by checking the repository class

### Upload Lock Re-entrancy
- `BotBehavior.upload_lock` is the same object as `SoundService.upload_lock`.
- If upload flows already hold that lock (for example `UploadSoundWithFileModal.callback` or `SoundService.prompt_upload_sound`) and then call `save_uploaded_sound_secure()`, the method must **not** try to acquire the same lock again.
- Use `save_uploaded_sound_secure(..., lock_already_held=True)` from these call sites to avoid self-deadlock.
- Symptom of regression: first upload hangs right after `calling save_uploaded_sound_secure`, then the next attempt reports upload is locked/in progress.

### Sounds Table Time Column
- Production `sounds` table writes use `timestamp` (not `date`) for insert paths.
- `SoundRepository.insert_sound()` and `SoundRepository.insert()` must target `timestamp` for modern schemas.
- Keep compatibility fallback to `date` only for legacy/test schemas that still expose `date`.
- Symptom of regression: upload/save reaches repository insert and fails with `table sounds has no column named date`.

### Similarity Cache After Upload
- New uploads that use `SoundRepository.insert_sound()` must invalidate the in-memory similarity cache (`Database.invalidate_sound_cache()`).
- Without cache invalidation, the sound exists on disk + DB but autocomplete/similarity (`Database.get_sounds_by_similarity`) can miss it until process restart.

### Ingest Loudness Normalization
- Direct MP3 ingest paths in `SoundService` (`save_uploaded_sound_secure` and `save_sound_from_url`) now normalize loudness on save before DB insert.
- This now uses a compression + peak-safe gain pass (not just flat average gain): `compress_dynamic_range` first, then gain clamped by `SOUND_INGEST_PEAK_CEILING_DBFS`.
- Defaults are tuned for "audible but not earrape": `SOUND_INGEST_TARGET_DBFS=-18.0`, `SOUND_INGEST_PEAK_CEILING_DBFS=-2.0`, `SOUND_INGEST_COMPRESS_ENABLED=true`, `SOUND_INGEST_COMPRESS_THRESHOLD_DBFS=-14.0`, `SOUND_INGEST_COMPRESS_RATIO=6.0`.
- Keep normalization best-effort (log failures and continue saving) so upload/import reliability is not blocked by ffmpeg/pydub edge cases.
- TikTok/YouTube/Instagram downloads that pass through `Downloads/` still get normalized in `SoundDownloader.move_sounds` and must use the same env knobs as `SoundService` to keep consistent loudness behavior.

### Testing Limitations
- Repository unit tests don't catch integration errors with Discord or BotBehavior
- Attribute name mismatches and service access patterns are only caught at runtime
- When adding new commands/UI, manually test the full flow to catch integration issues

### Web Playback Queueing
- `WebPage.py` now accepts omitted `guild_id` only when exactly one non-null guild ID can be inferred from stable persisted bot data (`guild_settings`, `sounds`, or `actions`). `playback_queue` is only a last-resort fallback if those tables are empty, so stale queue rows do not poison single-guild web playback. Multi-guild web callers must send `guild_id` explicitly or `/api/play_sound` returns `400`.
- Web playback now requires Discord OAuth login. `WebPage.py` expects `DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET`, and a stable `WEB_SESSION_SECRET`; set `DISCORD_OAUTH_REDIRECT_URI` explicitly in production if Flask cannot infer the public callback URL correctly.
- The Flask web app is now layered like the rest of the project: `WebPage.py` is only the entrypoint, `bot/web/app.py` builds the app, `bot/web/routes.py` owns route/controller wiring, and all SQL/business logic belongs in `bot/repositories/web_*.py` and `bot/services/web_*.py`.
- `playback_queue` rows now carry `request_username` and `request_user_id`. Keep schema migrations for those columns in place, and keep the queue consumer selecting them so web-triggered `play_request` analytics are attributed to the logged-in Discord user instead of `admin`/`webpage`.
- Do not embed raw sound filenames inside inline web `onclick` handlers. Many filenames contain apostrophes/quotes, so use `data-*` attributes plus JS event listeners for play buttons.
- Web routes should read SQLite via `app.config["DATABASE_PATH"]`, not a hardcoded `Data/database.db` path, so Flask tests and alternate DB configs hit the same code paths.
- When a web label can be censored or otherwise transformed for display, send `sound_id` back to `/api/play_sound` and resolve the real filename server-side instead of trusting the displayed string.

### Action Analytics Tracking
- For action rows that represent a sound play, store the sound database `id` in `actions.target`, not the filename. The stats/top/on-this-day queries join `actions.target` back to `sounds.id`, so filename targets make those plays disappear from analytics.
- Standardize list playback under action `play_from_list`. Do not invent per-list names like `play_random_from_<list_name>` unless you also update every stats query; existing leaderboards/year-review/on-this-day logic only recognizes `play_from_list`.

### Rocket League Store Data Source
- `/rlstore` uses `https://rlshop.gg/__data.json` for the featured shop and `https://rlshop.gg/<shop_id>/__data.json` for other active shops.
- Do not assume every active shop with `Type == "Featured"` uses the root `__data.json` node. The homepage node currently maps only to the shop whose `activeShops[].Name` matches decoded `shopName` (for example `Featured Shop` / id `52`), while other featured-type sections like `GARAGE GRAB` still require their own `/<shop_id>/__data.json` fetch.
- These payloads are SvelteKit/devalue-encoded: decode node `0` for `activeShops`/`lastUpdated` and node `1` for the selected shop body.
- The linked `dank/rlapi` repo is the upstream project behind `rlshop.gg`; using `rlshop.gg` avoids adding Epic auth/PsyNet session handling to this bot for read-only shop browsing.
- The interactive RL store UI now sends file attachments, not embeds, for the normal path. `RocketLeagueStoreView` renders a dedicated image card through `ImageGeneratorService.generate_rl_store_card()` so page buttons must replace the attached file (`attachments=[]` + `file=...`) when editing.
- RL store pages are now pre-rendered up front via `RocketLeagueStoreView.prepare_all_pages()`. Keep pagination tile-based and cache the image bytes so labeled direct-jump page buttons do not re-render on every button press.
- RL store paint badges in `templates/rl_store_card.html` are driven by per-paint style tokens from `RocketLeagueStoreView`; do not leave the badge CSS hard-coded to one color or paints like Orange/Sky Blue/Titanium White will render incorrectly.
- `RocketLeagueStoreView` uses `timeout=None` so shop page-jump buttons do not die after five minutes. Keep that unless the user explicitly wants expiring controls.
- RL store cards can exceed the simple `rows * constant height` estimate when item names wrap. Keep the Selenium render path measuring the real `.store-board` bounds and resizing the viewport before `Page.captureScreenshot`, otherwise the bottom of multi-row pages can get clipped.
- RL store notifications now also include a shared Merc-status string from `RocketLeagueStoreService.build_merc_status_text()`, and both the scheduled notification and `/rlstore` command notify the configured target user about that yes/no result.
- RL store notifications and `/rlstore` also include the `rlshop.gg` source URL from `RocketLeagueStoreService.build_source_url_text()`, wrapped as `<https://rlshop.gg>` so Discord does not unfurl it. Keep that helper shared so command and scheduler content stay aligned.
- The daily RL store notification in `BackgroundService` is intentionally a one-send-per-day catch-up window after the configured reset+5 time (default `19:05 UTC`), not an exact-minute-only fire. Dedupe is stored via `ActionRepository` with action `rlstore_daily_notification_sent`, so restarts later that day still send once instead of skipping the day entirely.
- The daily RL store notification now prefers a text channel named `botrl`; if `#botrl` does not exist in a guild, it falls back to the standard configured bot text channel via `MessageService.get_bot_channel()`.

### Requirements File Encoding
- `requirements.txt` is currently encoded as UTF-16 LE (with BOM), not UTF-8
- If dependency edits are needed, preserve UTF-16 encoding to avoid corrupting install behavior/diffs

### Sound Card Template Tracking
- The sound card UI used by `ImageGeneratorService` lives in `templates/sound_card.html`
- `templates/sound_card.html` is tracked in git; edits should appear in normal `git status`/`git diff`
- When changing sound-card layout/styling, verify behavior by running the bot and checking generated cards after deploy
- Image output size is also controlled in `bot/services/image_generator.py` via `_scale_png_bytes` (currently `self._card_image_scale = 0.75` in `ImageGeneratorService.__init__` and used by `_generate_sound_card_sync`), which affects all generated card sends (now-playing cards and `message_format="image"` notifications)
- Emoji in image-card text depends on container fonts and CSS fallback; keep `fonts-noto-color-emoji` installed in Docker and include emoji-capable families in the template `font-family` stack
- Keep a normal text font first in the stack (for example `DejaVu Sans`) and place emoji fonts later; if `Noto Color Emoji` is first, normal text can look spaced/odd

### Voice Session Analytics Tracking
- Voice analytics for `/top` and year-review now depend on `voice_activity` session rows written from `on_voice_state_update` in `PersonalGreeter.py`
- AFK transitions are intentionally handled as session boundaries for active channels only (joining AFK is not counted as active voice time)
- Voice session rows currently store `member.name` (not `name#discriminator`) to align with existing stats queries

### STT Feature Flag Enforcement
- `AudioService.start_keyword_detection` must enforce guild-level `stt_enabled` from `GuildSettingsService` before starting a sink.
- `ensure_voice_connected` can be invoked more than once in quick succession during join/event playback flows; without the guard, keyword detection may start even when STT is disabled and then immediately be stopped by background health checks.
- If Vosk appears to start and stop within seconds, verify `guild_settings.stt_enabled` for that guild first.
- **VoskWorker event-loop crash cycle**: The `KeywordDetectionSink` runs in a background thread. All `asyncio.run_coroutine_threadsafe()` calls in this thread MUST be guarded with `if not loop.is_closed():` before calling. Without this guard, the VoskWorker crashes with `RuntimeError: Event loop is closed` every time the bot shuts down while STT is active, which triggers a crash-restart loop every 2-3 minutes and leaves the voice client in a broken state. This was the root cause of intermittent silent audio including slap sounds.

### Inline Controls Button Normalization
- The minute background normalizer in `bot/services/background.py` is a safety dedupe pass; keep real-time cleanup in `on_message` (`handle_new_bot_message_for_controls_cleanup`) intact.
- When detecting/removing inline `⚙️` controls, prefer checking both reconstructed views (`discord.ui.View.from_message`) and raw `message.components`; relying on one source can miss existing buttons and cause duplicate `custom_id` edit failures.
- For row placement when adding buttons to existing messages, use live `message.components` row widths first and only fall back to reconstructed view row metadata.
- Avoid mass-rewriting recent playback messages in the minute normalizer. Reconstructing and re-saving old views can alter progress-button emoji/label presentation; only touch messages that actually need a controls-button fix.
- For real-time dedupe, remove old `⚙️` via raw component payload edits (using `message.components` + HTTP edit) instead of rebuilding with `discord.ui.View.from_message`; raw edits preserve existing progress-button labels/emoji better.
- Tracked `discord.Message` objects can have stale `components` after progress updates; fetch a fresh copy (`channel.fetch_message(message.id)`) before removing gear so current progress label/emoji are preserved.

### Progress Button Updates
- `AudioService.update_progress_bar` should not rely only on global `self.current_view`/`self.stop_progress_update` for task coordination; stale tasks can overwrite older messages after a new playback starts.
- Cancel the previous progress task before starting a new one and guard updates by message identity (`current_sound_message.id`) to keep historical progress labels stable.

### PCM Audio Mixing
- When combining concurrent raw PCM chunks from multiple users (e.g. from Discord Voice sinks), DO NOT simply concatenate them. Interleaved concatenations stretch out playback duration and cause severe lag/distortion.
- Use `audioop.add(mix_buffer, user_buffer, 2)` to properly sum overlapping 16-bit PCM bytes together while preserving real-time duration.

### FFmpegOpusAudio and Silent Failures
- `discord.FFmpegOpusAudio` wraps an `ffmpeg` process but its `AudioPlayer` thread silently ignores immediate `ffmpeg` exit-code crashes, interpreting empty pipe reads simply as normal EOF.
- When applying custom `before_options` like `-analyzeduration 0 -probesize 32`, mp3 files with ID3 headers larger than the probesize will cause ffmpeg to instantly crash.
- This creates an insidious bug where the bot's UI (progress bars, sound cards) fully iterates for the sound's standard duration, but absolutely no audio is emitted. Avoid specifying stringent probesize limits unless explicitly required.
- **stop/play race condition**: `voice_client.stop()` signals the AudioPlayer background thread to terminate, but returns immediately before the thread is done. Calling `voice_client.play()` too soon after (e.g. with a fixed `await asyncio.sleep(0.1)`) can race against the lingering thread, resulting in the new audio being silently discarded. Use a spinwait: `while voice_client.is_playing(): await asyncio.sleep(0.05)` (with a timeout) after `stop()` to guard against this.
- **is_playing() is NOT sufficient** as a completion guard: `AudioPlayer.is_playing()` returns `False` immediately after `stop()` sets the `_end` event — but the thread is still alive running its `finally` block (cleanup + `after` callback). The only reliable check is `player.is_alive()` on the thread object itself. Capture the `_player` reference **before** calling `stop()` (since `stop()` clears `voice_client._player` to `None`), then poll `player.is_alive()`. This is encapsulated in `AudioService._stop_voice_client_and_wait()`.
- The same `_player.is_alive()` guard is also needed for the **non-interrupt path** in `AudioService.play_audio()`: after a sound ends naturally, `voice_client.is_playing()` may already be `False` while the old `AudioPlayer` thread is still alive. Starting the next sound in that window can produce the "bot speaks / UI runs / no audible sound" symptom. Check for a lingering `_player` and wait before `voice_client.play()`.
- Join/entrance sounds can still be silently missed even when `PLAY-DEBUG` shows a healthy full playback lifecycle (`play_started`, `start_probe`, `play_after status=ok`) because the listener may not be fully ready right after `on_voice_state_update` join. `AudioService.play_audio()` now applies an entrance-only warmup delay before starting playback (configurable via `ENTRANCE_PLAYBACK_START_DELAY_SECONDS`, default `1.0`).
- `AudioService.play_slap()` must also guard the "not currently playing" path: even when `voice_client.is_playing()` is already `False`, a lingering `_player` thread can still be alive and drop the next slap silently. Check `_player.is_alive()` and wait before `voice_client.play()`.
- For slap playback specifically, adding a short ffmpeg pre-roll silence (`adelay=120:all=1`) in the filter chain helps avoid cases where Discord shows speaking but drops the first burst of audio.
- Short MP3 slap clips can decode as **empty output** under low-latency ffmpeg startup flags (`-fflags nobuffer -flags low_delay`). For slap reliability, use conservative `before_options` (`-nostdin`) even when global audio latency mode is `low_latency`.
- Short **non-slap** MP3 clips can hit the same low-latency startup issue. `AudioService.play_audio()` now enables short-clip safety for low-latency mode (<=2.0s MP3): conservative `before_options` (`-nostdin`) plus a small `adelay` pre-roll before playback.
- To reduce "first second cut" on normal MP3 playback in `low_latency` mode, `AudioService.play_audio()` now applies low-latency MP3 startup safety for all MP3s: conservative `before_options` plus a configurable pre-roll floor (`LOW_LATENCY_MP3_START_PREROLL_MS`, default `650`).
- `AudioService.play_audio()` now also applies playback-time ear-protection filters by default (compressor + lowpass + attenuation) via `SOUND_PLAYBACK_EAR_PROTECTION_*` envs, with stronger profile automatically for filenames matching `SOUND_EARRAPE_KEYWORDS`.
- Low-fidelity MP3 inputs (<=24kHz or <=96kbps) can develop rising hiss when playback-time compression is always on. `AudioService.play_audio()` now auto-relaxes ear-protection for those sources (skip compressor/lowpass, keep attenuation), except for filenames matching earrape keywords.
- In ffmpeg `acompressor`, `makeup` must stay in range `[1, 64]`. Using `makeup=0` causes filter-parse failure (`Error applying option 'makeup'`) and playback ends almost immediately with no audible output.
- If slap remains silent even with conservative `before_options` and logs show normal `voice_client.play()`/completion, prefer a slap-specific PCM path (`discord.FFmpegPCMAudio` + `discord.PCMVolumeTransformer`) instead of `FFmpegOpusAudio.from_probe` to avoid short-clip transcode/probe edge cases.

### Discord Voice 4017 (DAVE Enforcement)
- As of **March 2, 2026**, Discord enforces DAVE end-to-end encryption for **non-stage** voice calls. Outdated voice clients are rejected with close code `4017`.
- Symptom pattern in this project: `Failed to connect to voice... Retrying...` + `discord.errors.ConnectionClosed ... code 4017`, followed by playback failures like `Error starting playback: Not connected to voice.`
- This project now applies a runtime backport in `bot/voice_compat.py` (identify `max_dave_protocol_version`, DAVE transition handling, MLS binary frame handling, and DAVE-aware opus wrapping) to keep py-cord voice usable under enforcement.
- `davey==0.1.4` is now a hard runtime dependency for voice in Docker. If `davey` is missing, DAVE negotiation cannot complete and `4017` will recur.
- `VOICE_MAX_DAVE_PROTOCOL_VERSION` defaults to auto-detected `davey.DAVE_PROTOCOL_VERSION` (currently `1`). Do not force it to `0` in production unless intentionally disabling voice while debugging.
- In py-cord `VoiceClient.connect_websocket()`, `VoiceClient.ws` is still `utils.MISSING` while `ws.poll_event()` is processing handshake frames. Any DAVE MLS send path during `SESSION_DESCRIPTION` must use the live `DiscordVoiceWebSocket` reference (for example `_voicecompat_active_ws`) instead of `self.ws` to avoid `'_MissingSentinel' object has no attribute 'send_binary'`.
- Reconnect loops can additionally produce `_MissingSentinel` (`poll_event`/`close`) and `Unclosed connection` noise; these are secondary effects after the initial `4017` rejection.
- **STT/recording with DAVE requires inbound media decrypt**: patching only outbound voice packets (`encrypt_opus`) is not enough. `voice_client.start_recording()`/sinks receive RTP-decrypted bytes that still contain DAVE-encrypted opus payloads; without `dave_session.decrypt(user_id, davey.MediaType.audio, packet)` in `VoiceClient.unpack_audio`, logs spam `Error occurred while decoding opus frame.` / `error has happened in opus_decode` and keyword detection appears dead even though `audio_keyword_sink_count` is non-zero.
- DAVE inbound decrypt depends on `ssrc -> user_id` mapping (`ws.ssrc_map`). When mapping is not available yet, drop those packets until mapping arrives; attempting opus decode on still-encrypted payloads causes continuous decoder errors and high CPU.


## Deployment

### Restarting the Bot
After making code changes, **always restart the Docker containers** to deploy:

```bash
cd /home/gabi/github/Discord-Brain-Rot
docker-compose restart
```

The bot runs in Docker, so changes to Python files won't take effect until the container is restarted.

- The `web` service is now profile-gated (`profiles: ["web"]`) for public launch. In normal production flow, restart only the bot service:
```bash
docker-compose restart bot
```
- Compose profiles do not auto-stop already running containers. If `web` was previously started, explicitly stop it when launching bot-only mode:
```bash
docker-compose stop web
```

- If system dependencies or fonts change in `Dockerfile`, restart is not enough; rebuild and recreate containers first:
```bash
docker-compose build
docker-compose up -d --force-recreate
```

### Viewing Logs
To monitor the bot after restart:
```bash
docker-compose logs -f bot
```

Or check the log files directly in `Logs/` (named by date, e.g., `2026-01-26.log`).

- `docker-compose logs --tail=120 bot` right after `docker-compose restart` may include shutdown-time stack traces from the old container (for example `RuntimeError: Event loop is closed` from voice threads).
- Treat those as restart noise unless the same errors continue repeating after the new container is up and logging fresh heartbeat/activity lines.
