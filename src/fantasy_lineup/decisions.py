"""Decisions: the weekly lineup, close calls, gated add/drop moves, net change, and bye lookahead.

Pure logic over the player dicts advisor.py builds. No network calls of its own: per-expert lists
and evidence (news, recent points) come in through callbacks, so a failure there only marks an
evidence item as 'not checked'.

Player dict fields used here (missing fields are allowed):
    fpId, name, pos, group, slot ('starter'/'bench'/'free agent'), lineup_slot, locked,
    rank, proj, rank_min, rank_max, grade, opp, bye, bye_now, injury,
    ros_rank, ros_ave, ros_std
"""

from __future__ import annotations

from collections.abc import Callable
from statistics import mean

from fantasy_lineup.lineup import best_lineup, fillable, slot_accepts, unfilled

# Thresholds. They are deliberately conservative: a start/sit costs nothing to change back, but
# every add/drop spends a roster spot and possibly a waiver claim.
CLOSE_POINTS = 1.5          # projected-point gap below which a start/sit is a close call
MIN_EXPERTS = 5             # experts a consensus needs before a move can rest on it
MIN_ROS_GAP = 5             # an add must beat the drop by at least this many ROS ranks...
MIN_ROS_GAP_SHARE = 0.15    # ...or by this share of the drop's ROS rank, whichever is larger
UNDERDOG_WP = 0.40          # below this win probability, close calls go to the higher ceiling
FAVORITE_WP = 0.60          # above it, close calls go to the higher floor
NEWS_MAX_AGE_DAYS = 14      # older news is not role evidence
LOOKAHEAD_WEEKS = 3
UNRANKED = 10_000           # sort key for a startable player the cheat sheet does not list

UNAVAILABLE_STATUS = {"OUT", "IR", "INJURED RESERVE", "DOUBTFUL", "PUP", "SUSPENDED", "NOT STARTING"}
LONG_TERM_STATUS = {"IR", "INJURED RESERVE", "PUP", "SUSPENDED"}


# ---------------------------------------------------------------- availability

def injury_status(entries: list[str] | None) -> str:
    """The status word of the first injury entry ('Questionable'), or '' when none is listed."""
    for entry in entries or []:
        if entry.startswith("lookup failed"):
            return ""
        return entry.split("|")[0].strip()
    return ""


def unavailable(entries: list[str] | None) -> bool:
    """True when the injury entries say the player will not play or is not practicing at all.

    Entries look like "Out | Quad | practice DNP/DNP/DNP | comment". Lookup failures and empty lists are
    not unavailable: missing data means unchecked, not out.
    """
    for entry in entries or []:
        parts = [p.strip() for p in entry.split("|")]
        if parts and parts[0].upper() in UNAVAILABLE_STATUS:
            return True
        for part in parts:
            if part.startswith("practice "):
                days = part[len("practice "):].split("/")
                if days and all(d == "DNP" for d in days):
                    return True
    return False


def long_term_out(p: dict) -> bool:
    return injury_status(p.get("injury")).upper() in LONG_TERM_STATUS


def startable(p: dict) -> bool:
    """Can score this week: not on bye, not ruled out, and (for a bench or free agent) game not started."""
    return not p.get("bye_now") and not unavailable(p.get("injury")) and not p.get("locked")


def weekly_key(p: dict) -> float | None:
    """Sort key for this week (lower is better), or None when the player cannot start."""
    if not startable(p):
        return None
    return p["rank"] if p.get("rank") is not None else UNRANKED


def ros_key(p: dict) -> float:
    return p["ros_rank"] if p.get("ros_rank") is not None else UNRANKED


# ---------------------------------------------------------------- lineup

def posture(win_prob: float | None) -> str:
    if win_prob is None:
        return "neutral"
    if win_prob < UNDERDOG_WP:
        return "underdog"
    if win_prob > FAVORITE_WP:
        return "favorite"
    return "neutral"


