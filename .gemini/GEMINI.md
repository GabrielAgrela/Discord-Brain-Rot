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

### Web Playback Requests
- `WebPage.py` now accepts omitted `guild_id` only when exactly one non-null guild ID can be inferred from stable persisted bot data (`guild_settings`, `sounds`, `actions`, or `web_bot_status`). `playback_queue` is only a last-resort fallback if those tables are empty, so stale queue rows do not poison single-guild web playback. Multi-guild web callers must send `guild_id` explicitly or `/api/play_sound` returns `400`.
- The web soundboard has a guild selector backed by persisted guild data. Keep selected `guild_id` flowing through table endpoints, control-room status, play/control requests, and web uploads; do not regress to implicit guild inference for normal multi-guild UI actions.
- Web playback now requires Discord OAuth login. `WebPage.py` expects `DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET`, and a stable `WEB_SESSION_SECRET`; set `DISCORD_OAUTH_REDIRECT_URI` explicitly in production if Flask cannot infer the public callback URL correctly.
- Web uploads use the same user-facing fields as `UploadSoundWithFileModal`: URL, MP3 file, custom name, and video time limit. File upload takes priority over URL, supported URLs are MP3/TikTok/YouTube/Instagram, uploads are approved by default and recorded in `web_uploads`. Rejected web uploads should remain auditable and should blacklist the linked sound when `sounds.blacklist` exists.
- Web uploads are queued through in-process Flask background jobs. `/api/upload_sound` returns `202` with a `job_id`, and clients poll `/api/upload_sound/<job_id>` until `approved`/`error`; keep request handlers fast and do not move MP3 download/normalization back into the request thread. Job status is in-memory, so a web restart can drop active status polling even though already-started file processing may have completed or failed.
- Docker web uploads must write into the same host-mounted `Sounds/` directory that the bot reads (`/app/Sounds` in both containers). If the web service lacks that mount, uploads still appear in DB/web tables but bot playback skips them with `Sound file not found at '/app/Sounds/<name>.mp3'`.
- Do not put `.play-button` on the web upload submit button. Soundboard JS initializes every `.play-button` as an audio play control and will rewrite upload text to the play icon.
- Web upload moderation should follow `BotBehavior.is_admin_or_mod` semantics in web form: OAuth requests `identify guilds`, stores `DiscordWebUser.admin_guild_ids`, and treats users as web admins for a selected guild when they are in `OWNER_USER_IDS` or Discord reports Administrator / Manage Server / Manage Channels for that guild. If a known admin cannot see the inbox after this change, have them log out/in so the session gets the `guilds` scope and refreshed admin guild IDs.
- The Flask web app is now layered like the rest of the project: `WebPage.py` is only the entrypoint, `bot/web/app.py` builds the app, `bot/web/routes.py` owns route/controller wiring, and all SQL/business logic belongs in `bot/repositories/web_*.py` and `bot/services/web_*.py`.
- `playback_queue` is an internal Flask-to-bot transport table, not a user-facing sound queue. Do not show pending queue counts or "Queue/Queued" wording in the web UI; buttons should read as direct play/control requests with "Play" and "Sent" states.
- `playback_queue` rows now carry `request_username` and `request_user_id`. Keep schema migrations for those columns in place, and keep the request consumer selecting them so web-triggered `play_request` analytics are attributed to the logged-in Discord user instead of `admin`/`webpage`.
- Web Slap and mute-toggle controls are sent through `playback_queue` using `request_type`/`control_action`, not executed directly in Flask. Keep those column migrations and the bot-side `process_playback_queue_request()` dispatch in sync when adding more web controls.
- Web TTS is also sent through `playback_queue` as control action `tts`; its `sound_filename` payload is JSON containing `message` and `profile`, so keep bot-side control dispatch parsing that payload and routing Google profiles to `VoiceTransformationService.tts()` and ElevenLabs character profiles to `tts_EL()`.
- Web TTS should mirror Discord `/tts`: default the modal profile to `ventura`, send a loading GIF/card to the bot channel before generation, pass it as `loading_message`, and pass ElevenLabs profile thumbnails as `sts_thumbnail_url` so `AudioService.play_audio()` deletes the loading message and sends the final character card.
- Web TTS enhancement is a pre-send text transform, not part of playback queue execution. Keep `/api/tts/enhance` authenticated, route OpenRouter calls through `WebTtsEnhancerService`, and treat `OPENROUTER_API_KEY` as optional so normal TTS still works when enhancement is not configured.
- Web play-button latency is dominated by the bot-side `check_playback_queue` polling loop in `PersonalGreeter.py`. Keep it driven by `config.PLAYBACK_QUEUE_INTERVAL` (default `0.25` seconds), and avoid adding fixed sleeps after `process_playback_queue_request()` unless there is a concrete Discord rate-limit or race reason.
- Do not embed raw sound filenames inside inline web `onclick` handlers. Many filenames contain apostrophes/quotes, so use `data-*` attributes plus JS event listeners for play buttons.
- Web routes should read SQLite via `app.config["DATABASE_PATH"]`, not a hardcoded `Data/database.db` path, so Flask tests and alternate DB configs hit the same code paths.
- When a web label can be censored or otherwise transformed for display, send `sound_id` back to `/api/play_sound` and resolve the real filename server-side instead of trusting the displayed string.
- Web playback can encounter stale renamed DB rows where `sounds.Filename` no longer exists on disk but `sounds.originalfilename` still does. Keep the request consumer fallback in `WebPlaybackService.process_playback_queue_request()` so a missing requested filename tries the original file before skipping.
- The soundboard desktop layout should use the viewport as a maximum, not stretch tables to fill the viewport. Keep rows at their natural CSS height, keep `.table-container` as `flex: 0 1 auto` with a max-height, and keep `per_page` fixed to the chosen safe value. Stretching row heights or dynamically shrinking page size from JS caused bottom dead space, clipping, and `per_page` oscillation.
- Keep desktop soundboard control areas vertically balanced across cards. If one card has a custom control row like `.library-controls`, match its reserved bottom spacing to the normal search/filter footprint or card bottoms will drift even when each table has the same 7-row height.
- The soundboard rounded-bottom padding (`--table-bottom-inset`) is only visual breathing room. Clip detection should compare the last row against the actual `.table-container` bottom, not subtract that padding, or every natural-height table can look falsely clipped and collapse `per_page` down to 1.
- The soundboard first paint must stay layout-stable before API responses arrive. Render the first page of actions/favorites/all-sounds and visible action filters server-side in `index.html`, seed the JS cache from `initial_soundboard_data`, and do not immediately refetch/repaint on load. Keep initial filter payloads trimmed to visible controls; embedding unused sound/date filter lists can make first paint heavier and can cause the refresh loop to repaint filters. Falling back to placeholder rows or `display=swap` web fonts creates a visible opening adjustment even when the settled layout is correct.
- Soundboard refresh calls use `include_filters=0` for actions, favorites, and all-sounds. Treat missing/empty `filters` as "no filter update", not as an empty option list, or the first 2-second refresh collapses dropdowns to only their `All ...` option. Do not poll all-sounds with full filters; production sound/date filter metadata is hundreds of KB.
- Favorites table user filtering is based on the latest per-user `favorite_sound`/`unfavorite_sound` action for each sound, not raw historical favorites. Keep `WebContentRepository.get_favorites_page()`, `count_favorites()`, and `get_favorite_filters()` in sync if changing favorite semantics.
- Keep the desktop soundboard page size at 7 rows unless the card layout is redesigned. 8 natural-height rows fit only mathematically and can still clip visually against the rounded table/card bottom on real 1920x1080 browser chrome.
- Do not reintroduce click-time auto-shrink for soundboard `per_page`. The old `isLastTableRowClipped()` / `isCardOverflowingViewport()` reduction path made pagination keep getting smaller after Next/Prev clicks when browser chrome or responsive widths changed the measured geometry.
- Soundboard pagination must support direct `touchend` handling and should make exactly one fetch per tap/click. The old cooldown handler disabled both buttons and scheduled a second refresh after 500ms, which made mobile taps feel ignored or flaky.
- The web soundboard control-room panel is backed by `web_bot_status`, written by `BackgroundService.web_control_room_status_loop()` every 2 seconds. Keep runtime status writes in the bot process and web reads in `WebControlRoomRepository`/`WebControlRoomService`; do not try to inspect live Discord objects from Flask.
- `GET /api/control_room/status` combines `web_bot_status` and mute state. It intentionally does not expose pending `playback_queue` summary data. If changing web request guild inference, keep `web_bot_status` in the stable guild discovery set so single-guild deployments can load the control-room panel without an explicit `guild_id`.
- The web soundboard slap/mute controls belong inside the control-room panel, not in the nav header. Keep the control-room metrics as a flat status strip, not boxed cards inside the rounded banner, and verify the desktop control-room/table rhythm at screenshot-like viewports (around 1580x960); the 7-row tables fit by using compact desktop `--table-header-height`/`--table-row-height` values instead of shrinking `per_page`.
- On mobile, keep the control room as a compact two-row controller: status plus slap/mute buttons on the first row, voice facts on the second row. Avoid restoring the four-item metric grid on phones; it makes the banner look boxy and wastes vertical space.
- Mobile play/slap/mute buttons need direct `touchend` handlers with duplicate-click suppression, not only delegated `click`. Some mobile browsers can make the synthesized click path feel dead or delayed, and the soundboard already uses this pattern for pagination.
- On mobile, the nav intentionally scrolls away and the control-room panel is the sticky top element. Do not make both the nav and control room sticky on phones, or they stack awkwardly and waste vertical space.

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

