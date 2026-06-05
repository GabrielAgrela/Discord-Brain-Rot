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
- TikTok/YouTube/Instagram downloads passing through `downloads/` are normalized in `SoundDownloader.move_sounds`; keep env knobs consistent with `SoundService`.
- TikTok collection favorite watchers use `FavoriteWatcherService` and `SoundService.import_sound_from_video()` to import directly into the guild-scoped sound library. Adding a watcher seeds current collection videos as already seen so only future additions import, then each successful future import posts a `DownloadedSoundView` image-card notification.
- **Favorite watcher re-download spam gotcha**: The watcher must claim/record a video in the database **before** downloading it. `FavoriteWatcherRepository.claim_video_seen()` does an `INSERT OR IGNORE` and returns `True` only for a new row. The service calls this before `import_sound_from_video()`, so even if subsequent metadata writes (`record_video_seen`, `action_repo.insert`) fail with `database is locked`, the claim row already exists and the video will never be re-downloaded. Videos within a single scan are also deduplicated by `video_id` to avoid double-importing duplicate entries from yt-dlp.
- All sound import notifications (scraper `move_sounds`, favorite watcher, web upload, manual Discord upload) share the same `SoundImportNotificationService.send_notification()` method. Each source has a default title template, requester label, and accent colour. Web uploads and favorite watchers use blue (`#5865F2`); scraper/manual use red (`#ED4245`). Cross-process web upload notifications are queued in `sound_import_notifications` and drained by `BackgroundService.sound_import_notification_drain_loop`.
- When Honker is available, `SoundImportNotificationRepository.enqueue()` publishes a NOTIFY so the drain loop wakes immediately instead of waiting for the 3-second poll. `BackgroundService._start_honker_sound_import_listener()` is an async listener task that calls `drain_sound_import_notifications_once()` on each notification. Polling remains as fallback.

## Generated Sound Cards

- The sound card UI lives in `templates/sound_card.html`, which is tracked in git.
- Image output size is also controlled in `bot/services/image_generator.py` via `_scale_png_bytes` and `ImageGeneratorService._card_image_scale`.
- When changing card layout/styling, verify behavior by running the bot and checking generated cards after deploy.
- Emoji rendering depends on container fonts and CSS fallback. Keep `fonts-noto-color-emoji` installed in Docker and include emoji-capable families in the template `font-family` stack.
- Keep a normal text font first, such as `DejaVu Sans`, and place emoji fonts later. `Noto Color Emoji` first can make normal text spacing look odd.

## Cross-Process Playback Event Publishing

- `AudioService._publish_playback_event()` is the central, safe helper that publishes a Honker `control_room_changed` SSE event on every actual playback start and finish.
- It is called from `_mark_playback_started()` (covers `play_audio`, `play_slap`, and `play_tts_live_stream`) and `_mark_playback_finished()` (covers all `after_playing` callbacks).
- This ensures the web control room (`refreshControlRoomStatus` / `refreshWebControlState`) updates consistently across all playback code paths — normal play, slap, live TTS, Discord random button, web play button, and scheduled/periodic sounds.
- The method never blocks or fails playback: all exceptions (missing Honker, unavailable db_path, Honker publish failures) are caught and logged at `DEBUG` level.
- `db_path` is obtained from `self.sound_repo.db_path` (inherited from `BaseRepository`).
- Event payload includes `guild_id`, `audio_file`, `user`, `play_id`, `duration_seconds`, and a `reason` flag (`playback_started` / `playback_finished`).
- Only `control_room_changed` is published — action tables are not refreshed on playback events. Action-driven table updates continue to come from `actions_changed` events in `ActionRepository.insert()` / `Database.insert_action()`.

## Playback And FFmpeg

