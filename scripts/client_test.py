import argparse
import asyncio
import json
import os

import httpx
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ANSI Colors for better UX
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"


async def chat_loop(url: str, model: str, tools: list[str] | None, stream: bool, api_key: str | None):
    print(f"{BOLD}--- Agent Chassis CLI Client ---{RESET}")
    print(f"Target: {CYAN}{url}{RESET}")
    print(f"Model:  {CYAN}{model}{RESET}")
    print(f"Mode:   {GREEN}{'Streaming' if stream else 'Blocking'}{RESET}")
    print(f"Tools:  {YELLOW}{tools or 'All'}{RESET}")
    if api_key:
        print(f"API Key: {GREEN}Provided{RESET}")
    print(f"Type '{RED}exit{RESET}' or '{RED}quit{RESET}' to stop.\n")

    messages = []
    endpoint = f"{url}/api/v1/agent/completion"
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    async with httpx.AsyncClient(timeout=600.0) as client:
        while True:
            try:
                user_input = input(f"{BOLD}You > {RESET}")
                if user_input.lower() in ["exit", "quit"]:
                    break
            except EOFError:
                break

            messages.append({"role": "user", "content": user_input})

            payload = {"messages": messages, "model": model, "stream": stream, "allowed_tools": tools}

            print(f"{BOLD}Agent > {RESET}", end="", flush=True)

            try:
                if stream:
                    # Handle Server-Sent Events (SSE)
                    async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                        if response.status_code != 200:
                            # We can't easily await response.read() here because we are in a stream context context manager
                            # that expects to be consumed via iterator.
                            # Best to just print status and maybe consume a bit if possible, or just break.
                            print(f"{RED}Error {response.status_code}{RESET}")
                            continue

                        full_content = ""
                        async for line in response.aiter_lines():
                            if not line:
                                continue

                            # DEBUG: See what we are getting
                            # print(f"DEBUG RAW: {line}")

                            # Handle "data: " prefix if present (standard SSE)
                            if line.startswith("data: "):
                                line = line[6:]

                            try:
                                chunk = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            chunk_type = chunk.get("type")

                            if chunk_type == "content":
                                content = chunk.get("content", "")
                                print(content, end="", flush=True)
                                full_content += content

                            elif chunk_type == "tool_result":
                                tool_name = chunk.get("tool")
                                result = chunk.get("result")
                                print(
                                    f"\n{YELLOW}  [Tool: {tool_name}] -> {str(result)[:100]}...{RESET}",
                                    end="",
                                    flush=True,
                                )

                            elif chunk_type == "error":
                                print(f"\n{RED}Error: {chunk.get('content')}{RESET}")

                            elif chunk_type == "reasoning":
                                pass

                        print()  # Newline
                        messages.append({"role": "assistant", "content": full_content})

                else:
                    # Handle Blocking
                    response = await client.post(endpoint, json=payload, headers=headers)
                    if response.status_code != 200:
                        print(f"{RED}Error {response.status_code}: {response.text}{RESET}")
                        continue

                    data = response.json()
                    content = data.get("content", "")
                    print(content)
                    messages.append({"role": "assistant", "content": content})

                    if data.get("tool_calls"):
                        for tc in data["tool_calls"]:
                            print(f"{YELLOW}  [Used Tool: {tc['function']['name']}]{RESET}")

            except Exception as e:
                print(f"\n{RED}Client Error: {e}{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Agent Chassis Terminal Client")
    parser.add_argument("--url", default="http://localhost:8000", help="API Base URL")
    parser.add_argument("--model", default="kimi-k2-thinking", help="Model name")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming")
    parser.add_argument("--tools", nargs="+", help="List of allowed tools")
    parser.add_argument("--api-key", help="X-API-Key for authentication")

    args = parser.parse_args()

    api_key = args.api_key or os.getenv("CHASSIS_API_KEY")

    try:
        asyncio.run(chat_loop(args.url, args.model, args.tools, not args.no_stream, api_key))
    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()
