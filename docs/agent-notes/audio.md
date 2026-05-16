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

## Voice Commands (Wake Word + Groq Whisper)

- **Default wake word**: The default is `ventura`, which IS in the bundled Portuguese Vosk model vocabulary (`vosk-model-small-pt-0.3`). No OOV warnings, no phonetic aliases needed.
- **Two-layer design**: human-facing wake words (`VOICE_COMMAND_WAKE_WORDS`, default `ventura`) are used for transcript parsing, while **Vosk wake aliases** (`VOICE_COMMAND_WAKE_ALIASES`, default `ventura`) are injected into the Vosk grammar. Both default to the same word, but can be configured independently for custom models.
- **Historical OOV gotcha**: The prior default was the English token `bot`, which was **out of vocabulary** for `vosk-model-small-pt-0.3`. Injecting `bot` into Vosk grammar produced `Ignoring word missing in vocabulary` warnings and the word was never detected. To work around this, Portuguese phonetic aliases `bote,bota,boto` were used as the default aliases. This is no longer the default, but remains available via env overrides for custom models or backward compat.
- `AudioService.__init__` parses both env vars and produces `voice_command_transcript_wake_words` (the union, deduplicated) for stripping wake words from Groq transcripts.
- `VOICE_COMMAND_WAKE_CONFIDENCE_THRESHOLD` (default `0.85`, range `0.0`-`1.0`) controls confidence filtering for voice-command detection. The higher default (versus prior `0.75`) is appropriate since `ventura` is directly in vocabulary. Normal keywords (slap, list) still use `0.95`.
- `refresh_keywords()` injects `voice_command_vosk_wake_words` when non-empty; falls back to `voice_command_wake_words` when aliases list is empty (backward compat).
- All injection happens in-memory only — no DB migration or `/keyword add` is required. DB keywords that collide with a reserved wake word/alias are overridden with a log warning.
 - When `action == "voice_command"` in `trigger_action`, `_handle_voice_command` is called:
   1. Applies a per-user rate limit (configurable via `VOICE_COMMAND_COOLDOWN_SECONDS`, default 5 s).
   2. **Plays a start prompt clip** by filename from `Sounds/` (no DB lookup) via `AudioService._play_voice_command_prompt(channel, start_sound, wait=True)`. The clip is decoded to 48 kHz stereo 16-bit PCM using pydub and cached by `(filepath, mtime)` in `_voice_command_prompt_pcm_cache`. Playback uses direct `discord.PCMAudio(io.BytesIO(pcm))` — no FFmpeg. Waits for completion before proceeding to recording. Silently skipped when prompts disabled, voice client busy/disconnected, or file missing.
   3. **Fresh post-prompt command recording** via `_record_voice_command_after_beep()`. A capture entry is registered in `_active_captures[user_id]`, and the next incoming per-user PCM chunks (from `write()`) are appended to it. The method polls until the user stops speaking (configurable silence timeout via `VOICE_COMMAND_SILENCE_SECONDS`, default 1.0 s) or reaches the max duration (`VOICE_COMMAND_CAPTURE_SECONDS`, default 6 s). Only the triggering user's audio is captured — other users' audio is ignored. Capture state is cleaned up in a ``finally`` block.
   4. Wraps PCM as WAV via `pcm_to_wav()` from `bot/services/voice_command.py`.
   5. Sends the WAV to `GroqWhisperService.transcribe()` which POSTs to `https://api.groq.com/openai/v1/audio/transcriptions` with model `whisper-large-v3` (accuracy-optimised; override with `GROQ_WHISPER_MODEL` for speed).
      - The done/acknowledgment prompt is **no longer played before transcription**. It is now played after parse, only when a play command is detected (see step 8).
      - An optional `prompt` field (`GROQ_WHISPER_PROMPT`) can guide transcription, but the default is empty because verbose prompts caused Groq Whisper to hallucinate prompt text or generic Portuguese filler on short/noisy captures.
      - A `temperature` field (`GROQ_WHISPER_TEMPERATURE`, default `0`) is sent for deterministic transcription.
      - A `language` field (`GROQ_WHISPER_LANGUAGE`) is sent; default `"pt"` so Whisper transcribes Portuguese rather than auto-detecting and potentially translating to English. Set env `GROQ_WHISPER_LANGUAGE=` (empty) to restore auto-detect for strongly mixed-language deployments.
   6. Parses the transcript via `parse_voice_command()` using the combined `voice_command_transcript_wake_words`. The parser:
      - Finds the **last** wake word in the transcript (not only at the start), so English preamble before "Ventura" is ignored.
      - Supports both English (`play`) and Portuguese (`toca`, `tocar`, `mete`, `meter`, `põe`, `poe`, `reproduz`, `reproduzir`) command verbs — all normalised to `"play"`.
      - Returns `("play", "<sound name>")` on match, or `None`.
   7. **If** the parser returns `("play", "<sound name>")`:
      - **Plays a done prompt clip** (same mechanism as start, with `wait=True`) as acknowledgment.
      - Delegates to `SoundService.play_request(sound_name, requester_name, guild=self.guild, request_note=f"play {sound_name}", allow_rejected_exact_fallback=True)` — the fuzzy-matching path used by `/toca`, augmented with:
        - ``request_note`` — appears as a compact "Heard: play <sound>" pill on the generated sound card image (and in the embed fallback).
        - ``allow_rejected_exact_fallback=True`` — when the exact name match is blacklisted (rejected), the service does NOT immediately reject; instead it falls through to fuzzy search to find a non-blacklisted close match. This is important because voice commands have no autocomplete, so saying "ventura play despacito" should play "despacito cars.mp3" if that is the closest non-rejected sound.
   8. **Else** (no recognised play command):
      - **No done prompt** is played.
      - The transcript is sent to `VenturaChatService.reply()` (OpenRouter Qwen Coder model) which returns short European Portuguese text with ElevenLabs square-bracket performance tags.
      - The reply is piped through `VoiceTransformationService.tts_EL(lang="pt")` for ElevenLabs Ventura TTS and played in the user's voice channel.
      - Requires `OPENROUTER_API_KEY` for the chat model and `EL_key`/`EL_voice_id_pt` for TTS playback. When the API key is missing or the reply is empty, the command is silently skipped.
 - The ``request_note`` and ``allow_rejected_exact_fallback`` parameters flow through: ``SoundService.play_request`` → ``AudioService.play_audio`` / fuzzy search fallback. For non-voice-command playbacks (default `/toca`) both parameters are omitted, so the original exact-match rejection behavior is preserved.
 - Prompt filenames are configurable via `VOICE_COMMAND_START_SOUND` (default comma-separated pool of 4 files for random selection) and `VOICE_COMMAND_DONE_SOUND` (same). A single filename continues to work for backward compatibility. Set `VOICE_COMMAND_BEEP_ENABLED=false` to disable prompts. The old sine-wave beep frequency/duration/volume env vars are no longer used.
 - Prompt PCM is decoded via pydub and cached in `AudioService._voice_command_prompt_pcm_cache` keyed by `(filepath, mtime)`.
 - Requires `GROQ_API_KEY` in the environment. Disabled when the key is absent or `VOICE_COMMAND_ENABLED=false`.
 - `KeywordDetectionSink.get_user_buffer_content()` returns per-user raw PCM (not mixed), capped at 30 s. This is distinct from the all-user mixed `get_buffer_content()` used for web/STS.
 - **Fresh post-prompt capture**: `KeywordDetectionSink._record_voice_command_after_beep()` sets up an active capture entry in `_active_captures[user_id]`. Incoming PCM chunks for that user (from ``write()``) are appended to the capture under ``self.buffer_lock``. A polling loop detects silence once at least one chunk has arrived. The capture dict stores ``chunks``, ``last_audio_time``, and ``total_bytes``. Cleanup happens in a ``finally`` block.
 - **Debug save**: `GroqWhisperService` saves a copy of every WAV sent to the API when `GROQ_WHISPER_DEBUG_SAVE_AUDIO=true` (default). Files go to `GROQ_WHISPER_DEBUG_AUDIO_DIR` (default `Debug/groq_whisper/` under the project root) as timestamped `groq-whisper-<ISO8601>.wav` plus an overwritten `latest.wav`. Retention (`GROQ_WHISPER_DEBUG_AUDIO_KEEP`, default 25) prunes only timestamped files; `latest.wav` is never pruned. Failures are logged as warnings and never block transcription. The save happens inside `GroqWhisperService.transcribe()`, after the API key check and before the HTTP POST.
 - With fresh post-prompt capture, the saved debug WAV contains only the command speech after the start prompt (e.g., "play despacito"), not several pre-wake seconds.

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

