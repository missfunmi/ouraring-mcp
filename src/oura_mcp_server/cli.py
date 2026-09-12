"""CLI commands for Oura Ring MCP Server."""

import os
import sys

from oura_mcp_server.auth import (
    OAuthCredential,
    clear_credential,
    get_access_token,
    get_oauth_credential,
    get_storage_backend,
    is_keyring_available,
    store_oauth_credential,
)

OURA_AUTH_URL = "https://cloud.ouraring.com/oauth/authorize"
OURA_TOKEN_URL = "https://api.ouraring.com/oauth/token"
REDIRECT_URI = "http://localhost:8085/callback"
SCOPES = "email personal daily heartrate workout tag session spo2"


def _validate_access_token(token: str) -> tuple[bool, str]:
    """Hit the Oura personal_info endpoint. Returns (valid, email_or_error)."""
    import httpx
    try:
        resp = httpx.get(
            "https://api.ouraring.com/v2/usercollection/personal_info",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            email = resp.json().get("email", "unknown")
            return True, email
        if resp.status_code == 401:
            return False, "Token rejected (401)."
        return False, f"Unexpected status {resp.status_code}."
    except Exception as e:
        return False, f"Network error: {e}"


def _run_oauth_flow(client_id: str, client_secret: str) -> OAuthCredential | None:
    """Run the OAuth2 authorization code flow. Opens browser, waits for callback."""
    import secrets
    import time
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlencode, urlparse

    import httpx

    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    }
    auth_url = OURA_AUTH_URL + "?" + urlencode(params)

    callback_data: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/callback":
                qs = parse_qs(parsed.query)
                callback_data["code"] = qs.get("code", [""])[0]
                callback_data["state"] = qs.get("state", [""])[0]
                callback_data["error"] = qs.get("error", [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>Authentication successful!</h1>"
                    b"<p>You can close this tab.</p></body></html>"
                )

        def log_message(self, format: str, *args: object) -> None:
            pass  # suppress server logs

    server = HTTPServer(("localhost", 8085), CallbackHandler)

    print("Opening browser for Oura authorization...")
    print(f"If it doesn't open, visit:\n  {auth_url}")
    print()
    webbrowser.open(auth_url)

    deadline = time.monotonic() + 120
    while not callback_data and time.monotonic() < deadline:
        server.timeout = max(0.5, deadline - time.monotonic())
        server.handle_request()
    server.server_close()

    if callback_data.get("error"):
        print(f"Error from Oura: {callback_data['error']}")
        return None

    code = callback_data.get("code", "")
    if not code:
        print("Error: No authorization code received.")
        return None

    if callback_data.get("state") != state:
        print("Error: State mismatch — possible CSRF.")
        return None

    print("Exchanging code for tokens...")
    try:
        resp = httpx.post(
            OURA_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=15.0,
        )
        if resp.status_code != 200:
            print(f"Error: Token exchange failed ({resp.status_code}): {resp.text}")
            return None
        data = resp.json()
        return OAuthCredential(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            client_id=client_id,
            client_secret=client_secret,
            expires_at=time.time() + data.get("expires_in", 86400),
        )
    except Exception as e:
        print(f"Error during token exchange: {e}")
        return None


def cmd_auth() -> int:
    print("Oura Ring MCP Authentication")
    print("=" * 40)
    print()

    if not is_keyring_available():
        print("Warning: No system keyring available.")
        print("Credentials will be stored in an encrypted file at ~/.config/ouraring-mcp/")
        print()

    existing = get_access_token()
    if existing:
        print("Existing credential found. Validating...")
        valid, info = _validate_access_token(existing)
        if valid:
            print(f"Already authenticated: {info}")
            print()
            response = input("Re-authenticate? [y/N]: ").strip().lower()
            if response != "y":
                return 0
            print()

    print("Enter your Oura OAuth2 application credentials.")
    print("Get these from: https://cloud.ouraring.com/oauth/applications")
    print()

    existing_cred = get_oauth_credential()

    try:
        default_hint = f" [{existing_cred.client_id}]" if existing_cred else ""
        client_id = input(f"Client ID{default_hint}: ").strip()
        if not client_id and existing_cred:
            client_id = existing_cred.client_id

        import getpass
        default_hint = " [stored]" if existing_cred else ""
        client_secret = getpass.getpass(f"Client Secret{default_hint} (hidden): ").strip()
        if not client_secret and existing_cred:
            client_secret = existing_cred.client_secret
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 1

    if not client_id or not client_secret:
        print("Error: Client ID and Client Secret are required.")
        return 1

    print()
    cred = _run_oauth_flow(client_id, client_secret)
    if cred is None:
        return 1

    print("Validating token...")
    valid, info = _validate_access_token(cred.access_token)
    if not valid:
        print(f"Error: {info}")
        return 1

    result = store_oauth_credential(cred)
    if not result.success:
        print(f"Error storing credential: {result.message}")
        return 1

    print()
    print("Authentication successful!")
    print(f"  Account: {info}")
    print(f"  Storage: {get_storage_backend()}")
    print()
    print("Run 'oura-mcp install' to add it to Claude Desktop, then restart Claude.")
    return 0


def cmd_auth_status() -> int:
    token = get_access_token()
    if not token:
        print("Not authenticated. Run 'oura-mcp auth' to authenticate.")
        return 1

    print("Checking token...")
    valid, info = _validate_access_token(token)
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


def _claude_config_path() -> "Path":
    import platform
    from pathlib import Path

    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"


def _oura_mcp_entry() -> dict:
    import shutil
    from pathlib import Path

    path = shutil.which("oura-mcp") or str(Path(sys.executable).parent / "oura-mcp")
    return {"command": path, "args": ["serve"]}


def cmd_install() -> int:
    import json

    config_path = _claude_config_path()

    if not config_path.exists():
        print(f"Claude Desktop config not found at:\n  {config_path}")
        print("Is Claude Desktop installed?")
        return 1

    try:
        config = json.loads(config_path.read_text())
    except Exception as e:
        print(f"Error reading config: {e}")
        return 1

    config.setdefault("mcpServers", {})
    config["mcpServers"]["ouraring"] = _oura_mcp_entry()

    try:
        config_path.write_text(json.dumps(config, indent=2))
    except Exception as e:
        print(f"Error writing config: {e}")
        return 1

    print(f"Added 'ouraring' to mcpServers in:\n  {config_path}")
    print()
    print("Restart Claude Desktop to apply the change.")
    return 0


def cmd_config() -> int:
    import json

    config = {"ouraring": _oura_mcp_entry()}
    print('Add this inside "mcpServers": {} in your Claude Desktop config:')
    print()
    print(json.dumps(config, indent=2))
    print()
    print("Or run 'oura-mcp install' to add it automatically.")
    return 0


def cmd_help() -> int:
    print("Oura Ring MCP Server")
    print()
    print("Usage: oura-mcp <command>")
    print()
    print("Commands:")
    print("  auth          Authenticate via Oura OAuth2")
    print("  auth-status   Check if the stored credential is valid")
    print("  auth-clear    Remove stored credentials")
    print("  install       Add ouraring to Claude Desktop config automatically")
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
        "install": cmd_install,
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
