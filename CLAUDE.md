# Project: guides-api

## Layout
- `app/routers/` - FastAPI route handlers only, no business logic
- `app/services/` - business logic, no direct DB access
- `app/repositories/` - all DB queries via SQLAlchemy
- `app/rendering/` - the sheet: `render.py`, `templates/` (Jinja + CSS), `fonts/` (vendored)
- `app/sketch/` - the Claude redraw client, its versioned prompts, and the SVG sanitiser
- `app/storage.py` - content-addressed asset store; bytes on disk, paths in the database
- `tests/` - three tiers (`unit/`, `api/`, `integration/`), not a mirror of `app/`

## Commands
- Run: `uv run uvicorn app.main:api --reload`
- Test: `uv run pytest tests/` (needs Postgres; `TEST_DATABASE_URL` locates it)
- Fast tier: `uv run pytest tests/ -m "not integration" --no-cov`
  (`--no-cov` is required — the 85% floor is set against the *full* run, so a subset fails it)
- Migrations: `uv run alembic upgrade head`, `uv run alembic check`
- Preview a sheet without rendering: `GET /api/revisions/{id}/preview.html`

## Conventions (overrides or additions to global)
- All DB models live in `app/models/` and inherit from `Base` in `app/database.py`.
- All schemas live in `app/schemas` and inherit from `BaseModel` or a derived subclass.
- No `print()` in src/ — use the logger from `app/logging.py`.

## Versioning & Releases

Versions live **only in git tags** (`vX.Y.Z`). `.github/workflows/version-bump.yml` tags
every push to `main` and hatch-vcs stamps the build from that tag. Never hand-edit a
version, and never push a tag by hand.

**The bump level comes from the PR title**, which the workflow resolves via the GitHub API
(`gh pr view <N>`), using the `(#N)` suffix GitHub appends to the squash subject:

| Marker in the **PR title** | Bump | `v1.4.2` becomes |
|---|---|---|
| `[major]` | major | `v2.0.0` |
| `[minor]` | minor | `v1.5.0` |
| _(neither — the default)_ | patch | `v1.4.3` |

