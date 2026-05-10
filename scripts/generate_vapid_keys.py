"""Generate a fresh VAPID keypair for web push.  Run once during setup.

Usage::

    python scripts/generate_vapid_keys.py

Outputs three lines suitable for an .env file or GitHub Actions secrets:

    VAPID_PUBLIC_KEY=...
    VAPID_PRIVATE_KEY=...
    VAPID_SUBJECT=mailto:contact@example.com

Both keys are base64url-encoded, compatible with pywebpush AND web-push (npm).
"""

from __future__ import annotations

import base64
import sys

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def main() -> int:
    private_key = generate_private_key(SECP256R1())
    public_key = private_key.public_key()

    pub_bytes = public_key.public_bytes(
        encoding=Encoding.X962,
        format=PublicFormat.UncompressedPoint,
    )
    priv_bytes = private_key.private_numbers().private_value.to_bytes(32, "big")

    print(f"VAPID_PUBLIC_KEY={base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()}")
    print(f"VAPID_PRIVATE_KEY={base64.urlsafe_b64encode(priv_bytes).rstrip(b'=').decode()}")
    print("VAPID_SUBJECT=mailto:contact@example.com")
    return 0


if __name__ == "__main__":
    sys.exit(main())
