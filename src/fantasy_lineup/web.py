"""Web UX backend: the rankings, expert picks, and injuries the FantasyPros site shows.

Selected with FP_SOURCE=web in .env. The default source is the public API in advisor.py. This
module reads the site's own JSON endpoints (partners.fantasypros.com for rankings and expert groups)
and the injury table on www.fantasypros.com, so the two sources can be compared.

Sessions come from one of two approaches, chosen when the session is set up:
  mitmproxy  import the cookies that src/fantasy_lineup/capture_addon.py saved to var/capture/auth.json  (default)
  login      sign in with FANTASYPROS_USERNAME / FANTASYPROS_PASSWORD from .env (Playwright)
Both write var/session.json (Playwright storage-state format, mode 600, gitignored). The cookies are
attached to requests when present, so the data matches what a signed-in browser sees. The rankings
endpoints also answer without a login.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from fantasy_lineup.client import _is_logged_in, page_json_var
from fantasy_lineup.paths import AUTH_CAPTURE, SESSION_FILE, WEB_CACHE_DIR

PARTNERS = "https://partners.fantasypros.com/api/v1"
WWW = "https://www.fantasypros.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
MIN_INTERVAL = 1.0          # seconds between live requests to the site
RANKINGS_TTL = 6 * 3600     # same freshness as the public API client
INJURY_TTL = 3600
LOGIN_WAIT_SECONDS = 180


class WebError(RuntimeError):
    """A web UX failure with a message safe to show the user."""


_last_call = 0.0


def _cookie_header() -> str:
    """Cookie header built from the saved session, or '' when there is none. Never logged or cached."""
    if not SESSION_FILE.exists():
        return ""
    state = json.loads(SESSION_FILE.read_text())
    return "; ".join(f"{c['name']}={c['value']}" for c in state.get("cookies", [])
                     if "fantasypros.com" in c.get("domain", ""))


def _fetch(url: str, ttl: int, cookie: str = "") -> bytes:
    """GET a site URL and return the body. Responses are cached on disk for `ttl` seconds."""
    global _last_call
    cache_file = WEB_CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest() + ".bin")
    if ttl and cache_file.exists() and time.time() - cache_file.stat().st_mtime < ttl:
        return cache_file.read_bytes()

    pause = MIN_INTERVAL - (time.time() - _last_call)
    if pause > 0:
        time.sleep(pause)
    headers = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9",
               "Referer": f"{WWW}/nfl/rankings/"}
    if cookie:
        headers["Cookie"] = cookie
    _last_call = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
            body = r.read()
    except urllib.error.HTTPError as exc:
        raise WebError(f"{urllib.parse.urlsplit(url).path} returned HTTP {exc.code}") from exc
    if ttl:
        WEB_CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        cache_file.write_bytes(body)
        cache_file.chmod(0o600)
    return body


def _text(fragment: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _write_session(state: dict) -> None:
    # Create the file with mode 600 from the start so the cookies are never world-readable
    fd = os.open(SESSION_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(state, fh)
    SESSION_FILE.chmod(0o600)


def session_saved() -> bool:
    return SESSION_FILE.exists()


def session_logged_in() -> bool:
    """True when the saved session is accepted by the site (same check as client.py)."""
    cookie = _cookie_header()
    if not cookie:
        return False
    try:
        info = json.loads(_fetch(f"{WWW}/api/c1/user-info.php", ttl=0, cookie=cookie))
    except (WebError, json.JSONDecodeError):
        return False
    return bool(info.get("is_logged_in") or info.get("user_id") or info.get("id"))


def import_capture_session() -> None:
    """Approach 'mitmproxy': turn the cookies from the browser capture into var/session.json.

    The capture file holds the full request headers, so it is deleted once the cookies are saved.
    """
    if not AUTH_CAPTURE.exists():
        raise WebError("No browser capture found (var/capture/auth.json). Run the mitmproxy capture first.")
    headers = json.loads(AUTH_CAPTURE.read_text()).get("headers", {})
    cookie = next((v for k, v in headers.items() if k.lower() == "cookie"), "")
    cookies = []
    for part in cookie.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            cookies.append({"name": name, "value": value, "domain": ".fantasypros.com", "path": "/",
                            "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"})
    if not cookies:
        raise WebError("The capture has no cookies. Sign in in the captured browser, then capture again.")
    _write_session({"cookies": cookies, "origins": []})
    AUTH_CAPTURE.unlink()


def login_with_env(status: Callable[[str], None] = print) -> None:
    """Approach 'login': sign in with the .env credentials in a visible browser and save the session.

    The browser stays open so a verification challenge (Turnstile) can be completed by hand.
    The password is read from the environment and is never printed or stored.
    """
    from playwright.sync_api import sync_playwright

    user = os.environ.get("FANTASYPROS_USERNAME", "").strip()
    password = os.environ.get("FANTASYPROS_PASSWORD", "")
    if not user or not password:
        raise WebError("FANTASYPROS_USERNAME and FANTASYPROS_PASSWORD must be set in .env for the login approach.")
    status("Signing in to FantasyPros with the .env credentials (complete any verification in the window)")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            ctx = browser.new_context(user_agent=UA)
            page = ctx.new_page()
            page.goto(f"{WWW}/accounts/signin/", wait_until="domcontentloaded")
            page.fill('input[name="username"]', user)
            page.fill('input[name="password"]', password)
            page.keyboard.press("Enter")
            deadline = time.time() + LOGIN_WAIT_SECONDS
            while time.time() < deadline:
                if page.is_closed():
                    break
                try:
                    if "/accounts/signin" not in page.url and _is_logged_in(page):
                        ctx.storage_state(path=str(SESSION_FILE))
                        SESSION_FILE.chmod(0o600)
                        return
                except Exception:
                    pass  # page mid-navigation; keep polling
                time.sleep(2)
        finally:
            browser.close()
    raise WebError("Sign-in was not detected. Check the .env credentials and try again.")


class WebBackend:
    """Same method names and return shapes as the public-API functions in advisor.py."""

    name = "web"

    def __init__(self, year: str, status: Callable[[str], None] = print):
        self.year = year
        self.status = status
        self.cookie = _cookie_header()

    def current_week(self) -> int | None:
        """The NFL week the site's weekly QB rankings page is serving (ecrData.week)."""
        page = _fetch(f"{WWW}/nfl/rankings/qb.php", RANKINGS_TTL, self.cookie).decode("utf-8", "replace")
        week = page_json_var(page, "ecrData").get("week")
        return int(week) if str(week or "").isdigit() and int(week) > 0 else None

    def expert_ids(self, kind: str, grp: str, n: int, week: int | None) -> tuple[list[int], dict[int, str]]:
        """Top n experts for this group, from the site's named accuracy list ('Top N QB', 'Top N Overall').

        The site publishes the list, not a numeric score. The list is the site's own selection, so it
        can differ from the public API's accuracy_weekly ranking.
        """
        params = {"cors": 1, "sport": "NFL", "type": "weekly" if kind == "weekly" else "ros",
                  "position": "ALL" if grp == "FLX" else grp, "scoring": "STD",
                  "week": week if kind == "weekly" else 0}
        data = self._json(f"{PARTNERS}/expert-groups.php", params, RANKINGS_TTL)
        title = f"Top {n} {'Overall' if grp == 'FLX' else grp}"
        options = (data.get("expert_groups", {}).get("accuracy_weekly") or {}).get("options", [])
        option = next((o for o in options if o.get("title") == title), None)
        if option is None:
            raise WebError(f"the site has no '{title}' accuracy group for {grp} ({kind})")
        names = {int(e["id"]): f"{e['name']} ({e.get('site') or 'no site'})" for e in data.get("expert_data", [])}
        ids = [int(x) for x in option.get("experts", [])][:n]
        return ids, {i: names.get(i, str(i)) for i in ids}

    def consensus(self, kind: str, grp: str, ids: list[int], week: int | None,
                  warnings: list[str] | None = None) -> dict[int, dict]:
        """{player_id: {...}} for the consensus list filtered to these experts, same shape as the API client."""
        params = {"sport": "NFL", "year": self.year, "position": "ALL" if grp == "FLX" else grp,
                  "type": "weekly" if kind == "weekly" else "ros", "scoring": "STD",
                  "experts": "available", "week": week if kind == "weekly" else 0,
                  "filters": ":".join(map(str, ids))}
        data = self._json(f"{PARTNERS}/consensus-rankings.php", params, RANKINGS_TTL)
        if warnings is not None:
            used = {int(x) for x in (data.get("experts_available") or {}).get("included", [])}
            if used and used != set(ids):
                warnings.append(f"{grp}: site used {len(used)} of {len(ids)} requested experts "
                                f"(not used: {sorted(set(ids) - used)})")
        out = {}
        for p in data.get("players", []):
            out[int(p["player_id"])] = {
                "name": p["player_name"],
                "pos": p["player_position_id"],
                "team": p["player_team_id"],
                "rank": int(p["rank_ecr"]),
                "opp": p.get("player_opponent"),
                "bye": p.get("player_bye_week"),
                "url": p.get("player_page_url"),
            }
        return out

    def injuries(self, player_ids: list[int], week: int | None) -> dict[int, list[str]]:
        """Status and injury from the site's injury table, as 'Status | Injury' entries.

        The table only shows the current report, so `week` is ignored. It has no practice reports or
        comments, so only the status and injury fields are returned. Players not in the table have no entry.
        """
        if not player_ids:
            return {}
        wanted = set(player_ids)
        page = _fetch(f"{WWW}/nfl/players/injuries.php", INJURY_TTL, self.cookie).decode("utf-8", "replace")
        out: dict[int, list[str]] = {}
        for row in re.finditer(r"<tr>(.*?)</tr>", page, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)
            if len(cells) < 3:
                continue
            m = re.search(r"fp-id-(\d+)", cells[0])
            if not m or int(m.group(1)) not in wanted:
                continue
            text = " | ".join(b for b in (_text(cells[1]), _text(cells[2])) if b)
            if text:
                out.setdefault(int(m.group(1)), []).append(text)
        return out

    def _json(self, url: str, params: dict, ttl: int):
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        body = _fetch(f"{url}?{qs}", ttl, self.cookie)
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise WebError(f"{urllib.parse.urlsplit(url).path} did not return JSON") from exc
