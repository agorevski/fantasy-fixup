"""Lineup, waiver, and drop analysis for a FantasyPros-synced league.

Read-only: fetches FantasyPros rankings, experts, and injuries from the official
public API, plus your league roster, and prints recommendations. It never changes
your roster.

Usage:
    .venv/bin/python -m fantasy_lineup.advisor weekly     # start/sit, waiver adds, drops
    .venv/bin/python -m fantasy_lineup.advisor ros        # rest-of-season adds and drops
    .venv/bin/python -m fantasy_lineup.advisor discover   # list leagues captured by mitmproxy

Config (.env): FP_SOURCE (api or web, default api), FP_API_KEY (required for api),
FP_LEAGUE_KEY (required), FP_TEAM_ID (default 3), FP_SEASON (default 2026), FP_WEEK (optional).
FP_SOURCE=web reads the same data from the FantasyPros website (see web.py).

Expert selection (top N experts by the public API's per-position accuracy_weekly score):
    weekly  QB/K/DST -> top 10 at that position
            FLX      -> top 20 overall ("ALL")
    ros     QB/K/DST -> top 20 at that position
            FLX      -> top 20 overall ("ALL")
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

from fantasy_lineup.paths import API_CACHE_DIR, CACHE_DIR, CAPTURE_DIR, ENV_FILE, HISTORY_DIR

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
INJURY_TTL = 3600           # injury reports change more often
FLEX_POS = {"RB", "WR", "TE"}
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]

# analysis type -> position group -> (API ranking type, accuracy key, number of experts)
GROUPS = {
    "weekly": {
        "QB": ("WW", "QB", 10),
        "K": ("WW", "K", 10),
        "DST": ("WW", "DST", 10),
        "FLX": ("WW", "ALL", 20),
    },
    "ros": {
        "QB": ("ROS", "QB", 20),
        "K": ("ROS", "K", 20),
        "DST": ("ROS", "DST", 20),
        "FLX": ("ROS", "ALL", 20),
    },
}


class RateLimited(RuntimeError):
    """HTTP 429 that did not clear after retries (or asked us to wait too long)."""


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


def api_key() -> str:
    key = os.environ.get("FP_API_KEY", "").strip()
    if not key:
        raise SystemExit("FP_API_KEY missing from .env (copy it from .env.example and add your key)")
    return key


_last_call = 0.0


def _retry_after(exc: urllib.error.HTTPError) -> int | None:
    value = (exc.headers.get("Retry-After") or "").strip()
    return int(value) if value.isdigit() else None


def api_get(path: str, params: dict | None = None, ttl: int = RANKINGS_TTL):
    """GET a path under the official public API. Empty params are dropped from the query string.

    Responses are cached on disk for `ttl` seconds, so a rerun after a rate limit does not repeat
    calls that already succeeded. The API key is sent in a header only and never written to the cache.
    """
    global _last_call
    qs = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")})
    url = f"{API}/{path}" + (f"?{qs}" if qs else "")
    cache_file = API_CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < ttl:
        return json.loads(cache_file.read_text())

    key = api_key()
    for attempt in range(MAX_RETRIES + 1):
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
                if attempt == MAX_RETRIES or wait > MAX_RETRY_AFTER:
                    raise RateLimited(f"FantasyPros API {path} is rate limited (HTTP 429)") from exc
                status(f"rate limited on {path}; waiting {wait}s (retry {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            hint = {401: " (check FP_API_KEY)", 403: " (check FP_API_KEY and plan access)"}.get(exc.code, "")
            raise RuntimeError(f"FantasyPros API {path} returned HTTP {exc.code}{hint}") from exc
        data = json.loads(body)
        API_CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data))
        cache_file.chmod(0o600)
        return data
    raise RuntimeError("unreachable")  # the loop always returns or raises


def get_json(url: str):
    """League roster feed (MPB). Not part of the public API."""
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

    def current_week(self) -> int | None:
        return api_week()

    def expert_ids(self, kind: str, grp: str, n: int, week: int | None) -> tuple[list[int], dict[int, str]]:
        rtype, acc_key, _ = GROUPS[kind][grp]
        # Experts are fetched per position and never served from cache, so a stale expert set
        # cannot carry over from an earlier run.
        experts = api_get(f"nfl/{season()}/rankings/experts", {
            "position": None if grp == "FLX" else grp,
            "type": rtype,
            "scoring": "STD",
            "include_overall": "true",
        }, ttl=0).get("experts", [])
        return top_experts(experts, acc_key, n)

    def consensus(self, kind: str, grp: str, ids: list[int], week: int | None,
                  warnings: list[str] | None = None) -> dict[int, dict]:
        return consensus(kind, grp, ids, week, warnings)

    def injuries(self, player_ids: list[int], week: int | None) -> dict[int, list[str]]:
        return injuries_for(player_ids, week)


def make_backend():
    """The data source chosen by FP_SOURCE, read from the environment at call time."""
    if source_name() == "web":
        from fantasy_lineup import web  # imported lazily so api-only runs do not load the browser client
        return web.WebBackend(season(), status)
    return ApiBackend()


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


def consensus(kind: str, grp: str, ids: list[int], week: int | None,
              warnings: list[str] | None = None) -> dict[int, dict]:
    """Return {fpId: {...}} for the consensus list filtered to the given experts.

    When `warnings` is given, any difference between the experts requested and the experts the
    API actually used, or a list shorter than the API's own limit, is appended to it.
    """
    params = {
        "position": grp,
        "type": GROUPS[kind][grp][0],
        "scoring": "STD",
        "filters": ":".join(map(str, ids)),
        "experts": "available",
        "week": week if kind == "weekly" else None,
    }
    data = api_get(f"nfl/{season()}/consensus-rankings", params)
    if warnings is not None:
        avail = data.get("experts_available") or {}
        used = {int(x) for x in avail.get("included", [])}
        if used and used != set(ids):
            missing = sorted(set(ids) - used)
            warnings.append(f"{grp}: API used {len(used)} of {len(ids)} requested experts "
                            f"(not used: {missing})")
        limit = int(data.get("limit") or 0)
        if limit and len(data.get("players", [])) < limit:
            warnings.append(f"{grp}: the API returned {len(data.get('players', []))} players "
                            f"(limit {limit}); players not in that list show as unranked")
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


def injuries_for(player_ids: list[int], week: int | None) -> dict[int, list[str]]:
    """Injury status, injury type, practice reports, and comments for the given players, from one API call."""
    if not player_ids:
        return {}
    data = api_get("nfl/injuries", {
        "year": season(),
        "week": week,
        "player_ids": ":".join(map(str, sorted(set(player_ids)))),
    }, ttl=INJURY_TTL)
    out: dict[int, list[str]] = {}
    for inj in data.get("injuries", []):
        bits = [inj.get("status"), inj.get("injury_type")]
        practice = [inj.get(k) for k in ("practice_1", "practice_2", "practice_3")
                    if inj.get(k) and inj.get(k) != "--"]
        if practice:
            bits.append("practice " + "/".join(practice))
        bits.append(inj.get("comment"))
        text = " | ".join(str(b) for b in bits if b)
        if text:
            out.setdefault(int(inj["player_id"]), []).append(text)
    return out


def league_owners(key: str) -> dict[int, str]:
    """Map every rostered fpId in the league to the team id that owns it."""
    data = get_json(f"{MPB}/api/getLeagueRostersJSON?key={key}")
    owners = {}
    for t in data["teams"]:
        for fp_id in t["players"]:
            owners[int(fp_id)] = t["id"]
    return owners


def my_roster(key: str, team_id: str) -> list[dict]:
    """Starters and bench for one team, from the matchup feed (same data the site shows)."""
    m = get_json(f"{MPB}/json/matchup?matchup&key={key}&teamId={team_id}&from=web")
    mine = []
    for slot, block in (("starter", m["matchup"]["team1"]["starters"]), ("bench", m["matchup"]["team1"]["bench"])):
        for p in block:
            mine.append({
                "fpId": int(p["fpId"]),
                "name": p.get("full") or p.get("shortName"),
                "pos": p.get("real_position") or p.get("position"),
                "slot": slot,
                "proj": p.get("new_proj", p.get("original_proj")),
                "game": p.get("gameStatus"),
                "opp": p.get("opponent"),
            })
    return mine


def group_of(pos: str) -> str:
    """Group for ranking: RB/WR/TE (incl. multi-position like 'WR/RB/TE') share the FLX list."""
    primary = (pos or "").split("/")[0]
    return "FLX" if primary in FLEX_POS else primary


def rank_in(lists: dict, fp_id: int, grp: str) -> int | None:
    entry = lists.get(grp, {}).get(fp_id)
    return entry["rank"] if entry else None


def fmt_rank(r: int | None) -> str:
    return f"#{r}" if r is not None else "unranked"


def analyse(kind: str, week: int | None) -> dict:
    key = os.environ.get("FP_LEAGUE_KEY", "").strip()
    team_id = os.environ.get("FP_TEAM_ID", "3").strip()
    if not key:
        raise SystemExit("FP_LEAGUE_KEY missing from .env")
    src = make_backend()
    if src.name == "api":
        api_key()  # fail fast if the API key is not configured
    if kind == "weekly":
        week = week or src.current_week()

    lists = {}
    expert_ids_by_grp = {}
    expert_names = {}
    warnings: list[str] = []
    for grp, (_, acc_key, n) in GROUPS[kind].items():
        status(f"Loading {grp} expert pool ({src.name})")
        ids, names = src.expert_ids(kind, grp, n, week)
        if len(ids) < n:
            warnings.append(f"{grp}: only {len(ids)} of the {n} requested experts have a {acc_key} score")
        status(f"Building {grp} consensus from {len(ids)} experts: " +
               ", ".join(f"{names[i]} [{i}]" for i in ids))
        expert_ids_by_grp[grp] = ids
        expert_names.update(names)
        lists[grp] = src.consensus(kind, grp, ids, week, warnings)
        status(f"{grp}: {len(lists[grp])} ranked players from {len(ids)} experts")

    status("Reading league owners and your roster")
    owners = league_owners(key)
    roster = my_roster(key, team_id)
    mine_ids = {p["fpId"] for p in roster}

    # Free agents: ranked (in the filtered list) and not owned by any team in the league
    free_agents = {}
    for grp in GROUPS[kind]:
        pool = [
            {"fpId": fid, **info}
            for fid, info in lists[grp].items()
            if fid not in owners and (grp == "FLX" and info["pos"] in FLEX_POS or grp != "FLX" and info["pos"] == grp)
        ]
        free_agents[grp] = sorted(pool, key=lambda x: x["rank"])[:10]

    rows = []
    for p in roster:
        grp = group_of(p["pos"])
        p["group"] = grp
        p["rank"] = rank_in(lists, p["fpId"], grp)
        rows.append(p)

    notes: list[str] = []
    if kind == "weekly":
        status("Adding per-expert picks and injury notes")
        notes = enrich_weekly(src, rows, lists, free_agents, expert_ids_by_grp, expert_names, week)
    notes = warnings + notes

    # Injury status for every player we looked up (roster + top free agents). Players with no
    # injury data are treated as unchecked, not unavailable.
    injury_of = {p["fpId"]: p.get("injury", []) for p in rows}
    for fas in free_agents.values():
        for f in fas:
            injury_of[f["fpId"]] = f.get("injury", [])
    # Never recommend an unavailable free agent (OUT, IR, Doubtful, or no practice)
    free_agents = {g: [f for f in fas if not unavailable(injury_of.get(f["fpId"], []))]
                   for g, fas in free_agents.items()}

    # Start/sit: for each group, bench players ranked better than the weakest starter
    start_sit = []
    if kind == "weekly":
        for grp in GROUPS[kind]:
            starters = [r for r in rows if r["group"] == grp and r["slot"] == "starter"]
            bench = [r for r in rows if r["group"] == grp and r["slot"] == "bench"]
            ranked_starters = [s for s in starters if s["rank"] is not None]
            if not ranked_starters:
                continue
            worst = max(ranked_starters, key=lambda s: s["rank"])
            for b in bench:
                if b["rank"] is None or unavailable(b.get("injury", [])):
                    continue
                if b["rank"] < worst["rank"]:
                    start_sit.append((b, worst))

    # Add/drop: a free agent ranked better than my worst player in that group
    # Pair each of my weakest players with the best free agent that beats them, one drop per player
    add_drop = []
    for grp in GROUPS[kind]:
        # Unranked players are not on the list, so they cannot be compared and are never dropped
        drops = sorted([r for r in rows if r["group"] == grp and r["rank"] is not None],
                       key=lambda r: r["rank"], reverse=True)
        adds = list(free_agents[grp])
        for drop in drops:
            if not adds:
                break
            if adds[0]["rank"] < drop["rank"]:
                add_drop.append((adds.pop(0), drop))

    # Weekly only: QB/K/DST take the best-ranked available player; FLEX must beat last week's lineup
    best_picks = {}
    flex_check = []
    prior_label = None
    if kind == "weekly":
        status("Picking best QB, K, and DST and checking last week's FLEX lineup")
        label = period_label(week)
        for grp in ("QB", "K", "DST"):
            pool = [
                {"fpId": fid, **info}
                for fid, info in lists[grp].items()
                if (fid not in owners or str(owners[fid]) == team_id) and not on_bye(info, week)
                and not unavailable(injury_of.get(fid, []))
            ]
            if pool:
                best = min(pool, key=lambda x: x["rank"])
                best_picks[grp] = {"name": best["name"], "rank": best["rank"], "fpId": best["fpId"],
                                   "mine": best["fpId"] in mine_ids}
        prior = load_prior(kind, label, history_dir(src.name))
        if prior:
            prior_label = prior["period"]
            flex_check = compare_flex(prior, rows, lists["FLX"], owners, team_id, week, injury_of)
        else:
            prior_label = None

    res = {
        "kind": kind,
        "source": src.name,
        "period": period_label(week) if kind == "weekly" else None,
        "week": week if kind == "weekly" else None,
        "roster": rows,
        "start_sit": start_sit,
        "free_agents": free_agents,
        "add_drop": add_drop,
        "best_picks": best_picks,
        "prior_period": prior_label,
        "flex_vs_prior": flex_check,
        "notes": notes,
    }
    return res


def enrich_weekly(src, rows: list[dict], lists: dict, free_agents: dict, expert_ids_by_grp: dict,
                  expert_names: dict[int, str], week: int | None) -> list[str]:
    """Add bye week, injury report, and each expert's own rank to roster rows and top free agents.

    Bucket 2 (optional): injuries and per-expert picks. A failure here never stops the analysis;
    it is returned as a note and the affected fields are marked as unavailable.
    Bye weeks come from the cheat-sheet rankings (bucket 1) and are always present.
    """
    notes: list[str] = []
    for r in rows:
        info = lists.get(r["group"], {}).get(r["fpId"]) or {}
        r["bye"] = info.get("bye")
        r["url"] = info.get("url")
    targets = list(rows)
    for fas in free_agents.values():
        targets += fas[:5]
    for t in targets:
        t["bye_now"] = on_bye(t, week)

    # Injury report: one API call for every target
    try:
        injuries = src.injuries([t["fpId"] for t in targets], week)
        for t in targets:
            t["injury"] = injuries.get(t["fpId"], [])
    except Exception as exc:
        notes.append(f"injury reports unavailable ({exc}); injury status is unchecked")
        for t in targets:
            t["injury"] = [f"lookup failed: {exc}"]

    # Per-expert ranks for every target, across all four position groups.
    # Stop at the first failure and keep what was fetched; expert_coverage says how much that is.
    target_ids = {t["fpId"] for t in targets}
    picks: dict[int, list[dict]] = {fid: [] for fid in target_ids}
    total = sum(len(ids) for ids in expert_ids_by_grp.values())
    done = 0
    try:
        for grp, ids in expert_ids_by_grp.items():
            for e in ids:
                for fid, info in src.consensus("weekly", grp, [e], week).items():
                    if fid in target_ids:
                        picks[fid].append({"expert": expert_names.get(e, str(e)), "rank": info["rank"]})
                done += 1
    except Exception as exc:
        notes.append(f"expert picks partial: {done} of {total} experts checked ({exc})")
    for t in targets:
        t["expert_picks"] = sorted(picks[t["fpId"]], key=lambda x: x["rank"])
        ranks = [x["rank"] for x in t["expert_picks"]]
        t["expert_median"] = sorted(ranks)[len(ranks) // 2] if ranks else None
        t["expert_coverage"] = f"{done}/{total}"
    return notes


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


UNAVAILABLE_STATUS = {"OUT", "IR", "INJURED RESERVE", "DOUBTFUL", "PUP", "SUSPENDED", "NOT STARTING"}


def unavailable(entries: list[str]) -> bool:
    """True when the injury entries say the player will not play or is not practicing at all.

    Entries look like "Out | Quad | practice DNP/DNP/DNP | comment". Lookup failures and empty lists are
    not unavailable: missing data means unchecked, not out.
    """
    for entry in entries:
        parts = [p.strip() for p in entry.split("|")]
        if parts and parts[0].upper() in UNAVAILABLE_STATUS:
            return True
        for part in parts:
            if part.startswith("practice "):
                days = part[len("practice "):].split("/")
                if days and all(d == "DNP" for d in days):
                    return True
    return False


def on_bye(info: dict, week: int | None) -> bool:
    """True when this player's team is on a bye in the given week."""
    return bool(week) and str(info.get("bye")) == str(week)