def _grade_order(grade: str | None) -> int:
    """'A+' -> 0, 'A' -> 1, 'A-' -> 2, 'B+' -> 3 ... ; no grade sorts last."""
    if not grade:
        return 99
    letter, sign = grade[0].upper(), grade[1:]
    return (ord(letter) - ord("A")) * 3 + {"+": 0, "": 1, "-": 2}.get(sign, 1)


def _num(value, default: float = UNRANKED) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_close(a: dict, b: dict) -> bool:
    if a.get("proj") is not None and b.get("proj") is not None:
        return abs(float(a["proj"]) - float(b["proj"])) < CLOSE_POINTS
    ra, rb = a.get("rank"), b.get("rank")
    if ra is None or rb is None:
        return False
    return abs(ra - rb) <= max(2, round(0.1 * min(ra, rb)))


def prefer(a: dict, b: dict, stance: str) -> tuple[dict, str]:
    """Pick between two close players. Returns (choice, reason)."""
    qa = injury_status(a.get("injury")).upper() == "QUESTIONABLE"
    qb = injury_status(b.get("injury")).upper() == "QUESTIONABLE"
    if qa != qb:
        choice = b if qa else a
        return choice, "healthy over Questionable"
    if stance == "underdog":
        ca, cb = _num(a.get("rank_min")), _num(b.get("rank_min"))
        if ca != cb:
            return (a, "higher ceiling (best expert rank)") if ca < cb else (b, "higher ceiling (best expert rank)")
    elif stance == "favorite":
        fa, fb = _num(a.get("rank_max")), _num(b.get("rank_max"))
        if fa != fb:
            return (a, "higher floor (worst expert rank)") if fa < fb else (b, "higher floor (worst expert rank)")
    ga, gb = _grade_order(a.get("grade")), _grade_order(b.get("grade"))
    if ga != gb:
        return (a, "better start/sit grade") if ga < gb else (b, "better start/sit grade")
    ka, kb = weekly_key(a) or UNRANKED, weekly_key(b) or UNRANKED
    return (a, "better consensus rank") if ka <= kb else (b, "better consensus rank")


def _pin_locked_starters(rows: list[dict], slots: list[str]) -> dict[int, dict]:
    """Starters whose game has started stay in their slot: Yahoo will not move them."""
    fixed: dict[int, dict] = {}
    for p in rows:
        if p.get("slot") != "starter" or not p.get("locked"):
            continue
        free = [i for i in range(len(slots)) if i not in fixed]
        exact = [i for i in free if slots[i] == (p.get("lineup_slot") or "").upper()]
        fits = exact or [i for i in free if slot_accepts(slots[i], p.get("pos"))]
        if fits:
            fixed[fits[0]] = p
    return fixed


def points(lineup: dict[int, dict]) -> tuple[float, int]:
    """Projected points of a lineup and how many starters have no projection."""
    total, missing = 0.0, 0
    for p in lineup.values():
        if p.get("proj") is None:
            missing += 1
        elif startable(p) or p.get("locked"):
            total += float(p["proj"])
    return round(total, 1), missing


