"""Keyring-based credential storage for Oura Ring MCP authentication."""

from dataclasses import dataclass, field

import keyring
from keyring.errors import KeyringError, NoKeyringError

SERVICE_NAME = "ouraring-mcp"
USERNAME = "personal_access_token"


@dataclass
class CredentialResult:
    """Result of a credential operation."""

    success: bool
    message: str
    token: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        token_status = "present" if self.token else "None"
        return (
            f"CredentialResult(success={self.success},"
            f" token=<{token_status}>, message={self.message!r})"
        )


def is_keyring_available() -> bool:
    """Return True if a real keyring backend is available."""
    try:
        backend = keyring.get_keyring()
        backend_name = type(backend).__name__.lower()
        return not ("fail" in backend_name or "null" in backend_name)
    except (NoKeyringError, KeyringError):
        return False


def store_credential(token: str) -> CredentialResult:
    if not token or not token.strip():
        return CredentialResult(success=False, message="Token cannot be empty")
    try:
        keyring.set_password(SERVICE_NAME, USERNAME, token.strip())
        return CredentialResult(success=True, message="Token stored in keyring")
    except NoKeyringError:
        return CredentialResult(
            success=False,
            message="No keyring backend available. Use encrypted file storage.",
        )
    except KeyringError as e:
        return CredentialResult(success=False, message=f"Keyring error: {e}")


def get_credential() -> CredentialResult:
    try:
        token = keyring.get_password(SERVICE_NAME, USERNAME)
        if token:
            return CredentialResult(success=True, message="Token retrieved", token=token)
        return CredentialResult(success=False, message="No token stored")
    except NoKeyringError:
        return CredentialResult(
            success=False,
            message="No keyring backend available. Use encrypted file storage.",
        )
    except KeyringError as e:
        return CredentialResult(success=False, message=f"Keyring error: {e}")


def clear_credential() -> CredentialResult:
    try:
        keyring.delete_password(SERVICE_NAME, USERNAME)
        return CredentialResult(success=True, message="Token cleared")
    except keyring.errors.PasswordDeleteError:
        return CredentialResult(success=True, message="No token to clear")
    except NoKeyringError:
        return CredentialResult(success=False, message="No keyring backend available")
    except KeyringError as e:
        return CredentialResult(success=False, message=f"Keyring error: {e}")
