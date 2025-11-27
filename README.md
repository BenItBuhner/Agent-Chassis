# Agent Chassis

**A modular, scalable foundation for building AI agents with FastAPI, OpenAI, and MCP.**

This project serves as a "chassis" or scaffolding for building robust agentic applications. It handles the infrastructure—server management, protocol translation, tool execution—so you can focus on the agent's logic and capabilities.

## Key Features

*   **Modular Architecture**: Built on FastAPI with a clean separation of concerns (Routes, Services, Schemas).
*   **MCP Support**: Native integration with the **Model Context Protocol (MCP)**. Connect to any MCP-compliant server (local or remote) by simply adding it to `mcp_config.json`.
*   **Hybrid Tooling**: Seamlessly mixes **Remote MCP Tools** and **Local Python Functions** into a single toolset for the agent.
*   **Streaming Support**: Fully supports Server-Sent Events (SSE) for real-time feedback of content and tool execution status.
*   **OpenAI Compatible**: Automatically translates all tools into OpenAI's JSON Schema format and manages the tool-calling loop.
*   **Tool Filtering**: Securely restrict which tools are available per request using the `allowed_tools` parameter.
*   **Async & Scalable**: Fully asynchronous design using `asyncio` and FastAPI.
*   **Modern Tooling**: Built with `uv` for lightning-fast dependency management.

## Quick Start

### 1. Prerequisites

*   **uv**: An extremely fast Python package installer and resolver. [Install uv](https://github.com/astral-sh/uv).
*   `npm` (if using Node.js based MCP servers)

### 2. Installation

Clone the repository and sync dependencies:

```bash
uv sync
```

### 3. Configuration

1.  **Environment Variables**:
    Rename `.env.example` to `.env` and configure your settings:
    ```env
    OPENAI_API_KEY=sk-...
    OPENAI_BASE_URL=https://api.openai.com/v1 # Optional
    OPENAI_MODEL=kimi-k2-thinking             # Default model
    MCP_CONFIG_PATH=mcp_config.json
    CHASSIS_API_KEY=secret-key-123            # Optional: Protect your API
    ```

2.  **MCP Servers**:
    Define your MCP servers in `mcp_config.json`. 
    
    **Stdio Example (Local):**
    ```json
    {
      "mcpServers": {
        "filesystem": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]
        }
      }
    }
    ```

    **SSE Example (Remote):**
    ```json
    {
      "mcpServers": {
        "remote-server": {
          "url": "https://mcp.example.com/sse",
          "headers": {"Authorization": "Bearer token"}
        }
      }
    }
    ```

### 4. Running the Server

You can run the server using `uv` locally or via Docker.

**Local (uv):**
```bash
uv run uvicorn app.main:app --reload
```

**Docker:**
```bash
docker-compose up --build
```

The API will be available at `http://localhost:8000`.

## Usage

### Agent Completion Endpoint

**POST** `/api/v1/agent/completion`

Send a prompt to the agent. It will autonomously select tools, execute them, and return the result.

**Request Body (Non-Streaming):**

```json
{
  "messages": [
    {"role": "user", "content": "What time is it?"}
  ],
  "model": "kimi-k2-thinking",
  "allowed_tools": ["get_server_time"] 
}
```

**Request Body (Streaming):**

```json
{
  "messages": [
    {"role": "user", "content": "Calculate 5 * 5"}
  ],
  "stream": true
}
```

## Adding Tools

### Local Python Tools

Add a function to `app/services/local_tools.py` and decorate it:

```python
@local_registry.register
def my_custom_tool(x: int, y: int):
    """Adds two numbers."""
    return x + y
```

### Remote MCP Tools

Simply add the server configuration to your `mcp_config.json` file.

## Testing

Run the test suite with `uv run`:

```bash
uv run pytest
```

## Debugging

You can run a unified smoke test script to verify the agent's functionality (Blocking, Streaming, and MCP integration):

```bash
uv run python scripts/smoke_test.py --help
```

*   `--stream`: Test streaming mode.
*   `--mcp`: Test filesystem MCP integration.
*   Default: Test blocking mode with local tools.