def plan_lineup(rows: list[dict], slots: list[str], win_prob: float | None) -> dict:
    """The recommended legal lineup for this week, with the changes from the current one.

    Ranks set the lineup (the expert consensus is the product); projected points are reported, and
    a projected-point gap under CLOSE_POINTS is a close call settled by the matchup stance.
    """
    stance = posture(win_prob)
    fixed = _pin_locked_starters(rows, slots)
    lineup = best_lineup(rows, slots, weekly_key, fixed)

    # Close calls: the best eligible bench player for each slot, when the gap is inside the noise
    close_calls = []
    used = {id(p) for p in lineup.values()}
    for i in sorted(lineup, key=lambda i: -(weekly_key(lineup[i]) or 0)):
        if i in fixed:
            continue
        starter = lineup[i]
        alts = [b for b in rows if id(b) not in used and weekly_key(b) is not None
                and slot_accepts(slots[i], b.get("pos"))]
        if not alts:
            continue
        alt = min(alts, key=weekly_key)
        if not is_close(starter, alt):
            continue
        choice, reason = prefer(starter, alt, stance)
        close_calls.append({"slot": slots[i], "starter": starter["name"], "alternative": alt["name"],
                            "choice": choice["name"], "reason": reason,
                            "starter_proj": starter.get("proj"), "alt_proj": alt.get("proj")})
        if choice is alt:
            lineup[i] = alt
            used.discard(id(starter))
            used.add(id(alt))

    current = {p["fpId"] for p in rows if p.get("slot") == "starter"}
    chosen = {p["fpId"] for p in lineup.values()}
    ins = sorted((p for p in lineup.values() if p["fpId"] not in current), key=lambda p: weekly_key(p) or UNRANKED)
    outs = sorted((p for p in rows if p["fpId"] in current - chosen),
                  key=lambda p: -(weekly_key(p) or UNRANKED * 2))
    slot_of = {p["fpId"]: slots[i] for i, p in lineup.items()}
    changes = []
    for k, p in enumerate(ins):
        out = outs[k] if k < len(outs) else None
        changes.append({"start": p["name"], "slot": slot_of[p["fpId"]], "bench": out["name"] if out else None,
                        "why_out": _why_not(out) if out else None,
                        "gain": round(float(p["proj"]) - (float(out["proj"]) if out and startable(out) else 0.0), 1)
                        if p.get("proj") is not None and (out is None or out.get("proj") is not None) else None})
    for out in outs[len(ins):]:
        changes.append({"start": None, "slot": out.get("lineup_slot"), "bench": out["name"],
                        "why_out": _why_not(out), "gain": None})

    current_lineup = {i: p for i, p in enumerate(p for p in rows if p.get("slot") == "starter")}
    before, _ = points(current_lineup)
    after, missing = points(lineup)
    return {
        "slots": slots,
        "stance": stance,
        "win_prob": win_prob,
        "recommended": [{"slot": slots[i], **_brief(lineup[i]), "locked": bool(lineup[i].get("locked"))}
                        for i in sorted(lineup)],
        "empty_slots": [slots[i] for i in range(len(slots)) if i not in lineup],
        "changes": changes,
        "close_calls": close_calls,
        "proj_current": before,
        "proj_recommended": after,
        "proj_missing": missing,
    }


def _why_not(p: dict) -> str:
    if p.get("bye_now"):
        return "on bye"
    if unavailable(p.get("injury")):
        return injury_status(p.get("injury")) or "not practicing"
    return "ranked lower"


def _brief(p: dict) -> dict:
    return {k: p.get(k) for k in ("fpId", "name", "pos", "rank", "proj", "rank_min", "rank_max", "grade",
                                  "opp", "ros_rank")}


# ---------------------------------------------------------------- moves

def _ros_margin_ok(incoming: dict, outgoing: dict) -> bool:
    if outgoing.get("ros_rank") is None:
        return incoming.get("ros_rank") is not None
    gap = outgoing["ros_rank"] - ros_key(incoming)
    return gap >= max(MIN_ROS_GAP, MIN_ROS_GAP_SHARE * outgoing["ros_rank"])


def _weekly_value(p: dict) -> float:
    k = weekly_key(p)
    return k if k is not None else float("inf")


def breadth(lists: dict[int, dict[int, int]], a: int, b: int) -> dict:
    """How many experts rank player a ahead of player b, out of the experts who rank both.

    `lists` is {expert id: {fpId: rank}}. 'robust' is False when dropping the single most extreme
    expert on either side flips the majority, so one outlier cannot carry a move.
    """
    diffs = [ranks[b] - ranks[a] for ranks in lists.values() if a in ranks and b in ranks]
    cover_a = sum(1 for ranks in lists.values() if a in ranks)
    cover_b = sum(1 for ranks in lists.values() if b in ranks)
    ahead = sum(1 for d in diffs if d > 0)
    majority = bool(diffs) and ahead > len(diffs) / 2
    robust = majority
    for drop in (max(diffs, default=None), min(diffs, default=None)):
        if drop is None:
            continue
        rest = list(diffs)
        rest.remove(drop)
        if rest and (sum(1 for d in rest if d > 0) > len(rest) / 2) != majority:
            robust = False
    return {"both": len(diffs), "ahead": ahead, "majority": majority, "robust": robust,
            "experts_in": cover_a, "experts_out": cover_b}