## ElevenLabs TTS Optimization

- `save_as_mp3_EL` in `bot/tts.py` uses the streaming endpoint (`/stream`) by default (`EL_TTS_STREAMING_ENABLED=true`) with latency optimisation level 3 (`EL_TTS_OPTIMIZE_STREAMING_LATENCY=3`).
- **Critical**: The `eleven_v3` model does **not** support the `optimize_streaming_latency` query parameter. Sending it returns a 400 `unsupported_model` error. The code automatically omits this parameter when `el_tts_model_id` is `eleven_v3` (case-insensitive) via `_effective_el_tts_streaming_latency()`. If you switch to a model that supports latency optimisation (e.g. `eleven_turbo_v2`), the parameter is included normally.
- When streaming: MP3 bytes are written chunk-by-chunk directly to the target file (no pydub decode/re-encode).
- When non-streaming: all bytes are read at once and written directly (no pydub round-trip).
- The pydub decode/re-encode path is only used when `boost_volume != 0` (not currently used by any `save_as_mp3_EL` caller; all `boost_volume` values in the method are `0`).
- DB insert happens after the file write succeeds, avoiding orphan rows on write failure.
- Performance metrics are logged at INFO level with the prefix `EL_TTS perf` showing model/format/latency/time-to-first-chunk/total/file-size.
- Sending `output_format` as a query parameter is required for the streaming endpoint; the URL builder (`_build_el_tts_url`) uses `urllib.parse.urlencode`.

