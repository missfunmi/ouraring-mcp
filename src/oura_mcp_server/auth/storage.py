"""Unified credential storage with automatic backend selection.

OURA_API_TOKEN env var is a first-class auth source for headless/CI
and takes precedence over both stored backends.
"""

import json
import os
import time
from dataclasses import asdict, dataclass

from oura_mcp_server.auth.encrypted import (
    clear_credential_encrypted,
    get_credential_encrypted,
    store_credential_encrypted,
)
from oura_mcp_server.auth.keyring import CredentialResult, is_keyring_available
from oura_mcp_server.auth.keyring import clear_credential as clear_credential_keyring
from oura_mcp_server.auth.keyring import get_credential as get_credential_keyring
from oura_mcp_server.auth.keyring import store_credential as store_credential_keyring

ENV_VAR_NAME = "OURA_API_TOKEN"
OURA_TOKEN_URL = "https://api.ouraring.com/oauth/token"


@dataclass
class OAuthCredential:
    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str
    expires_at: float = 0.0  # Unix timestamp; 0 = unknown (assume valid)

    def is_expired(self) -> bool:
        if self.expires_at == 0:
            return False
        return time.time() >= self.expires_at - 60  # 60-second buffer


def get_storage_backend() -> str:
    if os.environ.get(ENV_VAR_NAME):
        return "environment"
    if is_keyring_available():
        return "keyring"
    return "encrypted_file"


def store_credential(token: str) -> CredentialResult:
    """Store a raw string token. Always writes encrypted file; also writes keyring when available."""
    encrypted_result = store_credential_encrypted(token)
    if is_keyring_available():
        try:
            keyring_result = store_credential_keyring(token)
            if keyring_result.success:
                return CredentialResult(
                    success=True,
                    message="Token stored in keyring and encrypted file",
                )
        except Exception:
            pass
    return encrypted_result


def store_oauth_credential(cred: OAuthCredential) -> CredentialResult:
    """Serialize an OAuthCredential to JSON and store it."""
    return store_credential(json.dumps(asdict(cred)))


def get_credential() -> CredentialResult:
    """Retrieve raw string token: env var → keyring → encrypted file."""
    env_token = os.environ.get(ENV_VAR_NAME)
    if env_token:
        return CredentialResult(
            success=True,
            message="Token from environment variable",
            token=env_token,
        )
    if is_keyring_available():
        result = get_credential_keyring()
        if result.success:
            return result
    return get_credential_encrypted()


def get_oauth_credential() -> OAuthCredential | None:
    """Deserialize the stored credential as an OAuthCredential, or None if absent/invalid."""
    result = get_credential()
    if not result.success or not result.token:
        return None
    try:
        data = json.loads(result.token)
        return OAuthCredential(**data)
    except Exception:
        return None


def _refresh_token(cred: OAuthCredential) -> OAuthCredential | None:
    """Exchange a refresh token for a new access token. Returns updated credential or None."""
    import httpx
    try:
        resp = httpx.post(
            OURA_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": cred.refresh_token,
                "client_id": cred.client_id,
                "client_secret": cred.client_secret,
            },
            timeout=15.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        new_cred = OAuthCredential(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", cred.refresh_token),
            client_id=cred.client_id,
            client_secret=cred.client_secret,
            expires_at=time.time() + data.get("expires_in", 86400),
        )
        store_oauth_credential(new_cred)
        return new_cred
    except Exception:
        return None


def get_access_token() -> str | None:
    """Return a valid access token: env var (PAT compat) → stored OAuth (refresh if expired)."""
    env_token = os.environ.get(ENV_VAR_NAME)
    if env_token:
        return env_token

    cred = get_oauth_credential()
    if cred is None:
        return None

    if cred.is_expired():
        cred = _refresh_token(cred)

    return cred.access_token if cred else None


def clear_credential() -> CredentialResult:
    """Clear token from all backends."""
    results = []
    if is_keyring_available():
        results.append(clear_credential_keyring())
    results.append(clear_credential_encrypted())
    if any(r.success for r in results):
        return CredentialResult(success=True, message="Credentials cleared")
    return CredentialResult(success=False, message="No credentials to clear")
