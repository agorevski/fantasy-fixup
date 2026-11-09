"""Lineup, waiver, and drop analysis for a FantasyPros-synced league.

Read-only: fetches FantasyPros rankings, projections, injuries, and news, plus your league roster
and matchup, and prints recommendations. It never changes your roster. Every input comes from
FantasyPros (the public API, the website, and the My Playbook league feed).

Usage:
    .venv/bin/python -m fantasy_lineup.advisor weekly         # lineup, close calls, gated add/drops
    .venv/bin/python -m fantasy_lineup.advisor ros            # rest-of-season add/drop view
    .venv/bin/python -m fantasy_lineup.advisor grade [week]   # score a past week's advice
    .venv/bin/python -m fantasy_lineup.advisor discover       # list leagues captured by mitmproxy

Config (.env): FP_SOURCE (api or web, default api), FP_API_KEY (required for api; on web it adds
practice reports, news, and recent points), FP_LEAGUE_KEY (required), FP_TEAM_ID (default 3),
FP_SEASON (default 2026), FP_WEEK (optional). FP_SOURCE=web reads rankings from the website (web.py).

Expert selection:
    weekly  QB/K/DST -> the top 10 experts at that position by accuracy
            FLX      -> the top 20 overall
    ros     every group uses the full consensus. Accuracy is measured on weekly picks, and most
            accurate weekly experts publish no ROS ranks, so filtering ROS by it leaves 2-3 experts.
"""

import contextvars
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

from fantasy_lineup import decisions
from fantasy_lineup.decisions import unavailable
from fantasy_lineup.lineup import parse_slots
from fantasy_lineup.paths import API_CACHE_DIR, CACHE_DIR, CAPTURE_DIR, ENV_FILE, HISTORY_DIR
from fantasy_lineup.rankings import consensus_info, parse_players

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
API = "https://api.fantasypros.com/public/v2/json"
MPB = "https://mpbnfl.fantasypros.com"

# Free-tier limits are not published, so the client stays conservative:
# pace live calls, retry 429s with backoff, and reuse responses cached on disk.
MIN_INTERVAL = 1.5          # seconds between live API requests
MAX_RETRIES = 3             # retries per request on HTTP 429
MAX_RETRY_AFTER = 120       # longer waits than this abort the run instead of sleeping
RANKINGS_TTL = 6 * 3600     # seconds a cached rankings/experts response stays fresh
INJURY_TTL = 3600           # injury reports and news change more often
FLEX_POS = {"RB", "WR", "TE"}
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]
FREE_AGENTS_PER_LIST = 10   # free agents taken from each of the weekly and ROS lists

# analysis type -> position group -> (accuracy key, number of experts; None = full consensus)
GROUPS = {
    "weekly": {"QB": ("QB", 10), "K": ("K", 10), "DST": ("DST", 10), "FLX": ("ALL", 20)},
    "ros": {"QB": ("QB", None), "K": ("K", None), "DST": ("DST", None), "FLX": ("ALL", None)},
}

# Public API ranking types to try, in order. The spec lists only 'WW' (waiver wire) for in-season
# use, and waiver-wire lists leave out rostered players, so 'WEEKLY' is tried first.
API_TYPES = {"weekly": ("WEEKLY", "WW"), "ros": ("ROS",)}


class RateLimited(RuntimeError):
    """HTTP 429 that did not clear after retries (or asked us to wait too long)."""


class ApiHttpError(RuntimeError):
    """A non-429 HTTP error from the public API."""

    def __init__(self, msg: str, code: int):
        super().__init__(msg)
        self.code = code


# Where status() sends its lines. The MCP server sets this per tool call so the client sees live
# progress; the CLI leaves it unset and status() prints to stderr. A ContextVar keeps concurrent
# calls from receiving each other's lines.
status_sink: contextvars.ContextVar[Callable[[str], None] | None] = contextvars.ContextVar(
    "status_sink", default=None)


def status(msg: str) -> None:
    """Report a stage or a wait, e.g. 'Loading experts' or 'rate limited; waiting 10s'."""
    sink = status_sink.get()
    if sink:
        sink(msg)
    else:
        print(f"  {msg}", file=sys.stderr)


def season() -> str:
    # An empty FP_SEASON= line in .env would otherwise override the default
    return os.environ.get("FP_SEASON", "").strip() or "2026"


def has_api_key() -> bool:
    return bool(os.environ.get("FP_API_KEY", "").strip())


def api_key() -> str:
    key = os.environ.get("FP_API_KEY", "").strip()
    if not key:
        raise SystemExit("FP_API_KEY missing from .env (copy it from .env.example and add your key)")
    return key


def normalize_scoring(value: str | None) -> str:
    """The league feed's scoring label as an API scoring type: STD, PPR, or HALF."""
    v = (value or "").upper()
    if "HALF" in v or "0.5" in v:
        return "HALF"
    if "PPR" in v:
        return "PPR"
    return "STD"


_last_call = 0.0


def _retry_after(exc: urllib.error.HTTPError) -> int | None:
    value = (exc.headers.get("Retry-After") or "").strip()
    return int(value) if value.isdigit() else None


_limited_until = 0.0  # after a 429 that did not clear, further live calls fail fast until this time
RATE_LIMIT_COOLDOWN = 600


