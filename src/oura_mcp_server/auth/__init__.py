"""Authentication module for Oura Ring MCP Server."""

from oura_mcp_server.auth.keyring import CredentialResult, is_keyring_available
from oura_mcp_server.auth.storage import (
    clear_credential,
    get_credential,
    get_storage_backend,
    store_credential,
)

__all__ = [
    "CredentialResult",
    "clear_credential",
    "get_credential",
    "get_storage_backend",
    "is_keyring_available",
    "store_credential",
]