def _role_evidence(ev: dict | None, today_ord: int) -> str | None:
    """A dated role line from recent points or fresh news, or None when there is none."""
    if not ev:
        return None
    bits = []
    pts = ev.get("points") or {}
    if pts:
        bits.append("recent pts " + ", ".join(f"wk{w} {v:g}" for w, v in sorted(pts.items())))
    for item in ev.get("news") or []:
        if item.get("date_ord") is not None and today_ord - item["date_ord"] <= NEWS_MAX_AGE_DAYS:
            bits.append(f"FP news {item['date']}: {item['title']}")
            break
    return "; ".join(bits) or None


def propose_moves(rows: list[dict], free_agents: dict[str, list[dict]], slots: list[str], *,
                  weekly: bool, coverage: dict[str, dict[str, int | None]],
                  expert_lists: Callable[[str], dict[int, dict[int, int]]] | None,
                  evidence: Callable[[list[dict]], dict[int, dict]] | None,
                  today_ord: int, week: int | None) -> dict:
    """Add/drop pairs that pass every gate, plus the held candidates and why they were held.

    Gates, in order (the first failure holds the pair):
        legal        the roster can still fill every starting slot after the swap
        available    the incoming player is not out, IR, doubtful, or not practicing
        ros_data     both horizons have rankings for this group
        coverage     each consensus used at least MIN_EXPERTS experts
        ros_better   the incoming player's ROS rank beats the outgoing player's (test A)
        ros_margin   by a real margin, not noise
        weekly       weekly runs: the incoming player is no worse this week (test B)
        breadth      weekly runs: most experts who rank both prefer the incoming player
    Then the evidence items (role and matchup, dated). A pair that passes the gates but lacks
    evidence is PROVISIONAL; only RECOMMEND pairs should be acted on.
    """
    roster = list(rows)
    recommended, provisional, held = [], [], []
    breadth_cache: dict[str, dict | None] = {}
    breadth_notes: list[str] = []

    def lists_for(grp: str):
        if grp not in breadth_cache:
            try:
                breadth_cache[grp] = expert_lists(grp) if expert_lists else None
            except Exception as exc:  # optional data: the move is marked 'not checked', never crashes
                breadth_cache[grp] = None
                breadth_notes.append(f"{grp}: per-expert lists unavailable ({exc}); breadth not checked")
        return breadth_cache[grp]

    def evaluate(inc: dict, out: dict, grp: str, cov: dict) -> tuple[str | None, dict | None]:
        failed = _gate(inc, out, roster, slots, weekly, cov)
        if failed:
            return failed, None
        pair = {"add": inc["name"], "add_id": inc["fpId"], "drop": out["name"], "drop_id": out["fpId"],
                "group": grp, "pos_in": inc.get("pos"), "pos_out": out.get("pos"),
                "ros": (inc.get("ros_rank"), out.get("ros_rank")),
                "ros_ave": (inc.get("ros_ave"), out.get("ros_ave")),
                "weekly": (inc.get("rank"), out.get("rank")),
                "proj": (inc.get("proj"), out.get("proj")),
                "experts": (cov.get("weekly"), cov.get("ros")),
                "evidence": {}}
        ev = pair["evidence"]
        ev["availability"] = (f"in: {injury_status(inc.get('injury')) or 'no injury listed'}"
                              f"{', BYE this week' if inc.get('bye_now') else ''}; "
                              f"out: {injury_status(out.get('injury')) or 'no injury listed'}"
                              f"{', BYE this week' if out.get('bye_now') else ''}")
        ev["two_horizon"] = (f"ROS #{inc.get('ros_rank')} vs #{out.get('ros_rank')}"
                             + (f"; week {week} #{inc.get('rank')} vs #{out.get('rank')}" if weekly else
                                "; weekly not checked (ROS run)"))
        if weekly:
            lists = lists_for(grp)
            if lists:
                b = breadth(lists, inc["fpId"], out["fpId"])
                if not b["majority"]:
                    return f"breadth: only {b['ahead']} of {b['both']} experts rank {inc['name']} ahead", None
                if min(b["experts_in"], b["experts_out"]) < MIN_EXPERTS:
                    return (f"coverage: only {b['experts_in']} / {b['experts_out']} experts rank "
                            f"{inc['name']} / {out['name']}"), None
                ev["breadth"] = (f"{b['ahead']} of {b['both']} experts rank {inc['name']} ahead of {out['name']}"
                                 + ("" if b["robust"] else " (weak: removing one outlier flips it)"))
                pair["robust"] = b["robust"]
            else:
                ev["breadth"] = None
            ev["matchup"] = (f"week {week}: {inc['name']} {inc.get('opp') or 'no game'} "
                             f"(grade {inc.get('grade') or 'n/a'}); {out['name']} {out.get('opp') or 'no game'} "
                             f"(grade {out.get('grade') or 'n/a'})") if inc.get("opp") or inc.get("bye_now") else None
        pair["_in"], pair["_out"] = inc, out
        return None, pair

    for grp, fas in free_agents.items():
        cov = coverage.get(grp, {})
        pool = sorted(fas, key=ros_key)
        drops = sorted((p for p in roster if p.get("group") == grp and not p.get("locked")),
                       key=lambda p: -ros_key(p))
        for out in drops:
            first_failure = None
            for inc in pool:
                if ros_key(inc) >= ros_key(out):
                    break  # the pool is sorted by ROS rank; nobody further down beats this player
                failed, pair = evaluate(inc, out, grp, cov)
                if failed:
                    first_failure = first_failure or (inc, failed)
                    continue
                pool.remove(inc)
                roster = [p for p in roster if p is not out] + [inc]
                recommended.append(pair)
                first_failure = None
                break
            if first_failure:
                inc, failed = first_failure
                same = next((h for h in held if h["add"] == inc["name"] and h["failed"] == failed), None)
                if same:  # one line per add when the reason is about the add itself (e.g. it is OUT)
                    same["drop"] += f", {out['name']}"
                else:
                    held.append({"add": inc["name"], "drop": out["name"], "group": grp, "failed": failed})

    # Evidence for the surviving pairs (dated role reporting from FantasyPros news and recent points)
    candidates = recommended + provisional
    ev_by_id: dict[int, dict] = {}
    evidence_note = None
    if candidates and evidence:
        try:
            ev_by_id = evidence([p for c in candidates for p in (c["_in"], c["_out"])])
        except Exception as exc:
            evidence_note = f"role evidence unavailable ({exc}); role is not checked"
    final_rec, final_prov = [], []
    for c in candidates:
        role_in = _role_evidence(ev_by_id.get(c["add_id"]), today_ord)
        role_out = _role_evidence(ev_by_id.get(c["drop_id"]), today_ord)
        c["evidence"]["role"] = (f"in: {role_in or 'no recent reporting found'}; "
                                 f"out: {role_out or 'no recent reporting found'}")
        c["evidence"]["news"] = [n for pid in (c["add_id"], c["drop_id"])
                                 for n in (ev_by_id.get(pid) or {}).get("news", [])[:2]]
        note = c["_in"].get("note")
        if note:
            c["evidence"]["expert_note"] = note[:400]
        missing = [k for k in ("breadth", "matchup") if weekly and not c["evidence"].get(k)]
        if not (role_in and role_out):
            missing.append("role")
        if weekly and not c.get("robust", True):
            missing.append("robust breadth")
        if not weekly:
            missing.append("weekly confirmation (run_weekly)")
        c["missing"] = missing
        c.pop("_in"), c.pop("_out")
        (final_prov if missing else final_rec).append(c)

    return {"recommended": final_rec, "provisional": final_prov, "held": held,
            "notes": breadth_notes + ([evidence_note] if evidence_note else [])}