def api_get(path: str, params: dict | None = None, ttl: int = RANKINGS_TTL, retries: int = MAX_RETRIES):
    """GET a path under the official public API. Empty params are dropped from the query string.

    Responses are cached on disk for `ttl` seconds, so a rerun after a rate limit does not repeat
    calls that already succeeded. The API key is sent in a header only and never written to the cache.
    Optional lookups pass retries=0 so a spent quota never makes the run wait.
    """
    global _last_call, _limited_until
    qs = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")})
    url = f"{API}/{path}" + (f"?{qs}" if qs else "")
    cache_file = API_CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < ttl:
        return json.loads(cache_file.read_text())
    if time.time() < _limited_until:
        raise RateLimited(f"FantasyPros API is rate limited (HTTP 429); skipped {path}")

    key = api_key()
    for attempt in range(retries + 1):
        pause = MIN_INTERVAL - (time.time() - _last_call)
        if pause > 0:
            time.sleep(pause)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json",
                                                   "x-api-key": key})
        _last_call = time.time()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = _retry_after(exc) or 10 * 3 ** attempt
                if attempt == retries or wait > MAX_RETRY_AFTER:
                    _limited_until = time.time() + RATE_LIMIT_COOLDOWN
                    raise RateLimited(f"FantasyPros API {path} is rate limited (HTTP 429)") from exc
                status(f"rate limited on {path}; waiting {wait}s (retry {attempt + 1}/{retries})")
                time.sleep(wait)
                continue
            hint = {401: " (check FP_API_KEY)", 403: " (check FP_API_KEY and plan access)"}.get(exc.code, "")
            raise ApiHttpError(f"FantasyPros API {path} returned HTTP {exc.code}{hint}", exc.code) from exc
        data = json.loads(body)
        API_CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data))
        cache_file.chmod(0o600)
        return data
    raise RuntimeError("unreachable")  # the loop always returns or raises


def get_json(url: str):
    """League roster and matchup feeds (My Playbook). Not part of the public API."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def source_name() -> str:
    value = os.environ.get("FP_SOURCE", "").strip().lower() or "api"
    if value not in ("api", "web"):
        raise SystemExit(f"FP_SOURCE must be 'api' or 'web', not '{value}' (check .env)")
    return value


class ApiBackend:
    """The official public API. Same method names as web.WebBackend."""

    name = "api"

    def __init__(self, scoring: str = "STD"):
        self.scoring = scoring

    def current_week(self) -> int | None:
        return api_week()

    def expert_ids(self, kind: str, grp: str, n: int | None, week: int | None) -> tuple[list[int], dict[int, str]]:
        if n is None:
            return [], {}
        acc_key = GROUPS[kind][grp][0]
        # Experts are fetched per position and never served from cache, so a stale expert set
        # cannot carry over from an earlier run.
        experts = api_get(f"nfl/{season()}/rankings/experts", {
            "position": None if grp == "FLX" else grp,
            "type": "WW",
            "scoring": "STD",
            "include_overall": "true",
        }, ttl=0).get("experts", [])
        return top_experts(experts, acc_key, n)

    def consensus(self, kind: str, grp: str, ids: list[int], week: int | None) -> tuple[dict[int, dict], dict]:
        return consensus(kind, grp, ids, week, self.scoring)

    def injuries(self, player_ids: list[int], week: int | None) -> dict[int, list[str]]:
        return injuries_for(player_ids, week)


def make_backend(scoring: str = "STD"):
    """The data source chosen by FP_SOURCE, read from the environment at call time."""
    if source_name() == "web":
        from fantasy_lineup import web  # imported lazily so api-only runs do not load the browser client
        return web.WebBackend(season(), status, scoring)
    return ApiBackend(scoring)


def history_dir(source: str) -> Path:
    """Weekly snapshots are kept per source so FLEX comparisons never mix the two sources."""
    return HISTORY_DIR / "web" if source == "web" else HISTORY_DIR


def top_experts(experts: list[dict], acc_key: str, n: int) -> tuple[list[int], dict[int, str]]:
    """The n experts with the highest accuracy_weekly score for acc_key, and their display names."""
    scored = [e for e in experts if (e.get("accuracy_weekly") or {}).get(acc_key) is not None]
    scored.sort(key=lambda e: e["accuracy_weekly"][acc_key], reverse=True)
    top = scored[:n]
    ids = [int(e["expert_id"]) for e in top]
    names = {int(e["expert_id"]): f"{e['name']} ({e.get('source') or 'no site'})" for e in top}
    return ids, names


_api_type: dict[str, str] = {}  # analysis kind -> the ranking type the API accepted this process


def consensus(kind: str, grp: str, ids: list[int], week: int | None,
              scoring: str = "STD") -> tuple[dict[int, dict], dict]:
    """({fpId: player}, info) for the consensus list, filtered to the given experts (all when empty)."""
    params = {
        "position": grp,
        "scoring": scoring,
        "filters": ":".join(map(str, ids)),
        "experts": "available",
        "week": week if kind == "weekly" else None,
    }
    types = (_api_type[kind],) if kind in _api_type else API_TYPES[kind]
    data = None
    for i, rtype in enumerate(types):
        try:
            data = api_get(f"nfl/{season()}/consensus-rankings", {**params, "type": rtype})
            _api_type[kind] = rtype
            break
        except ApiHttpError as exc:
            if exc.code != 400 or i == len(types) - 1:
                raise
    info = consensus_info(data, ids, grp, "API")
    if kind == "weekly" and "waiver" in (info.get("type_name") or "").lower():
        info["warnings"].append(f"{grp}: the API served waiver-wire rankings, not weekly rankings, so "
                                "rostered players show as unranked; use FP_SOURCE=web for the lineup")
    return parse_players(data), info


def injuries_for(player_ids: list[int], week: int | None, retries: int = MAX_RETRIES) -> dict[int, list[str]]:
    """Status, injury, practice reports, play probability, and comment for the players, in one API call."""
    if not player_ids:
        return {}
    data = api_get("nfl/injuries", {
        "year": season(),
        "week": week,
        "player_ids": ":".join(map(str, sorted(set(player_ids)))),
    }, ttl=INJURY_TTL, retries=retries)
    out: dict[int, list[str]] = {}
    for inj in data.get("injuries", []):
        bits = [inj.get("status"), inj.get("injury_type")]
        practice = [inj.get(k) for k in ("practice_1", "practice_2", "practice_3")
                    if inj.get(k) and inj.get(k) != "--"]
        if practice:
            bits.append("practice " + "/".join(practice))
        prob = inj.get("probability_of_playing")
        if prob not in (None, ""):
            try:
                bits.append(f"play prob {round(float(prob) * 100)}%")
            except ValueError:
                pass
        if inj.get("injury_update_date"):
            bits.append(f"updated {str(inj['injury_update_date'])[:10]}")
        bits.append(inj.get("comment"))
        text = " | ".join(str(b) for b in bits if b)
        if text:
            out.setdefault(int(inj["player_id"]), []).append(text)
    return out


def news_for(fp_id: int, limit: int = 3) -> list[dict]:
    """The latest FantasyPros news items for one player: date, title, impact, link."""
    data = api_get("nfl/news", {"fpid": fp_id, "limit": limit}, ttl=INJURY_TTL, retries=0)
    items = []
    for n in data.get("items", []):
        created = str(n.get("created") or "")[:10]
        try:
            date_ord = dt.date.fromisoformat(created).toordinal()
        except ValueError:
            date_ord = None
        items.append({"date": created, "date_ord": date_ord, "title": n.get("title"),
                      "impact": (n.get("impact") or "")[:400], "link": n.get("link")})
    return items


def player_points(start: int, end: int, scoring: str = "STD") -> dict[int, dict[int, float]]:
    """Actual fantasy points by week, {fpId: {week: points}}, for weeks start..end."""
    if end < start or end < 1:
        return {}
    data = api_get(f"nfl/{season()}/player-points", {"start": max(1, start), "end": end,
                                                     "scoring": scoring, "min": "true"}, retries=0)
    out: dict[int, dict[int, float]] = {}
    for p in data.get("players", []):
        weeks = {int(w): float(v) for w, v in (p.get("weeks") or {}).items()
                 if str(w).isdigit() and v is not None}
        out[int(p["player_id"])] = weeks
    return out


def league_info(key: str) -> dict:
    """Owners of every rostered player, plus the league's scoring and starting slots."""
    data = get_json(f"{MPB}/api/getLeagueRostersJSON?key={key}")
    owners = {}
    for t in data["teams"]:
        for fp_id in t["players"]:
            owners[int(fp_id)] = t["id"]
    return {"owners": owners, "scoring": normalize_scoring(data.get("scoring")),
            "slots": parse_slots(data.get("positions")), "name": data.get("nickname") or data.get("name")}


