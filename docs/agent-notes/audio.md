# Audio, Voice, And Sound Agent Notes

Read this when changing uploads, sound ingest, playback, generated sound cards, Discord voice, Vosk keyword detection, TTS/STS playback, or audio FFmpeg options.

## Upload And Ingest

- Upload flows that already hold `BotBehavior.upload_lock` / `SoundService.upload_lock` must pass `lock_already_held=True` into `save_uploaded_sound_secure()` to avoid self-deadlock.
- Production `sounds` inserts use `timestamp`, not `date`. Keep `date` only as a compatibility fallback for legacy/test schemas.
- New uploads through `SoundRepository.insert_sound()` must invalidate `Database.invalidate_sound_cache()` so similarity/autocomplete sees the new sound before restart.
- Direct MP3 ingest in `SoundService.save_uploaded_sound_secure()` and `save_sound_from_url()` normalizes loudness on save before DB insert.
- Normalization uses compression plus peak-safe gain: `compress_dynamic_range` first, then gain clamped by `SOUND_INGEST_PEAK_CEILING_DBFS`.
- Defaults are tuned for audible but controlled ingest: `SOUND_INGEST_TARGET_DBFS=-18.0`, `SOUND_INGEST_PEAK_CEILING_DBFS=-2.0`, `SOUND_INGEST_COMPRESS_ENABLED=true`, `SOUND_INGEST_COMPRESS_THRESHOLD_DBFS=-14.0`, `SOUND_INGEST_COMPRESS_RATIO=6.0`.
- Keep normalization best-effort: log failures and continue saving so ffmpeg/pydub edge cases do not block uploads/imports.
- TikTok/YouTube/Instagram downloads passing through `Downloads/` are normalized in `SoundDownloader.move_sounds`; keep env knobs consistent with `SoundService`.
- TikTok collection favorite watchers use `FavoriteWatcherService` and `SoundService.import_sound_from_video()` to import directly into the guild-scoped sound library. Adding a watcher seeds current collection videos as already seen so only future additions import, then each successful future import posts a `DownloadedSoundView` image-card notification.

## Generated Sound Cards

- The sound card UI lives in `templates/sound_card.html`, which is tracked in git.
- Image output size is also controlled in `bot/services/image_generator.py` via `_scale_png_bytes` and `ImageGeneratorService._card_image_scale`.
- When changing card layout/styling, verify behavior by running the bot and checking generated cards after deploy.
- Emoji rendering depends on container fonts and CSS fallback. Keep `fonts-noto-color-emoji` installed in Docker and include emoji-capable families in the template `font-family` stack.
- Keep a normal text font first, such as `DejaVu Sans`, and place emoji fonts later. `Noto Color Emoji` first can make normal text spacing look odd.

## Playback And FFmpeg

- `discord.FFmpegOpusAudio` can silently treat immediate ffmpeg crashes as normal EOF. The bot UI may run progress for the full duration while no audio is emitted.
- Avoid stringent probe flags such as `-analyzeduration 0 -probesize 32` for MP3s with large ID3 headers unless required.
- After `voice_client.stop()`, wait for the old audio player thread to finish before calling `play()`. `is_playing()` can become false before the thread exits.
- Capture `voice_client._player` before stop and poll `player.is_alive()` with a timeout. This is encapsulated in `AudioService._stop_voice_client_and_wait()`.
- Also guard the non-interrupt path before starting the next sound after natural completion; a lingering `_player` can drop the new sound.
- Join/entrance sounds use a warmup delay before playback because the listener may not be ready immediately after `on_voice_state_update`; default `ENTRANCE_PLAYBACK_START_DELAY_SECONDS=1.0`.
- `AudioService.play_slap()` must guard both interrupted and not-currently-playing paths for lingering player threads.
- Slap playback benefits from short ffmpeg pre-roll silence (`adelay=120:all=1`).
- Short MP3 slap clips can decode as empty output with low-latency ffmpeg startup flags. Use conservative slap `before_options` (`-nostdin`) even when global latency mode is low.
- Short non-slap MP3s also use low-latency safety: conservative `before_options` plus small pre-roll.
- Normal MP3 playback in low-latency mode uses a configurable pre-roll floor, `LOW_LATENCY_MP3_START_PREROLL_MS` default `650`.
- Playback-time ear protection is on by default through `SOUND_PLAYBACK_EAR_PROTECTION_*`; stronger settings apply for filenames matching `SOUND_EARRAPE_KEYWORDS`.
- Low-fidelity MP3 inputs can develop hiss with compression. The service relaxes ear protection for those sources except earrape-keyword matches.
- In ffmpeg `acompressor`, `makeup` must stay in `[1, 64]`; `makeup=0` fails filter parsing and can produce near-immediate silent completion.
- If slap remains silent despite conservative options and normal logs, prefer a slap-specific PCM path (`discord.FFmpegPCMAudio` + `discord.PCMVolumeTransformer`) over `FFmpegOpusAudio.from_probe`.

