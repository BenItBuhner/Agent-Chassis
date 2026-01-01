┌─────────────────────────────────────────┐
│              API Layer                  │
│         (FastAPI + Routes)              │
├─────────────────────────────────────────┤
│             Schema Layer                │
│        (Pydantic Models)                │
├─────────────────────────────────────────┤
│            Service Layer                │
│      (Business Logic + Handlers)        │
├─────────────────────────────────────────┤
│             Core Layer                  │
│       (Configuration + Security)        │
└─────────────────────────────────────────┘
```

### Asynchronous Design

The entire application is built on async/await patterns:

```python
# Example of async pattern in the agent service
async def process_request(self, request):
    async with self.mcp_manager:
        tools = await self.get_tools()
        response = await self.openai_client.chat.completions.create(...)
        return response
```

This design enables:
- Non-blocking I/O operations
- Efficient handling of concurrent requests
- Native support for streaming responses

### Plugin Architecture

The system uses a plugin architecture for tools, allowing you to easily extend functionality:

1. **Local Tools**: Decorate functions in your codebase
2. **MCP Tools**: External tools via Model Context Protocol servers
3. **Hybrid Composition**: Combine both types seamlessly

## Core Components

### 1. Agent Service (`app/services/agent_service.py`)

The heart of the system that orchestrates the agent's autonomy.

#### Key Concepts
- **Multi-turn Loop**: The agent can make multiple tool calls in sequence
- **Tool Selection**: Dynamically chooses tools based on user intent
- **Error Resilience**: Gracefully handles failures without crashing
- **Streaming Support**: Real-time token-by-token generation via SSE

#### Implementation Details
```python
class AgentService:
    async def completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        # Set up context with tools and allowed tools filter
        # Execute the multi-turn agent loop with Plan-Act-Observe pattern
        # Handle both streaming and non-streaming responses
        # Apply security boundaries with allowed_tools whitelist
```

#### Extending the Agent
To modify the agent's behavior:
1. Override the completion method for custom request handling
2. Modify the max_turns setting for different verbosity levels
3. Implement custom system prompts for specific domains
4. Add specialized error handling for your use case

### 2. MCP Manager (`app/services/mcp_manager.py`)

Manages connections to external MCP servers, the gateway to external tools and data.

#### Protocol Implementation
```python
class MCPManager:
    async def connect_to_server(self, server_config):
        # Establish connection based on protocol type
        # Handles stdio for subprocess-based servers
        # Handles SSE for HTTP-based servers
        # Uses AsyncExitStack for resource management
```

#### MCP Configuration
```json
{
  "servers": {
    "server_name": {
      "command": "server_command",
      "args": ["--arg1", "value1"],
      "protocol": "stdio" | "sse",
      "url": "https://server-url"  // For SSE protocol
    }
  }
}
```

#### Adding New MCP Servers
1. Update `mcp_config.json` with server details
2. Choose appropriate protocol (stdio for subprocesses, SSE for HTTP)
3. Restart the application to refresh connections

### 3. Local Tool Registry (`app/services/local_tools.py`)

The decorator-based system for exposing local Python functions as tools.

#### Tool Registration Pattern
```python
@local_registry.register
def my_tool(param1: type1, param2: type2) -> return_type:
    """
    Tool description becomes available to LLMs.
    
    Args:
        param1: Description of first parameter
        param2: Description of second parameter
        
    Returns:
        Description of return value
    """
    # Implementation here
    return result
```

#### Code Generation & Introspection
The registry uses Python's `inspect` module to:
- Extract type hints for parameter validation
- Parse docstrings for tool descriptions
- Generate OpenAI-compatible JSON schemas
- Provide function metadata for the agent

### 4. Tool Translator (`app/services/tool_translator.py`)

The universal adapter layer that standardizes different tool formats.

#### Translation Process
```python
class ToolTranslator:
    def translate_mcp_tool(self, mcp_tool) -> OpenAIFunction:
        # Convert MCP Tool object to OpenAI JSON Schema
        # Handles type mapping and parameter extraction
        # Preserves descriptions and metadata
        
    def translate_python_function(self, func) -> OpenAIFunction:
        # Use inspect to analyze Python functions
        # Convert type hints to JSON Schema types
        # Extract docstrings for descriptions
```

### 5. Security & Configuration (`app/core/`)

The foundation for secure, configurable operation.

#### Configuration Management
```python
class Settings(BaseSettings):
    openai_api_key: str
    openai_model: str = "gpt-4"
    chassis_api_key: Optional[str] = None
    redis_url: Optional[str] = None
    database_url: Optional[str] = None
    
    model_config = SettingsConfigDict(env_file=".env")
```

#### Authentication Layer
```python
class SecurityManager:
    def verify_api_key(self, api_key: str) -> bool:
        # Verifies API key if CHASSIS_API_KEY is set
        
    def create_jwt_token(self, user_data) -> str:
        # Creates JWT tokens for user authentication
        
    def verify_jwt_token(self, token: str) -> Optional[dict]:
        # Verifies and decodes JWT tokens
