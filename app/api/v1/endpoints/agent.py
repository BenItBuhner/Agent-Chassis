"""
Agent API endpoints for running LLM agent loops.

Supports two operational modes:
1. Client-side: Full message history in request (backward compatible)
2. Server-side: Session-based persistence with session_id

Authentication is optional based on CHASSIS_API_KEY configuration.
Includes ownership-based access control (OSP-12) for server-side sessions.
"""

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.security import UserContext, get_current_user
from app.schemas.agent import (
    AccessUpdateRequest,
    AccessUpdateResponse,
    CompletionRequest,
    CompletionResponse,
    SessionInfo,
)
from app.services.agent_service import AgentService
from app.services.session_manager import session_manager

router = APIRouter()


def get_openai_client():
    """Dependency to get configured OpenAI client."""
    if not settings.OPENAI_API_KEY:
        return None
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)


@router.post("/completion")
async def agent_completion(
    request: CompletionRequest,
    client: AsyncOpenAI = Depends(get_openai_client),
    user_ctx: UserContext = Depends(get_current_user),
):
    """
    Run the agent loop with tool calling capabilities.

    Supports two modes:

    **Client-side mode** (backward compatible):
    ```json
    {
        "messages": [{"role": "user", "content": "Hello!"}],
        "model": "kimi-k2-thinking"
    }
    ```

    **Server-side mode** (with persistence):
    ```json
    {
        "message": "Hello!",
        "model": "kimi-k2-thinking"
    }
    ```
    Response includes `session_id` for continuation:
    ```json
    {
        "session_id": "abc123",
        "message": "Continue the conversation"
    }
    ```

    **Access Control** (when authentication enabled):
    - New sessions are owned by the creator
    - Only owner can access by default
    - Use PATCH /session/{session_id}/access to share

    If `stream=True`, returns a text/event-stream with JSON chunks.
    Otherwise, returns a JSON CompletionResponse.
    """
    if not client:
        raise HTTPException(status_code=503, detail="OpenAI API Key not configured")

    service = AgentService(client)

    if request.stream:
        return StreamingResponse(
            service.run_agent_stream(request, user_ctx=user_ctx),
            media_type="text/event-stream",
        )

    result_message, session_id = await service.run_agent(request, user_ctx=user_ctx)
    return CompletionResponse(
        role=result_message.role,
        content=result_message.content,
        tool_calls=result_message.tool_calls,
        session_id=session_id,
    )


@router.get("/session/{session_id}")
async def get_session(
    session_id: str = Path(..., description="The session ID to retrieve"),
    user_ctx: UserContext = Depends(get_current_user),
) -> SessionInfo:
    """
    Get information about a session.

    Returns session metadata and message count.
    Access control settings are only included for the session owner.

    **Access Control**:
    - Returns 403 if user doesn't have access to the session
    - Returns 404 if session doesn't exist
    """
    session_info = await session_manager.get_session_info(session_id, user_ctx)

    if not session_info:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return SessionInfo(**session_info)


@router.patch("/session/{session_id}/access")
async def update_session_access(
    request: AccessUpdateRequest,
    session_id: str = Path(..., description="The session ID to update"),
    user_ctx: UserContext = Depends(get_current_user),
) -> AccessUpdateResponse:
    """
    Update access control settings for a session.

    **Only the session owner can modify access settings.**

    Options:
    - `is_public`: Set to true to allow anyone to access
    - `whitelist`: Replace the entire whitelist with new user IDs
    - `blacklist`: Replace the entire blacklist with new user IDs
    - `add_to_whitelist`: Add user IDs to the whitelist
    - `remove_from_whitelist`: Remove user IDs from the whitelist
    - `add_to_blacklist`: Add user IDs to the blacklist
    - `remove_from_blacklist`: Remove user IDs from the blacklist

    **Access Priority** (highest to lowest):
    1. Blacklist (always denied)
    2. Owner (always allowed)
    3. Public flag (if true, allows all except blacklisted)
    4. Whitelist (explicitly allowed)
    5. Default: Denied

    **Examples**:

    Make session public:
    ```json
    {"is_public": true}
    ```

    Share with specific users:
    ```json
    {"add_to_whitelist": ["user-123", "user-456"]}
    ```

    Block specific users (even if public):
    ```json
    {"add_to_blacklist": ["spam-user"]}
    ```
    """
    if not user_ctx.auth_enabled:
        raise HTTPException(
            status_code=400,
            detail="Access control requires authentication to be enabled (CHASSIS_API_KEY)",
        )

    result = await session_manager.update_access_settings(
        session_id=session_id,
        user_ctx=user_ctx,
        is_public=request.is_public,
        whitelist=request.whitelist,
        blacklist=request.blacklist,
        add_to_whitelist=request.add_to_whitelist,
        remove_from_whitelist=request.remove_from_whitelist,
        add_to_blacklist=request.add_to_blacklist,
        remove_from_blacklist=request.remove_from_blacklist,
    )

    return AccessUpdateResponse(**result)


@router.delete("/session/{session_id}")
async def delete_session(
    session_id: str = Path(..., description="The session ID to delete"),
    user_ctx: UserContext = Depends(get_current_user),
) -> dict:
    """
    Delete a session.

    **Only the session owner can delete a session.**

    Returns 204 No Content on success.
    """
    deleted = await session_manager.delete_session(session_id, user_ctx)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return {"status": "deleted", "session_id": session_id}
