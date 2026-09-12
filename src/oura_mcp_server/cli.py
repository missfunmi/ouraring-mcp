"""CLI commands for Oura Ring MCP Server."""

import getpass
import sys

from oura_mcp_server.auth import (
    clear_credential,
    get_credential,
    get_storage_backend,
    is_keyring_available,
    store_credential,
)


def _validate_token(token: str) -> tuple[bool, str]:
    """Hit the Oura API to confirm the token. Returns (valid, email_or_error)."""
    import httpx

    try:
        resp = httpx.get(
            "https://api.ouraring.com/v2/usercollection/personal_info",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            email = resp.json().get("data", {}).get("email", "unknown")
            return True, email
        if resp.status_code == 401:
            return False, "Token rejected (401). Check it was copied correctly."
        return False, f"Unexpected status {resp.status_code}."
    except Exception as e:
        return False, f"Network error: {e}"


def cmd_auth() -> int:
    print("Oura Ring MCP Authentication")
    print("=" * 40)
    print()

    if not is_keyring_available():
        print("Warning: No system keyring available.")
        print("Token will be stored in an encrypted file at ~/.config/ouraring-mcp/")
        print()

    existing = get_credential()
    if existing.success and existing.token:
        print("Existing token found. Validating...")
        valid, info = _validate_token(existing.token)
        if valid:
            print(f"Already authenticated: {info}")
            print()
            response = input("Re-authenticate? [y/N]: ").strip().lower()
            if response != "y":
                return 0

    print()
    print("Get your Personal Access Token from:")
    print("  https://cloud.ouraring.com/personal-access-tokens")
    print()

    try:
        token = getpass.getpass("Paste token (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 1

    if not token:
        print("Error: No token provided.")
        return 1

    print()
    print("Validating...")
    valid, info = _validate_token(token)
    if not valid:
        print(f"Error: {info}")
        return 1

    result = store_credential(token)
    if not result.success:
        print(f"Error storing token: {result.message}")
        return 1

    print()
    print("Authentication successful!")
    print(f"  Account: {info}")
    print(f"  Storage: {get_storage_backend()}")
    print()
    print("Run 'oura-mcp serve' to start the MCP server.")
    return 0


def cmd_auth_status() -> int:
    cred = get_credential()
    if not cred.success or not cred.token:
        print("Not authenticated. Run 'oura-mcp auth' to authenticate.")
        return 1

    print("Checking token...")
    valid, info = _validate_token(cred.token)
    if valid:
        print(f"Authenticated: {info}")
        print(f"Storage: {get_storage_backend()}")
        return 0

    print(f"Token invalid: {info}")
    print("Run 'oura-mcp auth' to re-authenticate.")
    return 1


def cmd_auth_clear() -> int:
    result = clear_credential()
    print("Credentials cleared." if result.success else f"Note: {result.message}")
    return 0


def cmd_serve() -> int:
    from oura_mcp_server.server import main
    main()
    return 0


def cmd_config() -> int:
    import json
    import shutil
    from pathlib import Path

    path = shutil.which("oura-mcp") or str(Path(sys.executable).parent / "oura-mcp")
    config = {"ouraring": {"command": path, "args": ["serve"]}}
    print('Add this inside "mcpServers": {} in your Claude Desktop config:')
    print()
    print(json.dumps(config, indent=2))
    return 0


def cmd_help() -> int:
    print("Oura Ring MCP Server")
    print()
    print("Usage: oura-mcp <command>")
    print()
    print("Commands:")
    print("  auth          Store your Oura Personal Access Token securely")
    print("  auth-status   Check if the stored token is valid")
    print("  auth-clear    Remove the stored token")
    print("  config        Print Claude Desktop config snippet")
    print("  serve         Start the MCP server")
    print()
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        return cmd_help()

    commands: dict[str, object] = {
        "auth": cmd_auth,
        "auth-status": cmd_auth_status,
        "auth-clear": cmd_auth_clear,
        "config": cmd_config,
        "serve": cmd_serve,
        "help": cmd_help,
        "--help": cmd_help,
        "-h": cmd_help,
    }

    command = sys.argv[1].lower()
    if command in commands:
        return commands[command]()  # type: ignore[operator]

    print(f"Unknown command: {command}")
    print("Run 'oura-mcp help' for usage.")
    return 1