def _gate(inc: dict, out: dict, roster: list[dict], slots: list[str], weekly: bool,
          cov: dict[str, int | None]) -> str | None:
    """The first gate this add/drop pair fails, as 'gate: reason', or None when it passes them all."""
    after = [p for p in roster if p is not out] + [inc]
    if not fillable(after, slots):
        return f"legal: dropping {out['name']} leaves no player for {', '.join(unfilled(after, slots))}"
    if unavailable(inc.get("injury")):
        return f"available: {inc['name']} is {injury_status(inc.get('injury')) or 'not practicing'}"
    if cov.get("ros") is None or (weekly and cov.get("weekly") is None):
        return "ros_data: no ROS rankings for this group" if cov.get("ros") is None else "ros_data: no weekly rankings"
    for horizon in ("weekly", "ros") if weekly else ("ros",):
        n = cov.get(horizon) or 0
        if n < MIN_EXPERTS:
            return f"coverage: the {horizon} consensus used {n} experts (need {MIN_EXPERTS})"
    if ros_key(inc) >= ros_key(out):
        return f"ros_better: ROS #{inc.get('ros_rank')} is not better than #{out.get('ros_rank')}"
    if not _ros_margin_ok(inc, out):
        return f"ros_margin: ROS #{inc.get('ros_rank')} vs #{out.get('ros_rank')} is inside the noise"
    if weekly and _weekly_value(inc) > _weekly_value(out):
        return (f"weekly: {inc['name']} is worse this week "
                f"({'bye' if inc.get('bye_now') else '#' + str(inc.get('rank'))} vs "
                f"{'bye' if out.get('bye_now') else '#' + str(out.get('rank'))})")
    return None