def league_owners(key: str) -> dict[int, str]:
    """Map every rostered fpId in the league to the team id that owns it."""
    return league_info(key)["owners"]


_IN_PROGRESS = ("Q1", "Q2", "Q3", "Q4", "OT", "HALF", "FINAL", "END")


def _matchup_started(p: dict) -> bool:
    return bool(p.get("isGameOver")) or str(p.get("gameStatus") or "").upper().startswith(_IN_PROGRESS)


def my_matchup(key: str, team_id: str) -> dict:
    """Your starters and bench, the slot each starter fills, and the matchup from FantasyPros' feed."""
    m = get_json(f"{MPB}/json/matchup?matchup&key={key}&teamId={team_id}&from=web")["matchup"]
    roster = []
    for slot, block in (("starter", m["team1"]["starters"]), ("bench", m["team1"]["bench"])):
        for p in block:
            roster.append({
                "fpId": int(p["fpId"]),
                "name": p.get("full") or p.get("shortName"),
                "pos": p.get("real_position") or p.get("position"),
                "slot": slot,
                "lineup_slot": p.get("position") if slot == "starter" else "BN",
                "team": p.get("real_team"),
                "proj_matchup": p.get("original_proj", p.get("new_proj")),
                "game": p.get("gameStatus"),
                "opp": p.get("opponent"),
                "sos": p.get("sos"),
                "game_started": _matchup_started(p),
                "url": p.get("playerPage"),
            })
    opp = m.get("team2") or {}
    wp = m.get("win_probability")
    return {
        "roster": roster,
        "win_prob": float(wp) if isinstance(wp, (int, float)) else None,
        "pre_game": m.get("isPreGame"),
        "my_proj": m["team1"].get("original_proj"),
        "opponent": {"name": opp.get("name"), "proj": opp.get("original_proj"), "record": opp.get("record")},
    }


def my_roster(key: str, team_id: str) -> list[dict]:
    """Starters and bench for one team, from the matchup feed (same data the site shows)."""
    return my_matchup(key, team_id)["roster"]


def group_of(pos: str) -> str:
    """Group for ranking: RB/WR/TE (incl. multi-position like 'WR/RB/TE') share the FLX list."""
    primary = (pos or "").split("/")[0]
    return "FLX" if primary in FLEX_POS else primary


def rank_in(lists: dict, fp_id: int, grp: str) -> int | None:
    entry = lists.get(grp, {}).get(fp_id)
    return entry["rank"] if entry else None


def fmt_rank(r: int | None) -> str:
    return f"#{r}" if r is not None else "unranked"


