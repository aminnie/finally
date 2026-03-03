# FinAlly — AI Trading Workstation

A visually stunning AI-powered trading workstation that streams live market data, simulates portfolio trading, and integrates an LLM chat assistant that can analyze positions and execute trades via natural language.

Built entirely by coding agents as a capstone project for an agentic AI coding course.

## Features

- **Live price streaming** via SSE with green/red flash animations
- **Simulated portfolio** — $10k virtual cash, market orders, instant fills
- **Portfolio visualizations** — heatmap (treemap), P&L chart, positions table
- **AI chat assistant** — analyzes holdings, suggests and auto-executes trades
- **Watchlist management** — track tickers manually or via AI
- **Dark terminal aesthetic** — Bloomberg-inspired, data-dense layout

## Architecture

Single Docker container serving everything on port 8000:

- **Frontend**: Next.js (static export) with TypeScript and Tailwind CSS
- **Backend**: FastAPI (Python/uv) with SSE streaming
- **Database**: SQLite with lazy initialization
- **AI**: LiteLLM → OpenRouter (Cerebras inference) with structured outputs
- **Market data**: Built-in GBM simulator (default) or Massive API (optional)

## Quick Start

```bash
# Clone and configure
cp .env.example .env
# Add your OPENROUTER_API_KEY to .env

# Run with Docker
docker build -t finally .
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally

# Open http://localhost:8000
```

### Run Without Docker

```bash
uv run --project backend --extra dev uvicorn app.main:app --reload --port 8000
```

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev      # local Next.js dev server
npm run build    # static export to frontend/out
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for AI chat |
| `MASSIVE_API_KEY` | No | Massive (Polygon.io) key for real market data; omit to use simulator |
| `LLM_MOCK` | No | Set `true` for deterministic mock LLM responses (testing) |

## Project Structure

```
finally/
├── frontend/    # Next.js static export
├── backend/     # FastAPI uv project
├── planning/    # Project documentation and agent contracts
├── test/        # Playwright E2E tests
├── db/          # SQLite volume mount (runtime)
└── scripts/     # Start/stop helpers
```

## Plugin Validation

Validate Cursor plugin manifests and related files with:

```bash
bash scripts/validate-plugins-readonly.sh
```

The validator is read-only and checks marketplace/plugin JSON, skills/rules layout, hook script references, and MCP config sanity.

## Install Local Skill

To register local in-repo skills for Codex session discovery:

```bash
mkdir -p ~/.codex/skills/start-simple
ln -sf "$(pwd)/plugins/starter-simple/skills/code-reviewer/SKILL.md" \
  ~/.codex/skills/start-simple/SKILL.md

mkdir -p ~/.codex/skills/start-advanced
ln -sf "$(pwd)/plugins/starter-advanced/skills/code-reviewer/SKILL.md" \
  ~/.codex/skills/start-advanced/SKILL.md
```

Installed skill names in `~/.codex/skills` should be `start-simple` and `start-advanced`.
Verify both are present with:

```bash
ls -la ~/.codex/skills/start-*
```

Restart Cursor/Codex after installing so the skills are picked up by new sessions.

## License

See [LICENSE](LICENSE).