- `discord.FFmpegOpusAudio` can silently treat immediate ffmpeg crashes as normal EOF. The bot UI may run progress for the full duration while no audio is emitted.
- Avoid stringent probe flags such as `-analyzeduration 0 -probesize 32` for MP3s with large ID3 headers unless required.
- After `voice_client.stop()`, wait for the old audio player thread to finish before calling `play()`. `is_playing()` can become false before the thread exits.
- Capture `voice_client._player` before stop and poll `player.is_alive()` with a timeout. This is encapsulated in `AudioService._stop_voice_client_and_wait()`.
- Also guard the non-interrupt path before starting the next sound after natural completion; a lingering `_player` can drop the new sound.
- Join/entrance sounds use a warmup delay before playback because the listener may not be ready immediately after `on_voice_state_update`; default `ENTRANCE_PLAYBACK_START_DELAY_SECONDS=1.0`.
- `personal_greeter.play_audio_for_event()` must pass `is_entrance=True` for join sounds. Without that flag, `AudioService._maybe_apply_entrance_playback_warmup()` is bypassed even though the join path appears to use the normal playback service.
- Entrance sounds should still run `AudioService.handle_ui()` and send the bot-channel sound card. Suppress similar-sound suggestions for `is_entrance=True`, but do not return before card/progress UI is created.
- `AudioService.play_slap()` must guard both interrupted and not-currently-playing paths for lingering player threads.
- Slap playback benefits from short ffmpeg pre-roll silence (`adelay=120:all=1`).
- Short MP3 slap clips can decode as empty output with low-latency ffmpeg startup flags. Use conservative slap `before_options` (`-nostdin`) even when global latency mode is low.
- Short non-slap MP3s also use low-latency safety: conservative `before_options` plus small pre-roll.
- Normal MP3 playback in low-latency mode uses a configurable pre-roll floor, `LOW_LATENCY_MP3_START_PREROLL_MS` default `650`.
- `play_after` debug lines include expected decoded duration, player frame count, frame-derived duration, and `duration_mismatch=True` when callback elapsed time is much larger. If frame duration is normal but elapsed is high, inspect voice connectivity, ffmpeg cleanup, or host stalls instead of assuming the MP3 contains silence.
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

## Speech Training Dataset Capture & Labeling

- **Labels vs detection metadata**: `label` is always human ground truth (`ventura`, `chapada`, `none`, `potential`). `transcript` is the human transcript. Vosk scan results are stored separately in `detected_*`/`detection_*` columns and never overwrite human fields. When keyword scan labels matches as ``potential``, they are moved from unlabeled to the ``potential`` label for human review, not stored as detection metadata.
- **False positives** are derivable as `label='none' AND detected_keyword IS NOT NULL`. **False negatives** as `label='<keyword>' AND (detected_keyword IS NULL OR detected_keyword != label)`. The `detection_keywords_json` column preserves which keywords were targeted in the scan so past scans remain interpretable.
- Schema migration (adding `detected_*` columns) is idempotent in `SpeechTrainingRepository.ensure_schema()` via `PRAGMA table_info`.
- `update_detection_metadata()` in the repository sets `detection_scanned_at = CURRENT_TIMESTAMP` and is safe to call on labeled or unlabeled clips — it never touches `label`, `transcript`, or `notes`.

## Speech Training Dataset Capture

- The opt-in speech training recorder (`SPEECH_TRAINING_RECORDING_ENABLED=true`) uses the same `KeywordDetectionSink` receive audio that Vosk uses. This avoids adding a separate Discord recording sink.
- The recorder can start the sink when collection is enabled even if guild STT is disabled, but Vosk keyword processing must remain gated by guild STT (`sink.stt_enabled`).
- PCM-to-MP3 export uses pydub in a background daemon writer thread (`SpeechTrainingRecorderService._writer_loop`) and must **not** block the `write()` receive thread.
- Segment boundary detection runs in the receive thread (`_feed_speech_segmenter`). It now uses **energy-gated detection**:
  - Each incoming PCM chunk is evaluated for RMS amplitude vs `SPEECH_TRAINING_SPEECH_RMS_THRESHOLD` (default 250).
  - Segments **only start on voiced chunks** (RMS >= threshold). Low-energy chunks before the first voiced frame are buffered in a preroll buffer (`SPEECH_TRAINING_PREROLL_SECONDS`, default 0.08 s) and prepended so word onsets are not clipped.
  - Silence duration is measured from the **last voiced chunk** (not the last packet), so continuous room noise does not prevent finalization.
  - Trailing low-energy frames are trimmed before enqueuing when `SPEECH_TRAINING_TRIM_SILENCE=true` (default).
  - Max-duration forced splits (`SPEECH_TRAINING_MAX_DURATION_SECONDS`) still apply regardless of voicing.
