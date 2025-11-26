# Agent Chassis - Project Context

## Project Overview

**Agent Chassis** is a modular, asynchronous foundation for building AI agents. It serves as a robust "scaffolding" for agentic applications, handling the heavy lifting of infrastructure, protocol management, and tool execution so developers can focus on agent logic.

### Core Technologies & Stack
*   **FastAPI**: High-performance, async-first web framework for the API layer.
*   **uv**: Modern, ultra-fast Python package manager used for dependency resolution and project management.
*   **OpenAI SDK (Async)**: The primary interface for LLM inference, configured for standard chat completions and tool calling.
*   **Model Context Protocol (MCP)**: Native integration for connecting to external data and tools via standard `stdio` (local) or `SSE` (remote) protocols.
*   **Pydantic V2**: Used extensively for strict type validation, settings management, and schema definitions.
*   **Pytest**: Comprehensive testing suite with async support.

## Architecture & Key Components

### 1. Agent Service (`app/services/agent_service.py`)
The central "brain" of the application. It orchestrates the autonomous execution loop:
*   **Plan-Act-Observe Loop**: Executes a multi-turn loop (default max 5 steps) where the model can request tool calls, receive results, and iterate.
*   **Streaming Support**: Fully supports Server-Sent Events (SSE) for real-time feedback (token-by-token generation and tool execution status).
*   **Robust Error Handling**: The agent loop is hardened to gracefully handle API failures or tool errors without crashing the entire request.
*   **Hybrid Tooling**: Dynamically aggregates tools from two sources:
    *   **Remote MCP Servers**: Discovered via `MCPManager`.
    *   **Local Python Functions**: Registered via `LocalToolRegistry`.
*   **Tool Filtering**: Securely filters available tools per request using the `allowed_tools` whitelist.
*   **System Prompt Injection**: Supports dynamic system prompts injected at runtime via the API request.

### 2. MCP Manager (`app/services/mcp_manager.py`)
Manages the lifecycle of connections to Model Context Protocol servers.
*   **Protocol Support**: Fully supports both **Stdio** (subprocess) and **SSE** (Server-Sent Events) connections.
*   **Configuration**: Reads server definitions from a JSON file (default `mcp_config.json`), supporting hot-swappable configs via environment variables.
*   **Resource Safety**: Uses `AsyncExitStack` to ensure connections are cleanly initialized and closed during the application lifespan.

### 3. Local Tool Registry (`app/services/local_tools.py`)
A lightweight, decorator-based system for adding local Python logic as tools.
*   **Usage**: Decorate any function with `@local_registry.register` to expose it to the agent.
*   **Introspection**: Automatically parses function signatures and docstrings to generate OpenAI-compatible JSON schemas.
*   **Built-in Tools**: Includes a `calculate` tool (basic arithmetic) and `get_server_time`.

### 4. Tool Translator (`app/services/tool_translator.py`)
The universal adapter layer.
*   **MCP Adapter**: Converts MCP `Tool` objects into OpenAI JSON Schema format.
*   **Python Adapter**: Uses `inspect` to convert Python functions into OpenAI JSON Schema format, with robust type mapping (int, float, bool, list, dict).

### 5. Security & Configuration (`app/core/`)
*   **Settings**: All config is managed via `pydantic-settings` (`app/core/config.py`), loading from `.env`.
*   **Authentication**: Implements a lightweight API Key mechanism (`app/core/security.py`).
    *   Enforced via `CHASSIS_API_KEY` environment variable.
    *   Clients must send `X-API-Key` header if enabled.

## Setup & Development

### Prerequisites
*   **uv**: [Install uv](https://github.com/astral-sh/uv)
*   `npm`: Required only if running Node.js-based MCP servers (e.g., the filesystem server).

### Installation & Running
1.  **Sync Dependencies**:
    ```bash
    uv sync
    ```
2.  **Configure Environment**:
    Copy `.env.example` to `.env` and set your keys.
    *   **Default Model**: `kimi-k2-thinking` (configurable via `OPENAI_MODEL`).
    *   **Base URL**: Configurable via `OPENAI_BASE_URL` (e.g., for 3rd party providers).
3.  **Run Server**:
    ```bash
    uv run uvicorn app.main:app --reload
    ```
4.  **Run Tests**:
    ```bash
    uv run pytest
    ```

### Directory Structure
```
.
├── app/
│   ├── api/          # API Routes and Endpoints
│   ├── core/         # Config, Security, Logging
│   ├── schemas/      # Pydantic Data Models
│   └── services/     # Business Logic (Agent, MCP, Tools)
├── scripts/          # Debug and Smoke Test scripts
├── tests/            # Pytest Suite
├── mcp_config.json   # MCP Server Definitions
├── pyproject.toml    # Project Metadata & Dependencies
└── uv.lock           # Dependency Lockfile
```

## API Usage

**POST** `/api/v1/agent/completion`

**Headers:**
*   `X-API-Key`: (If configured)

**Body (Non-Streaming):**
```json
{
  "messages": [
    {"role": "user", "content": "Calculate 123 + 456"}
  ],
  "model": "kimi-k2-thinking",
  "allowed_tools": ["calculate"]
}
```

**Body (Streaming):**
```json
{
  "messages": [
    {"role": "user", "content": "Calculate 123 + 456"}
  ],
  "model": "kimi-k2-thinking",
  "allowed_tools": ["calculate"],
  "stream": true
}
```

## Debugging & Tools

Scripts in the `scripts/` directory are excluded from the package build but useful for validation:

*   `uv run python scripts/smoke_test.py`: Runs the unified smoke test.
    *   **Default**: Blocking mode (Local Calculator/Time tools).
    *   `--stream`: Streaming mode (Server-Sent Events).
    *   `--mcp`: Test Memory MCP integration (creating entities).

*   `uv run python scripts/client_test.py`: **Interactive Terminal Client**.
    *   Full REPL interface for chatting with the agent.
    *   Supports streaming (`--no-stream` to disable).
    *   Supports API Key (`--api-key` or from `.env`).
    *   Example: `uv run python scripts/client_test.py --tools calculate get_server_time`