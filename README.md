# Agent Chassis

**A modular, scalable foundation for building AI agents with FastAPI, OpenAI, and MCP.**

You can view the full documentation [here with Mintlify](https://agent-chassis.techlitnow.com).

## Why it’s useful
- Hybrid tools (local Python + MCP) with OpenAI-compatible schemas.
- Streaming and non-streaming agent loop with tool calling.
- Optional persistence (Redis/Postgres) and auth (API key / JWT).

## Quick start (bite-sized)
1) Install deps  
```bash
uv sync
```
2) Configure env  
```bash
cp .env.example .env  # set OPENAI_API_KEY, CHASSIS_API_KEY (optional)
```
3) Run the API  
```bash
uv run uvicorn app.main:app --reload
```
API lives at http://localhost:8000 (see Mintlify for endpoints and tool setup).

## Basic usage
- Add local tools in `app/services/local_tools.py` with `@local_registry.register`.
- Add MCP servers in `mcp_config.json` (stdio/SSE/streamable-http).
- Restrict allowed tools per request via `allowed_tools`.

## Testing
```bash
uv run pytest
```