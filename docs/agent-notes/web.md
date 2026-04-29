# Web Soundboard Agent Notes

Read this when changing `WebPage.py`, `bot/web/`, web repositories/services, templates/static assets for the soundboard, Flask auth, web uploads, web playback, web TTS, or the web control room.

## Architecture

- The Flask app is layered like the bot: `WebPage.py` is only the entrypoint, `bot/web/app.py` builds the app, `bot/web/routes.py` registers focused route modules (`*_routes.py`), and shared route helpers live in `bot/web/route_helpers.py`.
- Flask-owned page templates and static assets live under `bot/web/templates/` and `bot/web/static/`. Root `templates/sound_card.html` and `templates/rl_store_card.html` are image-card templates used by `ImageGeneratorService`, not Flask page templates.
- SQL/business logic belongs in `bot/repositories/web_*.py` and `bot/services/web_*.py`; route modules should stay thin request/response adapters.
- Web routes should read SQLite through `app.config["DATABASE_PATH"]`, not a hardcoded `Data/database.db`, so tests and alternate DB configs use the same paths.
- The web control-room panel is backed by `web_bot_status`, written by `BackgroundService.web_control_room_status_loop()` every 2 seconds. Flask reads it through `WebControlRoomRepository`/`WebControlRoomService`; do not inspect live Discord objects from Flask.

## Guilds And Auth

- Omitted `guild_id` is allowed only when exactly one non-null guild can be inferred from stable persisted data: `guild_settings`, `sounds`, `actions`, or `web_bot_status`. `playback_queue` is only a last-resort fallback when those tables are empty.
- Multi-guild web callers must send `guild_id` explicitly or `/api/play_sound` returns `400`.
- The soundboard has a guild selector backed by persisted guild data. Keep selected `guild_id` flowing through table endpoints, control-room status, play/control requests, and web uploads.
- Web playback requires Discord OAuth login. `WebPage.py` expects `DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET`, and stable `WEB_SESSION_SECRET`; set `DISCORD_OAUTH_REDIRECT_URI` explicitly in production if Flask cannot infer the public callback URL.
- Web upload moderation should mirror `BotBehavior.is_admin_or_mod`: OAuth requests `identify guilds`, stores `DiscordWebUser.admin_guild_ids`, and treats users as web admins for a selected guild when they are owners or Discord reports Administrator / Manage Server / Manage Channels. If a known admin cannot see the inbox, have them log out/in to refresh scopes and admin guild IDs.

## Playback Queue Transport

- `playback_queue` is an internal Flask-to-bot transport table, not a user-facing sound queue. Do not show pending queue counts or "Queue/Queued" wording in the UI.
- Rows carry `request_username` and `request_user_id`; keep migrations and bot-side selection in sync so web-triggered analytics are attributed to the logged-in Discord user.
- Web Slap and mute-toggle controls are sent through `playback_queue` using `request_type`/`control_action`, not executed directly in Flask.
- Web "Play similar" uses `request_type='play_sound'` and `playback_queue.play_action='play_similar_sound'` so analytics match the Discord similar-sound select.
- Web TTS uses control action `tts`; `sound_filename` is JSON with `message` and `profile`. Bot-side dispatch routes Google profiles to `VoiceTransformationService.tts()` and ElevenLabs character profiles to `tts_EL()`.
- Web play-button latency is dominated by the bot-side `check_playback_queue` polling loop in `PersonalGreeter.py`. Keep it driven by `config.PLAYBACK_QUEUE_INTERVAL` (default `0.25` seconds); avoid fixed sleeps after `process_playback_queue_request()` without a concrete Discord race or rate-limit reason.
- Web playback can hit stale renamed DB rows where `sounds.Filename` is missing on disk but `sounds.originalfilename` still exists. Keep the fallback in `WebPlaybackService.process_playback_queue_request()`.
- Web soundboard duration display has the same renamed-row issue: show `sounds.Filename` to users, but fall back to `sounds.originalfilename` when reading MP3 metadata from disk.

## Uploads

- Web uploads use the same user-facing fields as `UploadSoundWithFileModal`: URL, MP3 file, custom name, and video time limit. File upload takes priority. Supported URLs are MP3/TikTok/YouTube/Instagram.
- Uploads are approved by default and recorded in `web_uploads`. Rejected uploads should remain auditable and should blacklist the linked sound when `sounds.blacklist` exists.
- Web uploads are queued through in-process Flask background jobs. `/api/upload_sound` returns `202` with `job_id`; clients poll `/api/upload_sound/<job_id>` until `approved` or `error`. Keep request handlers fast.
- Job status is in-memory; a web restart can drop active status polling even when already-started processing completed or failed.
- Docker web uploads must write to the same host-mounted `Sounds/` directory the bot reads (`/app/Sounds` in both containers).
- Do not put `.play-button` on the web upload submit button. Soundboard JS initializes every `.play-button` as an audio control and can rewrite upload text to the play icon.

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

## Soundboard Layout

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
- Verify desktop control-room/table rhythm around screenshot-like viewports such as `1580x960`; the 7-row tables rely on compact desktop header/row heights.
- On mobile, the control room should be a compact two-row controller: status plus slap/mute buttons on row one, voice facts on row two.
- Mobile play/slap/mute buttons need direct `touchend` handlers with duplicate-click suppression.
- On mobile, nav intentionally scrolls away and the control-room panel is the sticky top element. Do not make both sticky.
