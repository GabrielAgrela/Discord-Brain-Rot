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

## Deployment

### Restarting the Bot
After making code changes, **always restart the Docker containers** to deploy:

```bash
cd /home/gabi/github/Discord-Brain-Rot
docker-compose restart
```

This restarts both the bot and web containers. The bot runs in Docker, so changes to Python files won't take effect until the container is restarted.

### Viewing Logs
To monitor the bot after restart:
```bash
docker-compose logs -f bot
```

Or check the log files directly in `Logs/` (named by date, e.g., `2026-01-26.log`).
