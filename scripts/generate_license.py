#!/usr/bin/env python3
"""
generate_license.py — Internal tool for generating OH license files.

Usage:
    python scripts/generate_license.py --client "wizzysocial" --hwid "abc123..." --expires "2027-04-06"
    python scripts/generate_license.py --client "wizzysocial" --hwid "abc123..." --days 365

Outputs:
    license_<client>.key  (in current directory)

The Ed25519 private key must be stored at: scripts/.license_private_key
(This file is gitignored and MUST NOT be committed.)

To generate a new keypair (first-time setup only):
    python scripts/generate_license.py --generate-keypair
"""
import argparse
import base64
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization

PRIVATE_KEY_PATH = Path(__file__).parent / ".license_private_key"
SIGNATURE_SEPARATOR = "---SIGNATURE---"


def generate_keypair() -> None:
    """Generate a new Ed25519 keypair and save/display it."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_bytes = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    pub_bytes = public_key.public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )

    # Save private key
    PRIVATE_KEY_PATH.write_bytes(priv_bytes)
    print(f"Private key saved to: {PRIVATE_KEY_PATH}")
    print(f"  (hex): {priv_bytes.hex()}")
    print()
    print(f"Public key (embed in license_service.py):")
    print(f"  (hex): {pub_bytes.hex()}")
    print(f"  (b64): {base64.b64encode(pub_bytes).decode()}")
    print()
    print("IMPORTANT: Never commit the private key to git!")


def load_private_key() -> Ed25519PrivateKey:
    """Load the Ed25519 private key from disk."""
    if not PRIVATE_KEY_PATH.exists():
        print(f"ERROR: Private key not found at {PRIVATE_KEY_PATH}")
        print("Run with --generate-keypair to create one (first-time only).")
        sys.exit(1)

    priv_bytes = PRIVATE_KEY_PATH.read_bytes()
    if len(priv_bytes) != 32:
        print(f"ERROR: Private key file has wrong size ({len(priv_bytes)} bytes, expected 32)")
        sys.exit(1)

    return Ed25519PrivateKey.from_private_bytes(priv_bytes)


def generate_license(client: str, hwid: str, expires: str, features: list) -> str:
    """
    Generate a signed license file content.

    Returns the full license file content (JSON + separator + signature).
    """
    private_key = load_private_key()

    payload = {
        "client": client,
        "hwid": hwid,
        "issued": date.today().isoformat(),
        "expires": expires,
        "features": features,
    }

    payload_str = json.dumps(payload, indent=2)

    # Sign the payload
    signature = private_key.sign(payload_str.encode("utf-8"))
    sig_b64 = base64.b64encode(signature).decode("ascii")

    # Combine into license file format
    license_content = f"{payload_str}\n{SIGNATURE_SEPARATOR}\n{sig_b64}\n"
    return license_content


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate OH license files (internal tool)."
    )
    parser.add_argument(
        "--generate-keypair",
        action="store_true",
        help="Generate a new Ed25519 keypair (first-time setup only).",
    )
    parser.add_argument("--client", type=str, help="Client name (e.g. 'wizzysocial')")
    parser.add_argument("--hwid", type=str, help="Machine HWID (32-char hex)")
    parser.add_argument("--expires", type=str, help="Expiry date (YYYY-MM-DD)")
    parser.add_argument(
        "--days",
        type=int,
        help="Alternative to --expires: number of days from today.",
    )
    parser.add_argument(
        "--features",
        type=str,
        default="all",
        help="Comma-separated feature list (default: 'all').",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file path (default: license_<client>.key).",
    )

    args = parser.parse_args()

    if args.generate_keypair:
        generate_keypair()
        return

    if not args.client or not args.hwid:
        parser.error("--client and --hwid are required.")

    if args.expires:
        expires = args.expires
        # Validate date format
        try:
            date.fromisoformat(expires)
        except ValueError:
            parser.error(f"Invalid date format: {expires}. Use YYYY-MM-DD.")
    elif args.days:
        expires = (date.today() + timedelta(days=args.days)).isoformat()
    else:
        parser.error("Either --expires or --days is required.")

    features = [f.strip() for f in args.features.split(",")]

    license_content = generate_license(args.client, args.hwid, expires, features)

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        safe_client = args.client.replace(" ", "_").lower()
        out_path = Path(f"license_{safe_client}.key")

    out_path.write_text(license_content, encoding="utf-8")
    print(f"License generated: {out_path}")
    print(f"  Client:  {args.client}")
    print(f"  HWID:    {args.hwid}")
    print(f"  Expires: {expires}")
    print(f"  Features: {features}")

    # Also show public key info for verification
    private_key = load_private_key()
    public_key = private_key.public_key()
    pub_bytes = public_key.public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    print(f"\n  Public key (hex): {pub_bytes.hex()}")


if __name__ == "__main__":
    main()
