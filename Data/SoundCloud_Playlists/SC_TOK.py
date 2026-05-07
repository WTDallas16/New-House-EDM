from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

load_dotenv(".env")

AUTH_URL = "https://secure.soundcloud.com/authorize"
TOKEN_URL = "https://secure.soundcloud.com/oauth/token"


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else ""


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def token_file() -> Path:
    return Path(env("SC_TOKEN_FILE", "sc_token.json"))


def print_authorize_url() -> None:
    client_id = env("SC_CLIENT_ID")
    redirect_uri = env("SC_REDIRECT_URI", "http://127.0.0.1:8000/auth-callback")
    verifier = env("SC_CODE_VERIFIER") or new_code_verifier()
    challenge = code_challenge(verifier)
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    print("Open this URL, approve SoundCloud, then copy the code= value from the redirect URL:\n")
    print(f"{AUTH_URL}?{query}\n")
    print("Use this exact verifier for the token exchange:\n")
    print(verifier)
    print("\nAdd it to .env as SC_CODE_VERIFIER before exchanging the code.")


def exchange_code() -> None:
    client_id = env("SC_CLIENT_ID")
    client_secret = env("SC_CLIENT_SECRET")
    redirect_uri = env("SC_REDIRECT_URI", "http://127.0.0.1:8000/auth-callback")
    auth_code = env("SC_AUTH_CODE") or input("Paste fresh SoundCloud code= value: ").strip()
    verifier = env("SC_CODE_VERIFIER") or input("Paste matching SC_CODE_VERIFIER: ").strip()

    missing = [name for name, value in {
        "SC_CLIENT_ID": client_id,
        "SC_CLIENT_SECRET": client_secret,
        "SC_AUTH_CODE": auth_code,
        "SC_CODE_VERIFIER": verifier,
    }.items() if not value]
    if missing:
        raise SystemExit(f"Missing required values: {', '.join(missing)}")

    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code": auth_code,
        "code_verifier": verifier,
    }
    response = requests.post(TOKEN_URL, data=payload, timeout=30)
    if response.status_code >= 400:
        print(f"SoundCloud token exchange failed: HTTP {response.status_code}", file=sys.stderr)
        print("Response body:", file=sys.stderr)
        print(response.text, file=sys.stderr)
        raise SystemExit(1)

    token = response.json()
    expires_in = int(token.get("expires_in") or 3600)
    token["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).timestamp()
    output = token_file()
    output.write_text(json.dumps(token, indent=2), encoding="utf-8")
    print(f"Wrote SoundCloud token to {output}")


def refresh_existing_token() -> None:
    client_id = env("SC_CLIENT_ID")
    client_secret = env("SC_CLIENT_SECRET")
    path = token_file()
    token = json.loads(path.read_text(encoding="utf-8"))
    refresh_token = token.get("refresh_token") or env("SC_REFRESH_TOKEN")
    if not refresh_token:
        raise SystemExit("No refresh_token found in token file or SC_REFRESH_TOKEN.")
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        print(f"SoundCloud token refresh failed: HTTP {response.status_code}", file=sys.stderr)
        print(response.text, file=sys.stderr)
        raise SystemExit(1)

    refreshed = response.json()
    refreshed.setdefault("refresh_token", refresh_token)
    expires_in = int(refreshed.get("expires_in") or 3600)
    refreshed["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).timestamp()
    path.write_text(json.dumps(refreshed, indent=2), encoding="utf-8")
    print(f"Refreshed SoundCloud token in {path}")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "exchange"
    if mode == "authorize-url":
        print_authorize_url()
    elif mode == "exchange":
        exchange_code()
    elif mode == "refresh":
        refresh_existing_token()
    else:
        raise SystemExit("Usage: python3 SC_TOK.py [authorize-url|exchange|refresh]")


if __name__ == "__main__":
    main()
