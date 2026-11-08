"""Headless-Chromium client for FantasyPros.

Login is manual: `python fp_client.py login` opens a visible browser at the
sign-in page, you sign in yourself (including any verification prompt), and the
script saves the resulting session cookies to .fp_session.json (chmod 600,
gitignored). Later runs reuse that session headlessly. Credentials are never
typed or stored by the script.

API calls run inside the logged-in page so they carry the same cookies and
browser fingerprint the site's own JavaScript uses.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from playwright.sync_api import BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent
SESSION_FILE = ROOT / ".fp_session.json"
BASE = "https://www.fantasypros.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
LOGIN_WAIT_SECONDS = 300


class FPError(RuntimeError):
    """Raised for session and API failures with a message safe to show the user."""


def load_config() -> dict:
    load_dotenv(ROOT / ".env")
    return {
        "headless": os.environ.get("FP_HEADLESS", "true").lower() != "false",
        "season": os.environ.get("FP_SEASON") or None,
        "week": os.environ.get("FP_WEEK") or None,
    }


def _is_logged_in(page: Page) -> bool:
    """Ask the site whether the current session is authenticated."""
    data = page.evaluate(
        """async () => {
            const r = await fetch('/api/c1/user-info.php', {credentials: 'include'});
            return {status: r.status, text: await r.text()};
        }"""
    )
    if data["status"] != 200:
        return False
    try:
        info = json.loads(data["text"])
    except json.JSONDecodeError:
        return False
    return bool(info.get("is_logged_in") or info.get("user_id") or info.get("id"))


def manual_login() -> None:
    """Open a visible browser, wait for the user to sign in, then save the session."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()
        page.goto(f"{BASE}/accounts/signin/", wait_until="domcontentloaded")
        print("Sign in to FantasyPros in the browser window (complete any check).")
        print(f"Waiting up to {LOGIN_WAIT_SECONDS // 60} minutes for sign-in to finish…")
        deadline = time.time() + LOGIN_WAIT_SECONDS
        while time.time() < deadline:
            if page.is_closed():
                break
            try:
                if "/accounts/signin" not in page.url and _is_logged_in(page):
                    ctx.storage_state(path=str(SESSION_FILE))
                    SESSION_FILE.chmod(0o600)
                    print(f"Session saved to {SESSION_FILE.name} (mode 600). You can close the window.")
                    browser.close()
                    return
            except Exception:
                pass  # page mid-navigation; keep polling
            time.sleep(2)
        browser.close()
    raise FPError("Sign-in was not detected. Run `python fp_client.py login` again.")


@contextmanager
def fp_session(cfg: dict | None = None) -> Iterator[Page]:
    """Yield a logged-in Page using the saved session. Raises FPError if none is valid."""
    if not SESSION_FILE.exists():
        raise FPError("No saved session. Run `python fp_client.py login` and sign in.")
    cfg = cfg or load_config()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=cfg["headless"])
        ctx: BrowserContext = browser.new_context(
            user_agent=USER_AGENT, storage_state=str(SESSION_FILE)
        )
        page = ctx.new_page()
        try:
            page.goto(f"{BASE}/nfl/rankings/qb.php", wait_until="domcontentloaded")
            if not _is_logged_in(page):
                raise FPError(
                    "Saved session has expired. Run `python fp_client.py login` again."
                )
            yield page
        finally:
            browser.close()


def page_json_var(html: str, name: str) -> dict:
    """Parse an inline `var <name> = {...};` JSON blob embedded in a rankings page."""
    m = re.search(rf"var {re.escape(name)} = ", html)
    if not m:
        raise FPError(f"'{name}' not found on page; the site layout may have changed")
    obj, _ = json.JSONDecoder().raw_decode(html[m.end():])
    return obj


def api_get(page: Page, path: str) -> object:
    """GET a site API path from inside the logged-in page context."""
    res = page.evaluate(
        """async (p) => {
            const r = await fetch(p, {credentials: 'include',
                headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}});
            return {status: r.status, text: await r.text()};
        }""",
        path,
    )
    if res["status"] != 200:
        raise FPError(f"GET {path} returned HTTP {res['status']}")
    try:
        return json.loads(res["text"])
    except json.JSONDecodeError as exc:
        raise FPError(f"GET {path} did not return JSON") from exc


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "login":
        manual_login()
    else:
        print("usage: python fp_client.py login", file=sys.stderr)
        sys.exit(2)