```

## Development Workflow

### 1. Setting Up Your Development Environment

```bash
# Clone the repository
git clone <repository-url>
cd agent-chassis

# Install dependencies with uv
uv sync

# Copy environment file
cp .env.example .env
# Edit .env with your configuration

# Run the development server
uv run uvicorn app.main:app --reload
```

### 2. Making Changes

1. **Code Organization**: Follow the existing structure with clear separation of concerns
2. **Type Hints**: Use proper type hints for all function signatures
3. **Error Handling**: Implement proper try/catch blocks for async operations
4. **Documentation**: Update docstrings for any new functions or modified behavior

### 3. Testing

```bash
# Run all tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=app

# Run specific test file
uv run pytest tests/test_agent_service.py
```

### 4. Testing with Docker

```bash
# Build the Docker image
docker build -t agent-chassis .

# Run with Docker Compose (includes Redis, Postgres)
docker-compose up -d
```

## Building Upon the Chassis

### Scenario 1: Adding a Custom Domain-Specific Agent

To create an agent specialized for a particular domain:

1. **Extend AgentService**:
```python
class LegalAgentService(AgentService):
    async def completion(self, request):
        # Add legal-specific system prompt
        request.system_prompt = """
        You are a legal assistant specializing in contract analysis.
        Provide clear, accurate legal information and always suggest
        consulting with a qualified attorney for specific cases.
        """
        
        # Filter to legal-relevant tools
        request.allowed_tools = [
            "search_legal_database",
            "extract_contract_terms",
            "analyze_legal_document"
        ]
        
        return await super().completion(request)
```

2. **Create API Endpoint**:
```python
# app/api/v1/endpoints/legal.py
from fastapi import APIRouter, Depends
from app.services.legal_agent_service import LegalAgentService

router = APIRouter()

@router.post("/legal/analyze")
async def analyze_legal_document(
    request: ChatCompletionRequest,
    service: LegalAgentService = Depends()
):
    return await service.completion(request)
```

3. **Register with App**:
```python
# app/main.py
from app.api.v1.endpoints import legal

app.include_router(legal.router, prefix="/api/v1")
```

### Scenario 2: Adding a Local Tool with External Dependencies

```python
# app/services/local_tools.py
import requests
from typing import Dict, Any
from app.services.local_tools import local_registry

@local_registry.register
def fetch_weather_data(location: str) -> Dict[str, Any]:
    """
    Fetches current weather data for a location.
    
    Args:
        location: The city name or zip code
        
    Returns:
        Dictionary with weather information
    """
    api_key = os.getenv("WEATHER_API_KEY")
    url = f"http://api.weatherapi.com/v1/current.json?key={api_key}&q={location}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}
```

### Scenario 3: Creating a Custom MCP Server

```python
# my_custom_mcp_server.py
import asyncio
import sys
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

