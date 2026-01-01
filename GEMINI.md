# Agent Chassis - AI Assistant Context

## Project Overview

Agent Chassis is a modular, asynchronous foundation for building AI agents with FastAPI, OpenAI, and MCP (Model Context Protocol). This document provides detailed technical context for AI assistants working on this codebase, with specific focus on implementation patterns and architectural decisions.

## Architecture Deep Dive

### Layered Architecture Pattern

The project follows a clean layered architecture with clear separation of concerns:

1. **API Layer** (`app/api/`): FastAPI routes and request/response handling
2. **Schema Layer** (`app/schemas/`): Pydantic models for request/response validation
3. **Service Layer** (`app/services/`): Business logic and core functionality
4. **Core Layer** (`app/core/`): Configuration, security, and application settings

### Asynchronous Design Principles

The entire application is built on async/await patterns for non-blocking operation:

```python
# Pattern example from agent_service.py
async def completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
    async with self.mcp_manager:
        tools = await self.get_tools(request.allowed_tools)
        response = await self.openai_client.chat.completions.create(...)
        return response
```

### Dependency Injection

The project uses FastAPI's dependency injection system:

```python
# Example from agent endpoint
@router.post("/completion")
async def completion(
    request: ChatCompletionRequest,
    service: AgentService = Depends()  # Automatic instantiation
):
    return await service.completion(request)
```

## Core Components Analysis

### 1. Agent Service (`app/services/agent_service.py`)

The central orchestrator implementing a multi-turn plan-act-observe loop.

#### Implementation Pattern

```python
class AgentService(BaseModel):
    max_iterations: int = 5  # Safeguard against infinite loops
    
    async def completion(self, request: ChatCompletionRequest):
        # Set up context with available tools
        tools = await self.get_tools(request.allowed_tools)
        
        # Execute the multi-turn loop
        for iteration in range(self.max_iterations):
            # Generate response with possible tool calls
            response = await openai_client.chat.completions.create(...)
            
            # Check for tool calls
            tool_calls = response.choices[0].message.tool_calls
            
            if not tool_calls:
                # No more tools, return final response
                break
                
            # Execute tools and continue loop
            tool_results = await self.execute_tools(tool_calls)
            
            # Add results to conversation for next iteration
            messages.extend(tool_results)
        
        return response
```

#### Streaming Implementation

```python
async def streaming_completion(self, request: ChatCompletionRequest):
    async def event_generator():
        # Create a streaming response from OpenAI
        stream = await openai_client.chat.completions.create(..., stream=True)
        
        async for chunk in stream:
            # Handle different chunk types
            if chunk.choices[0].delta.tool_calls:
                # Tool call in progress
                yield self.format_tool_call_event(chunk)
            elif chunk.choices[0].delta.content:
                # Content token
                yield self.format_content_event(chunk)
            elif chunk.choices[0].finish_reason:
                # Stream complete
                yield self.format_finish_event(chunk)
                
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 2. MCP Manager (`app/services/mcp_manager.py`)

Manages the lifecycle of connections to Model Context Protocol servers.

#### Resource Management Pattern

```python
class MCPManager:
    def __init__(self, config_path: str = "mcp_config.json"):
        self.config = self._load_config(config_path)
        self.connections = {}
        self._stack = AsyncExitStack()
    
    async def __aenter__(self):
        # Establish all connections using AsyncExitStack for proper cleanup
        for name, server_config in self.config.items():
            if server_config.protocol == "stdio":
                # Subprocess-based connection
                transport = await self._create_stdio_transport(server_config)
            elif server_config.protocol == "sse":
                # HTTP-based connection
                transport = await self._create_sse_transport(server_config)
                
            # Register with exit stack for automatic cleanup
            connection = self._stack.enter_context(transport)
            self.connections[name] = connection
            
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Cleanly close all connections
        await self._stack.aclose()
        self.connections = {}
```

#### Configuration Structure

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/files"],
      "protocol": "stdio"
    },
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"],
      "protocol": "stdio"
    },
    "web-search": {
      "url": "https://api.example.com/mcp/stream",
      "protocol": "sse",
      "headers": {
        "Authorization": "Bearer ${API_TOKEN}"
      }
    }
  }
}
```

### 3. Local Tool Registry (`app/services/local_tools.py`)

Implements a decorator registry pattern for local Python functions.

#### Registration Pattern

