# Discord Brain Rot - Agent Guidelines

`AGENTS.md` is a symlink to this file. Keep this file short: it is loaded into agent context on every task. Put feature-specific or historical notes in `docs/agent-notes/` and link them from here.

## Read First

- Follow the repository architecture: commands/UI delegate to services, services contain business logic, repositories contain data access only, and models stay as simple domain entities.
- Use existing patterns before adding abstractions. Check the relevant command, service, repository, UI, and tests before changing behavior.
- Do not touch unrelated dirty worktree files. The repo may already contain user edits.
- Use the project logger from `bot/logger.py` for significant runtime operations.
- `requirements.txt` is UTF-16 LE with BOM. Preserve that encoding if editing dependencies.
- Treat reusable user corrections about agent workflow as repo knowledge: update the narrowest relevant `docs/agent-notes/` file, or this file if it must be always-loaded, before finalizing.

## Architecture

- `bot/commands/`: Discord slash commands and command wiring.
- `bot/ui/`: Discord views, buttons, modals, and other UI components.
- `bot/services/`: business logic and orchestration. Dependencies should be injected.
- `bot/repositories/`: database access only. Repositories extend `BaseRepository` and use `_execute`, `_execute_one`, and `_execute_write`.
- `bot/models/`: simple data classes/entities.
- `bot/downloaders/`: external content downloaders.

Keep SQL out of commands/UI/services unless an established repository boundary does not exist yet and you are explicitly creating it as part of the change.

## Coding Standards

- Add type hints for function parameters and return values.
- Public methods need docstrings. Use Args/Returns sections for complex methods.
- Use async/await for Discord and I/O-bound operations.
- Avoid god classes and unrelated refactors.
- Update `README.md` when user-facing behavior, setup, environment variables, web routes, commands, or operational workflows change. If no README update is needed, say why in the final response.

## Testing

- Tests use pytest and live under `tests/`.
- Preferred command: `./venv/bin/python -m pytest -q tests/`
- Repository tests should use in-memory SQLite fixtures from `tests/conftest.py`.
- Mock Discord dependencies in service tests.
- Add or update tests when behavior changes and it is feasible.

## Definition Of Done

Choose verification based on the task's blast radius. Agents should not blindly run the full test/deploy path for every edit.

Use the full verify/deploy path when touching bot runtime Python, repositories/services, database migrations, Docker/dependencies, audio/voice behavior, scheduled jobs, or anything likely to affect the running bot:

```bash
./scripts/verify_and_deploy.sh
```

For docs-only changes, comments, agent-note updates, or low-risk static web/template/CSS changes, use judgement: run targeted checks when useful, and skip Docker restart when the running containers do not need it. Most webpage asset/template-only changes do not require restarting the bot container.

If verification or deploy is skipped, say why in the final response. If a command fails, report the failing command and a concise error summary.

The script is intentionally concise on success. Do not paste full pytest output or long Docker logs into the final response; summarize the pass/fail result and only include detailed log excerpts when a failure occurs.

Before finalizing any implemented change, include:

- test result summary
- test-gap analysis covering regression risk, edge cases, service/repository/UI boundaries, and whether tests were added
- deploy/restart result summary
- post-restart bot log health summary
- whether `AGENTS.md` / `.gemini/GEMINI.md` or `docs/agent-notes/` knowledge was updated, and why

## Critical Gotchas

- `BotBehavior` services are private attributes such as `behavior._audio_service` and `behavior._sound_service`.
- Services expose repositories as attributes such as `sound_service.sound_repo`; verify actual repository method names before use.
- Upload flows that already hold `BotBehavior.upload_lock` / `SoundService.upload_lock` must call `save_uploaded_sound_secure(..., lock_already_held=True)` to avoid self-deadlock.
- Production `sounds` inserts use `timestamp`, not `date`. Keep `date` only as a compatibility fallback for legacy/test schemas.
- New uploads through `SoundRepository.insert_sound()` must invalidate `Database`'s in-memory sound similarity cache.
- `playback_queue` is an internal Flask-to-bot transport, not a user-facing queue.
- For sound play analytics, store the sound database `id` in `actions.target`; list playback should use action `play_from_list`.
- `DailyLogFileHandler` writes `Logs/YYYY-MM-DD.log` directly. Do not replace it with `TimedRotatingFileHandler` using a date-stamped base filename.

## Topic Notes

Read the focused notes only when your task touches that area:

- Web soundboard, OAuth, uploads, playback queue, web TTS, and Flask layering: `docs/agent-notes/web.md`
- Sound ingest, generated sound cards, Discord audio playback, DAVE, Vosk, STS, and voice gotchas: `docs/agent-notes/audio.md`
- Rocket League store command, cards, data source, and daily notification: `docs/agent-notes/rlstore.md`
- Analytics, voice activity, `/yearreview`, and `/weeklywrapped`: `docs/agent-notes/analytics.md`
- Deployment, Docker restart rules, logs, and verification workflow: `docs/agent-notes/operations.md`

When you discover a reusable pattern or pitfall, add it to the narrowest relevant note file instead of expanding this root file.
