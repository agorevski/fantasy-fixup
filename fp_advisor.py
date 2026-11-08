"""Lineup, waiver, and drop analysis for a FantasyPros-synced league.

Read-only: fetches public FantasyPros rankings plus league data and prints
recommendations. It never changes your roster.

Usage:
    .venv/bin/python fp_advisor.py weekly     # start/sit, waiver adds, drops
    .venv/bin/python fp_advisor.py ros        # rest-of-season adds and drops

Config (.env): FP_LEAGUE_KEY (required), FP_TEAM_ID (default 3), FP_WEEK (optional).

Expert selection (from the site's own accuracy groups):
    weekly  QB/K/DST -> Top 10 in-season accuracy at that position
            FLX      -> Top 20 overall in-season accuracy
    ros     QB/K/DST -> Top 20 in-season accuracy at that position (ROS pages)
            FLX      -> Top 20 overall in-season accuracy (ROS pages)
"""

import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".fp_cache"
HISTORY = CACHE / "history"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
SITE = "https://www.fantasypros.com/nfl/rankings"
PARTNERS = "https://partners.fantasypros.com/api/v1/consensus-rankings.php"
MPB = "https://mpbnfl.fantasypros.com"
FLEX_POS = {"RB", "WR", "TE"}
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]

# analysis type -> position group -> (rankings page, accuracy group id)
GROUPS = {
    "weekly": {
        "QB": ("qb", "top10_qb_in_season"),
        "K": ("k", "top10_k_in_season"),
        "DST": ("dst", "top10_dst_in_season"),
        "FLX": ("flex", "top20_all_in_season"),
    },
    "ros": {
        "QB": ("ros-qb", "top20_qb_in_season"),
        "K": ("ros-k", "top20_k_in_season"),
        "DST": ("ros-dst", "top20_dst_in_season"),
        "FLX": ("ros-flex", "top20_all_in_season"),
    },
}


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def page_var(html: str, name: str) -> dict:
    m = re.search(rf"var {re.escape(name)} = ", html)
    if not m:
        raise RuntimeError(f"'{name}' not found on rankings page (site layout may have changed)")
    return json.JSONDecoder().raw_decode(html[m.end():])[0]


EXPERT_CACHE = CACHE / "experts.json"


def expert_ids(page: str, group_id: str) -> tuple[list[int], dict[int, str]]:
    """Read the accuracy-group expert IDs, and every expert's display name, from a public rankings page.

    The rankings HTML can be blocked (HTTP 403). Good reads are cached in .fp_cache/experts.json, and
    that cache is used when the page cannot be fetched, so the analysis keeps working.
    """
    key = f"{page}:{group_id}"
    cached = json.loads(EXPERT_CACHE.read_text()) if EXPERT_CACHE.exists() else {}
    try:
        groups = page_var(get_text(f"{SITE}/{page}.php"), "expertGroupsData")
    except Exception as exc:
        if key not in cached:
            raise
        print(f"  warning: {page}.php unavailable ({exc}); using cached expert list", file=sys.stderr)
        return cached[key]["ids"], {int(k): v for k, v in cached[key]["names"].items()}
    names = {int(e["id"]): f"{e['name']} ({e.get('site') or 'no site'})" for e in groups.get("expert_data", [])}
    for opt in groups["expert_groups"]["accuracy_weekly"]["options"]:
        if opt["id"] == group_id:
            ids = opt.get("experts", [])
            cached[key] = {"ids": ids, "names": {str(k): v for k, v in names.items()}}
            CACHE.mkdir(mode=0o700, exist_ok=True)
            EXPERT_CACHE.write_text(json.dumps(cached, indent=2))
            EXPERT_CACHE.chmod(0o600)
            return ids, names
    raise RuntimeError(f"accuracy group {group_id} not offered on {page}.php")


INJURY_TABLE = re.compile(r'<table[^>]*injury-table[^>]*>(.*?)</table>', re.S)


INJURY_STATUS = re.compile(r'<[^>]*class="injury"[^>]*>(.*?)</', re.S)


def _clean(html: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).strip()


def injury_report(url: str) -> list[str]:
    """Injury status and injury-table rows from a player's FantasyPros page. Empty list when none are listed."""
    html = get_text(url)
    rows = []
    status = INJURY_STATUS.search(html)
    if status and _clean(status.group(1)):
        rows.append(f"status: {_clean(status.group(1))}")
    m = INJURY_TABLE.search(html)
    if m:
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(1), re.S):
            cells = [_clean(c) for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)]
            cells = [c for c in cells if c]
            if cells:
                rows.append(" | ".join(cells))
    return rows


