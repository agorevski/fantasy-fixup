"""Grade a past week's advice against FantasyPros' actual player points, and keep a season log.

For one saved weekly snapshot it compares three lineups, all scored with that week's real points:
    actual       the starters on the roster when the snapshot was taken
    recommended  the lineup the advisor recommended
    hindsight    the best legal lineup from the same roster (the ceiling)
and scores each recommended add against its drop. Results are appended to season-log.json next to
the snapshots, so the season totals show whether following the advice gains points.

Needs FP_API_KEY (player points come from the public API).
"""

from __future__ import annotations

import json

from fantasy_lineup import advisor
from fantasy_lineup.lineup import DEFAULT_SLOTS, best_lineup

LOG_NAME = "season-log.json"


def _snapshots(source: str) -> list[tuple[int, dict]]:
    hist = advisor.history_dir(source)
    out = []
    for path in sorted(hist.glob("weekly-week*.json")) if hist.exists() else []:
        snap = json.loads(path.read_text())
        if snap.get("week"):
            out.append((int(snap["week"]), snap))
    return out


def _load_log(source: str) -> dict:
    path = advisor.history_dir(source) / LOG_NAME
    return json.loads(path.read_text()) if path.exists() else {}


def _save_log(source: str, log: dict) -> None:
    hist = advisor.history_dir(source)
    hist.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = hist / LOG_NAME
    path.write_text(json.dumps(log, indent=2, sort_keys=True))
    path.chmod(0o600)


def grade_week(week: int | None = None, source: str | None = None) -> str:
    """Grade one week (default: the latest snapshot that has points) and update the season log."""
    source = source or advisor.source_name()
    snaps = dict(_snapshots(source))
    if not snaps:
        return "No weekly snapshots saved yet. Run run_weekly during a week, then grade it after the games."
    candidates = [week] if week else sorted(snaps, reverse=True)
    for w in candidates:
        if w not in snaps:
            return f"No snapshot for week {w}. Saved weeks: {', '.join(map(str, sorted(snaps)))}"
        snap = snaps[w]
        pts = advisor.player_points(w, w, snap.get("scoring") or "STD")
        if any(w in weeks for weeks in pts.values()):
            break
        if week:
            return f"FantasyPros has no player points for week {w} yet. Grade it after the games."
    else:
        return "None of the saved weeks has player points yet. Grade after the games."

    roster = snap["roster"]
    slots = snap.get("slots") or DEFAULT_SLOTS
    by_id = {p["fpId"]: p for p in roster}

    def scored(fid: int) -> float:
        return float(pts.get(fid, {}).get(w, 0.0))

    actual = round(sum(scored(p["fpId"]) for p in roster if p.get("slot") == "starter"), 1)
    rec_ids = [p["fpId"] for p in (snap.get("lineup") or {}).get("recommended", [])]
    recommended = round(sum(scored(i) for i in rec_ids), 1) if rec_ids else None
    hindsight_lineup = best_lineup(roster, slots, key=lambda p: -scored(p["fpId"]))
    hindsight = round(sum(scored(p["fpId"]) for p in hindsight_lineup.values()), 1)

    move_results = []
    for m in ((snap.get("moves") or {}).get("recommended") or []):
        move_results.append({"add": m["add"], "drop": m["drop"],
                             "add_pts": scored(m["add_id"]), "drop_pts": scored(m["drop_id"])})

    entry = {"week": w, "source": source, "snapshot_taken": snap.get("generated"),
             "actual": actual, "recommended": recommended, "hindsight": hindsight,
             "advice_gain": round(recommended - actual, 1) if recommended is not None else None,
             "left_on_bench": round(hindsight - actual, 1), "moves": move_results}
    log = _load_log(source)
    log[str(w)] = entry
    _save_log(source, log)

    lines = [f"# Week {w} grade ({source} source)",
             f"- Starters when the snapshot was taken: {actual} pts"
             + (f" (snapshot {snap.get('generated')}; later lineup edits are not seen)" if snap.get("generated") else ""),
             f"- Recommended lineup: {recommended if recommended is not None else 'n/a (snapshot predates lineup advice)'} pts",
             f"- Best possible lineup from the roster: {hindsight} pts (left on the bench: {entry['left_on_bench']})"]
    if entry["advice_gain"] is not None:
        lines.append(f"- Following the advice: {entry['advice_gain']:+.1f} pts vs the starters as set")
    for r in move_results:
        lines.append(f"- Move add {r['add']} ({r['add_pts']:g}) / drop {r['drop']} ({r['drop_pts']:g}): "
                     f"{r['add_pts'] - r['drop_pts']:+.1f} pts that week")
    swaps = [(by_id[i]["name"], scored(i)) for i in rec_ids if i in by_id and by_id[i].get("slot") != "starter"]
    if swaps:
        lines.append("- Recommended starts that were on the bench: "
                     + ", ".join(f"{n} {p:g}" for n, p in swaps))
    lines.append("")
    lines.append(season_summary(source))
    return "\n".join(lines)


def season_summary(source: str | None = None) -> str:
    source = source or advisor.source_name()
    log = _load_log(source)
    if not log:
        return "Season log: no graded weeks yet."
    weeks = [log[k] for k in sorted(log, key=int)]
    graded = [e for e in weeks if e.get("advice_gain") is not None]
    gain = round(sum(e["advice_gain"] for e in graded), 1)
    bench = round(sum(e["left_on_bench"] for e in weeks), 1)
    move_net = round(sum(m["add_pts"] - m["drop_pts"] for e in weeks for m in e.get("moves", [])), 1)
    lines = [f"## Season log ({source} source, {len(weeks)} weeks graded)",
             "| Week | Actual | Recommended | Hindsight best | Advice gain | Left on bench |",
             "|---|---|---|---|---|---|"]
    for e in weeks:
        lines.append(f"| {e['week']} | {e['actual']} | {e['recommended'] if e['recommended'] is not None else '-'} "
                     f"| {e['hindsight']} | {e['advice_gain'] if e['advice_gain'] is not None else '-'} "
                     f"| {e['left_on_bench']} |")
    lines.append(f"\nTotals: advice gain {gain:+.1f} pts over {len(graded)} weeks; "
                 f"{bench} pts left on the bench; recommended moves net {move_net:+.1f} pts in their week.")
    return "\n".join(lines)
