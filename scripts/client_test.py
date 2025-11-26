"""
Agent Chassis Interactive Terminal Client.

Supports:
- JWT authentication (login, register, token refresh)
- Server-side persistence (session_id mode)
- Client-side mode (backward compatible)
- API key authentication (legacy)
- Streaming and blocking responses
"""

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ANSI Colors for better UX
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
RESET = "\033[0m"
BOLD = "\033[1m"


class AuthClient:
    """Handles authentication operations."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_expires_at: datetime | None = None

    async def register(self, email: str, password: str, display_name: str | None = None) -> dict:
        """Register a new user account."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/v1/auth/register",
                json={"email": email, "password": password, "display_name": display_name},
            )
            response.raise_for_status()
            return response.json()

    async def verify_email(self, email: str, code: str) -> dict:
        """Verify email address with verification code."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/v1/auth/verify-email",
                json={"email": email, "code": code},
            )
            response.raise_for_status()
            return response.json()

    async def login(self, email: str, password: str) -> dict:
        """Login and store tokens."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/v1/auth/login",
                json={"email": email, "password": password},
            )
            response.raise_for_status()
            data = response.json()
            self.access_token = data["access_token"]
            self.refresh_token = data["refresh_token"]
            expires_in = data.get("expires_in", 1800)  # Default 30 minutes
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
            return data

    async def refresh_access_token(self) -> bool:
        """Refresh the access token using refresh token."""
        if not self.refresh_token:
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/auth/refresh",
                    json={"refresh_token": self.refresh_token},
                )
                response.raise_for_status()
                data = response.json()
                self.access_token = data["access_token"]
                expires_in = data.get("expires_in", 1800)
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                return True
        except Exception:
            return False

    def get_auth_headers(self) -> dict:
        """Get authentication headers (JWT Bearer token)."""
        if self.access_token:
            # Check if token is expired or about to expire (within 1 minute)
            if self.token_expires_at and datetime.now() >= self.token_expires_at - timedelta(minutes=1):
                # Try to refresh (synchronous check, async refresh happens in background)
                asyncio.create_task(self.refresh_access_token())
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}

    async def get_user_info(self) -> dict | None:
        """Get current user information."""
        if not self.access_token:
            return None

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/auth/me",
                    headers=self.get_auth_headers(),
                )
                response.raise_for_status()
                return response.json()
        except Exception:
            return None


async def chat_loop(
    url: str,
    model: str,
    tools: list[str] | None,
    stream: bool,
    api_key: str | None,
    use_server_side: bool,
    auth_client: AuthClient | None = None,
):
    """Main chat loop for interacting with the agent."""
    print(f"{BOLD}--- Agent Chassis CLI Client ---{RESET}")
    print(f"Target: {CYAN}{url}{RESET}")
    print(f"Model:  {CYAN}{model}{RESET}")
    print(f"Mode:   {GREEN}{'Streaming' if stream else 'Blocking'}{RESET}")
    print(
        f"Persistence: {GREEN if use_server_side else YELLOW}{'Server-side (session_id)' if use_server_side else 'Client-side (messages)'}{RESET}"
    )
    print(f"Tools:  {YELLOW}{tools or 'All'}{RESET}")

    if auth_client and auth_client.access_token:
        user_info = await auth_client.get_user_info()
        if user_info:
            print(f"User:   {GREEN}{user_info.get('email', 'Unknown')}{RESET}")
        print(f"Auth:   {GREEN}JWT Token{RESET}")
    elif api_key:
        print(f"Auth:   {YELLOW}API Key{RESET}")
    else:
        print(f"Auth:   {RED}None (unauthenticated){RESET}")

    print(f"\nType '{RED}exit{RESET}' or '{RED}quit{RESET}' to stop.")
    print(f"Type '{BLUE}/session{RESET}' to show current session ID.")
    print(f"Type '{BLUE}/info{RESET}' to show session info.\n")

    messages = []
    session_id: str | None = None
    endpoint = f"{url}/api/v1/agent/completion"
    headers = {}

    # Set authentication headers
    if auth_client and auth_client.access_token:
        headers.update(auth_client.get_auth_headers())
    elif api_key:
        headers["X-API-Key"] = api_key

    async with httpx.AsyncClient(timeout=600.0) as client:
        while True:
            try:
                user_input = input(f"{BOLD}You > {RESET}")
                if user_input.lower() in ["exit", "quit"]:
                    break
                elif user_input.lower() == "/session":
                    if session_id:
                        print(f"{CYAN}Session ID: {session_id}{RESET}\n")
                    else:
                        print(f"{YELLOW}No active session (using client-side mode){RESET}\n")
                    continue
                elif user_input.lower() == "/info":
                    if session_id:
                        try:
                            info_endpoint = f"{url}/api/v1/agent/session/{session_id}"
                            response = await client.get(info_endpoint, headers=headers)
                            if response.status_code == 200:
                                info = response.json()
                                print(f"{CYAN}Session Info:{RESET}")
                                print(f"  ID: {info.get('session_id')}")
                                print(f"  Messages: {info.get('message_count', 0)}")
                                print(f"  Created: {info.get('created_at')}")
                                print(f"  Updated: {info.get('updated_at')}")
                                if info.get("access_settings"):
                                    access = info["access_settings"]
                                    print(f"  Public: {access.get('is_public', False)}")
                                    print(f"  Owner: {access.get('owner_id', 'None')}")
                            else:
                                print(f"{RED}Failed to fetch session info: {response.text}{RESET}")
                        except Exception as e:
                            print(f"{RED}Error fetching session info: {e}{RESET}")
                    else:
                        print(f"{YELLOW}No active session{RESET}\n")
                    continue
            except EOFError:
                break

            # Prepare payload based on mode
            if use_server_side:
                # Server-side mode: use session_id or message
                if session_id:
                    payload = {"session_id": session_id, "message": user_input, "model": model, "stream": stream}
                else:
                    # First message in server-side mode
                    payload = {"message": user_input, "model": model, "stream": stream}
                if tools:
                    payload["allowed_tools"] = tools
            else:
                # Client-side mode: use messages array
                messages.append({"role": "user", "content": user_input})
                payload = {"messages": messages, "model": model, "stream": stream}
                if tools:
                    payload["allowed_tools"] = tools

            print(f"{BOLD}Agent > {RESET}", end="", flush=True)

            try:
                if stream:
                    # Handle Server-Sent Events (SSE)
                    async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                        if response.status_code != 200:
                            error_text = await response.aread()
                            print(f"{RED}Error {response.status_code}: {error_text.decode()}{RESET}")
                            continue

                        full_content = ""
                        async for line in response.aiter_lines():
                            if not line:
                                continue

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

                        # Extract session_id from response if present
                        if use_server_side:
                            # For streaming, session_id might be in a special chunk or we need to parse headers
                            # For now, we'll get it from the final response or make a separate call
                            pass

                        if not use_server_side:
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

                    # Extract session_id if present (server-side mode)
                    if "session_id" in data and data["session_id"]:
                        if not session_id:
                            session_id = data["session_id"]
                            print(f"\n{MAGENTA}[Session created: {session_id}]{RESET}")

                    if data.get("tool_calls"):
                        for tc in data["tool_calls"]:
                            print(f"{YELLOW}  [Used Tool: {tc['function']['name']}]{RESET}")

                    if not use_server_side:
                        messages.append({"role": "assistant", "content": content})

            except Exception as e:
                print(f"\n{RED}Client Error: {e}{RESET}")