def consensus(kind: str, pos: str, ids: list[int], week: int | None) -> dict[int, dict]:
    """Return {fpId: {...}} for the consensus list filtered to the given experts."""
    params = {
        "sport": "NFL",
        "position": pos,
        "type": "weekly" if kind == "weekly" else "ROS",
        "scoring": "STD",
        "year": os.environ.get("FP_SEASON", "2026"),
        "filters": ":".join(map(str, ids)),
        "experts": "available",
    }
    if kind == "weekly" and week:
        params["week"] = str(week)
    data = get_json(f"{PARTNERS}?{urllib.parse.urlencode(params)}")
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
    if kind == "weekly":
        week = week or api_week()

    lists = {}
    expert_ids_by_grp = {}
    expert_names = {}
    for grp, (page, gid) in GROUPS[kind].items():
        ids, names = expert_ids(page, gid)
        expert_ids_by_grp[grp] = ids
        expert_names.update(names)
        pos_param = grp  # QB, K, DST, or FLX
        lists[grp] = consensus(kind, pos_param, ids, week)
        print(f"  {kind} {grp}: {len(lists[grp])} ranked players from {len(ids)} experts", file=sys.stderr)

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

    if kind == "weekly":
        enrich_weekly(rows, lists, free_agents, expert_ids_by_grp, expert_names, week)

    # Start/sit: for each group, bench players ranked better than the weakest starter
    start_sit = []
    if kind == "weekly":
        for grp in GROUPS[kind]:
            starters = [r for r in rows if r["group"] == grp and r["slot"] == "starter"]
            bench = [r for r in rows if r["group"] == grp and r["slot"] == "bench"]
            for b in bench:
                if b["rank"] is None:
                    continue
                worst = max(starters, key=lambda s: s["rank"] or 9999, default=None)
                if worst and (worst["rank"] is None or b["rank"] < worst["rank"]):
                    start_sit.append((b, worst))

    # Add/drop: a free agent ranked better than my worst player in that group
    # Pair each of my weakest players with the best free agent that beats them, one drop per player
    add_drop = []
    for grp in GROUPS[kind]:
        drops = sorted([r for r in rows if r["group"] == grp], key=lambda r: r["rank"] or 9999, reverse=True)
        adds = list(free_agents[grp])
        for drop in drops:
            if not adds:
                break
            if adds[0]["rank"] < (drop["rank"] or 9999):
                add_drop.append((adds.pop(0), drop))

    # Weekly only: QB/K/DST take the best-ranked available player; FLEX must beat last week's lineup
    best_picks = {}
    flex_check = []
    prior_label = None
    if kind == "weekly":
        label = period_label(week)
        for grp in ("QB", "K", "DST"):
            pool = [
                {"fpId": fid, **info}
                for fid, info in lists[grp].items()
                if (fid not in owners or str(owners[fid]) == team_id) and not on_bye(info, week)
            ]
            if pool:
                best = min(pool, key=lambda x: x["rank"])
                best_picks[grp] = {"name": best["name"], "rank": best["rank"], "fpId": best["fpId"],
                                   "mine": best["fpId"] in mine_ids}
        prior = load_prior(kind, label)
        if prior:
            prior_label = prior["period"]
            flex_check = compare_flex(prior, rows, lists["FLX"], owners, team_id, week)
        else:
            prior_label = None

    res = {
        "kind": kind,
        "period": period_label(week) if kind == "weekly" else None,
        "week": week if kind == "weekly" else None,
        "roster": rows,
        "start_sit": start_sit,
        "free_agents": free_agents,
        "add_drop": add_drop,
        "best_picks": best_picks,
        "prior_period": prior_label,
        "flex_vs_prior": flex_check,
    }
    return res