- Minimum duration and RMS thresholds prevent saving near-silent artifacts.
- `_flush_silence()` in the Vosk worker loop also flushes pending speech segments via `_flush_speech_segments()` (using last-voiced time). `stop()` calls `_force_finalize_all_speech_segments()`.
- Directory layout: `<data_dir>/<guild_id>/<sanitised_username>_<user_id>/<timestamp>_<dur-ms>ms.mp3`.
- Raw captured PCM is preserved as-is; no loudness normalization for training data.
- **Web auto-transcript throttling**: The web auto-transcript job (`transcribe_empty_clips()`) sends Groq Whisper requests sequentially with a configurable delay (`WEB_TRANSCRIPT_REQUEST_DELAY_SECONDS`, default 1.0 s). On HTTP 429, it retries up to `WEB_TRANSCRIPT_429_MAX_RETRIES` times (default 3) with exponential backoff, respecting the `Retry-After` header. Persistent 429 stops the job early with an error in the UI. These env vars are in `web_speech_training.py` as module-level constants parsed from environment.
- The automatic bot-side speech training keyword scan defaults to `SPEECH_TRAINING_KEYWORD_SCAN_WORKERS=4` and is bounded to 1–8 workers. The scan service parallelizes per-clip decode/Vosk work while repository writes remain in the collecting thread. Manual web keyword scans still use `WebSpeechTrainingService.KEYWORD_SCAN_WORKERS` unless changed separately.

## Vosk Keyword Detection