async def interactive_auth(base_url: str) -> AuthClient | None:
    """Interactive authentication flow."""
    auth_client = AuthClient(base_url)

    print(f"\n{BOLD}--- Authentication ---{RESET}")
    print("1. Login (existing account)")
    print("2. Register (new account)")
    print("3. Skip authentication")
    choice = input(f"\n{BOLD}Choice (1-3): {RESET}").strip()

    if choice == "1":
        email = input(f"{BOLD}Email: {RESET}").strip()
        password = input(f"{BOLD}Password: {RESET}").strip()
        try:
            await auth_client.login(email, password)
            print(f"{GREEN}Login successful!{RESET}\n")
            return auth_client
        except httpx.HTTPStatusError as e:
            print(f"{RED}Login failed: {e.response.text}{RESET}\n")
            return None
        except Exception as e:
            print(f"{RED}Error: {e}{RESET}\n")
            return None

    elif choice == "2":
        email = input(f"{BOLD}Email: {RESET}").strip()
        password = input(f"{BOLD}Password (min 8 chars, must include letter and digit): {RESET}").strip()
        display_name = input(f"{BOLD}Display Name (optional): {RESET}").strip() or None

        try:
            await auth_client.register(email, password, display_name)
            print(f"{GREEN}Registration successful!{RESET}")
            print(f"{YELLOW}Verification email sent. Please check your inbox.{RESET}")
            verify_code = input(f"{BOLD}Enter verification code (or press Enter to skip): {RESET}").strip()

            if verify_code:
                try:
                    await auth_client.verify_email(email, verify_code)
                    print(f"{GREEN}Email verified!{RESET}")
                    # Auto-login after verification
                    await auth_client.login(email, password)
                    print(f"{GREEN}Logged in!{RESET}\n")
                    return auth_client
                except Exception as e:
                    print(f"{YELLOW}Verification failed: {e}{RESET}")
                    print(f"{YELLOW}You can verify later and login.{RESET}\n")
                    return None
            else:
                print(f"{YELLOW}You can verify your email later and login.{RESET}\n")
                return None
        except httpx.HTTPStatusError as e:
            print(f"{RED}Registration failed: {e.response.text}{RESET}\n")
            return None
        except Exception as e:
            print(f"{RED}Error: {e}{RESET}\n")
            return None

    else:
        print(f"{YELLOW}Skipping authentication.{RESET}\n")
        return None


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Agent Chassis Terminal Client")
    parser.add_argument("--url", default="http://localhost:8000", help="API Base URL")
    parser.add_argument("--model", default="kimi-k2-thinking", help="Model name")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming")
    parser.add_argument("--tools", nargs="+", help="List of allowed tools")
    parser.add_argument("--api-key", help="X-API-Key for authentication (legacy)")
    parser.add_argument("--server-side", action="store_true", help="Use server-side persistence (session_id)")
    parser.add_argument("--no-auth", action="store_true", help="Skip interactive authentication")

    args = parser.parse_args()

    api_key = args.api_key or os.getenv("CHASSIS_API_KEY")

    # Check if user auth is enabled (we'll try to use it unless --no-auth is set)
    auth_client = None
    if not args.no_auth:
        try:
            # Try interactive auth (will return None if skipped or failed)
            auth_client = asyncio.run(interactive_auth(args.url))
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Auth cancelled.{RESET}\n")
            auth_client = None

    try:
        asyncio.run(
            chat_loop(
                args.url,
                args.model,
                args.tools,
                not args.no_stream,
                api_key,
                args.server_side,
                auth_client,
            )
        )
    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()