server = Server("my-custom-server")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="custom_tool",
            description="A custom tool that does something specific",
            inputSchema={
                "type": "object",
                "properties": {
                    "param": {"type": "string", "description": "A parameter"}
                },
                "required": ["param"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "custom_tool":
        param = arguments.get("param")
        # Do something with the parameter
        result = f"Processed: {param}"
        return [{"type": "text", "text": result}]
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
```

## Design Patterns & Best Practices

### 1. Dependency Injection

The system uses FastAPI's dependency injection to manage services:

```python
#app/api/v1/endpoints/agent.py
from fastapi import Depends
from app.services.agent_service import AgentService

router = APIRouter()

@router.post("/completion")
async def completion(
    request: ChatCompletionRequest,
    service: AgentService = Depends()  # Automatic injection
):
    return await service.completion(request)
```

### 2. Resource Management with Async Context Managers

```python
#app/services/mcp_manager.py
class MCPManager:
    async def __aenter__(self):
        # Initialize connections to all MCP servers
        for server_name, server_config in self.mcp_servers.items():
            connection = await self._connect_to_server(server_config)
            self.connections[server_name] = connection
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Cleanly close all connections
        for server_name, connection in self.connections.items():
            await connection.close()
        self.connections = {}
```

### 3. Configuration Management with Pydantic Settings

```python
#app/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # OpenAI configuration
    openai_api_key: str
    openai_model: str = "gpt-4"
    openai_base_url: Optional[str] = None
    
    # Chassis configuration
    chassis_api_key: Optional[str] = None
    max_agent_iterations: int = 5
    
    # MCP configuration
    mcp_config_path: str = "mcp_config.json"
    
    # Optional Persistence
    redis_url: Optional[str] = None
    database_url: Optional[str] = None
    enable_persistence: bool = False
    
    # Optional Authentication
    enable_user_auth: bool = False
    jwt_secret_key: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    
    model_config = SettingsConfigDict(env_file=".env")
```

### 4. Error Handling Strategy

```python
#app/services/agent_service.py
async def completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
    try:
        # Main logic here
        pass
    except OpenAIError as e:
        logger.error(f"OpenAI API error: {e}")
        raise HTTPException(status_code=500, detail="LLM service unavailable")
    except MCPCallingError as e:
        logger.error(f"MCP tool calling error: {e}")
        raise HTTPException(status_code=500, detail="Tool service unavailable")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
```

## Extending the System

### 1. Adding New Tool Protocols

To support a new tool protocol beyond MCP and local Python functions:

1. Create a new adapter in `app/services/tool_translator.py`:
```python
class ToolTranslator:
    def translate_custom_protocol(self, tool) -> OpenAIFunction:
        # Implementation for the new protocol
        pass
```

2. Update `AgentService` to handle the new protocol:
```python
async def get_tools(self, allowed_tools: List[str] = None) -> List[OpenAIFunction]:
    tools = []
    
    # Local tools
    for name, func in self.local_registry.get_tools().items():
        if not allowed_tools or name in allowed_tools:
            tools.append(self.tool_translator.translate_python_function(func))
    
    # MCP tools
    async with self.mcp_manager as mcp:
        for server_name, connection in mcp.connections.items():
            # Get tools from this server
            # Filter by allowed_tools
            # Convert with translate_mcp_tool
            pass
    
    # Custom protocol tools
    for tool in self.get_custom_tools():
        if not allowed_tools or tool.name in allowed_tools:
            tools.append(self.tool_translator.translate_custom_protocol(tool))
    
    return tools
```

### 2. Implementing Agent State Persistence

To implement a different persistence mechanism:

1. Create a new persistence service:
```python
# app/services/custom_persistence_service.py
class CustomPersistenceService:
    async def save_conversation(self, session_id: str, conversation: List[dict]):
        # Save to your custom storage
        pass
        
    async def load_conversation(self, session_id: str) -> List[dict]:
        # Load from your custom storage
        return []
```

2. Update the AgentService to use it:
```python
# app/services/agent_service.py
class AgentService:
    def __init__(
        self,
        openai_client: AsyncOpenAI = Depends(),
        mcp_manager: MCPManager = Depends(),
        local_registry: LocalToolRegistry = Depends(),
        tool_translator: ToolTranslator = Depends(),
        persistence_service: CustomPersistenceService = Depends()  # New dependency
    ):
        self.persistence_service = persistence_service
```

3. Update the completion method to use the new persistence:
```python
async def completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
    # Load conversation if session_id provided
    if request.session_id and self.persistence_service:
        conversation = await self.persistence_service.load_conversation(request.session_id)
        # Use loaded conversation
```

### 3. Adding Streaming Protocol Support

To add support for a different streaming protocol beyond Server-Sent Events:

1. Create a new streaming handler:
```python
# app/streaming/custom_streaming.py
class CustomStreamingHandler:
    def __init__(self, response):
        self.response = response
        
    async def send_token(self, token: str):
        # Send token using your custom protocol
        pass
        
    async def close(self):
        # Close the stream
        pass
```

2. Update the agent endpoint:
```python
# app/api/v1/endpoints/agent.py
@router.post("/completion")
async def completion(
    request: ChatCompletionRequest,
    service: AgentService = Depends()
):
    if request.stream:
        # Determine streaming protocol from request or config
        if request.stream_protocol == "sse":
            return StreamingResponse(
                service.streaming_completion(request),
                media_type="text/event-stream"
            )
        elif request.stream_protocol == "custom":
            handler = CustomStreamingHandler(response)
            return StreamingResponse(
                service.custom_streaming_completion(request, handler),
                media_type="your-custom-media-type"
            )
    else:
        return await service.completion(request)
```

## Troubleshooting

### Common Issues

1. **MCP Connection Failures**
   - Verify the MCP server is installed and accessible
   - Check the command/executable path in the MCP configuration
   - For stdio servers, ensure all dependencies are installed
   - For SSE servers, verify the URL is accessible and auth is correct

2. **Tool Execution Errors**
   - Check that required environment variables are set
   - Verify that API keys have proper permissions
   - Review tool-specific error messages in logs

3. **Authentication Issues**
   - Ensure API key is correctly set in environment or request headers
   - For JWT auth, verify the secret key is consistent
   - Check that token expiration times are reasonable

4. **Performance Issues**
   - Profile agent execution time to identify bottlenecks
   - Consider limiting agent iterations with `max_iterations`
   - Optimize tool functions for faster execution

### Debugging Tools

1. **Use the Interactive Client**:
```bash
# Run the interactive client for debugging
uv run python scripts/client_test.py --stream
```

2. **Enable Debug Logging**:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

3. **Inspect Agent State**:
```python
# In your agent service, add debug logging
logger.debug(f"Available tools: {[tool['name'] for tool in tools]}")
logger.debug(f"Model response: {response}")
logger.debug(f"Tool calls: {response.choices[0].message.tool_calls}")
```

4. **Test MCP Connections Separately**:
```bash
# Test MCP server directly
npx @modelcontextprotocol/server-filesystem /path/to/dir
```

Remember that this chassis is designed to be flexible and extensible. When building upon it, maintain the clean separation of concerns and async patterns that make it robust and scalable.