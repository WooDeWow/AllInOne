"""Indie license gate: local trial + HTTPS check-back to a configurable endpoint.

Store: ~/.allinone/license.json (survives git pulls).
Endpoint: config.json license_url or env ALLINONE_LICENSE_URL (Apps Script Web App).
Dev bypass: ALLINONE_DEV_UNLOCK=1 (not for production builds).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PRODUCT_NAME = "AllInOne"
TRIAL_DAYS = 7
TRIAL_MAX_USES = 10
RECHECK_HOURS = 24
OFFLINE_GRACE_DAYS = 7

# Prefer user home so pulls / reinstalls keep the license + trial clock
LICENSE_DIR = Path.home() / ".allinone"
LICENSE_PATH = LICENSE_DIR / "license.json"

# Project-local config (seller copies from config.example.json)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = _PROJECT_ROOT / "config.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        text = str(s).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def machine_fingerprint() -> str:
    """Stable non-PII hash of machine-ish identifiers (not for tracking people)."""
    raw = "|".join(
        [
            platform.node() or "",
            platform.system() or "",
            platform.machine() or "",
            hex(uuid.getnode()),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def load_config() -> dict[str, Any]:
    cfg: dict[str, Any] = {"product_name": PRODUCT_NAME, "license_url": ""}
    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            pass
    env_url = os.environ.get("ALLINONE_LICENSE_URL", "").strip()
    if env_url:
        cfg["license_url"] = env_url
    return cfg


def license_url() -> str:
    return str(load_config().get("license_url") or "").strip()


def _default_state() -> dict[str, Any]:
    return {
        "license_key": None,
        "email": None,
        "status": None,
        "expires": None,
        "valid": False,
        "last_check": None,
        "last_check_ok": False,
        "trial_started": None,
        "uses": 0,
        "machine_fingerprint": machine_fingerprint(),
        "product": PRODUCT_NAME,
    }


def load_state() -> dict[str, Any]:
    state = _default_state()
    if LICENSE_PATH.is_file():
        try:
            data = json.loads(LICENSE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                state.update(data)
        except Exception:
            pass
    # Ensure fingerprint exists
    if not state.get("machine_fingerprint"):
        state["machine_fingerprint"] = machine_fingerprint()
    # Start trial clock on first load
    if not state.get("trial_started"):
        state["trial_started"] = _iso(_utc_now())
        save_state(state)
    return state


def save_state(state: dict[str, Any]) -> None:
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LICENSE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(LICENSE_PATH)


def is_dev_unlocked() -> bool:
    return os.environ.get("ALLINONE_DEV_UNLOCK", "").strip() in ("1", "true", "True", "yes", "YES")


@dataclass
class AccessInfo:
    allowed: bool
    mode: str  # licensed | trial | locked | dev
    message: str
    email: str | None = None
    expires: str | None = None
    trial_days_left: int | None = None
    trial_uses_left: int | None = None
    needs_setup: bool = False


def _trial_remaining(state: dict[str, Any]) -> tuple[int, int, bool]:
    """Return (days_left, uses_left, still_in_trial)."""
    started = _parse_iso(state.get("trial_started")) or _utc_now()
    elapsed = _utc_now() - started
    days_left = max(0, TRIAL_DAYS - int(elapsed.total_seconds() // 86400))
    # Partial day still counts as a day left if under TRIAL_DAYS calendar window
    if elapsed < timedelta(days=TRIAL_DAYS):
        # ceil-ish: if any time remains in the window, at least show 1 until last day ends
        rem = TRIAL_DAYS - elapsed.total_seconds() / 86400.0
        days_left = max(0, int(rem) if rem == int(rem) else int(rem) + (1 if rem > 0 else 0))
        days_left = min(TRIAL_DAYS, max(0, days_left))
    else:
        days_left = 0

    uses = int(state.get("uses") or 0)
    uses_left = max(0, TRIAL_MAX_USES - uses)
    in_trial = days_left > 0 and uses_left > 0
    return days_left, uses_left, in_trial


def _license_still_valid_locally(state: dict[str, Any]) -> bool:
    if not state.get("valid") or not state.get("license_key"):
        return False
    if str(state.get("status") or "").lower() == "revoked":
        return False
    exp = _parse_iso(state.get("expires"))
    if exp is not None and _utc_now() > exp:
        return False
    return bool(state.get("last_check_ok"))


def _within_offline_grace(state: dict[str, Any]) -> bool:
    last = _parse_iso(state.get("last_check"))
    if not last or not _license_still_valid_locally(state):
        return False
    return (_utc_now() - last) <= timedelta(days=OFFLINE_GRACE_DAYS)


def _needs_online_recheck(state: dict[str, Any]) -> bool:
    last = _parse_iso(state.get("last_check"))
    if not last:
        return True
    return (_utc_now() - last) >= timedelta(hours=RECHECK_HOURS)


def validate_key_remote(key: str, timeout: float = 12.0) -> dict[str, Any]:
    """
    HTTPS GET to license_url with key (+ fingerprint).
    Expects JSON: {valid, email, expires, status}.
    """
    url = license_url()
    if not url:
        return {
            "ok": False,
            "error": "no_url",
            "message": (
                "No license server URL configured. Copy config.example.json to config.json "
                "and set license_url to your Apps Script Web App URL "
                "(see LICENSE_SETUP.md). Or set ALLINONE_LICENSE_URL."
            ),
        }

    key = (key or "").strip()
    if not key:
        return {"ok": False, "error": "empty", "message": "Enter a license key."}

    fp = machine_fingerprint()
    # Support both GET query and POST JSON-ish form
    qs = urlencode({"key": key, "fingerprint": fp, "product": PRODUCT_NAME})
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}{qs}"

    req = Request(
        full,
        method="GET",
        headers={
            "User-Agent": f"{PRODUCT_NAME}/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            return {"ok": False, "error": "http", "message": f"License server HTTP {e.code}."}
    except URLError as e:
        return {
            "ok": False,
            "error": "network",
            "message": f"Could not reach license server (offline or blocked): {e.reason}",
        }
    except Exception as e:
        return {"ok": False, "error": "network", "message": f"License check failed: {e}"}

    # Apps Script sometimes returns HTML redirect wrappers; try to find JSON
    data = _parse_json_loose(body)
    if data is None:
        return {
            "ok": False,
            "error": "bad_response",
            "message": "License server did not return JSON. Check Apps Script deployment.",
        }

    valid = bool(data.get("valid"))
    status = str(data.get("status") or ("active" if valid else "invalid")).lower()
    if status == "revoked":
        valid = False
    expires = data.get("expires")
    # Normalize null / empty
    if expires in ("", "null", "None"):
        expires = None
    email = data.get("email") or None

    return {
        "ok": True,
        "valid": valid,
        "email": email,
        "expires": expires,
        "status": status,
        "raw": data,
    }


def _parse_json_loose(body: str) -> dict | None:
    body = (body or "").strip()
    if not body:
        return None
    try:
        data = json.loads(body)
        return data if isinstance(data, dict) else None
    except Exception:
        # Try extract first {...} block
        start = body.find("{")
        end = body.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(body[start : end + 1])
                return data if isinstance(data, dict) else None
            except Exception:
                return None
    return None


def activate_license(key: str) -> AccessInfo:
    """Validate key online and persist if valid."""
    if is_dev_unlocked():
        return get_access(force_recheck=False)

    result = validate_key_remote(key)
    state = load_state()

    if result.get("error") == "no_url":
        return AccessInfo(
            allowed=False,
            mode="locked",
            message=result["message"],
            needs_setup=True,
        )

    if not result.get("ok"):
        return AccessInfo(
            allowed=_compute_allowed_offline(state),
            mode=_mode_for_state(state),
            message=result.get("message") or "Activation failed.",
            email=state.get("email"),
            expires=state.get("expires"),
        )

    now = _utc_now()
    state["license_key"] = key.strip()
    state["email"] = result.get("email")
    state["expires"] = result.get("expires")
    state["status"] = result.get("status")
    state["valid"] = bool(result.get("valid"))
    state["last_check"] = _iso(now)
    state["last_check_ok"] = bool(result.get("valid"))
    state["machine_fingerprint"] = machine_fingerprint()
    save_state(state)

    if result.get("valid"):
        exp = result.get("expires") or "never"
        email = result.get("email") or "—"
        return AccessInfo(
            allowed=True,
            mode="licensed",
            message=f"License activated. Status: active · Email: {email} · Expires: {exp}",
            email=result.get("email"),
            expires=result.get("expires"),
        )

    days_left, uses_left, in_trial = _trial_remaining(state)
    if in_trial:
        return AccessInfo(
            allowed=True,
            mode="trial",
            message=(
                f"Key not valid ({result.get('status')}). "
                f"Trial continues: {days_left} day(s) or {uses_left} use(s) left."
            ),
            trial_days_left=days_left,
            trial_uses_left=uses_left,
        )

    return AccessInfo(
        allowed=False,
        mode="locked",
        message=f"License not valid (status: {result.get('status')}). Trial ended — activate a valid key.",
        email=result.get("email"),
        expires=result.get("expires"),
    )


def _compute_allowed_offline(state: dict[str, Any]) -> bool:
    if _license_still_valid_locally(state) and _within_offline_grace(state):
        return True
    _, _, in_trial = _trial_remaining(state)
    return in_trial


def _mode_for_state(state: dict[str, Any]) -> str:
    if _license_still_valid_locally(state) and _within_offline_grace(state):
        return "licensed"
    _, _, in_trial = _trial_remaining(state)
    if in_trial:
        return "trial"
    return "locked"


def get_access(force_recheck: bool = False) -> AccessInfo:
    """
    Determine whether compress/convert features are allowed.

    Policy: trial = full features for 7 days from first run OR 10 uses
    (whichever comes first). Then lock until licensed.
    Licensed: re-check every 24h when online; offline grace 7 days after last OK check.
    """
    if is_dev_unlocked():
        return AccessInfo(
            allowed=True,
            mode="dev",
            message="DEV UNLOCK active (ALLINONE_DEV_UNLOCK=1). Not for production builds.",
        )

    state = load_state()
    url = license_url()

    # Licensed path: periodic re-check
    if state.get("license_key") and state.get("valid"):
        if force_recheck or _needs_online_recheck(state):
            if url:
                result = validate_key_remote(str(state["license_key"]))
                if result.get("ok"):
                    state["valid"] = bool(result.get("valid"))
                    state["email"] = result.get("email")
                    state["expires"] = result.get("expires")
                    state["status"] = result.get("status")
                    state["last_check"] = _iso(_utc_now())
                    state["last_check_ok"] = bool(result.get("valid"))
                    save_state(state)
                    if not result.get("valid"):
                        # Fall through to trial / lock
                        pass
                    else:
                        return AccessInfo(
                            allowed=True,
                            mode="licensed",
                            message=(
                                f"Licensed · {state.get('email') or '—'} · "
                                f"Expires: {state.get('expires') or 'never'}"
                            ),
                            email=state.get("email"),
                            expires=state.get("expires"),
                        )
                else:
                    # Network failure — grace if last check OK
                    if _within_offline_grace(state):
                        return AccessInfo(
                            allowed=True,
                            mode="licensed",
                            message=(
                                "Licensed (offline grace). Last successful check within 7 days. "
                                f"Server: {result.get('message')}"
                            ),
                            email=state.get("email"),
                            expires=state.get("expires"),
                        )
            else:
                # No URL but we have a previously validated key — honor grace
                if _within_offline_grace(state):
                    return AccessInfo(
                        allowed=True,
                        mode="licensed",
                        message="Licensed (cached). Configure license_url to re-validate online.",
                        email=state.get("email"),
                        expires=state.get("expires"),
                        needs_setup=True,
                    )

        if _license_still_valid_locally(state) and _within_offline_grace(state):
            return AccessInfo(
                allowed=True,
                mode="licensed",
                message=(
                    f"Licensed · {state.get('email') or '—'} · "
                    f"Expires: {state.get('expires') or 'never'}"
                ),
                email=state.get("email"),
                expires=state.get("expires"),
            )

    # Trial
    days_left, uses_left, in_trial = _trial_remaining(state)
    needs_setup = not bool(url)
    setup_hint = ""
    if needs_setup:
        setup_hint = (
            "\n\nSeller setup: copy config.example.json → config.json and set "
            "license_url to your Apps Script Web App URL (see LICENSE_SETUP.md)."
        )

    if in_trial:
        return AccessInfo(
            allowed=True,
            mode="trial",
            message=(
                f"Trial active — full features for {days_left} day(s) or {uses_left} use(s) "
                f"(whichever ends first). Activate a license for unlimited use.{setup_hint}"
            ),
            trial_days_left=days_left,
            trial_uses_left=uses_left,
            needs_setup=needs_setup,
        )

    return AccessInfo(
        allowed=False,
        mode="locked",
        message=(
            "Trial ended (7 days or 10 uses). Enter a valid license key on the License tab "
            f"to unlock Compress and Convert.{setup_hint}"
        ),
        trial_days_left=0,
        trial_uses_left=0,
        needs_setup=needs_setup,
    )


def record_use() -> None:
    """Increment trial use counter (only counts while unlicensed)."""
    if is_dev_unlocked():
        return
    state = load_state()
    if state.get("valid") and _license_still_valid_locally(state):
        return
    state["uses"] = int(state.get("uses") or 0) + 1
    save_state(state)


def clear_license() -> AccessInfo:
    """Remove stored key (keeps trial clock / uses)."""
    state = load_state()
    state["license_key"] = None
    state["email"] = None
    state["status"] = None
    state["expires"] = None
    state["valid"] = False
    state["last_check"] = None
    state["last_check_ok"] = False
    save_state(state)
    return get_access(force_recheck=False)


def status_banner() -> str:
    info = get_access(force_recheck=False)
    if info.mode == "licensed":
        return f"**License:** {info.message}"
    if info.mode == "dev":
        return f"**License:** {info.message}"
    if info.mode == "trial":
        return f"**License:** Unlicensed — {info.message}"
    return f"**License:** Locked — {info.message}"
