"""Unified credential storage with automatic backend selection.

OURA_API_TOKEN env var is a first-class auth source for headless/CI
and takes precedence over both stored backends.
"""

import os

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


def get_storage_backend() -> str:
    if os.environ.get(ENV_VAR_NAME):
        return "environment"
    if is_keyring_available():
        return "keyring"
    return "encrypted_file"


def store_credential(token: str) -> CredentialResult:
    """Store token. Always writes encrypted file first; also writes keyring when available."""
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


def get_credential() -> CredentialResult:
    """Retrieve token: env var → keyring → encrypted file."""
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


def clear_credential() -> CredentialResult:
    """Clear token from all backends."""
    results = []
    if is_keyring_available():
        results.append(clear_credential_keyring())
    results.append(clear_credential_encrypted())
    if any(r.success for r in results):
        return CredentialResult(success=True, message="Credentials cleared")
    return CredentialResult(success=False, message="No credentials to clear")