### Live FIFO Streaming (EL_TTS_LIVE_PLAYBACK_ENABLED)

- When enabled (default `true`), `save_as_mp3_EL` creates a POSIX FIFO and starts `AudioService.play_tts_live_stream()` as a background task **before** writing MP3 chunks.
- The FIFO is opened with `O_RDWR` (non-blocking open under Linux). The pipe buffer is bumped to ~256 KB via `fcntl(fd, F_SETPIPE_SZ, 262144)`.
- Live playback eligibility requires ALL of: `el_tts_live_playback_enabled`, `el_tts_streaming_enabled`, `boost_volume == 0`, `loudnorm_mode == "off"`, and a voice channel available.
- `play_tts_live_stream()` on `AudioService` (lines ~1456+) uses `discord.FFmpegPCMAudio` directly with the FIFO path — `FFmpegOpusAudio.from_probe` cannot be used because the FIFO is not a seekable file.
- Sound card (TTS embed) is sent in a background task after playback starts, with no DB stats (no play count/duration) since the DB row is created later.
- If FIFO setup or live playback fails, the fallback saves the full MP3 to disk and calls the normal `play_audio()` path.
- `FFmpegPCMAudio` startup uses a basic volume-only filter (`volume=1.0,adelay=100:all=1`) for reliability; no ear protection filters are applied.
- The FIFO and its temp directory are cleaned up in the chunk-writing code path after the write completes; failures during cleanup are logged as debug warnings.
- `VoiceTransformationService.play_tts_live_stream()` is a pass-through wrapper to `AudioService.play_tts_live_stream()`, providing the same interface required by the legacy `TTS` class via `self.behavior`.

## AFK Channel Handling

- `AudioService.is_afk_channel(channel)` is the canonical check: compares `channel.guild.afk_channel.id` first, then falls back to `channel.name.lower().startswith('afk')`.
- `ensure_voice_connected` refuses AFK channels by returning `None` immediately with a log message. This is the last-resort defense.
- `get_largest_voice_channel` and `get_user_voice_channel` both skip AFK channels via `is_afk_channel`.
- In `PersonalGreeter.on_voice_state_update`, a user auto-moved to the guild AFK channel is treated as a **leave** event from their previous channel. The immediate auto-disconnect is skipped for AFK redirects so the leave sound can play in the now-empty previous channel.
- `play_audio_for_event` accepts `afk_redirect=False`. When `True`: (1) the `is_channel_empty` skip is bypassed, and (2) the bot disconnects after the event if it is alone in the previous channel.
- Leave events without a custom sound no longer connect to voice at all; they just log the analytics action.