> **Do not read the bump marker from the commit subject.** A squash-merge subject only
> carries the PR title when the PR had more than one commit. For a *single-commit* PR,
> GitHub uses that commit's own message instead, silently dropping a `[minor]`/`[major]`
> marker that exists only in the title — the release then ships as a patch. This has cost
> us four wrong releases (control-api #186, imp-player #11 and #27, imp-dglab #16). The
> workflow must look the title up via the API; the commit subject is only a fallback for
> direct pushes to `main` that have no PR.

This convention is shared across every app in the org. Full reference:
[`release-process.md`](https://github.com/Glitchedpixel-io/claude-code/blob/main/docs/standards/release-process.md) and
[`VERSIONING.md`](https://github.com/Glitchedpixel-io/claude-skills/blob/main/skills/apply-versioning/VERSIONING.md). To apply the
pattern to another repo, invoke the `apply-versioning` skill.

**Landing a change on `main`:** squash merge only (rebase breaks the bump convention by
landing N commits), CI `test` must be green, linear history. See
[`release-process.md`](https://github.com/Glitchedpixel-io/claude-code/blob/main/docs/standards/release-process.md) §6.

## Deployment

**Record which CI-gating design this repo uses**, because it is invisible otherwise:

- [x] `on: push` — requires the `Require CI to pass before merging to main` ruleset to exist
      on this repo. Verified 2026-08-26 at repo creation: `new-repo.sh` applied it and
      confirmed `test` is a required check.
      Re-verify: `gh api /repos/Glitchedpixel-io/guides-api/rulesets | jq '.[].name'`
- [ ] `on: workflow_run [Tests]` + conclusion guard — safe without any ruleset.

There is **no `deploy.yml` yet**. Nothing ships from this repo automatically.

> Two repos shipped with `on: push` and no ruleset, able to tag and deploy a failing build,
> because they were scaffolded from a sibling whose safety lived in GitHub settings rather
> than in the copied files. Tick a box above, and check it.

## Known gotchas

Each of these cost a debugging session while building the sheet. They are all silent
failures — nothing raised, the output was just wrong.

- **The test suite needs Postgres.** `TEST_DATABASE_URL` locates it; in the dev container
  it is already set, pointing at `db:5432`. `localhost` is *not* it — probing localhost
  finds nothing and reads as "no database available".

- **WeasyPrint needs Pango and Cairo**, which are C libraries, not wheels. Without them the
  import succeeds and the first render fails.

- **`position: fixed` is laid out against each page's *content* area, not the paper.**
  Offsets are therefore measured from the content origin and are negative where the sheet
  furniture sits out in the margin. The consequence that matters: **page margins must be
  identical on every page.** A `@page :first` margin override slides the frame and the
  registration marks with it, so page 1's frame lands somewhere page 2's does not. The
  geometry is computed in `app/rendering/render.py:page_geometry` and injected into the
  template for exactly this reason — do not hardcode it in the CSS.

- **WeasyPrint ignores `background-size` on a gradient**, in both the shorthand
  (`background: linear-gradient(...) center/1px 100%`) and the longhand form. The canvas
  drew its registration crosshairs that way; each one rendered as a solid black square.
  They are two child elements now.

- **The compact two-position colour-stop syntax is ignored too.** `repeating-linear-gradient(
  rgba(0,0,0,.07) 0 1px, transparent 1px 0.125in)` renders as nothing at all — that is one
  declaration, and it silently took out the plate grid, the safety-panel hatch and the ruled
  notes field together. Spell out both ends of every stop.

- **CSS grid is unreliable**; a `grid-column: 1 / -1` cell collapses to zero width. The
  title block is a `<table>`. Its table layout is solid — prefer tables for anything grid-shaped.

- **A flex container does not fragment.** When content does not fit the remaining column it
  overruns into the footer band and prints on top of the title block instead of breaking.
  `.step__body` carries `break-inside: avoid` so it moves to the next page instead.

- **An empty flex item has no baseline**, and under `align-items: baseline` WeasyPrint drops
  it far down the page — the dotted step leader printed straight across the drawing plate.
  The step header centres instead.

- **`text-wrap: balance` is a no-op**, so the masthead's two-line title needs an explicit
  break point. It is stored as `guides.title_break_after`, a word index.

- **Reading an ORM attribute after `commit()` raises `MissingGreenlet`.** With
  `expire_on_commit=True` the commit expires every attribute, so touching `orm.id`
  afterwards triggers a lazy refresh from synchronous context. Flush, read the generated id
  into a plain `int`, *then* commit. `app/repositories/step_repo.py` shows the shape.

- **Renumbering an ordered collection needs two phases.** `unique (revision_id, position)`
  means assigning final positions directly collides the moment two rows swap. Everything is
  parked on negative positions first.

- **U+2300 (`⌀`, DIAMETER SIGN) has no glyph in either vendored font.** The canvas used it
  in the symbols legend and it looked right in a browser, where a system fallback supplied
  it; the PDF would have printed tofu. The sheet uses `Ø↔` instead, and
  `tests/unit/test_font_coverage.py` fails if any legend glyph is unrenderable. WeasyPrint
  substitutes silently, so nothing else would catch it.

## The sheet template

`app/rendering/templates/` is the Claude Design canvas **"Blueprint instruction template"**
(project `60a23956-721f-4c9c-85e3-ffd66c812fe8`), flattened for print. The canvas remains
the design source of truth; it is not synced automatically, so a design change means
re-reading it and re-flattening.

Three things changed in the flattening, deliberately:

1. **Pagination is CSS, not fixed artboards.** The canvas hard-codes three fixed-height
   pages with hand-repeated headers and a literal `PAGE 1 OF 3`. Here the frame and
   registration marks are `position: fixed` (WeasyPrint repeats those per page), the header
   and footer are running elements in `@page` margin boxes, and the page counter is
   `counter(page)`/`counter(pages)`. Steps then simply flow.
2. **One footer on every page**, rather than a title block on page 1 and a compact strip
   after. Uniform margins are required by the fixed-frame constraint above, and a title
   block on every sheet is ordinary drafting practice — a sheet separated from its fellows
   must still identify itself.
3. **Fonts are vendored**, not loaded from the Google Fonts CDN. A PDF whose typography
   depends on network reachability is not reproducible, and production has no egress.

`GD_TEMPLATE_VERSION` is recorded on every render. **Bump it whenever the template
changes**: the same revision rendered under a restyled template is a different document, and
without the version there is no way to tell which one someone is holding.

## Application Configuration & Environment Management

This project uses `pydantic-settings` for environment loading and plain frozen dataclasses for configuration values. Configuration lives in `app/config/`.

```
app/config/
├── schema.py    # frozen dataclasses — the config interface the rest of the app uses
└── settings.py  # pydantic-settings loaders — env vars, .env files, factory function
```

`pydantic-settings` is an infrastructure concern and must not leak beyond `app/config/settings.py`. All other modules — services, routers, workers — depend only on the plain dataclasses in `schema.py`.

### Environment Selection

The active environment is controlled by the `APP_ENV` environment variable. Valid values are:

- `development` (default if unset)
- `test`
- `production`

A factory function in `settings.py` reads `APP_ENV`, instantiates the appropriate `BaseSettings` subclass, and maps it onto the frozen dataclasses from `schema.py`. The result is cached with `@lru_cache` so loading happens once per process.

### Config Schema (`app/config/schema.py`)

Define one frozen dataclass per logical config group, plus a top-level `AppConfig` that composes them:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    pool_size: int = 5

@dataclass(frozen=True)
class AppConfig:
    debug: bool
    secret_key: str
    database: DatabaseConfig
```

These dataclasses have no knowledge of how values are sourced — they are the single type the rest of the codebase depends on.

### Settings Loader (`app/config/settings.py`)

```python
from functools import lru_cache
import os
from pydantic_settings import BaseSettings
from app.config.schema import AppConfig, DatabaseConfig

class _Settings(BaseSettings):
    debug: bool = False
    secret_key: str
    database_url: str
    database_pool_size: int = 5

    class Config:
        env_file = ".env.development"

class _TestSettings(_Settings):
    class Config:
        env_file = ".env.test"

class _ProductionSettings(_Settings):
    class Config:
        env_file = None  # rely solely on real environment variables

def _build_database_config(s: _Settings) -> DatabaseConfig:
    return DatabaseConfig(url=s.database_url, pool_size=s.database_pool_size)

def _load() -> AppConfig:
    env = os.getenv("APP_ENV", "development").lower()
    match env:
        case "production":
            s = _ProductionSettings()
        case "test":
            s = _TestSettings()
        case _:
            s = _Settings()
    return AppConfig(
        debug=s.debug,
        secret_key=s.secret_key,
        database=_build_database_config(s),
    )

@lru_cache
def get_config() -> AppConfig:
    return _load()

def get_db_config() -> DatabaseConfig:
    return get_config().database
```

As a project grows, extract a `_build_*` factory function per config group. This keeps `_load()` readable as orchestration rather than a wall of field assignments, and enables cheap, cacheable per-group accessors (e.g. `get_db_config`) that serve as correct `Depends` targets and `dependency_overrides` keys in integration tests. Do not give each `_build_*` function its own `@lru_cache` — the cache belongs only on `get_config()`.

### Accessing Config

Services and other classes receive config dataclasses via constructor injection — they never call `get_config()` themselves:

```python
# app/services/database.py
class DatabaseService:
    def __init__(self, config: DatabaseConfig):
        self.engine = create_engine(config.url, pool_size=config.pool_size)
```

Never import from `app.config.settings` outside of `app/config/` and router/lifespan wiring. Never hardcode environment-specific values anywhere outside `app/config/`.

### .env Files

| File | Purpose | In git? |
|---|---|---|
| `.env.example` | Template with all keys, no real values | ✅ Yes |
| `.env.development` | Local dev overrides | ❌ No |
| `.env.test` | Test runner overrides | ❌ No |
| `.env.production` | Must not exist — use real env vars | ❌ No |

Production **must not** rely on `.env` files. Secrets must be injected by the platform (Docker, Kubernetes, CI/CD) as real environment variables, or mounted via `secrets_dir`.

### Testing

Because service classes depend only on plain frozen dataclasses, construct config objects directly in tests — no env vars, no cache-clearing, no patching:

```python
# tests/services/test_database_service.py
from app.config.schema import DatabaseConfig
from app.services.database import DatabaseService

def test_connects_with_correct_pool_size():
    config = DatabaseConfig(url="sqlite:///:memory:", pool_size=2)
    service = DatabaseService(config)
    ...
```

For FastAPI integration tests that go through the full request cycle, override the relevant per-group accessor — not `get_config` itself, since that would require constructing the full `AppConfig`:

```python
# tests/routers/test_my_router.py
from app.config.schema import DatabaseConfig
from app.config.settings import get_db_config
from app.main import app

def test_handler(client):
    app.dependency_overrides[get_db_config] = lambda: DatabaseConfig(
        url="sqlite:///:memory:"
    )
    response = client.get("/")
    app.dependency_overrides.clear()
```

Do not patch env vars or clear the `get_config` cache in tests — if you feel the need to, the config dependency is not being injected correctly. Modules must also never call `get_config()` at import time (only inside functions); an import-time call will populate the cache before any `dependency_overrides` are in place and silently win for the rest of the process.

# Dependency Injection & Service Lifecycle

## Structure

Dependencies are managed in `app/dependencies.py`, which is the single source of truth
for wiring together sessions, repositories, services, and long-lived singletons.

The file is organised into clearly commented sections:

```
# session
# repositories
# services
# service managers / guides-api   (one section per integration)
# runtime / guides-api            (one section per runtime component)
```

All imports belong at the top of the file. Do not place imports mid-file, even for
optional integrations — this avoids masking circular import issues.

---

## Database Sessions

One session per request, provided via an async generator:

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

---

## Repositories

Each repository is constructed from a session. These functions exist primarily as
named, introspectable nodes in the dependency graph — not as composable intermediaries.

```python
def get_device_repository(db: AsyncSession = Depends(get_db)) -> DeviceRepository:
    return SQLAlchemyDeviceRepository(db)
```

---

## Service Factories

**Critical:** when a service depends on more than one repository, inject the session
directly and construct all repositories from the same session. Do not chain multiple
`Depends(get_*_repository)` calls — FastAPI treats each as a distinct dependency and
will open a separate database session for each, silently breaking transactional
consistency.

```python
# Correct — single session, multiple repositories
def get_sensor_service(db: AsyncSession = Depends(get_db)) -> SensorService:
    return SensorService(
        SQLAlchemySensorRepository(db),
        SQLAlchemyDeviceRepository(db),
    )

# Wrong — two sessions opened per request
def get_sensor_service(
    repo: SensorRepository = Depends(get_sensor_repository),
    device_repo: DeviceRepository = Depends(get_device_repository),
) -> SensorService:
    return SensorService(repo, device_repo)
```

Services that depend on only one repository may use the repository dependency directly,
since no session-sharing issue arises:

```python
def get_device_service(
    repo: DeviceRepository = Depends(get_device_repository),
) -> DeviceService:
    return DeviceService(repo)
```

---

## Long-lived Singletons

Services that do not depend on a database session (e.g. MQTT publishers, Modbus
managers, runtime engines) are managed as module-level singletons with an `init_*`/
`get_*` pair each:

```python
_mqtt_publisher: MqttPublisher | None = None

def get_mqtt_publisher() -> MqttPublisher | None:
    return _mqtt_publisher

def init_mqtt_publisher() -> MqttPublisher | None:
    global _mqtt_publisher
    try:
        _mqtt_publisher = MqttPublisher()
    except ValueError as e:
        logfire.error(f"MQTT Publisher initialization failed: {e}")
        _mqtt_publisher = None
    return _mqtt_publisher
```

Where a singleton is required (not optional), guard against uninitialised access with
an explicit `RuntimeError` — not `assert`, which is silently stripped when Python runs
with the `-O` flag:

```python
def get_manifest_hub() -> ManifestHub:
    if _manifest_hub is None:
        raise RuntimeError("ManifestHub not initialized")
    return _manifest_hub
```

Optional singletons (integrations that may not be configured) return `None` and callers
are responsible for handling the absent case.

---

## Lifespan Wiring

The lifespan is created via a factory function that closes over app config, returning
a properly typed async context manager:

```python
def get_lifespan(config: AppConfig) -> Callable[[FastAPI], AsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # startup
        ...
        yield
        # shutdown
        ...
    return lifespan
```

### Rules

- Every long-lived service that needs to be accessible to routers or background tasks
  must be registered in `dependencies.py` via an `init_*`/`get_*` pair. Do not hold
  services as bare local variables in the lifespan closure — they will be invisible to
  the rest of the application.
- A service's `start()` method must bring it to a fully operational state. Do not call
  additional setup methods after `start()`.
- `get_*` functions are used everywhere outside of lifespan — in routers, background
  tasks, and other services — via `Depends(get_service)`.

### Extracting startup into helper functions

The lifespan function should read as an orchestration script, not an implementation.
Extract conditional startup blocks into clearly named async helpers:

```python
async def _start_mqtt(config: MqttConfig) -> tuple[MqttSubscriber | None, MqttPublisher | None]:
    if config.broker is None or config.port is None:
        return None, None
    subscriber = MqttSubscriber(config)
    await subscriber.start()
    publisher = init_mqtt_publisher(config)
    if publisher is not None:
        await publisher.start()
    return subscriber, publisher

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    engine = init_trigger_engine()
    await engine.start()
    mqtt_sub, mqtt_pub = await _start_mqtt(config.mqtt)
    ...
    yield
    # shutdown
    ...
```

### safe_stop

A utility for graceful shutdown with timeout protection. Define once in `app/lifespan.py` (or similar) and use throughout shutdown:

```python
async def safe_stop(name: str, coro: Coroutine[Any, Any, None], timeout: float = 5.0) -> None:
    """Stop a service with timeout protection."""
    try:
        await asyncio.wait_for(coro, timeout=timeout)
        logfire.debug(f"{name} stopped successfully")
    except asyncio.TimeoutError:
        logfire.warning(f"{name} stop timed out after {timeout}s")
    except Exception as e:
        logfire.exception(f"Error stopping {name}: {e}")
```

### Shutdown ordering

Stop consumers before producers; stop event-generating services before the
infrastructure they write to. Phase shutdown explicitly with comments:

1. Stop event-generating services (hubs, SSE emitters)
2. Stop the trigger/event engine
3. Brief `asyncio.sleep(0.1)` to drain in-flight operations (pragmatic workaround, not a guarantee — avoid in latency-sensitive contexts)
4. Stop independent external services in parallel via `asyncio.gather`
5. Stop messaging infrastructure last — publisher before subscriber, so other
   services can still publish during their own shutdown
6. Close write-only sinks (time-series DBs, log shippers)
7. Dispose the database engine

`safe_stop(label, coro)` should log and swallow exceptions so one failing service
does not prevent the rest from shutting down cleanly.

### Services that need DB access outside a request context

Some long-lived services need to query the database in response to events, with no
request-scoped session available. Pass `AsyncSessionLocal` (the session factory)
directly rather than constructing a duck-typed service wrapper to work around the
missing session:

```python
# Correct — the service creates its own sessions as needed
hub = init_event_hub(session_factory=AsyncSessionLocal)

# Wrong — wrapper class with # type: ignore is a sign the dependency is wrong
class _ServiceWrapper:
    async def get_data(self) -> Data:
        async with AsyncSessionLocal() as session:
            return await DataService(DataRepository(session)).get_data()

hub = init_event_hub(_ServiceWrapper())  # type: ignore
```