def load_prior(kind: str, label: str, hist: Path) -> dict | None:
    """Most recent saved snapshot for this analysis type, excluding the current period."""
    if not hist.exists():
        return None
    files = sorted(p for p in hist.glob(f"{kind}-*.json") if p.stem != f"{kind}-{label}")
    return json.loads(files[-1].read_text()) if files else None


def compare_flex(prior: dict, rows: list[dict], flex_ranks: dict, owners: dict, team_id: str,
                 week: int | None, injury_of: dict[int, list[str]]) -> list[dict]:
    """Compare this week's best FLEX lineup to last week's actual FLEX starters, both at this week's ranks.

    Pairs the two lineups best-to-worst. A slot is 'better' only if this week's pick ranks strictly higher.
    A slot is 'not better' when the best reachable player is no better than last week's starter there,
    or when last week's starter is no longer reachable (owned by another team).
    """
    def now_rank(fid: int) -> int:
        return (flex_ranks.get(fid) or {}).get("rank") or 9999

    prior_starters = [p for p in prior["roster"] if p["group"] == "FLX" and p["slot"] == "starter"]
    n = len([r for r in rows if r["group"] == "FLX" and r["slot"] == "starter"])
    pool = [
        {"fpId": fid, **info}
        for fid, info in flex_ranks.items()
        if info["pos"] in FLEX_POS and (fid not in owners or str(owners[fid]) == team_id)
        and not on_bye(info, week) and not unavailable(injury_of.get(fid, []))
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


def player_tags(p: dict) -> str:
    """Bye, injury, and expert-consensus notes for one player (weekly only)."""
    parts = []
    if p.get("bye_now"):
        parts.append("BYE THIS WEEK")
    elif p.get("bye"):
        parts.append(f"bye wk {p['bye']}")
    if p.get("injury"):
        parts.append("INJURY: " + "; ".join(p["injury"])[:120])
    if p.get("expert_median") is not None:
        parts.append(f"expert median #{p['expert_median']}")
    coverage = p.get("expert_coverage")
    if coverage and coverage.split("/")[0] != coverage.split("/")[1]:
        parts.append(f"experts checked {coverage}")
    return "  [" + ", ".join(parts) + "]" if parts else ""


def report(res: dict) -> None:
    kind = res["kind"]
    print(f"\n=== {kind.upper()} analysis (no roster changes made) ===")
    print(f"Source: {'FantasyPros website (web UX)' if res.get('source') == 'web' else 'FantasyPros public API'}\n")
    if res.get("notes"):
        print("Data status (read before acting on the ranks):")
        for n in res["notes"]:
            print(f"  - {n}")
        print()
    if kind == "weekly":
        print("Start/sit (bench player ranked above a starter in the same group):")
        if not res["start_sit"]:
            print("  none")
        for b, s in res["start_sit"]:
            print(f"  START {b['name']} ({b['pos']} {fmt_rank(b['rank'])}) over {s['name']} ({fmt_rank(s['rank'])})")
        print()
    print("Free agents worth a look (ranked by filtered experts, not owned in the league):")
    for grp, fas in res["free_agents"].items():
        listing = ", ".join(f"{f['name']} {fmt_rank(f['rank'])}" for f in fas[:5])
        print(f"  {grp}: {listing or 'none'}")
    print("\nSuggested add/drop pairs (free agent better than your weakest player in that group):")
    if not res["add_drop"]:
        print("  none")
    for fa, drop in res["add_drop"]:
        print(f"  ADD {fa['name']} ({fa['pos']} {fmt_rank(fa['rank'])}) / DROP {drop['name']} ({drop['pos']} {fmt_rank(drop['rank'])})")
    print("\nYour roster (group rank):")
    for r in sorted(res["roster"], key=lambda r: (r["group"], r["rank"] or 9999)):
        print(f"  {r['group']:<4} {r['slot']:<7} {r['name']:<24} {fmt_rank(r['rank'])}{player_tags(r)}")
    if kind != "weekly":
        return
    print("\nTop free agents with the same checks:")
    for grp, fas in res["free_agents"].items():
        for f in fas[:3]:
            print(f"  {grp:<4} {f['name']:<24} {fmt_rank(f['rank'])}{player_tags(f)}")
    print(f"\nWeekly best pick (QB/K/DST: start the top-ranked player; weekly-only rule):")
    for grp in ("QB", "K", "DST"):
        b = res["best_picks"].get(grp)
        if b:
            tag = "on your roster" if b["mine"] else "available"
            print(f"  {grp}: {b['name']} {fmt_rank(b['rank'])} ({tag})")
    print(f"\nFLEX vs last week ({res['prior_period'] or 'no prior snapshot yet, baseline saved'}):")
    if not res["flex_vs_prior"]:
        print("  n/a")
    for c in res["flex_vs_prior"]:
        verdict = "IMPROVED" if c["better"] else "NO IMPROVEMENT"
        src = "" if c["now_mine"] else " [free agent]"
        reach = "" if c["prior_reachable"] else " [no longer available]"
        print(f"  slot {c['slot']}: {c['now']}{src} {fmt_rank(c['now_rank'])} vs last week {c['prior']} "
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
        raise SystemExit("No league capture found. Run the mitmproxy capture (see the fantasy-lineup skill) first.")
    entry = entries[-1]
    key = urllib.parse.parse_qs(urllib.parse.urlsplit(entry["url"]).query).get("key", [""])[0]
    league = json.loads((cap / entry["body_file"]).read_text())
    teams = {t["id"]: t["name"] for t in league["teams"]}
    print(f"League: {league['nickname']} ({league['host']}, {league['scoring']})")
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
        # Snapshot per period; the next run compares its FLEX lineup against this one
        hist = history_dir(res["source"])
        hist.mkdir(mode=0o700, parents=True, exist_ok=True)
        snap = hist / f"{kind}-{res['period']}.json"
        snap.write_text(json.dumps(res, indent=2, default=str))
        snap.chmod(0o600)
    return res


if __name__ == "__main__":
    main()
