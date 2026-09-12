"""Encrypted file-based credential storage for Oura Ring MCP.

Fallback for environments where system keyring is unavailable.
Key is bound to this machine via PBKDF2-HMAC-SHA256 with a machine
fingerprint as salt. Anyone with access to the machine and this code
can derive the key — use the system keyring for stronger protection.
"""

import base64
import contextlib
import os
import platform
import stat
from pathlib import Path

from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from oura_mcp_server.auth.keyring import CredentialResult

CONFIG_DIR = Path.home() / ".config" / "ouraring-mcp"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.enc"

_KDF_ITERATIONS = 600_000


def _get_machine_id() -> bytes:
    """Build a machine fingerprint used as the KDF salt."""
    components = [platform.node(), platform.machine(), platform.system()]
    try:
        if platform.system() == "Darwin":
            import subprocess
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "IOPlatformUUID" in line:
                    components.append(line.split("=")[-1].strip().strip('"'))
                    break
    except Exception:
        pass
    try:
        machine_id_path = Path("/etc/machine-id")
        if machine_id_path.exists():
            components.append(machine_id_path.read_text().strip())
    except Exception:
        pass
    return "|".join(components).encode("utf-8")


def _derive_key() -> bytes:
    """Derive a 32-byte AES key via PBKDF2-HMAC-SHA256."""
    machine_id = _get_machine_id()
    kdf = PBKDF2HMAC(
        algorithm=crypto_hashes.SHA256(),
        length=32,
        salt=machine_id,
        iterations=_KDF_ITERATIONS,
    )
    return kdf.derive(b"ouraring-mcp-default")


def _ensure_secure_directory() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(CONFIG_DIR, stat.S_IRWXU)


def _set_file_permissions(path: Path) -> None:
    with contextlib.suppress(OSError):
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


class EncryptedCredentialStore:
    """AES-256-GCM encrypted file storage."""

    def __init__(self) -> None:
        self._key = _derive_key()

    def store(self, token: str) -> CredentialResult:
        if not token or not token.strip():
            return CredentialResult(success=False, message="Token cannot be empty")
        try:
            _ensure_secure_directory()
            nonce = os.urandom(12)
            aesgcm = AESGCM(self._key)
            ciphertext = aesgcm.encrypt(nonce, token.strip().encode("utf-8"), None)
            CREDENTIALS_FILE.write_bytes(base64.b64encode(nonce + ciphertext))
            _set_file_permissions(CREDENTIALS_FILE)
            return CredentialResult(success=True, message="Token stored in encrypted file")
        except Exception as e:
            return CredentialResult(success=False, message=f"Encryption error ({type(e).__name__})")

    def get(self) -> CredentialResult:
        if not CREDENTIALS_FILE.exists():
            return CredentialResult(success=False, message="No credential file found")
        try:
            encrypted_data = base64.b64decode(CREDENTIALS_FILE.read_bytes())
            nonce, ciphertext = encrypted_data[:12], encrypted_data[12:]
            aesgcm = AESGCM(self._key)
            token = aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
            return CredentialResult(success=True, message="Token retrieved", token=token)
        except Exception:
            return CredentialResult(
                success=False,
                message="Decryption failed. Run 'oura-mcp auth' to re-authenticate.",
            )

    def clear(self) -> CredentialResult:
        try:
            CREDENTIALS_FILE.unlink(missing_ok=True)
            return CredentialResult(success=True, message="Credential file removed")
        except Exception as e:
            return CredentialResult(success=False, message=f"Error removing file ({type(e).__name__})")


_default_store: EncryptedCredentialStore | None = None


def _get_store() -> EncryptedCredentialStore:
    global _default_store
    if _default_store is None:
        _default_store = EncryptedCredentialStore()
    return _default_store


def store_credential_encrypted(token: str) -> CredentialResult:
    return _get_store().store(token)


def get_credential_encrypted() -> CredentialResult:
    return _get_store().get()


def clear_credential_encrypted() -> CredentialResult:
    return _get_store().clear()
