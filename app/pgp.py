"""NodeMarket PGP layer. Encrypts buyer delivery data with the store's
public key BEFORE it is written to disk. Uses PGPy (pure Python OpenPGP).
"""

from . import pgp_compat  # noqa: F401  (installs imghdr shim before PGPy loads)
from pgpy import PGPKey, PGPMessage
from pgpy.errors import PGPError


def validate_public_key(armored: str) -> tuple[bool, str]:
    """Return (ok, message). Ok means a loadable, unexpired public key.

    Definitive encryption capability is proven at checkout time by the
    encrypt attempt itself (checkout fails closed), so this check only
    rejects unparseable or expired keys.
    """
    if not armored or not armored.strip():
        return False, "No key configured."
    if "BEGIN PGP PUBLIC KEY BLOCK" not in armored:
        return False, "Not an ASCII-armored public key block."
    try:
        key, _ = PGPKey.from_blob(armored)
    except (PGPError, ValueError) as exc:
        return False, f"Key failed to parse: {exc}"
    if key.is_expired:
        return False, "Key is expired."
    return True, f"Key loaded (fingerprint {key.fingerprint})."

def encrypt_for_store(armored_key: str, plaintext: str) -> str:
    """Encrypt plaintext to the store's public key; return ASCII-armored ciphertext.

    Raises PGPError/ValueError if the key is unusable - callers must fail closed
    (no plaintext order data is ever persisted).
    """
    key, _ = PGPKey.from_blob(armored_key)
    message = PGPMessage.new(plaintext)
    ciphertext = key.encrypt(message)
    return str(ciphertext)