def _locked(info: dict, now: float) -> bool:
    """The player's game has started (from the rankings' kickoff time and game status)."""
    if (info.get("game_status") or "").lower() in ("inprogress", "closed", "final", "complete"):
        return True
    return bool(info.get("kickoff")) and info["kickoff"] <= now


def _merge(p: dict, grp: str, lists: dict, pos_lists: dict, ros_lists: dict, week: int | None,
           now: float, current_week: bool) -> dict:
    """Fill one player dict with weekly, per-position, and ROS ranking fields."""
    info = lists.get(grp, {}).get(p["fpId"]) or {}
    pos_info = pos_lists.get((p.get("pos") or "").split("/")[0], {}).get(p["fpId"]) or {}
    ros = ros_lists.get(grp, {}).get(p["fpId"]) or {}
    p["group"] = grp
    p["rank"] = info.get("rank")
    for k in ("rank_min", "rank_max", "rank_ave", "rank_std", "ecr_delta", "owned_yahoo", "note"):
        p[k] = info.get(k)
    p["pos_rank"] = pos_info.get("pos_rank") or info.get("pos_rank")
    p["grade"] = pos_info.get("grade") or info.get("grade")
    p["opp"] = info.get("opp") or pos_info.get("opp") or p.get("opp")
    p["bye"] = info.get("bye") or ros.get("bye")
    p["url"] = info.get("url") or ros.get("url") or p.get("url")
    if pos_info.get("proj") is not None or info.get("proj") is not None:
        p["proj"], p["proj_src"] = (pos_info.get("proj") if pos_info.get("proj") is not None
                                    else info.get("proj")), "FP rankings-to-projections"
    elif p.get("proj_matchup") is not None:
        p["proj"], p["proj_src"] = float(p["proj_matchup"]), "FP matchup projection"
    else:
        p["proj"], p["proj_src"] = None, None
    p["ros_rank"], p["ros_ave"], p["ros_std"], p["ros_proj"] = (ros.get("rank"), ros.get("rank_ave"),
                                                                ros.get("rank_std"), ros.get("proj"))
    p["bye_now"] = on_bye_week(p, week)
    started = _locked({**pos_info, **info}, now) or (current_week and p.get("game_started"))
    p["locked"] = bool(started)
    return p


def on_bye_week(info: dict, week: int | None) -> bool:
    """True when this player's team is on a bye in the given week."""
    return bool(week) and str(info.get("bye")) == str(week)


on_bye = on_bye_week


