import argparse
import asyncio
import json
import os
import sys

from openai import AsyncOpenAI

from app.core.config import settings
from app.schemas.agent import ChatMessage, CompletionRequest
from app.services.agent_service import AgentService
from app.services.mcp_manager import mcp_manager

# Ensure we can import app
sys.path.append(os.getcwd())


async def run_streaming_test(service: AgentService, prompt: str, tools: list[str]):
    print("\n[Stream] Sending Streaming Request...")
    print(f"Prompt: {prompt}")

    request = CompletionRequest(messages=[ChatMessage(role="user", content=prompt)], allowed_tools=tools, stream=True)

    print("\n--- Stream Start ---")
    try:
        async for chunk_str in service.run_agent_stream(request):
            chunk = json.loads(chunk_str)
            chunk_type = chunk.get("type")

            if chunk_type == "content":
                # Print content updates as they come
                print(chunk["content"], end="", flush=True)

            elif chunk_type == "tool_result":
                print(f"\n\n[Tool Result] {chunk['tool']}: {chunk['result']}")

            elif chunk_type == "status":
                print(f"\n[Status] {chunk['content']}")

            elif chunk_type == "error":
                print(f"\n[Error] {chunk['content']}")

            elif chunk_type == "finish":
                print("\n\n[Finished]")

            elif chunk_type == "reasoning":
                print(f"\n[Reasoning] {chunk['content']}", end="", flush=True)

            else:
                print(f"\n[Unknown Chunk] {chunk}")

    except Exception as e:
        print(f"\n\nError during streaming: {e}")


async def run_blocking_test(service: AgentService, prompt: str, tools: list[str]):
    print("\n[Block] Sending Blocking Request...")
    print(f"Prompt: {prompt}")

    request = CompletionRequest(messages=[ChatMessage(role="user", content=prompt)], allowed_tools=tools)

    try:
        response = await service.run_agent(request)
        print("\n--- Agent Response ---")
        print(f"Role: {response.role}")
        print(f"Content: {response.content}")
        if response.tool_calls:
            print(f"Tool Calls: {response.tool_calls}")
    except Exception as e:
        print(f"\nError during inference: {e}")


async def main():
    parser = argparse.ArgumentParser(description="Agent Chassis Smoke Test")
    parser.add_argument("--stream", action="store_true", help="Enable streaming mode")
    parser.add_argument("--mcp", action="store_true", help="Test MCP filesystem tool instead of local calc")
    parser.add_argument("--prompt", type=str, help="Custom prompt to override default")
    args = parser.parse_args()

    print("--- Starting Unified Smoke Test ---")
    print(f"Model: {settings.OPENAI_MODEL}")
    print(f"Base URL: {settings.OPENAI_BASE_URL}")

    # 1. Initialize MCP
    print("\n[1] Loading MCP Servers...")
    try:
        await mcp_manager.load_servers()
    except Exception as e:
        print(f"Error loading MCP servers: {e}")
        return

    # 2. Initialize OpenAI Client
    print("\n[2] Initializing OpenAI Client...")
    if not settings.OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not found.")
        return

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    service = AgentService(client)

    # 3. Determine Test Logic
    if args.mcp:
        prompt = args.prompt or "Create a memory entity named 'TestEntity'."
        tools = ["create_entities"]
        print("\n[Test Mode] MCP Memory Tool")
    else:
        prompt = args.prompt or "Calculate 5 * 5 and then tell me the result."
        tools = ["calculate", "get_server_time"]
        print("\n[Test Mode] Local Tools (Calculator/Time)")

    # 4. Execute
    if args.stream:
        await run_streaming_test(service, prompt, tools)
    else:
        await run_blocking_test(service, prompt, tools)

    # Cleanup
    print("\n[Cleanup] Shutting down...")
    await mcp_manager.cleanup()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