## Progress And Inline Controls

- `AudioService.update_progress_bar` should not rely only on global `self.current_view` / `self.stop_progress_update`; stale tasks can overwrite older messages.
- Cancel the previous progress task before starting a new one and guard updates by `current_sound_message.id`.
- The minute background inline-controls normalizer in `bot/services/background.py` is a safety dedupe pass; keep real-time cleanup in `on_message`.
- When detecting/removing inline controls, check reconstructed views and raw `message.components`.
- For row placement, prefer live `message.components` row widths and only fall back to reconstructed view metadata.
- Avoid mass-rewriting recent playback messages. Only touch messages that need a controls-button fix.
- Real-time dedupe should remove old controls through raw component payload edits, preserving existing progress labels/emoji.
- Tracked `discord.Message` objects can have stale `components`; fetch a fresh copy before removing controls.

## Vosk Keyword Detection

- Vosk keyword detection remains supported for configured trigger words. Do not remove `Data/models/vosk-model-small-pt-0.3`, `KeywordCog`, `KeywordRepository`, the `AudioService` recording sink, or DAVE inbound decrypt unless explicitly asked.
- The removed feature is only ambient Ventura LLM/commentary: no LLM provider/profile stack, no `_ai_commentary_service`, and no `/ventura` admin toggle. Manual Ventura `/tts` and `/sts` remains.
- `AudioService.start_keyword_detection` must enforce guild-level `stt_enabled` from `GuildSettingsService`.
- `ensure_voice_connected` can be invoked multiple times during join/event playback; guard against starting keyword detection when STT is disabled.
- If Vosk starts and stops within seconds, verify `guild_settings.stt_enabled` first.
- `KeywordDetectionSink` runs in a background thread. Guard `asyncio.run_coroutine_threadsafe()` with `if not loop.is_closed():`.
- Startup auto-join is owned by `BackgroundService._auto_join_channels()`. Do not add a second `on_ready` auto-join in `PersonalGreeter.py`.
- Final keyword latency is driven by `KeywordDetectionSink.silence_flush_seconds` / `KEYWORD_SILENCE_FLUSH_SECONDS` plus worker queue timeout. Partials are faster but less stable.

## PCM And DAVE

- When combining concurrent raw PCM chunks from Discord voice sinks, do not concatenate; use `audioop.add(mix_buffer, user_buffer, 2)` to preserve real-time duration.
- As of March 2, 2026, Discord enforces DAVE end-to-end encryption for non-stage voice calls. Outdated voice clients fail with close code `4017`.
- Symptom: `Failed to connect to voice... Retrying...`, `discord.errors.ConnectionClosed ... code 4017`, then playback errors such as `Not connected to voice`.
- Runtime backport lives in `bot/voice_compat.py` and handles identify `max_dave_protocol_version`, DAVE transition, MLS binary frames, and DAVE-aware opus wrapping.
- `davey==0.1.4` is a hard runtime dependency for Docker voice.
- `VOICE_MAX_DAVE_PROTOCOL_VERSION` defaults to detected `davey.DAVE_PROTOCOL_VERSION`; do not force `0` in production unless intentionally disabling voice while debugging.
- During py-cord handshake, `VoiceClient.ws` can still be `utils.MISSING`; DAVE MLS send paths must use the live websocket reference such as `_voicecompat_active_ws`.
- STT/recording with DAVE requires inbound media decrypt in `VoiceClient.unpack_audio`; outbound encryption alone is not enough.
- DAVE inbound decrypt depends on `ssrc -> user_id` mapping from `ws.ssrc_map`; drop packets until mapping exists.

## STS Playback

- STS generated audio should call `AudioService.play_audio(..., is_tts=True, allow_tts_interrupt=True)`. Without `allow_tts_interrupt=True`, transformed clips can be dropped as "Another TTS is already running" while the source/previous sound is still playing.