def analyse(kind: str, week: int | None) -> dict:
    key = os.environ.get("FP_LEAGUE_KEY", "").strip()
    team_id = os.environ.get("FP_TEAM_ID", "3").strip()
    if not key:
        raise SystemExit("FP_LEAGUE_KEY missing from .env")
    if source_name() == "api":
        api_key()  # fail fast if the API key is not configured

    status("Reading the league (scoring, starting slots, owners)")
    league = league_info(key)
    src = make_backend(league["scoring"])
    current = src.current_week()
    if kind == "weekly":
        week = week or current
    now = time.time()

    notes: list[str] = []
    lists: dict[str, dict] = {}
    coverage: dict[str, dict] = {g: {} for g in GROUPS["weekly"]}
    expert_ids_by_grp: dict[str, list[int]] = {}
    for grp, (acc_key, n) in GROUPS[kind].items():
        status(f"Loading {grp} expert pool ({src.name})")
        ids, names = src.expert_ids(kind, grp, n, week)
        if n is not None and len(ids) < n:
            notes.append(f"{grp}: only {len(ids)} of the {n} requested experts have a {acc_key} score")
        status(f"Building {grp} {kind} consensus from "
               + (f"{len(ids)} experts: " + ", ".join(f"{names[i]} [{i}]" for i in ids) if ids else "all experts"))
        expert_ids_by_grp[grp] = ids
        lists[grp], info = src.consensus(kind, grp, ids, week)
        notes += info["warnings"]
        coverage[grp]["weekly" if kind == "weekly" else "ros"] = info["experts"]

    # Bucket 2: per-position weekly lists (projections and start/sit grades are only on these),
    # and the ROS lists the add/drop gates need. Missing pieces are noted, never fatal.
    pos_lists: dict[str, dict] = {}
    ros_lists: dict[str, dict] = lists if kind == "ros" else {}
    if kind == "weekly":
        for pos in ("RB", "WR", "TE"):
            try:
                pos_lists[pos], _ = src.consensus("weekly", pos, expert_ids_by_grp["FLX"], week)
            except Exception as exc:
                notes.append(f"{pos} projections unavailable ({exc}); FLEX projections fall back to the matchup feed")
        status("Loading rest-of-season consensus for the add/drop gates")
        for grp in GROUPS["ros"]:
            try:
                ros_lists[grp], info = src.consensus("ros", grp, [], None)
                notes += info["warnings"]
                coverage[grp]["ros"] = info["experts"]
            except Exception as exc:
                notes.append(f"{grp} ROS rankings unavailable ({exc}); {grp} add/drops are held")
                coverage[grp]["ros"] = None
    for grp, cov in coverage.items():
        if cov.get("ros") is not None and cov["ros"] < decisions.MIN_EXPERTS:
            notes.append(f"{grp}: the ROS consensus has only {cov['ros']} experts; {grp} add/drops are held")

    status("Reading your roster and matchup")
    matchup = my_matchup(key, team_id)
    owners = league["owners"]
    is_current = kind == "weekly" and week == current
    weekly_lists = lists if kind == "weekly" else {}
    rows = [_merge(p, group_of(p["pos"]), weekly_lists, pos_lists, ros_lists, week, now, is_current)
            for p in matchup["roster"]]
    mine_ids = {p["fpId"] for p in rows}

    # Free agents: the best unowned players on the weekly list and on the ROS list, per group
    free_agents: dict[str, list[dict]] = {}
    for grp in GROUPS[kind]:
        picked: dict[int, dict] = {}
        for source_list in (lists.get(grp, {}), ros_lists.get(grp, {})):
            pool = sorted(((fid, info) for fid, info in source_list.items()
                           if fid not in owners and (info["pos"] in FLEX_POS if grp == "FLX" else info["pos"] == grp)),
                          key=lambda x: x[1]["rank"])
            for fid, info in pool[:FREE_AGENTS_PER_LIST]:
                picked.setdefault(fid, {"fpId": fid, "name": info["name"], "pos": info["pos"],
                                        "slot": "free agent", "team": info.get("team")})
        free_agents[grp] = [_merge(p, grp, weekly_lists, pos_lists, ros_lists, week, now, is_current)
                            for p in picked.values()]

    status("Adding injury reports")
    targets = rows + [f for fas in free_agents.values() for f in fas]
    try:
        injuries = src.injuries([t["fpId"] for t in targets], week)
        for t in targets:
            t["injury"] = injuries.get(t["fpId"], [])
    except RateLimited as exc:
        notes.append(f"injury reports rate limited ({exc}); injury status is unchecked")
        for t in targets:
            t["injury"] = ["lookup failed: rate limited"]
    except Exception as exc:
        notes.append(f"injury reports unavailable ({exc}); injury status is unchecked")
        for t in targets:
            t["injury"] = [f"lookup failed: {exc}"]

    slots = league["slots"]
    lineup = decisions.plan_lineup(rows, slots, matchup["win_prob"]) if kind == "weekly" else None

    # Per-expert weekly lists, fetched only for groups that have a candidate move (breadth check)
    per_expert: dict[str, dict] = {}

    def expert_lists(grp: str) -> dict[int, dict[int, int]]:
        if grp not in per_expert:
            status(f"Checking expert breadth for {grp} moves")
            per_expert[grp] = {e: {fid: info["rank"] for fid, info in src.consensus("weekly", grp, [e], week)[0].items()}
                               for e in expert_ids_by_grp[grp]}
        return per_expert[grp]

    def evidence(players: list[dict]) -> dict[int, dict]:
        if not has_api_key():
            raise RuntimeError("FP_API_KEY is not set, so FantasyPros news and recent points are not available")
        status("Reading FantasyPros news and recent points for the proposed moves")
        ids = sorted({p["fpId"] for p in players})
        ref_week = week or current or 1
        pts = player_points(ref_week - 3, ref_week - 1, league["scoring"])
        return {fid: {"points": pts.get(fid, {}), "news": news_for(fid)} for fid in ids}

    moves = decisions.propose_moves(
        rows, free_agents, slots, weekly=kind == "weekly", coverage=coverage,
        expert_lists=expert_lists if kind == "weekly" else None, evidence=evidence,
        today_ord=dt.date.today().toordinal(), week=week)
    notes += moves.pop("notes")
    net = decisions.net_change(rows, moves["recommended"], free_agents, slots, matchup["win_prob"]) \
        if kind == "weekly" else None
    if net and net["roster_ros_avg"][0] is not None and net["roster_ros_avg"][1] is not None \
            and net["roster_ros_avg"][1] > net["roster_ros_avg"][0]:
        for m in moves["recommended"]:
            m["missing"] = ["net change not better"]
        moves["provisional"] += moves["recommended"]
        moves["recommended"] = []

    best_picks, flex_check, prior_label, trend_info, ahead = {}, [], None, None, []
    if kind == "weekly":
        status("Picking the best available QB, K, and DST and checking byes ahead")
        label = period_label(week)
        for grp in ("QB", "K", "DST"):
            pool = [p for p in rows + free_agents.get(grp, []) if p.get("group") == grp and decisions.startable(p)
                    and p.get("rank") is not None and (p["fpId"] not in owners or str(owners[p["fpId"]]) == team_id)]
            if pool:
                best = min(pool, key=lambda x: x["rank"])
                best_picks[grp] = {"name": best["name"], "rank": best["rank"], "fpId": best["fpId"],
                                   "proj": best.get("proj"), "mine": best["fpId"] in mine_ids}
        prior = load_prior(kind, label, history_dir(src.name))
        if prior:
            prior_label = prior["period"]
            injury_of = {p["fpId"]: p.get("injury", []) for p in targets}
            flex_check = compare_flex(prior, rows, lists["FLX"], owners, team_id, week, injury_of)
            ros_of = {fid: info["rank"] for fid, info in ros_lists.get("FLX", {}).items()}
            for g in ("QB", "K", "DST"):
                ros_of.update({fid: info["rank"] for fid, info in ros_lists.get(g, {}).items()})
            trend_info = decisions.trend(lineup, prior, ros_of.get)
        ahead = decisions.lookahead(rows, slots, week)

    return {
        "kind": kind,
        "source": src.name,
        "league": league["name"],
        "scoring": league["scoring"],
        "slots": slots,
        "period": period_label(week) if kind == "weekly" else None,
        "week": week if kind == "weekly" else None,
        "generated": dt.datetime.now().isoformat(timespec="minutes"),
        "matchup": {k: matchup[k] for k in ("win_prob", "pre_game", "my_proj", "opponent")},
        "roster": rows,
        "lineup": lineup,
        "free_agents": free_agents,
        "moves": moves,
        "net": net,
        "trend": trend_info,
        "lookahead": ahead,
        "best_picks": best_picks,
        "prior_period": prior_label,
        "flex_vs_prior": flex_check,
        "coverage": coverage,
        "notes": notes,
    }