# ---------------------------------------------------------------- roster summaries

def net_change(rows: list[dict], moves: list[dict], free_agents: dict[str, list[dict]], slots: list[str],
               win_prob: float | None) -> dict:
    """Roster ROS average and recommended-lineup projection, before and after the recommended moves."""
    by_id = {p["fpId"]: p for fas in free_agents.values() for p in fas}
    after = list(rows)
    for m in moves:
        after = [p for p in after if p["fpId"] != m["drop_id"]] + [dict(by_id[m["add_id"]], slot="bench")]

    def ros_avg(players):
        ranked = [p["ros_rank"] for p in players if p.get("ros_rank") is not None]
        return round(mean(ranked), 1) if ranked else None

    return {
        "roster_ros_avg": (ros_avg(rows), ros_avg(after)),
        "proj": (plan_lineup(rows, slots, win_prob)["proj_recommended"],
                 plan_lineup(after, slots, win_prob)["proj_recommended"]),
    }


def trend(lineup: dict, prior: dict | None, ros_rank_of: Callable[[int], int | None]) -> dict | None:
    """Starters' average ROS rank now vs. the prior snapshot's starters, both at this week's ROS ranks."""
    if not prior:
        return None
    prior_ids = [p["fpId"] for p in (prior.get("lineup") or {}).get("recommended", [])] or \
                [p["fpId"] for p in prior.get("roster", []) if p.get("slot") == "starter"]
    now_ids = [p["fpId"] for p in lineup["recommended"]]

    def avg(ids):
        ranks = [r for i in ids if (r := ros_rank_of(i)) is not None]
        return round(mean(ranks), 1) if ranks else None

    return {"prior_period": prior.get("period"), "prior": avg(prior_ids), "now": avg(now_ids)}


def lookahead(rows: list[dict], slots: list[str], week: int | None, weeks: int = LOOKAHEAD_WEEKS) -> list[str]:
    """Upcoming weeks where byes or long-term injuries leave a starting slot with nobody to fill it."""
    if not week:
        return []
    out = []
    for w in range(week + 1, min(week + weeks, 18) + 1):
        avail = [p for p in rows if str(p.get("bye")) != str(w) and not long_term_out(p)]
        missing = unfilled(avail, slots)
        if missing:
            on_bye = [p["name"] for p in rows if str(p.get("bye")) == str(w)]
            out.append(f"week {w}: cannot fill {', '.join(missing)}"
                       + (f" (on bye: {', '.join(on_bye)})" if on_bye else ""))
    hurt = [p["name"] for p in rows if long_term_out(p)]
    if hurt:
        out.append(f"long-term out (IR/PUP/suspended): {', '.join(hurt)}")
    return out
