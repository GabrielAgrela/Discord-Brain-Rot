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

### Testing Limitations
- Repository unit tests don't catch integration errors with Discord or BotBehavior
- Attribute name mismatches and service access patterns are only caught at runtime
- When adding new commands/UI, manually test the full flow to catch integration issues

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