def api_week() -> int | None:
    """The NFL week the FantasyPros consensus feed is currently serving."""
    d = api_get(f"nfl/{season()}/consensus-rankings", {"position": "QB", "type": "WW", "scoring": "STD",
                                                       "experts": "available"})
    return int(d["week"]) if d.get("week") else None


def period_label(week: int | None) -> str:
    """Snapshot key: the NFL week, or the ISO week of today if the week is unknown."""
    if week:
        return f"week{int(week):02d}"
    year, wk, _ = dt.date.today().isocalendar()
    return f"{year}-W{wk:02d}"


def load_prior(kind: str, label: str, hist: Path) -> dict | None:
    """Most recent saved snapshot for this analysis type, excluding the current period."""
    if not hist.exists():
        return None
    files = sorted(p for p in hist.glob(f"{kind}-week*.json") if p.stem != f"{kind}-{label}")
    return json.loads(files[-1].read_text()) if files else None


def compare_flex(prior: dict, rows: list[dict], flex_ranks: dict, owners: dict, team_id: str,
                 week: int | None, injury_of: dict[int, list[str]]) -> list[dict]:
    """Informational: this week's best FLEX lineup vs last week's FLEX starters, both at this week's ranks.

    Never gates a decision. The lineup is set to win this week; a weaker week than last (byes,
    injuries) still gets the best available lineup.
    """
    def now_rank(fid: int) -> int:
        return (flex_ranks.get(fid) or {}).get("rank") or 9999

    prior_starters = [p for p in prior["roster"] if p["group"] == "FLX" and p["slot"] == "starter"]
    n = len([r for r in rows if r["group"] == "FLX" and r["slot"] == "starter"])
    pool = [
        {"fpId": fid, **info}
        for fid, info in flex_ranks.items()
        if info["pos"] in FLEX_POS and (fid not in owners or str(owners[fid]) == team_id)
        and not on_bye_week(info, week) and not unavailable(injury_of.get(fid, []))
    ]
    best = sorted(pool, key=lambda x: x["rank"])[:n]
    prior_sorted = sorted(prior_starters, key=lambda p: now_rank(p["fpId"]))
    out = []
    for i, (new, old) in enumerate(zip(best, prior_sorted), start=1):
        old_rank = now_rank(old["fpId"])
        out.append({
            "slot": i,
            "now": new["name"], "now_rank": new["rank"], "now_mine": new["fpId"] in {r["fpId"] for r in rows},
            "prior": old["name"], "prior_rank": old_rank if old_rank != 9999 else None,
            "prior_reachable": old["fpId"] not in owners or str(owners[old["fpId"]]) == team_id,
            "better": new["rank"] < old_rank,
        })
    return out


# ---------------------------------------------------------------- report

def _pts(v) -> str:
    return f"{float(v):.1f}" if v is not None else "n/a"


def _cell(v) -> str:
    return str(v if v not in (None, "") else "-").replace("|", "/")


def _availability(p: dict) -> str:
    bits = []
    if p.get("bye_now"):
        bits.append("BYE THIS WEEK")
    elif p.get("bye"):
        bits.append(f"bye wk {p['bye']}")
    if p.get("injury"):
        bits.append("INJURY: " + "; ".join(p["injury"])[:110])
    if p.get("locked"):
        bits.append("LOCKED (game started)")
    return ", ".join(bits) or "-"


