"""Dev helper: generate a throwaway RSA keypair for local testing.

Usage: .venv\\Scripts\\python.exe tools\\gen_test_key.py [priv_output] [pub_output]
Defaults: test_pgp_key.sec / test_pgp_key.pub
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import pgp_compat  # noqa: E402
from pgpy import PGPKey, PGPUID  # noqa: E402
from pgpy.constants import (  # noqa: E402
    PubKeyAlgorithm, KeyFlags, HashAlgorithm,
    SymmetricKeyAlgorithm, CompressionAlgorithm,
)


def main() -> None:
    priv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("test_pgp_key.sec")
    pub_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("test_pgp_key.pub")

    key = PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
    uid = PGPUID.new("NodeMarket Test <store@test.local>")
    key.add_uid(
        uid,
        usage={KeyFlags.Sign, KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage},
        hashes=[HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.ZLIB, CompressionAlgorithm.ZIP,
                     CompressionAlgorithm.Uncompressed],
    )
    priv_path.write_text(str(key), encoding="utf-8")
    pub_path.write_text(str(key.pubkey), encoding="utf-8")
    print(f"private key: {priv_path}")
    print(f"public key:  {pub_path}")


if __name__ == "__main__":
    main()
