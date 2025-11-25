from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.security import get_api_key
from app.schemas.agent import CompletionRequest, CompletionResponse
from app.services.agent_service import AgentService

router = APIRouter()


def get_openai_client():
    if not settings.OPENAI_API_KEY:
        return None
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)


@router.post("/completion", dependencies=[Depends(get_api_key)])
async def agent_completion(request: CompletionRequest, client: AsyncOpenAI = Depends(get_openai_client)):
    """
    Run the agent loop.

    If `stream=True` in the request, returns a text/event-stream.
    Otherwise, returns a JSON CompletionResponse.
    """
    if not client:
        raise HTTPException(status_code=503, detail="OpenAI API Key not configured")

    service = AgentService(client)

    if request.stream:
        return StreamingResponse(service.run_agent_stream(request), media_type="text/event-stream")

    result_message = await service.run_agent(request)
    return CompletionResponse(
        role=result_message.role, content=result_message.content, tool_calls=result_message.tool_calls
    )
