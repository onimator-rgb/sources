"""
LicenseService — offline license verification for OH.

Uses Ed25519 signatures to verify license authenticity.
The public key is embedded here; the private key lives only on the build machine.

License file location: %APPDATA%\\OH\\license.key
"""
import base64
import hashlib
import json
import logging
import os
import platform
import subprocess
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.exceptions import InvalidSignature

from oh.models.license import LicenseInfo, LicenseStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedded Ed25519 PUBLIC key (raw 32 bytes, hex-encoded)
# The corresponding private key is stored ONLY on the build machine.
# ---------------------------------------------------------------------------
_PUBLIC_KEY_HEX = "eb30629d47184b7018a649520c27c97d3b2944bb70044f9b6643738e10e90e12"

# Grace period: number of days after expiry where app still works with warning
GRACE_PERIOD_DAYS = 7

# License file name
LICENSE_FILENAME = "license.key"

# Separator between JSON payload and signature in the license file
SIGNATURE_SEPARATOR = "---SIGNATURE---"


def _get_appdata_dir() -> Path:
    """Return %APPDATA%\\OH, creating it if necessary."""
    app_data = os.environ.get("APPDATA") or str(Path.home())
    d = Path(app_data) / "OH"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_disk_serial() -> str:
    """Read the first disk serial number via wmic (Windows only)."""
    try:
        result = subprocess.run(
            ["wmic", "diskdrive", "get", "serialnumber"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        lines = [
            l.strip()
            for l in result.stdout.strip().split("\n")
            if l.strip() and l.strip() != "SerialNumber"
        ]
        return lines[0] if lines else "unknown"
    except Exception:
        return "unknown"


def generate_hwid() -> str:
    """
    Generate a hardware ID for this machine.

    Combines MAC address + hostname + disk serial, hashed with SHA-256.
    Returns 32-char hex string.
    """
    parts = [
        str(uuid.getnode()),
        platform.node(),
        _get_disk_serial(),
    ]
    raw = "-".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _get_public_key() -> Ed25519PublicKey:
    """Reconstruct the Ed25519 public key from embedded hex bytes."""
    pub_bytes = bytes.fromhex(_PUBLIC_KEY_HEX)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    return Ed25519PublicKey.from_public_bytes(pub_bytes)


def _parse_license_file(content: str):
    """
    Parse a license file into (payload_json_str, signature_b64).
    Returns (None, None) if format is invalid.
    """
    if SIGNATURE_SEPARATOR not in content:
        return None, None
    parts = content.split(SIGNATURE_SEPARATOR, 1)
    if len(parts) != 2:
        return None, None
    payload_str = parts[0].strip()
    sig_b64 = parts[1].strip()
    if not payload_str or not sig_b64:
        return None, None
    return payload_str, sig_b64


class LicenseService:
    """
    Manages license verification for OH.

    On construction, loads and verifies the license file.
    Call verify() to get the current status.
    """

    def __init__(self, license_path: Optional[Path] = None) -> None:
        if license_path is None:
            self._license_path = _get_appdata_dir() / LICENSE_FILENAME
        else:
            self._license_path = license_path

        self._info: Optional[LicenseInfo] = None
        self._status: LicenseStatus = LicenseStatus.MISSING
        self._machine_hwid: str = generate_hwid()

        logger.info("LicenseService initializing. HWID=%s", self._machine_hwid)
        self._load_and_verify()

    def _load_and_verify(self) -> None:
        """Load the license file and verify it."""
        if not self._license_path.exists():
            logger.warning("License file not found: %s", self._license_path)
            self._status = LicenseStatus.MISSING
            self._info = None
            return

        try:
            content = self._license_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("Cannot read license file: %s", exc)
            self._status = LicenseStatus.CORRUPT
            self._info = None
            return

        payload_str, sig_b64 = _parse_license_file(content)
        if payload_str is None:
            logger.error("License file has invalid format")
            self._status = LicenseStatus.CORRUPT
            self._info = None
            return

        # Verify signature
        try:
            sig_bytes = base64.b64decode(sig_b64)
            public_key = _get_public_key()
            public_key.verify(sig_bytes, payload_str.encode("utf-8"))
            signature_valid = True
        except (InvalidSignature, Exception) as exc:
            logger.error("License signature verification failed: %s", exc)
            self._status = LicenseStatus.INVALID_SIGNATURE
            self._info = LicenseInfo(
                client="",
                hwid="",
                issued="",
                expires="",
                features=[],
                status=LicenseStatus.INVALID_SIGNATURE,
                days_remaining=0,
                signature_valid=False,
                hwid_match=False,
                raw_payload=payload_str,
            )
            return

        # Parse JSON payload
        try:
            data = json.loads(payload_str)
        except json.JSONDecodeError as exc:
            logger.error("License JSON is invalid: %s", exc)
            self._status = LicenseStatus.CORRUPT
            self._info = None
            return

        client = data.get("client", "")
        hwid = data.get("hwid", "")
        issued = data.get("issued", "")
        expires = data.get("expires", "")
        features = data.get("features", [])

        # Check HWID
        hwid_match = (hwid == self._machine_hwid)
        if not hwid_match:
            logger.error(
                "HWID mismatch. License=%s, Machine=%s",
                hwid, self._machine_hwid,
            )
            self._status = LicenseStatus.INVALID_HWID
            self._info = LicenseInfo(
                client=client,
                hwid=hwid,
                issued=issued,
                expires=expires,
                features=features,
                status=LicenseStatus.INVALID_HWID,
                days_remaining=0,
                signature_valid=True,
                hwid_match=False,
                raw_payload=payload_str,
            )
            return

        # Check expiry
        try:
            expiry_date = date.fromisoformat(expires)
        except (ValueError, TypeError):
            logger.error("Invalid expiry date in license: %s", expires)
            self._status = LicenseStatus.CORRUPT
            self._info = None
            return

        today = date.today()
        days_remaining = (expiry_date - today).days

        if days_remaining >= 0:
            status = LicenseStatus.VALID
        elif abs(days_remaining) <= GRACE_PERIOD_DAYS:
            status = LicenseStatus.GRACE_PERIOD
            logger.warning(
                "License expired %d day(s) ago — grace period active (%d days left)",
                abs(days_remaining),
                GRACE_PERIOD_DAYS - abs(days_remaining),
            )
        else:
            status = LicenseStatus.EXPIRED
            logger.error("License expired %d day(s) ago — beyond grace period", abs(days_remaining))

        self._status = status
        self._info = LicenseInfo(
            client=client,
            hwid=hwid,
            issued=issued,
            expires=expires,
            features=features,
            status=status,
            days_remaining=days_remaining,
            signature_valid=True,
            hwid_match=True,
            raw_payload=payload_str,
        )

        logger.info(
            "License loaded: client=%s, expires=%s, days_remaining=%d, status=%s",
            client, expires, days_remaining, status.value,
        )

    def verify(self) -> LicenseStatus:
        """Return the current license status."""
        return self._status

    def get_client_name(self) -> str:
        """Return the client name from the license, or empty string."""
        if self._info is not None:
            return self._info.client
        return ""

    def get_expiry_date(self) -> str:
        """Return the expiry date string, or empty string."""
        if self._info is not None:
            return self._info.expires
        return ""

    def get_hwid(self) -> str:
        """Return this machine's HWID."""
        return self._machine_hwid

    def days_remaining(self) -> int:
        """Return days until expiry (negative if expired)."""
        if self._info is not None:
            return self._info.days_remaining
        return 0

    def is_valid(self) -> bool:
        """Return True if license is VALID or in GRACE_PERIOD."""
        return self._status in (LicenseStatus.VALID, LicenseStatus.GRACE_PERIOD)

    def get_info(self) -> Optional[LicenseInfo]:
        """Return the full LicenseInfo or None."""
        return self._info

    def reload(self, license_path: Optional[Path] = None) -> LicenseStatus:
        """
        Reload and re-verify the license file.
        Optionally load from a new path (e.g. after user imports a file).
        """
        if license_path is not None:
            self._license_path = license_path
        self._load_and_verify()
        return self._status

    def install_license_file(self, source_path: Path) -> LicenseStatus:
        """
        Copy a license file from source_path to the standard location,
        then reload and verify.
        """
        import shutil
        dest = _get_appdata_dir() / LICENSE_FILENAME
        try:
            shutil.copy2(str(source_path), str(dest))
            logger.info("License file installed from %s to %s", source_path, dest)
        except Exception as exc:
            logger.error("Failed to install license file: %s", exc)
            return LicenseStatus.MISSING

        self._license_path = dest
        self._load_and_verify()
        return self._status

    @staticmethod
    def quick_verify() -> bool:
        """
        Fast re-verification check. Creates a throwaway LicenseService
        and returns True if license is valid/grace.
        Used for tamper-resistance checks at multiple code points.
        """
        try:
            svc = LicenseService()
            return svc.is_valid()
        except Exception:
            return False