def report(res: dict) -> None:
    kind = res["kind"]
    src = "FantasyPros website (web UX)" if res.get("source") == "web" else "FantasyPros public API"
    print(f"# {kind.upper()} analysis{' — week ' + str(res['week']) if res.get('week') else ''} "
          f"(no roster changes made)")
    print(f"Source: {src} | League: {res.get('league')} | Scoring: {res.get('scoring')} | "
          f"Slots: {', '.join(res.get('slots') or [])}")
    m = res.get("matchup") or {}
    lineup = res.get("lineup")
    if kind == "weekly" and m:
        opp = m.get("opponent") or {}
        wp = m.get("win_prob")
        print(f"Matchup: vs {opp.get('name')} ({opp.get('record')}) | FP win probability "
              f"{f'{wp:.0%}' if wp is not None else 'n/a'} | stance: {lineup['stance'] if lineup else 'n/a'} | "
              f"projected {_pts(m.get('my_proj'))} vs {_pts(opp.get('proj'))}")
    moves = res["moves"]

    # 1. Actions first
    print("\n## Do this in Yahoo")
    actions = []
    if lineup:
        for c in lineup["changes"]:
            if c["start"]:
                gain = f" (+{c['gain']:.1f} proj pts)" if c.get("gain") is not None else ""
                actions.append(f"START {c['start']} at {c['slot']}"
                               + (f", bench {c['bench']} ({c['why_out']})" if c["bench"] else "") + gain)
            else:
                actions.append(f"BENCH {c['bench']} ({c['why_out']}); no eligible replacement on the roster")
        for s in lineup["empty_slots"]:
            actions.append(f"EMPTY SLOT {s}: nobody on the roster can start there this week; see the moves below")
    for mv in moves["recommended"]:
        actions.append(f"ADD {mv['add']} / DROP {mv['drop']} (ROS #{mv['ros'][0]} for #{mv['ros'][1]})")
    if not actions:
        actions.append("No changes: your current lineup is the best legal lineup and no move passed every gate."
                       if kind == "weekly" else "No add/drop passed every gate (ROS view; confirm with run_weekly).")
    for i, a in enumerate(actions, start=1):
        print(f"{i}. {a}")
    if lineup:
        print(f"\nProjected points: current lineup {_pts(lineup['proj_current'])} -> recommended "
              f"{_pts(lineup['proj_recommended'])}"
              + (f" ({lineup['proj_missing']} starters have no projection)" if lineup["proj_missing"] else ""))

    # 2. Data status
    if res.get("notes"):
        print("\n## Data status (read before acting on the ranks)")
        for n in res["notes"]:
            print(f"- {n}")
    cov = res.get("coverage") or {}
    print("\nExperts per consensus: " + "; ".join(
        (f"{g} weekly {c.get('weekly', '-')}, ROS {c.get('ros', '-')}" if kind == "weekly" else f"{g} ROS {c.get('ros', '-')}")
        for g, c in cov.items()))

    # 3. Lineup
    if lineup:
        print("\n## Recommended lineup")
        print("| Slot | Player | Pos | Weekly rank (best-worst) | Proj | Grade | Opp | ROS | Bye / injury / lock |")
        print("|---|---|---|---|---|---|---|---|---|")
        by_id = {p["fpId"]: p for p in res["roster"]}
        for s in lineup["recommended"]:
            p = by_id.get(s["fpId"], s)
            spread = f" ({p.get('rank_min')}-{p.get('rank_max')})" if p.get("rank_min") is not None else ""
            print(f"| {s['slot']} | {p['name']} | {p['pos']} | {fmt_rank(p.get('rank'))}{spread} | {_pts(p.get('proj'))} "
                  f"| {_cell(p.get('grade'))} | {_cell(p.get('opp'))} | {fmt_rank(p.get('ros_rank'))} | {_cell(_availability(p))} |")
        for s in lineup["empty_slots"]:
            print(f"| {s} | EMPTY | - | - | - | - | - | - | - |")
        starting = {s["fpId"] for s in lineup["recommended"]}
        print("\nBench:")
        for p in sorted((p for p in res["roster"] if p["fpId"] not in starting),
                        key=lambda p: (p["group"], p.get("rank") or 9999)):
            print(f"- {p['name']} ({p['pos']}) {fmt_rank(p.get('rank'))}, proj {_pts(p.get('proj'))}, "
                  f"ROS {fmt_rank(p.get('ros_rank'))} [{_availability(p)}]")
        if lineup["close_calls"]:
            print(f"\n## Close calls (projected gap under {decisions.CLOSE_POINTS} pts; stance: {lineup['stance']})")
            for c in lineup["close_calls"]:
                print(f"- {c['slot']}: {c['starter']} ({_pts(c['starter_proj'])}) vs {c['alternative']} "
                      f"({_pts(c['alt_proj'])}) -> start {c['choice']}: {c['reason']}")

    # 4. Moves
    print("\n## Add/drop moves")
    if moves["recommended"]:
        print("| Add | Drop | Weekly rank (in/out) | ROS rank (in/out) | Proj (in/out) | Experts (weekly/ROS) |")
        print("|---|---|---|---|---|---|")
        for mv in moves["recommended"]:
            print(f"| {mv['add']} | {mv['drop']} | {fmt_rank(mv['weekly'][0])} / {fmt_rank(mv['weekly'][1])} "
                  f"| {fmt_rank(mv['ros'][0])} / {fmt_rank(mv['ros'][1])} | {_pts(mv['proj'][0])} / {_pts(mv['proj'][1])} "
                  f"| {_cell(mv['experts'][0])} / {_cell(mv['experts'][1])} |")
    else:
        print("No add/drop passed every gate.")
    for title, group in (("Recommended", moves["recommended"]), ("Provisional (evidence missing: do not act yet)",
                                                                  moves["provisional"])):
        for mv in group:
            print(f"\n### {title}: add {mv['add']} / drop {mv['drop']}")
            if mv.get("missing"):
                print(f"Missing: {', '.join(mv['missing'])}")
            ev = mv["evidence"]
            for k in ("breadth", "two_horizon", "availability", "role", "matchup"):
                print(f"- {k.replace('_', '-')}: {ev.get(k) or 'not checked'}")
            for n in ev.get("news", []):
                print(f"  - FP news {n['date']}: {n['title']}" + (f" — {n['impact'][:200]}" if n.get("impact") else ""))
            if ev.get("expert_note"):
                print(f"  - FP expert note: {ev['expert_note'][:300]}")
    if moves["held"]:
        print("\nHeld (failed a gate):")
        for h in moves["held"]:
            print(f"- add {h['add']} / drop {h['drop']} ({h['group']}): {h['failed']}")
    net = res.get("net")
    if net:
        ros_before, ros_after = net["roster_ros_avg"]
        print(f"\nNet change after recommended moves: roster ROS avg {ros_before} -> {ros_after}; "
              f"lineup projection {_pts(net['proj'][0])} -> {_pts(net['proj'][1])}")
    t = res.get("trend")
    if t:
        print(f"Trend: starters' avg ROS rank {t['prior']} ({t['prior_period']}) -> {t['now']} now (lower is better)")

    # 5. Lookahead and the rest
    if kind == "weekly":
        print("\n## Byes and injuries ahead")
        for line in res.get("lookahead") or ["no slot gaps in the next 3 weeks"]:
            print(f"- {line}")
        print("\n## Best available this week (QB/K/DST; streaming view, not gated)")
        for grp in ("QB", "K", "DST"):
            b = res["best_picks"].get(grp)
            if b:
                print(f"- {grp}: {b['name']} {fmt_rank(b['rank'])}, proj {_pts(b.get('proj'))} "
                      f"({'on your roster' if b['mine'] else 'free agent'})")
    print("\n## Free agents to watch")
    for grp, fas in res["free_agents"].items():
        top = sorted(fas, key=lambda f: (f.get("rank") or 9999, f.get("ros_rank") or 9999) if kind == "weekly"
                     else f.get("ros_rank") or 9999)[:5]
        listing = ", ".join(
            (f"{f['name']} wk {fmt_rank(f.get('rank'))} / ROS {fmt_rank(f.get('ros_rank'))}" if kind == "weekly"
             else f"{f['name']} ROS {fmt_rank(f.get('ros_rank'))}")
            + (f", {f['owned_yahoo']:.0f}% owned" if f.get("owned_yahoo") is not None else "")
            + (f", trend {f['ecr_delta']:+d}" if f.get("ecr_delta") else "")
            for f in top)
        print(f"- {grp}: {listing or 'none'}")
    if kind == "weekly":
        print(f"\nFLEX vs last week (informational only; {res['prior_period'] or 'no prior snapshot yet, baseline saved'}):")
        for c in res["flex_vs_prior"] or []:
            verdict = "IMPROVED" if c["better"] else "NO IMPROVEMENT"
            fa = "" if c["now_mine"] else " [free agent]"
            reach = "" if c["prior_reachable"] else " [no longer available]"
            print(f"- slot {c['slot']}: {c['now']}{fa} {fmt_rank(c['now_rank'])} vs last week {c['prior']} "
                  f"{fmt_rank(c['prior_rank'])}{reach} -> {verdict}")


