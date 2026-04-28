# Operations Agent Notes

Read this when changing deployment, Docker, dependencies, logging, verification scripts, or runtime operations.

## Verification

- Choose verification based on the task's blast radius. Do not run full tests/deploy reflexively for every edit.
- Run `./scripts/verify_and_deploy.sh` for bot runtime Python, repositories/services, database migrations, Docker/dependency changes, audio/voice behavior, scheduled jobs, or other changes that must be active in the running bot immediately.
- For docs-only changes, comment-only changes, agent-note edits, and other non-runtime updates, skip tests/deploy and state why.
- For narrow Python changes, targeted tests may be enough during iteration; run the full script before finishing when the change affects production bot behavior.
- For static web/template/CSS-only changes, do not restart the bot container. Run targeted web tests or inspect the page when useful. Restart `web` only if the container needs to reload Python code, templates are cached, or a dependency/config/runtime boundary changed.
- If the script fails, report the exact failing command and concise error summary. Do not claim completion.
- The verification script captures successful pytest and bot log output, then prints summaries. Keep it quiet on success and verbose only on failure.
- The preferred standalone test command is `./venv/bin/python -m pytest -q tests/`.
- Testing artifacts such as `.pytest_cache/`, `.coverage`, and `htmlcov/` are ignored.

## Docker Restart Rules

- The bot runs in Docker, so Python changes do not take effect until the container restarts.
- Normal production flow restarts the bot service:

```bash
docker-compose restart bot
```

- `./scripts/verify_and_deploy.sh` uses `docker-compose restart`, which may only restart default-profile services.
- The `web` service is profile-gated (`profiles: ["web"]`). Restart `web` when changing Flask Python code, web runtime configuration, dependencies, or when manual inspection shows templates/assets are not being picked up:

```bash
docker-compose restart web
```

- Compose profiles do not auto-stop already running containers. If `web` was previously started, explicitly stop it when launching bot-only mode:

```bash
docker-compose stop web
```

- If system dependencies or fonts change in `Dockerfile`, restart is not enough; rebuild and recreate containers:

```bash
docker-compose build
docker-compose up -d --force-recreate
```

## Logs

- Use the project logger from `bot/logger.py`.
- Logs go to daily files in `Logs/` named `YYYY-MM-DD.log`.
- `DailyLogFileHandler` writes daily log files directly. Do not replace it with `TimedRotatingFileHandler` using a date-stamped base filename, which can create doubled names like `2026-04-27.log.2026-04-27`.
- To monitor after restart:

```bash
docker-compose logs -f bot
```

- For a quick health check:

```bash
docker-compose logs --tail=120 bot
```

- Logs immediately after restart may include shutdown-time stack traces from the old container, such as `RuntimeError: Event loop is closed` from voice threads. Treat them as restart noise unless they repeat after fresh startup heartbeat/activity lines.
- For automated health checks, prefer logs since the new bot container `StartedAt` timestamp so shutdown noise from the old process does not contaminate the result.

## Agent Note Hygiene

- Keep `.gemini/GEMINI.md` short because `AGENTS.md` points to it and agents load it into context.
- Add feature-specific guidance to the narrowest file in `docs/agent-notes/`.
- Periodically remove duplicate, obsolete, or one-off historical notes. Keep symptoms and invariants that still prevent real regressions.