```python
class LocalToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
    
    def register(self, func: Callable) -> Callable:
        # Store the function and return it unchanged
        self._tools[func.__name__] = func
        return func
    
    def get_tools(self) -> Dict[str, Callable]:
        return self._tools.copy()

# Global instance
local_registry = LocalToolRegistry()
```

#### Example Implementation

```python
@local_registry.register
def calculate(operation: str, a: float, b: float) -> str:
    """
    Performs basic arithmetic operations.
    
    Args:
        operation: One of 'add', 'subtract', 'multiply', 'divide'
        a: First number
        b: Second number
        
    Returns:
        Result as a string
    """
    try:
        if operation == "add":
            return str(a + b)
        elif operation == "subtract":
            return str(a - b)
        elif operation == "multiply":
            return str(a * b)
        elif operation == "divide":
            if b == 0:
                return "Error: Division by zero"
            return str(a / b)
        else:
            return f"Error: Unknown operation '{operation}'"
    except Exception as e:
        return f"Error: {str(e)}"
```

### 4. Tool Translator (`app/services/tool_translator.py`)

Universal adapter for converting different tool formats to OpenAI compatible schemas.

#### Type Mapping Implementation

```python
class ToolTranslator:
    # Mapping from Python types to JSON Schema types
    TYPE_MAP = {
        int: "integer",
        float: "number",
        str: "string",
        bool: "boolean",
        dict: "object",
        list: "array",
    }
    
    def translate_python_function(self, func: Callable) -> Dict[str, Any]:
        # Extract function signature and docstring
        sig = inspect.signature(func)
        doc = inspect.getdoc(func) or ""
        
        # Build properties from parameters
        properties = {}
        required = []
        
        for name, param in sig.parameters.items():
            param_type = self._get_json_type(param.annotation)
            properties[name] = {"type": param_type}
            
            if param.default == inspect.Parameter.empty:
                required.append(name)
        
        # Build OpenAI function schema
        return {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": doc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }
```

### 5. Security & Configuration (`app/core/`)

#### Configuration Management with Pydantic Settings

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # OpenAI configuration
    openai_api_key: str
    openai_model: str = "gpt-4"
    openai_base_url: Optional[str] = None
    
    # Chassis settings
    chassis_api_key: Optional[str] = None
    max_agent_iterations: int = 5
    
    # MCP configuration
    mcp_config_path: str = "mcp_config.json"
    
    # Optional persistence
    redis_url: Optional[str] = None
    database_url: Optional[str] = None
    enable_persistence: bool = False
    
    # Optional user authentication
    enable_user_auth: bool = False
    jwt_secret_key: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    
    model_config = SettingsConfigDict(env_file=".env")
```

#### Authentication Implementation

```python
# API Key middleware
class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip auth if no API key is configured
        if not settings.chassis_api_key:
            return await call_next(request)
        
        # Check for API key in headers
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != settings.chassis_api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        return await call_next(request)

# JWT authentication (optional)
class JWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip auth for certain paths
        if not settings.enable_user_auth or request.url.path in ["/docs", "/openapi.json"]:
            return await call_next(request)
        
        # Check for valid JWT
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing valid JWT")
        
        token = auth_header.split(" ")[1]
        payload = verify_jwt_token(token)
        
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid JWT")
        
        # Store user info in request state
        request.state.user = payload
        
        return await call_next(request)
```

## Development Patterns

### Error Handling Strategy

The application uses a layered error handling approach:

1. **Agent Level**: Handles LLM and tool execution errors
2. **Service Level**: Handles business logic errors
3. **API Level**: Converts service errors to HTTP responses

```python
async def completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
    try:
        # Main logic
        return await self._process_completion(request)
    except OpenAIError as e:
        logger.error(f"OpenAI API error: {e}")
        # Retry logic or fallback
        raise ServiceError("LLM service unavailable")
    except MCPCallingError as e:
        logger.error(f"MCP error: {e}")
        # Graceful degradation
        raise ServiceError("Tool service unavailable")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise ServiceError("Internal server error")
```

### Resource Management Pattern

Using AsyncExitStack for proper resource cleanup:

```python
async def with_resources(self):
    async with AsyncExitStack() as stack:
        # Enter multiple contexts
        db_connection = await stack.enter_async_context(create_db_connection())
        api_client = await stack.enter_async_context(create_api_client())
        
        # Use resources
        result = await self.process_with_resources(db_connection, api_client)
        
        # All resources are automatically cleaned up when exiting
        return result