- Vosk keyword detection remains supported for configured trigger words. Do not remove `data/models/vosk-model-small-pt-0.3`, `KeywordCog`, `KeywordRepository`, the `AudioService` recording sink, or DAVE inbound decrypt unless explicitly asked.
- The removed feature is only ambient Ventura LLM/commentary: no LLM provider/profile stack, no `_ai_commentary_service`, and no `/ventura` admin toggle. Manual Ventura `/tts` and `/sts` remains.
- `AudioService.start_keyword_detection` must enforce guild-level `stt_enabled` from `GuildSettingsService`.
- `ensure_voice_connected` can be invoked multiple times during join/event playback; guard against starting keyword detection when STT is disabled.
- If Vosk starts and stops within seconds, verify `guild_settings.stt_enabled` first.
- `KeywordDetectionSink` runs in a background thread. Guard `asyncio.run_coroutine_threadsafe()` with `if not loop.is_closed():`.
- Startup auto-join is owned by `BackgroundService._auto_join_channels()`. Do not add a second `on_ready` auto-join in `personal_greeter.py`.
- Final keyword latency is driven by `KeywordDetectionSink.silence_flush_seconds` / `KEYWORD_SILENCE_FLUSH_SECONDS` plus worker queue timeout. Partials are faster but less stable.
- After voice moves/reconnects (e.g. `move_to` in `ensure_voice_connected` or AutoFollow), keyword detection start failures schedule a short retry loop via `AudioService.schedule_keyword_detection_restart()` instead of waiting for the 30-second health check in `BackgroundService.keyword_detection_health_check`. The retry loop uses exponential backoff (2 s, 4 s, 8 s cap) for up to 5 attempts. Use `reason="auto_follow_move"` or similar labels to distinguish log origins. Pass `schedule_retry=False` to `start_keyword_detection` to suppress retry nesting (done automatically by the restart loop).
- py-cord already runs an internal reconnect loop after abnormal voice websocket closes such as code `1006`. `bot/voice_compat.py` stamps `_voicecompat_last_ws_close_at` on the `VoiceClient`; Vosk/background health checks must respect `AudioService.is_voice_library_reconnect_pending()` before forcing their own reconnect, otherwise one Discord voice socket drop can become duplicate visible leave/rejoin cycles.

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
   2. **Plays a start prompt clip** by filename from `sounds/` (no DB lookup) via `AudioService._play_voice_command_prompt(channel, start_sound, wait=True)`. The clip is decoded to 48 kHz stereo 16-bit PCM using pydub and cached by `(filepath, mtime)` in `_voice_command_prompt_pcm_cache`. Playback uses direct `discord.PCMAudio(io.BytesIO(pcm))` — no FFmpeg. Waits for completion before proceeding to recording. Silently skipped when prompts disabled, voice client busy/disconnected, or file missing.
    3. **Fresh post-prompt command recording** via `_record_voice_command_after_beep()`. A capture entry is registered in `_active_captures[user_id]`, and the next incoming per-user PCM chunks (from `write()`) are appended to it. The method polls until the user stops speaking (configurable silence timeout via `VOICE_COMMAND_SILENCE_SECONDS`, default 1.0 s) or reaches the max duration (`VOICE_COMMAND_CAPTURE_SECONDS`, default 6 s). Only the triggering user's audio is captured — other users' audio is ignored. Capture state is cleaned up in a ``finally`` block.
   4. Wraps PCM as WAV via `pcm_to_wav()` from `bot/services/voice_command.py`.
   5. Sends the WAV to `GroqWhisperService.transcribe()` which POSTs to `https://api.groq.com/openai/v1/audio/transcriptions` with model `whisper-large-v3` (accuracy-optimised; override with `GROQ_WHISPER_MODEL` for speed).
      - The done/acknowledgment prompt is **no longer played before transcription**. It is now played after parse, only when a play command is detected (see step 8).
      - An optional `prompt` field (`GROQ_WHISPER_PROMPT`) can guide transcription, but the default is empty because verbose prompts caused Groq Whisper to hallucinate prompt text or generic Portuguese filler on short/noisy captures.
      - A `temperature` field (`GROQ_WHISPER_TEMPERATURE`, default `0`) is sent for deterministic transcription.
      - A `language` field (`GROQ_WHISPER_LANGUAGE`) is sent; default `"pt"` so Whisper transcribes Portuguese rather than auto-detecting and potentially translating to English. Set env `GROQ_WHISPER_LANGUAGE=` (empty) to restore auto-detect for strongly mixed-language deployments.
     6. Parses the transcript via `parse_voice_command()` using the combined `voice_command_transcript_wake_words`. The parser:

        - Portuguese command verbs only (English `play` is **not** recognised): `toca`, `tocar`, `toque`, `mete`, `meter`, `põe`, `poe`, `reproduz`, `reproduzir` — all normalised to `"play"`. Whisper occasionally transcribes the spoken imperative `toca` as the formal/conjunctive `toque`, so `toque` is included as a recognised alias. Also supports `"mute"` and the following mute aliases — all returning `("mute", "")` (no trailing argument required):

          ``mute``, ``cala-te``, ``cala te``, ``calate``,
          ``silêncio``, ``silencio``,
          ``shut up``, ``shutup``, ``quiet``

        - Returns `("play", "<sound name>")`, `("mute", "")`, or `None`.
    7. **If** the parser returns `("play", "<sound name>")`:
       - **Plays a done prompt clip** (same mechanism as start, with `wait=True`) as acknowledgment.
       - **List routing**: Before falling back to `play_request`, the handler checks whether the sound name matches an existing list in the guild (via `sound_service.list_repo.get_by_name()`). If found, it calls `SoundService.play_random_sound_from_list(list_name, requester_name, guild=self.guild, request_note=f"toca {argument}")` instead. Explicit marker prefixes (`lista `, `a lista `, `da lista `) force list lookup even if the name could be a sound.
       - **List name matching is case-insensitive**: Both `get_by_name()` and `get_random_sound_from_list()` in `ListRepository` use `COLLATE NOCASE` on the `list_name` column, so Whisper transcripts with arbitrary capitalisation (e.g. `GAY`, `Gay`, `gay`) all match the stored list. The voice command handler in `_handle_voice_command()` also uses the **canonical stored list name** (`existing_list[1]`) when calling `play_random_sound_from_list`, so the downstream call uses the original DB casing regardless of what Whisper returned.
       - If no list matches, delegates to `SoundService.play_request(sound_name, requester_name, guild=self.guild, request_note=f"toca {sound_name}", allow_rejected_exact_fallback=True)` — the fuzzy-matching path used by `/toca`, augmented with:
         - ``request_note`` — appears as a compact "Heard: toca <sound>" pill on the generated sound card image (and in the embed fallback). For list playback it shows the full transcript (e.g. "toca memes" or "toca lista memes").
         - ``allow_rejected_exact_fallback=True`` — when the exact name match is blacklisted (rejected), the service does NOT immediately reject; instead it falls through to fuzzy search to find a non-blacklisted close match. This is important because voice commands have no autocomplete, so saying "ventura toca despacito" should play "despacito cars.mp3" if that is the closest non-rejected sound.
    8. **If** the parser returns `("mute", "")`:
       - **No done prompt** is played.
       - The bot attempts a best-effort random slap playback (via `AudioService.play_slap`), then calls `MuteService.activate(duration_seconds=1800)` to mute the bot for 30 minutes.
       - An action `"mute_30_minutes"` is logged via `ActionRepository.insert(requester_name, "mute_30_minutes", "", guild_id=...)`.
       - This mirrors the behavior of the mute button and web mute control.
     9. **Else** (no recognised play/mute command):
       - **No done prompt** is played.
       - A `request_note` is computed from the transcript via `build_voice_request_note()` (strips the last wake word and trailing punctuation) so the generated TTS sound card shows the user's heard command as a ``TTS:`` footer pill — the same footer style used for play commands.
        - The transcript is sent to `VenturaChatService.reply()` (OpenRouter DeepSeek model) which returns short European Portuguese text with ElevenLabs square-bracket performance tags.
        - The reply is piped through `VoiceTransformationService.tts_EL(lang="pt", request_note=request_note)` for ElevenLabs Ventura TTS and played in the user's voice channel.
        - Requires `OPENROUTER_API_KEY` for the chat model and `EL_key`/`EL_voice_id_pt` for TTS playback. When the API key is missing or the reply is empty, the command is silently skipped.
        - `request_note` threads through `VoiceTransformationService.tts_EL` → `TTS.save_as_mp3_EL` → both live `play_tts_live_stream` and fallback `play_audio`, and ultimately to `generate_sound_card(request_note=...)`. The TTS card's title/quote remains Ventura's reply; only the footer pill shows the user's command.
        - `VenturaChatService` keeps an in-memory rolling history (up to 3 last user/assistant exchanges from the last `VENTURA_CHAT_HISTORY_RETENTION_SECONDS`, default 300 s / 5 min) per conversation key. The key format is `f"guild:{guild.id}:user:{user_id}"` (set in `KeywordDetectionSink._handle_voice_command`). Including history in OpenRouter payload allows follow-up queries to retain context. Each entry stores a `time.monotonic()` timestamp; expired entries are pruned before building the request payload and before appending new exchanges. If retention is `0`, history is effectively disabled. By default, it includes up to the last 3 unexpired prior exchanges. History is only appended on successful non-empty replies; API errors/timeouts/empty responses do not pollute history. The transcript sent to OpenRouter is prefixed with the requester's name as a speaker label (e.g. `Sopustos: <transcript>`) when available so the chat model knows who is speaking. This formatted form is also stored in the history.
          - Before each POST, `VenturaChatService.reply()` logs the request summary at INFO level with the `[VenturaChat] Request payload` pretty JSON (or `[VenturaChat] Request summary` prefix if `VENTURA_CHAT_LOG_PAYLOAD=false`). No secrets (API keys, auth headers) are included in the log. Timing metrics (total duration, status code, model) are logged under `[VenturaChat] OpenRouter completed in ...` to measure OpenRouter model latency.
 - The ``request_note`` and ``allow_rejected_exact_fallback`` parameters flow through: ``SoundService.play_request`` → ``AudioService.play_audio`` / fuzzy search fallback. ``SoundService.play_random_sound_from_list`` also accepts ``request_note`` and forwards it to ``play_audio``; analytics action remains ``play_from_list`` regardless. For non-voice-command playbacks (default `/toca`) both parameters are omitted, so the original exact-match rejection behavior is preserved.
 - Prompt filenames are configurable via `VOICE_COMMAND_START_SOUND` (default comma-separated pool of 4 files for random selection) and `VOICE_COMMAND_DONE_SOUND` (same). A single filename continues to work for backward compatibility. Set `VOICE_COMMAND_BEEP_ENABLED=false` to disable prompts. The old sine-wave beep frequency/duration/volume env vars are no longer used.
 - Prompt PCM is decoded via pydub and cached in `AudioService._voice_command_prompt_pcm_cache` keyed by `(filepath, mtime)`.
 - Requires `GROQ_API_KEY` in the environment. Disabled when the key is absent or `VOICE_COMMAND_ENABLED=false`.
 - `KeywordDetectionSink.get_user_buffer_content()` returns per-user raw PCM (not mixed), capped at 30 s. This is distinct from the all-user mixed `get_buffer_content()` used for web/STS.
  - **Keyword suppression while listening**: When ``_handle_voice_command()`` is triggered, ``_begin_voice_command_listening(user_id)`` sets a state flag that suppresses all other Vosk keyword actions (slap, list, second wake word) until the start prompt + fresh post-prompt capture finishes. ``_end_voice_command_listening(user_id)`` is called in the ``finally`` block immediately after ``_record_voice_command_after_beep()`` returns, so keyword detection resumes during Groq/Ventura/TTS processing. The suppression works at three levels:
    1. **``write()``** – skips queuing audio to the Vosk worker entirely while the flag is active (but still feeds ``_active_captures`` for the triggering user).
    2. **``detect_keyword()``** – returns early without any Vosk processing.
    3. **``trigger_action()``** – silently discards non-``voice_command`` actions that arrive from already-queued items.
    - The helpers (``_is_voice_command_listening``, ``_begin_voice_command_listening``, ``_end_voice_command_listening``) use ``getattr`` fallbacks so they work on instances created with ``__new__()`` during tests.
  - **Fresh post-prompt capture**: `KeywordDetectionSink._record_voice_command_after_beep()` sets up an active capture entry in `_active_captures[user_id]`. Incoming PCM chunks for that user (from ``write()``) are appended to the capture under ``self.buffer_lock``. A polling loop detects silence once at least one chunk has arrived. The capture dict stores ``chunks``, ``last_audio_time``, and ``total_bytes``. Cleanup happens in a ``finally`` block.
   - **Debug save**: `GroqWhisperService` can persist a copy of every WAV sent to the API when `GROQ_WHISPER_DEBUG_SAVE_AUDIO=true` (disabled by default). Files go to `GROQ_WHISPER_DEBUG_AUDIO_DIR` (default `debug/groq_whisper/` under the project root) as timestamped `groq-whisper-<ISO8601>.wav` plus an overwritten `latest.wav`. Retention (`GROQ_WHISPER_DEBUG_AUDIO_KEEP`, default 25) prunes only timestamped files; `latest.wav` is never pruned. Failures are logged as warnings and never block transcription. The save happens inside `GroqWhisperService.transcribe()`, after the API key check and before the HTTP POST.
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

