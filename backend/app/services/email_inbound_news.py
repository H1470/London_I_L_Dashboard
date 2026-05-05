"""
Fetch news-like messages from an IMAP inbox and persist headline + URL + timestamp.

Configure via real environment files only — `repo/.env`, `backend/.env`, then `cwd/.env`
(see `backend/.env.example` for **names only**; that file is never loaded at runtime):
  NEWS_IMAP_HOST, NEWS_IMAP_USER, NEWS_IMAP_PASSWORD
  optional: NEWS_IMAP_PORT (default 993), NEWS_IMAP_FOLDER (default INBOX)

Parsing: Subject line → headline (Re:/Fwd: stripped). First https?:// URL in plain/HTML body.
Duplicate Message-IDs are ignored by the store.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from app.data.news_store import upsert_story

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[misc, assignment]

_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)


def _imap_error_message(exc: BaseException) -> str:
    """imaplib often puts b'...' in args; avoid repr like \"b'LOGIN failed.'\" in API output."""
    if isinstance(exc, imaplib.IMAP4.error):
        for arg in exc.args:
            if isinstance(arg, (bytes, bytearray)):
                return bytes(arg).decode("utf-8", errors="replace")
    return str(exc)


def _login_failed_hint(host: str, err_text: str) -> str | None:
    if "LOGIN" not in err_text.upper():
        return None
    h = host.lower()
    if "office365" in h or "outlook" in h:
        return (
            "Microsoft 365 often rejects normal account passwords over IMAP (basic auth disabled). "
            "Try an app password if the account uses MFA, or ask your Microsoft 365 admin to allow "
            "IMAP and authenticated SMTP for this mailbox. This integration does not implement OAuth2."
        )
    return "Check NEWS_IMAP_USER and NEWS_IMAP_PASSWORD; the server rejected LOGIN."


def _manual_env_file(path: Path) -> None:
    """Parse KEY=VAL lines into os.environ (UTF-8 with BOM ok). Works even if python-dotenv is missing."""
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if not val:
            continue
        os.environ[key] = val


def _env_file_paths() -> tuple[Path, Path, Path]:
    """From .../backend/app/services/<this>.py: repo root, backend/, cwd .env paths."""
    here = Path(__file__).resolve()
    repo_env = here.parents[3] / ".env"
    backend_env = here.parents[2] / ".env"
    cwd_env = Path.cwd() / ".env"
    return repo_env, backend_env, cwd_env


def _news_key_names_in_file(path: Path) -> list[str]:
    """Key names only (no values) for NEWS_* lines — helps spot typos vs required names."""
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    found: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, _ = line.partition("=")
        k = key.strip()
        if k.upper().startswith("NEWS_"):
            found.add(k)
    return sorted(found)


def _load_env() -> None:
    """
    Load .env from (in order, later overrides): repo root, backend/, current working directory.
    Uses python-dotenv when installed, then always applies the same files manually so variables
    still load if dotenv is missing or skipped.
    """
    repo_env, backend_env, cwd_env = _env_file_paths()

    try:
        from dotenv import load_dotenv

        load_dotenv(repo_env, override=False)
        load_dotenv(backend_env, override=True)
        load_dotenv(cwd_env, override=True)
    except ImportError:
        pass

    _manual_env_file(repo_env)
    _manual_env_file(backend_env)
    _manual_env_file(cwd_env)


def _decode_subject(raw: str | None) -> str:
    if not raw:
        return "News item"
    parts = decode_header(raw)
    chunks: list[str] = []
    for text, enc in parts:
        if isinstance(text, bytes):
            chunks.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            chunks.append(text)
    s = "".join(chunks).strip()
    s = re.sub(r"^\s*(re|fwd)\s*:\s*", "", s, flags=re.IGNORECASE).strip()
    return s or "News item"


def _first_url_from_text(text: str) -> str | None:
    m = _URL_RE.search(text or "")
    if not m:
        return None
    u = m.group(0).rstrip(").,;]")
    return u or None


def _extract_urls_from_html(html: str) -> str | None:
    if not html or BeautifulSoup is None:
        return _first_url_from_text(html or "")
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if href.startswith("http://") or href.startswith("https://"):
            return href.split()[0]
    return _first_url_from_text(html)