```

### Plugin Architecture

The system uses a plugin pattern for extensibility:

```python
class ToolPlugin(ABC):
    @abstractmethod
    async def initialize(self, config: Dict[str, Any]) -> None:
        pass
    
    @abstractmethod
    async def get_tools(self) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        pass

# Register plugins
def register_plugin(name: str, plugin: ToolPlugin) -> None:
    self.plugins[name] = plugin
```

## Important Implementation Details

### Agent Loop Safety

The agent loop has safeguards against infinite execution:

```python
async def completion(self, request: ChatCompletionRequest):
    max_iterations = request.max_iterations or settings.max_agent_iterations
    
    for iteration in range(max_iterations):
        # Process one iteration
        
        if self.should_stop(response):
            break  # Early exit conditions
    
    return response
```

### Tool Execution Isolation

Tools are executed with appropriate isolation:

```python
async def execute_tool(self, tool_call: ChatCompletionMessageToolCall) -> Dict[str, Any]:
    tool_name = tool_call.function.name
    tool_args = json.loads(tool_call.function.arguments)
    
    try:
        # Check if tool is local
        if tool_name in self._local_tools:
            # Call local function
            result = await self._call_local_tool(tool_name, tool_args)
        else:
            # Call through MCP
            result = await self._call_mcp_tool(tool_name, tool_args)
            
        return {
            "tool_call_id": tool_call.id,
            "output": result
        }
    except Exception as e:
        # Always return success to agent to prevent breaking the loop
        return {
            "tool_call_id": tool_call.id,
            "output": f"Error executing tool {tool_name}: {str(e)}"
        }
```

### Streaming Event Format

The SSE streaming follows a specific format for different event types:

```python
def format_stream_event(self, event_type: str, data: Dict[str, Any]) -> str:
    """Format data as Server-Sent Event."""
    if event_type == "content":
        return f"data: {json.dumps({'type': 'content', 'delta': data['delta']})}\n\n"
    elif event_type == "tool_call":
        return f"data: {json.dumps({'type': 'tool_call', **data})}\n\n"
    elif event_type == "tool_result":
        return f"data: {json.dumps({'type': 'tool_result', **data})}\n\n"
    elif event_type == "complete":
        return f"data: {json.dumps({'type': 'complete', **data})}\n\n"
    elif event_type == "error":
        return f"data: {json.dumps({'type': 'error', 'message': data['message']})}\n\n"

def format_done_event(self) -> str:
    """Signal end of stream."""
    return "data: [DONE]\n\n"
```

## Testing Patterns

### Async Testing with Pytest

```python
@pytest.mark.asyncio
async def test_agent_completion_with_tool():
    # Setup test
    mock_openai = AsyncMock()
    mock_openai.chat.completions.create.return_value = mock_response
    
    # Test agent service
    agent_service = AgentService(openai_client=mock_openai)
    
    # Execute test
    request = ChatCompletionRequest(
        messages=[{"role": "user", "content": "Calculate 5+3"}],
        allowed_tools=["calculate"]
    )
    response = await agent_service.completion(request)
    
    # Verify results
    assert "8" in response.choices[0].message.content
```

### Integration Testing

```python
async def test_full_agent_flow():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/agent/completion",
            json={
                "messages": [{"role": "user", "content": "What time is it?"}],
                "model": "gpt-4",
                "allowed_tools": ["get_server_time"]
            },
            headers={"X-API-Key": "test-key"}
        )
    assert response.status_code == 200
    assert "response" in response.json()
```

## Key Considerations for Modifications

### Adding New Tool Types

When adding support for new tool types beyond MCP and local functions:

1. Update `ToolTranslator` with a new translation method
2. Extend `AgentService.get_tools()` to handle the new tool type
3. Add appropriate error handling for the new tool type
4. Update tests to cover the new tool type

### Modifying the Agent Loop

When changing the agent execution loop:

1. Maintain the maximum iteration safeguard
2. Preserve error handling that prevents loop termination
3. Ensure tool result formatting is consistent
4. Consider impact on streaming responses

### Extending Configuration

When adding new configuration options:

1. Add to the `Settings` class in `app/core/config.py`
2. Update `.env.example` with the new options
3. Add appropriate validation if needed
4. Update documentation

### Adding New Endpoints

When creating new API endpoints:

1. Follow the existing patterns in `app/api/v1/endpoints/`
2. Use FastAPI dependency injection for services
3. Implement proper request/response models in `app/schemas/`
4. Add appropriate error handling
5. Include OpenAPI documentation via FastAPI decorators