- When enabled (default `true`), `save_as_mp3_EL` creates a POSIX FIFO and starts `AudioService.play_tts_live_stream()` as a background task **after receiving a successful HTTP 200 response** from ElevenLabs. This prevents ghost sound cards / empty voice playback when the API returns a quota error or any non-200 response.
- To ensure the live task starts setting up immediately after the 200 response, `save_as_mp3_EL` yields to the event loop via `await asyncio.sleep(0)` right after creating the task.
- The FIFO is opened with `O_RDWR` (non-blocking open under Linux). The pipe buffer is bumped to ~256 KB via `fcntl(fd, F_SETPIPE_SZ, 262144)`.
- Live playback eligibility requires ALL of: `el_tts_live_playback_enabled`, `el_tts_streaming_enabled`, `boost_volume == 0`, `loudnorm_mode == "off"`, and a voice channel available.
- `play_tts_live_stream()` on `AudioService` (lines ~1456+) uses `discord.FFmpegPCMAudio` directly with the FIFO path — `FFmpegOpusAudio.from_probe` cannot be used because the FIFO is not a seekable file.
- Sound card (TTS embed) is sent in a background task after playback starts, with no DB stats (no play count/duration) since the DB row is created later.
- If FIFO setup or live playback fails, the fallback saves the full MP3 to disk and calls the normal `play_audio()` path.
- `FFmpegPCMAudio` startup uses a basic volume-only filter (`volume=1.0`) and conditionally appends `adelay={EL_TTS_LIVE_PREROLL_MS}:all=1` only if `EL_TTS_LIVE_PREROLL_MS` > 0 (defaults to `120` ms to add a small startup buffer that protects the first decoded packets from clipping); no ear protection filters are applied.
- High-resolution timing metrics are captured across key milestones (`live_ready_time`, `fifo_open_time`, `first_chunk_time`, `first_fifo_write_start`, `first_fifo_write_end`, and `total`) and logged as `EL_TTS live timing | ...` to accurately diagnose where latency originates (ElevenLabs TTFB vs. FIFO open vs. FFmpeg start).
- FFmpeg live TTS playback options are optimized by skip-probing: when `EL_TTS_LIVE_ASSUME_MP3_FORMAT` is true (default) and input format is detected as `mp3`, FFmpeg is instructed with `-f mp3` to bypass file-format probing. Low latency flags `-fflags nobuffer -flags low_delay` are appended only when `EL_TTS_LIVE_LOW_LATENCY_FFMPEG=true` (default false); enabling them can reduce startup latency but may clip first words.
- The FIFO and its temp directory are cleaned up in the chunk-writing code path after the write completes; failures during cleanup are logged as debug warnings.
- `VoiceTransformationService.play_tts_live_stream()` is a pass-through wrapper to `AudioService.play_tts_live_stream()`, providing the same interface required by the legacy `TTS` class via `self.behavior`.
- **CRITICAL — never write to the FIFO directly in the async event loop.** The original implementation called `os.write(live_fifo_fd, chunk)` directly in the async chunk loop. When FFmpeg consumed slower than ElevenLabs produced, the pipe buffer filled up and `os.write` blocked the entire event-loop thread, preventing Discord heartbeat/button-defer/keyword-action dispatch for seconds.
- The fix: run FIFO writes through `asyncio.to_thread(_write_all_to_fd, live_fifo_fd, chunk)` where `_write_all_to_fd` is a module-level helper in `bot/tts.py` that handles partial writes in a loop. This keeps the event loop free while the thread handles FIFO backpressure.
- Same principle applies to any future synchronous I/O in an async hot path that can block.