def set_env(updates: dict[str, str]) -> None:
    """Set or add KEY=value lines in .env, keeping the rest of the file as-is."""
    path = ENV_FILE
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip()
        if k in updates:
            lines[i] = f"{k}={updates[k]}"
            seen.add(k)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)


def discover(team_id: str | None) -> None:
    """Find the league from the mitmproxy capture and save FP_LEAGUE_KEY / FP_TEAM_ID to .env.

    Only needed once: the league key is not exposed by the public API, so it comes from the
    browser's league-roster traffic.
    """
    cap = CAPTURE_DIR
    entries = [json.loads(l) for l in (cap / "requests.jsonl").read_text().splitlines() if "getLeagueRostersJSON" in l]
    if not entries:
        raise SystemExit("No league capture found. Run the mitmproxy capture (see the fantasy-fixup skill) first.")
    entry = entries[-1]
    key = urllib.parse.parse_qs(urllib.parse.urlsplit(entry["url"]).query).get("key", [""])[0]
    league = json.loads((cap / entry["body_file"]).read_text())
    teams = {t["id"]: t["name"] for t in league["teams"]}
    print(f"League: {league['nickname']} ({league['host']}, {league['scoring']})")
    print(f"Starting slots: {', '.join(parse_slots(league.get('positions')))}")
    for tid, name in teams.items():
        print(f"  team id {tid}: {name}")
    if team_id is None:
        print("\nRe-run with --team-id <id> to save your team.")
        return
    if team_id not in teams:
        raise SystemExit(f"team id {team_id} is not in this league")
    set_env({"FP_LEAGUE_KEY": key, "FP_TEAM_ID": team_id})
    print(f"\nSaved FP_LEAGUE_KEY and FP_TEAM_ID={team_id} ({teams[team_id]}) to .env")


def main() -> None:
    load_dotenv(ENV_FILE)
    if len(sys.argv) >= 2 and sys.argv[1] == "discover":
        team = sys.argv[sys.argv.index("--team-id") + 1] if "--team-id" in sys.argv else None
        discover(team)
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "grade":
        from fantasy_lineup import grade
        print(grade.grade_week(int(sys.argv[2]) if len(sys.argv) > 2 else None))
        return
    if len(sys.argv) != 2 or sys.argv[1] not in ("weekly", "ros"):
        print(__doc__)
        sys.exit(2)
    kind = sys.argv[1]
    week = int(os.environ["FP_WEEK"]) if os.environ.get("FP_WEEK") else None
    try:
        res = run_and_save(kind, week)
    except RateLimited as exc:
        raise SystemExit(f"{exc}. Progress is cached; wait a while, then run again.")
    report(res)


def run_and_save(kind: str, week: int | None = None) -> dict:
    """Run one analysis, save it to var/cache (and a history snapshot for weekly), and return it.

    Raises RateLimited if required cheat-sheet data cannot be fetched. Optional data failures
    are recorded in res["notes"] instead.
    """
    res = analyse(kind, week)
    suffix = "-web" if res["source"] == "web" else ""
    CACHE_DIR.mkdir(mode=0o700, exist_ok=True)
    out = CACHE_DIR / f"{kind}{suffix}.json"
    out.write_text(json.dumps(res, indent=2, default=str))
    out.chmod(0o600)
    if kind == "weekly":
        # Snapshot per period; the next run compares against it and grade_week scores it
        hist = history_dir(res["source"])
        hist.mkdir(mode=0o700, parents=True, exist_ok=True)
        snap = hist / f"{kind}-{res['period']}.json"
        snap.write_text(json.dumps(res, indent=2, default=str))
        snap.chmod(0o600)
    return res


if __name__ == "__main__":
    main()
