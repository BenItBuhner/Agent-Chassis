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

## What is Agent Chassis?

Agent Chassis is a modular, asynchronous foundation for building AI agents with FastAPI, OpenAI, and MCP (Model Context Protocol). It serves as a robust "scaffolding" for agentic applications, handling the heavy lifting of infrastructure, protocol management, and tool execution so developers can focus on agent logic.

### Core Components

1. **Agent Service** (`app/services/agent_service.py`): The central brain that orchestrates a multi-turn Plan-Act-Observe loop with streaming support and robust error handling.

2. **MCP Manager** (`app/services/mcp_manager.py`): Manages connections to Model Context Protocol servers via stdio or Server-Sent Events (SSE) protocols.

3. **Local Tool Registry** (`app/services/local_tools.py`): A decorator-based system for exposing local Python functions as tools to the agent.

4. **Tool Translator** (`app/services/tool_translator.py`): Universal adapter that converts MCP Tools and Python functions to OpenAI JSON Schema format.

5. **Security & Configuration** (`app/core/`): Manages API key authentication, settings via pydantic-settings, and environment configuration.

### Key Features

- **Hybrid Tooling**: Combine remote MCP tools with local Python functions seamlessly
- **Streaming & Non-Streaming**: Choose between real-time token-by-token feedback or blocking responses
- **Session Persistence**: Optional Redis + PostgreSQL storage for conversation history
- **Authentication**: Support for API key and JWT-based auth with Google OAuth
- **OpenAI Compatible**: Works with OpenAI API and compatible providers

### Next Steps

- View the full documentation at [agent-chassis.techlitnow.com](https://agent-chassis.techlitnow.com)
- Check out [AGENTS.md](./AGENTS.md) for a more in-depth codebase walkthrough
- See [CLAUDE.md](./CLAUDE.md) for detailed context for AI assistants
- Explore the `/docs` directory for comprehensive guides on configuration, tool development, and MCP integration