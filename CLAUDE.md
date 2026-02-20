# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment and setup

- Use **Python 3.12** for development (repo pins `.python-version` to `3.12`, and CI runs 3.12).
- Use **uv** as the primary Python package manager.

```bash
pip install uv
uv sync
mkdir -p data/plugins data/config data/temp
```

- Optional git hook setup:

```bash
pip install pre-commit
pre-commit install
```

## Common commands (repository root)

- Run AstrBot (core + dashboard):

```bash
uv run main.py
```

- Run with an explicit built WebUI directory:

```bash
uv run main.py --webui-dir /absolute/path/to/dist
```

- Lint and format (Ruff):

```bash
uv run ruff check .
uv run ruff format --check .
uv run ruff format .
```

- Run tests (CI-like local run):

```bash
mkdir -p data/plugins data/config data/temp
TESTING=true uv run pytest --cov=. -v -o log_cli=true -o log_level=DEBUG
```

- Run a single test file:

```bash
TESTING=true uv run pytest tests/test_main.py -v
```

- Run a single test case:

```bash
TESTING=true uv run pytest tests/test_main.py::test_name -v
```

- Worktree helpers:

```bash
make worktree-add <branch> [base-branch]
make worktree-rm <branch>
```

## Dashboard (frontend) commands

Run in `dashboard/`:

```bash
npm install
npm run dev
npm run build
npm run typecheck
npm run lint
```

Notes:
- CI also uses `pnpm` for dashboard builds, but local scripts are defined in `dashboard/package.json`.
- Backend runtime serves dashboard static assets from `data/dist` (or `--webui-dir`).

## High-level architecture

### Boot and runtime wiring

- `main.py` bootstraps runtime TLS/CA behavior, validates environment, ensures `data/` directories, optionally downloads dashboard assets, then starts `InitialLoader`.
- `astrbot/core/initial_loader.py` starts:
  - core runtime (`AstrBotCoreLifecycle`)
  - dashboard HTTP server (`AstrBotDashboard`)

### Core lifecycle composition

`astrbot/core/core_lifecycle.py` is the central runtime assembler. It initializes and wires:

- DB and migrations
- config routing/management (`UmopConfigRouter`, `AstrBotConfigManager`)
- persona/conversation/message-history managers
- provider system (`ProviderManager`)
- platform adapters (`PlatformManager`)
- plugin system (`PluginManager`, called “Stars”)
- knowledge base manager
- cron manager and temp directory cleaner
- per-config pipeline schedulers
- global event bus

### Message/event pipeline (critical flow)

1. Platform adapters receive inbound messages and create `AstrMessageEvent`.
2. Events are pushed into a shared async queue.
3. `EventBus` dispatches each event to the correct `PipelineScheduler` using `unified_msg_origin` mapping.
4. Scheduler executes onion-style stages in fixed order:
   - `WakingCheckStage`
   - `WhitelistCheckStage`
   - `SessionStatusCheckStage`
   - `RateLimitStage`
   - `ContentSafetyCheckStage`
   - `PreProcessStage`
   - `ProcessStage`
   - `ResultDecorateStage`
   - `RespondStage`
5. `ProcessStage` runs activated plugin handlers first; if no handler already answered and wake conditions match, it enters the default agent/LLM path.

### Plugin (Star) architecture

- Built-in plugins: `astrbot/builtin_stars/`
- User plugins: `data/plugins/`
- Managed by `astrbot/core/star/star_manager.py`

Capabilities include:
- discovery/loading from plugin directories (`main.py` or `<plugin>.py`)
- metadata via `metadata.yaml` (with legacy compatibility)
- dependency handling from plugin `requirements.txt`
- install/uninstall/update
- enable/disable and reload
- optional file-watch hot reload (when enabled)
- plugin-bound tool and platform-adapter unregistration on unload

Plugin runtime API surface is provided through `astrbot/core/star/context.py` (`Context`), including:
- model calls (`llm_generate`, `tool_loop_agent`)
- sending messages by session
- LLM tool registration/activation
- plugin web API registration (`register_web_api`)

### Provider architecture

- `astrbot/core/provider/manager.py` dynamically loads provider implementations from `astrbot/core/provider/sources/`.
- Supports provider types:
  - chat completion
  - STT
  - TTS
  - embedding
  - rerank
- Provider selection can be scoped per unified message origin (session-aware), with fallback to configured defaults.
- LLM tool subsystem also initializes MCP clients during startup.

### Platform adapter architecture

- `astrbot/core/platform/manager.py` dynamically loads adapters from `astrbot/core/platform/sources/` based on config.
- Includes WebChat adapter startup by default.
- Platform run tasks are wrapped for lifecycle/state/error tracking and controlled termination.

### Dashboard/API architecture

- `astrbot/dashboard/server.py` runs Quart/Hypercorn server for API + static UI.
- `/api/*` is JWT-protected except explicit allowlist routes.
- Plugin HTTP extensions are routed through `/api/plug/<subpath>` from handlers registered via `Context.register_web_api`.

## Repository-specific guidance from existing instructions

From `.github/copilot-instructions.md`, preserve these conventions when editing this repo:

- Prefer `uv`-based workflows for Python dependency/runtime commands.
- Run `ruff check` and `ruff format` before finishing changes.
- Keep plugin work aligned with:
  - built-in plugins in `astrbot/builtin_stars/`
  - user plugins in `data/plugins/`
- Ensure local runtime prerequisites under `data/` exist (`plugins`, `config`, `temp`).