### ElevenLabs Quota Circuit Breaker

- `TTS` in `bot/tts.py` now has an in-memory + database-backed quota circuit breaker to prevent repeated looping when ElevenLabs returns `quota_exceeded` (usually a 401/402/429 with `detail.code` or `detail.status` set to `"quota_exceeded"`).
- **Persistence**: The quota block expiry is persisted to the `app_settings` SQLite table via `_set_elevenlabs_quota_blocked()` / `_persist_quota_block()`. On bot startup, `_load_elevenlabs_quota_block()` restores the block so the bot does not waste tokens rediscovering quota after restart.
- **Error detection**: A helper `_check_el_quota_exceeded(status, body)` checks HTTP status 401/402/429 and parses the JSON body for `detail.code == "quota_exceeded"` / `detail.status == "quota_exceeded"`, with a plain-text fallback for `"quota_exceeded"` in the body. Non-quota errors raise `ElevenLabsAPIError`; quota errors raise `ElevenLabsQuotaExceededError`.
- **Circuit breaker**: When a quota error is detected, `TTS._set_elevenlabs_quota_blocked()` stores a global block expiry (`_el_tts_quota_block_until`). All subsequent `save_as_mp3_EL` calls check `is_elevenlabs_quota_blocked()` before making any HTTP request or FIFO setup, raising `ElevenLabsQuotaExceededError` immediately. The block duration is configurable via `EL_TTS_QUOTA_COOLDOWN_SECONDS` (default `3600` seconds / 1 hour).
- **Live FIFO gated behind 200**: FIFO creation and `play_tts_live_stream()` task start have been moved to inside the `response.status == 200` block. This means on quota errors the sound card / voice playback is never initiated — no ghost UI, no empty voice playback.
- **Non-play Ventura chat branch skips quota**: Quota checks are no longer at the keyword-action stage in `trigger_action()`. Instead, they apply only in the non-play Ventura chat + ElevenLabs TTS branch inside `_handle_voice_command()`. After Groq Whisper transcription and command parsing, if the transcript does **not** contain a recognised `play` or `mute` command, the handler checks the global TTS circuit breaker (`vt_service.is_elevenlabs_quota_blocked()`) and any per-user quota cooldown (`_voice_command_quota_cooldowns`). When blocked or cooled down, it skips OpenRouter and returns early (optionally setting a new per-user cooldown + sending an image-type error card, rate-limited to once per 60 s per guild). This means `toca`, `mute`, and list playback voice commands continue to work even when ElevenLabs quota is exhausted — only the Ventura chat + TTS reply branch is suppressed.
- **Per-user quota cooldown**: The per-user cooldown is set whenever the handler encounters a quota-blocked state (either from the global circuit breaker check or from an `ElevenLabsQuotaExceededError` raised during `tts_EL()`). The cooldown key format is `"{guild_id}:{user_id}"` with configurable `VOICE_COMMAND_QUOTA_COOLDOWN_SECONDS` (default 3600). Only the non-play Ventura branch checks this cooldown; play/mute paths ignore it.
- **Test coverage**: `tests/services/test_tts.py` covers quota detection (401/429 JSON, plain-text), circuit breaker (subsequent calls skip HTTP), helper parsing, and a dedicated test verifying no FIFO/live setup on 401 quota. `tests/services/test_audio_service.py` covers: trigger_action delegating to handler regardless of quota state; play/toca path working when quota blocked; play/toca path working when per-user cooldown active; non-play path skipping Ventura chat when per-user cooldown active; non-play path setting cooldown + sending notification when quota blocked; and catching `ElevenLabsQuotaExceededError` during TTS with cooldown+notification.