### Year Review GIF Generation
- `/yearreview` and `/weeklywrapped` send compact animated GIFs generated from a Remotion MP4 render. `YearReviewVideoService` prepares props from stats payloads, invokes the local Remotion CLI from `trailer/node_modules/.bin/remotion`, then converts/compresses with ffmpeg.
- `/yearreview` should edit the original progress response into a file-only GIF message instead of sending a separate captioned follow-up. Keep the animated top-sounds scene capped to four rows unless the layout is redesigned; five rows clip at 960x540.
- Keep the year-review/weekly-wrapped Remotion background visually seamless with Discord chat (`#313338`) and avoid decorative confetti/equalizer/glow layers; those made the GIF look detached from the chat UI and worsened compression.
- The Docker bot image must include Node.js because Remotion's CLI is a Node executable. If `/yearreview` fails with `env: 'node': No such file or directory`, rebuild/recreate the bot image; a plain restart is not enough after Dockerfile dependency changes.
- The Remotion source lives under `bot/remotion_year_review/` instead of `trailer/` because `bot/` is volume-mounted into the Docker bot container for normal restart deploys. Do not move required runtime composition files into unmounted `trailer/src` unless the deploy flow is changed to rebuild/recreate the image.
- Keep Remotion/GIF generation in the service layer and keep Discord progress edits in `StatsCog`; the renderer should not import Discord APIs or query repositories directly.
- GIF output is capped by the guild upload limit with a conservative margin, or by `YEAR_REVIEW_GIF_MAX_MB` / `WEEKLY_WRAPPED_GIF_MAX_MB` when set. If the GIF still exceeds the cap, the command should fall back to the text embed instead of attempting an oversize upload.

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