def _walk_parts(msg: email.message.Message) -> tuple[str, str]:
    """Return (plain_text, html_text) best-effort."""
    plain: list[str] = []
    html: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                try:
                    t = part.get_content()
                    plain.append(t if isinstance(t, str) else str(t))
                except Exception:
                    pass
            elif ctype == "text/html":
                try:
                    t = part.get_content()
                    html.append(t if isinstance(t, str) else str(t))
                except Exception:
                    pass
    else:
        ctype = msg.get_content_type()
        try:
            body = msg.get_content()
        except Exception:
            body = ""
        if ctype == "text/html":
            html.append(str(body))
        else:
            plain.append(str(body))
    return "\n".join(plain), "\n".join(html)


def _message_dt(msg: email.message.Message) -> datetime:
    raw = msg.get("Date")
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def sync_inbox_to_store() -> dict[str, Any]:
    """
    Connect over IMAP SSL, read UNSEEN messages, extract fields, store, mark \\Seen.
    Returns counts for logging / API (no secrets).
    """
    _load_env()
    host = (os.getenv("NEWS_IMAP_HOST") or "").strip()
    user = (os.getenv("NEWS_IMAP_USER") or "").strip()
    password = (os.getenv("NEWS_IMAP_PASSWORD") or "").strip()
    folder = (os.getenv("NEWS_IMAP_FOLDER") or "INBOX").strip() or "INBOX"
    port = int(os.getenv("NEWS_IMAP_PORT") or "993")

    if not host or not user or not password:
        repo_env, backend_env, cwd_env = _env_file_paths()
        return {
            "ok": False,
            "error": "IMAP not configured (NEWS_IMAP_HOST / NEWS_IMAP_USER / NEWS_IMAP_PASSWORD)",
            "inserted": 0,
            "hint": "Use exact names NEWS_IMAP_HOST, NEWS_IMAP_USER, NEWS_IMAP_PASSWORD in backend/.env. Run sync from the backend folder so .env is found.",
            "checked_files": {
                "repo_dotenv": str(repo_env),
                "repo_dotenv_exists": repo_env.is_file(),
                "backend_dotenv": str(backend_env),
                "backend_dotenv_exists": backend_env.is_file(),
                "cwd_dotenv": str(cwd_env),
                "cwd_dotenv_exists": cwd_env.is_file(),
            },
            "news_keys_found_in_backend_env": _news_key_names_in_file(backend_env),
            "seen": {"host": bool(host), "user": bool(user), "password": bool(password)},
        }

    inserted = 0
    examined = 0
    errors: list[str] = []

    try:
        M = imaplib.IMAP4_SSL(host, port)
        M.login(user, password)
        typ, _ = M.select(folder, readonly=False)
        if typ != "OK":
            M.logout()
            return {"ok": False, "error": f"Could not select folder {folder}", "inserted": 0}

        typ, data = M.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            M.logout()
            return {"ok": True, "inserted": 0, "examined": 0, "message": "No unseen messages"}

        for num in data[0].split():
            examined += 1
            typ, msg_data = M.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            chunk = msg_data[0]
            raw_bytes: bytes | None
            if isinstance(chunk, tuple) and len(chunk) >= 2 and isinstance(chunk[1], (bytes, bytearray)):
                raw_bytes = bytes(chunk[1])
            elif isinstance(chunk, (bytes, bytearray)):
                raw_bytes = bytes(chunk)
            else:
                continue
            msg = email.message_from_bytes(raw_bytes)
            mid = (msg.get("Message-ID") or f"no-id-{num.decode()}").strip()
            headline = _decode_subject(msg.get("Subject"))
            plain, html = _walk_parts(msg)
            url = _extract_urls_from_html(html) if html.strip() else None
            if not url:
                url = _first_url_from_text(plain)
            if not url:
                errors.append(f"skip {mid}: no URL found")
                try:
                    M.store(num, "+FLAGS", "\\Seen")
                except Exception:
                    pass
                continue
            received_at = _message_dt(msg).isoformat()
            if upsert_story(message_id=mid, headline=headline, url=url, received_at=received_at):
                inserted += 1
            try:
                M.store(num, "+FLAGS", "\\Seen")
            except Exception:
                pass

        M.logout()
    except Exception as exc:  # noqa: BLE001
        err_text = _imap_error_message(exc)
        out: dict[str, Any] = {
            "ok": False,
            "error": err_text,
            "inserted": inserted,
            "examined": examined,
        }
        hint = _login_failed_hint(host, err_text)
        if hint:
            out["hint"] = hint
        return out

    return {
        "ok": True,
        "inserted": inserted,
        "examined": examined,
        "errors": errors[:20],
    }