### Live FIFO Interruption (play_slap / play_audio skip)

- When `play_slap()` or `play_audio()` interrupt an active live TTS stream, the FIFO writer in `save_as_mp3_EL` must stop quickly so the per-guild TTS lock is released for subsequent replies.
- Without a mechanism, the writer can block forever on a full FIFO buffer because `os.O_RDWR` keeps a read end open (so no `SIGPIPE`/`BrokenPipeError`).
- The fix uses a per-guild `threading.Event` stored in `AudioService._guild_live_tts_interrupt_events`:
  1. `save_as_mp3_EL` creates a `threading.Event` and passes it to `play_tts_live_stream(interrupt_event=...)`.
  2. The FIFO is opened with `os.O_RDWR | os.O_NONBLOCK` so `os.write` raises `BlockingIOError` (not hang) when the pipe buffer is full.
  3. `_write_all_to_fd` accepts the event parameter: on `BlockingIOError` it sleeps 10ms and retries while the event is not set; raises `BrokenPipeError` immediately if the event is set.
  4. The chunk loop in `save_as_mp3_EL` also checks `interrupt_event.is_set()` before each chunk and breaks early if set.
  5. `play_slap` / `play_audio` call `AudioService._interrupt_live_tts_stream(guild_id, reason="...")` **before** `_stop_voice_client_and_wait`, which sets the event.
  6. `play_tts_live_stream`'s `after_playing` callback also sets the event (catching natural FFmpeg exit).
  7. When interrupted, `save_as_mp3_EL` cleans up: closes the FIFO fd, unlinks the FIFO, removes the partial output file, logs, and returns immediately **without** DB insert or `play_audio` fallback.
- `VoiceTransformationService.play_tts_live_stream()` passes through `**kwargs` so the new `interrupt_event` parameter flows automatically.

## AFK Channel Handling

- `AudioService.is_afk_channel(channel)` is the canonical check: compares `channel.guild.afk_channel.id` first, then falls back to `channel.name.lower().startswith('afk')`.
- `ensure_voice_connected` refuses AFK channels by returning `None` immediately with a log message. This is the last-resort defense.
- `get_largest_voice_channel` and `get_user_voice_channel` both skip AFK channels via `is_afk_channel`.
- In `personal_greeter.on_voice_state_update`, a user auto-moved to the guild AFK channel is treated as a **leave** event from their previous channel. The immediate auto-disconnect is skipped for AFK redirects so the leave sound can play in the now-empty previous channel.
- `play_audio_for_event` accepts `afk_redirect=False`. When `True`: (1) the `is_channel_empty` skip is bypassed, and (2) the bot disconnects after the event if it is alone in the previous channel.
- Leave events without a custom sound no longer connect to voice at all; they just log the analytics action.
