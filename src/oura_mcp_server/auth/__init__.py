"""Authentication module for Oura Ring MCP Server."""

from oura_mcp_server.auth.keyring import CredentialResult, is_keyring_available
from oura_mcp_server.auth.storage import (
    OAuthCredential,
    clear_credential,
    get_access_token,
    get_credential,
    get_oauth_credential,
    get_storage_backend,
    store_credential,
    store_oauth_credential,
)

__all__ = [
    "CredentialResult",
    "OAuthCredential",
    "clear_credential",
    "get_access_token",
    "get_credential",
    "get_oauth_credential",
    "get_storage_backend",
    "is_keyring_available",
    "store_credential",
    "store_oauth_credential",
]