def enrich_weekly(rows: list[dict], lists: dict, free_agents: dict, expert_ids_by_grp: dict,
                  expert_names: dict[int, str], week: int | None) -> None:
    """Add bye week, injury report, and each expert's own rank to roster rows and top free agents.

    Expert picks come from the same accuracy groups used for the rankings (one filtered call per expert).
    """
    for r in rows:
        info = lists.get(r["group"], {}).get(r["fpId"]) or {}
        r["bye"] = info.get("bye")
        r["url"] = info.get("url")
    targets = list(rows)
    for fas in free_agents.values():
        targets += fas[:5]
    for t in targets:
        t["bye_now"] = on_bye(t, week)

    # Injury report: one player page each, fetched in parallel
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {t["fpId"]: pool.submit(injury_report, t["url"]) for t in targets if t.get("url")}
        for t in targets:
            fut = futures.get(t["fpId"])
            if fut is None:
                continue
            try:
                t["injury"] = fut.result()
            except Exception as exc:  # report the failure instead of hiding it
                t["injury"] = [f"lookup failed: {exc}"]

    # Per-expert ranks for every target, across all four position groups
    target_ids = {t["fpId"] for t in targets}
    picks: dict[int, list[dict]] = {fid: [] for fid in target_ids}
    for grp, ids in expert_ids_by_grp.items():
        for e in ids:
            for fid, info in consensus("weekly", grp, [e], week).items():
                if fid in target_ids:
                    picks[fid].append({"expert": expert_names.get(e, str(e)), "rank": info["rank"]})
    for t in targets:
        t["expert_picks"] = sorted(picks[t["fpId"]], key=lambda x: x["rank"])
        ranks = [x["rank"] for x in t["expert_picks"]]
        t["expert_median"] = sorted(ranks)[len(ranks) // 2] if ranks else None


def api_week() -> int | None:
    """The NFL week the FantasyPros consensus feed is currently serving."""
    d = get_json(f"{PARTNERS}?{urllib.parse.urlencode({'sport': 'NFL', 'position': 'QB', 'type': 'weekly', 'scoring': 'STD', 'year': os.environ.get('FP_SEASON', '2026'), 'experts': 'available'})}")
    return int(d["week"]) if d.get("week") else None


def period_label(week: int | None) -> str:
    """Snapshot key: the NFL week, or the ISO week of today if the week is unknown."""
    if week:
        return f"week{int(week):02d}"
    year, wk, _ = dt.date.today().isocalendar()
    return f"{year}-W{wk:02d}"


def on_bye(info: dict, week: int | None) -> bool:
    """True when this player's team is on a bye in the given week."""
    return bool(week) and str(info.get("bye")) == str(week)


def load_prior(kind: str, label: str) -> dict | None:
    """Most recent saved snapshot for this analysis type, excluding the current period."""
    files = sorted(p for p in HISTORY.glob(f"{kind}-*.json") if p.stem != f"{kind}-{label}")
    return json.loads(files[-1].read_text()) if files else None


def compare_flex(prior: dict, rows: list[dict], flex_ranks: dict, owners: dict, team_id: str,
                 week: int | None) -> list[dict]:
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
        and not on_bye(info, week)
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
    return "  [" + ", ".join(parts) + "]" if parts else ""


def report(res: dict) -> None:
    kind = res["kind"]
    print(f"\n=== {kind.upper()} analysis (no roster changes made) ===\n")
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
    path = ROOT / ".env"
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
    """Find the league from the mitmproxy capture and save FP_LEAGUE_KEY / FP_TEAM_ID to .env."""
    cap = ROOT / ".fp_capture"
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
    load_dotenv(ROOT / ".env")
    if len(sys.argv) >= 2 and sys.argv[1] == "discover":
        team = sys.argv[sys.argv.index("--team-id") + 1] if "--team-id" in sys.argv else None
        discover(team)
        return
    if len(sys.argv) != 2 or sys.argv[1] not in ("weekly", "ros"):
        print(__doc__)
        sys.exit(2)
    kind = sys.argv[1]
    week = int(os.environ["FP_WEEK"]) if os.environ.get("FP_WEEK") else None
    res = analyse(kind, week)
    CACHE.mkdir(mode=0o700, exist_ok=True)
    out = CACHE / f"{kind}.json"
    out.write_text(json.dumps(res, indent=2, default=str))
    out.chmod(0o600)
    if kind == "weekly":
        # Snapshot per period; the next run compares its FLEX lineup against this one
        HISTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
        snap = HISTORY / f"{kind}-{res['period']}.json"
        snap.write_text(json.dumps(res, indent=2, default=str))
        snap.chmod(0o600)
    report(res)


if __name__ == "__main__":
    main()