### Vosk Keyword Detection
- Vosk keyword detection is still supported for configured trigger words (for example `diogo`, `hugo`, and other DB keywords). Do not remove `Data/models/vosk-model-small-pt-0.3`, `KeywordCog`, `KeywordRepository`, the `AudioService` recording sink, or DAVE inbound decrypt unless explicitly asked.
- The removed feature is only the ambient Ventura LLM/commentary routine: no LLM provider/profile stack, no `_ai_commentary_service`, and no `/ventura` admin toggle. Manual Ventura `/tts` and `/sts` voice support stays intact.
- `AudioService.start_keyword_detection` must enforce guild-level `stt_enabled` from `GuildSettingsService` before starting a sink.
- `ensure_voice_connected` can be invoked more than once in quick succession during join/event playback flows; without the guard, keyword detection may start even when STT is disabled and then immediately be stopped by background health checks.
- If Vosk appears to start and stop within seconds, verify `guild_settings.stt_enabled` for that guild first.
- `KeywordDetectionSink` runs in a background thread. All `asyncio.run_coroutine_threadsafe()` calls in this thread must be guarded with `if not loop.is_closed():` before calling.
- Startup auto-join is owned by `BackgroundService._auto_join_channels()`. Do not add a second `on_ready` auto-join path in `PersonalGreeter.py`; duplicate joins can disconnect the first voice client and make startup playback fail with `Not connected to voice`.
- Final keyword detection latency is driven by `KeywordDetectionSink.silence_flush_seconds` / `KEYWORD_SILENCE_FLUSH_SECONDS` plus the worker queue timeout. Keep detection based on final/silence flush unless explicitly asked to use Vosk partial hypotheses; partials are faster but less stable.

### PCM Audio Mixing
- When combining concurrent raw PCM chunks from multiple users (for example from Discord Voice sinks), do not concatenate them. Interleaved concatenations stretch playback duration and cause severe lag/distortion.
- Use `audioop.add(mix_buffer, user_buffer, 2)` to properly sum overlapping 16-bit PCM bytes while preserving real-time duration.

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
- STT/recording with DAVE requires inbound media decrypt: patching only outbound voice packets (`encrypt_opus`) is not enough. `voice_client.start_recording()`/sinks receive RTP-decrypted bytes that still contain DAVE-encrypted opus payloads; without `dave_session.decrypt(user_id, davey.MediaType.audio, packet)` in `VoiceClient.unpack_audio`, logs spam `Error occurred while decoding opus frame.` / `error has happened in opus_decode` and keyword detection appears dead even when `audio_keyword_sink_count` is non-zero.
- DAVE inbound decrypt depends on `ssrc -> user_id` mapping (`ws.ssrc_map`). When mapping is not available yet, drop those packets until mapping arrives; attempting opus decode on still-encrypted payloads causes continuous decoder errors and high CPU.

### Speech-to-Speech Playback
- STS generated audio should call `AudioService.play_audio(..., is_tts=True, allow_tts_interrupt=True)`. Without `allow_tts_interrupt=True`, `play_audio()` treats the transformed clip like normal TTS and drops it with "Another TTS is already running" whenever the source/previous sound is still playing.


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
- `./scripts/verify_and_deploy.sh` uses `docker-compose restart`, which may only restart default-profile services. After web UI/template/static changes, explicitly restart `web` too when that profile-gated container is running:
```bash
docker-compose restart web
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
