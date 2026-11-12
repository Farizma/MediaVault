"""Settings > Privacy > Lock Media Vault: ask for a password, Windows Hello, a security key (YubiKey) or a phone
passkey before the library shows.

A lock screen, not encryption: it stops someone opening Media Vault on this PC. Your video files, and Media Vault's
own files, stay readable in File Explorer.

- Password: kept only as a salted scrypt hash. Wrong guesses wait longer each time.
- Windows Hello, security keys and phone passkeys are all WebAuthn (FIDO2) credentials, made and checked through
  Windows' own sign-in prompt (webauthn.dll, via the python-fido2 library). Media Vault keeps only each
  credential's public key; a sign-in is a fresh signature over a random challenge, checked against that key.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import database as db

SETTING = "app_lock"
RP_ID = "mediavault.farizma.github.io"      # the "site" the passkeys belong to (shown in Windows' prompt)
ORIGIN = f"https://{RP_ID}"
RP = {"id": RP_ID, "name": "Media Vault"}
USER = {"id": b"media-vault-lock", "name": "Media Vault", "display_name": "Media Vault"}
KINDS = {   # what each "Add" button asks Windows for
    "hello": {"attachment": "platform", "hints": ["client-device"], "label": "Windows Hello"},
    "key": {"attachment": "cross-platform", "hints": ["security-key"], "label": "Security key"},
    "phone": {"attachment": "cross-platform", "hints": ["hybrid"], "label": "Phone passkey"},
}
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
MIN_PASSWORD = 4


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def config() -> dict:
    try:
        cfg = json.loads(db.get_setting(SETTING, "") or "{}")
        return cfg if isinstance(cfg, dict) else {}
    except ValueError:
        return {}


def _save(cfg: dict) -> None:
    db.set_setting(SETTING, json.dumps(cfg))


def enabled() -> bool:
    cfg = config()
    return bool(cfg.get("password") or cfg.get("keys"))


def summary() -> dict:
    """For Settings and the lock screen: what is set up (never any secret)."""
    cfg = config()
    return {"enabled": enabled(), "password": bool(cfg.get("password")),
            "keys": [{"id": k["id"], "kind": k["kind"], "label": k["label"], "added": k.get("added", "")}
                     for k in cfg.get("keys") or []],
            "webauthn": webauthn_available(), "hello": hello_available()}


# ------------------------------------------------------------------ password

def _hash(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=32)


def set_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"use at least {MIN_PASSWORD} characters")
    salt = secrets.token_bytes(16)
    cfg = config()
    cfg["password"] = {"salt": _b64(salt), "hash": _b64(_hash(password, salt, **SCRYPT)), **SCRYPT}
    _save(cfg)


def clear_password() -> None:
    cfg = config()
    cfg.pop("password", None)
    _save(cfg)


_failures = 0


def check_password(password: str) -> bool:
    """Constant-time compare; each wrong guess in a row waits a little longer (up to 5 s)."""
    global _failures
    pw = config().get("password")
    if not pw:
        return False
    try:
        ok = hmac.compare_digest(_hash(password, _unb64(pw["salt"]), pw["n"], pw["r"], pw["p"]), _unb64(pw["hash"]))
    except (KeyError, ValueError):
        ok = False
    if ok:
        _failures = 0
    else:
        _failures += 1
        time.sleep(min(5.0, 0.4 * 2 ** (_failures - 1)))
    return ok


# ------------------------------------------------------------------ passkeys and security keys

def webauthn_available() -> bool:
    if os.name != "nt":
        return False
    try:
        from fido2.client.windows import WindowsClient
        return WindowsClient.is_available()
    except Exception:
        return False


def hello_available() -> bool:
    """Windows Hello (PIN, face or fingerprint) is set up for this Windows account."""
    if not webauthn_available():
        return False
    try:
        import ctypes
        from fido2.client.win_api import WEBAUTHN
        ok = ctypes.c_bool(False)
        return WEBAUTHN.WebAuthNIsUserVerifyingPlatformAuthenticatorAvailable(ctypes.byref(ok)) == 0 and ok.value
    except Exception:
        return False


def _server():
    from fido2.server import Fido2Server
    return Fido2Server(RP, verify_origin=lambda origin: origin == ORIGIN)


def _client(hwnd=None):
    from fido2.client import DefaultClientDataCollector
    from fido2.client.windows import WindowsClient
    return WindowsClient(DefaultClientDataCollector(ORIGIN, verify=lambda rp_id, origin: rp_id == RP_ID), handle=hwnd)


def _credentials(cfg: dict, kind: str | None = None) -> list:
    from fido2.webauthn import AttestedCredentialData
    return [AttestedCredentialData(_unb64(k["data"])) for k in cfg.get("keys") or [] if kind in (None, k["kind"])]


def add_key(kind: str, hwnd=None, client=None) -> dict:
    """Make a new credential through Windows' prompt (blocks until the person finishes it). Returns its summary."""
    if kind not in KINDS:
        raise ValueError("unknown kind of sign-in")
    cfg = config()
    server, want = _server(), KINDS[kind]
    options, state = server.register_begin(USER, _credentials(cfg), user_verification="preferred",
                                           authenticator_attachment=want["attachment"], resident_key_requirement="discouraged")
    public_key = dict(options)["publicKey"]
    public_key = {**dict(public_key), "hints": want["hints"]}
    response = (client or _client(hwnd)).make_credential(public_key)
    auth_data = server.register_complete(state, response)
    data = bytes(auth_data.credential_data)
    same = sum(1 for k in cfg.get("keys") or [] if k["kind"] == kind)
    entry = {"id": auth_data.credential_data.credential_id.hex()[:16], "kind": kind, "data": _b64(data),
             "label": want["label"] + (f" {same + 1}" if same else ""), "added": time.strftime("%Y-%m-%d")}
    cfg.setdefault("keys", []).append(entry)
    _save(cfg)
    return {k: entry[k] for k in ("id", "kind", "label", "added")}


def remove_key(key_id: str) -> None:
    cfg = config()
    cfg["keys"] = [k for k in cfg.get("keys") or [] if k["id"] != key_id]
    _save(cfg)


def verify_key(kind: str | None = None, hwnd=None, client=None) -> bool:
    """Ask Windows for a signature from one of the saved credentials (of one kind, or any); True when it checks out
    against the public key kept here. Cancelling, a timeout or a wrong key is False."""
    cfg = config()
    creds = _credentials(cfg, kind)
    if not creds:
        return False
    server = _server()
    options, state = server.authenticate_begin(creds, user_verification="preferred")
    public_key = dict(dict(options)["publicKey"])
    if kind:
        public_key["hints"] = KINDS[kind]["hints"]
    try:
        selection = (client or _client(hwnd)).get_assertion(public_key)
        server.authenticate_complete(state, creds, selection.get_response(0))
        return True
    except Exception:
        import logging
        logging.getLogger(__name__).info("security key sign-in did not complete", exc_info=True)
        return False


def reset() -> None:
    """Turn the lock off (all sign-ins). From Settings while unlocked, or `MediaVault.exe --reset-lock`."""
    _save({})
