"""Parsing shared by both data sources: consensus-ranking entries and the metadata around them.

The public API and the website's consensus endpoint return the same player fields, so both sources
turn them into the same dict here. Fields the source does not send come back as None.
"""

from __future__ import annotations


def _int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_player(p: dict) -> dict:
    """One consensus-ranking entry as the advisor's player dict."""
    return {
        "name": p["player_name"],
        "pos": p["player_position_id"],
        "team": p.get("player_team_id"),
        "rank": int(p["rank_ecr"]),
        "pos_rank": p.get("pos_rank"),
        "rank_min": _int(p.get("rank_min")),
        "rank_max": _int(p.get("rank_max")),
        "rank_ave": _float(p.get("rank_ave")),
        "rank_std": _float(p.get("rank_std")),
        "proj": _float(p.get("r2p_pts")),          # FantasyPros rankings-to-projections points
        "grade": p.get("start_sit_grade"),
        "opp": p.get("player_opponent"),
        "bye": p.get("player_bye_week"),
        "kickoff": _int(p.get("player_game_kickoff_ts")),
        "game_status": p.get("player_game_status"),
        "ecr_delta": _int(p.get("player_ecr_delta")),
        "owned_yahoo": _float(p.get("player_owned_yahoo")),
        "note": p.get("note") or None,             # expert write-up (public API waiver list only)
        "url": p.get("player_page_url"),
    }


def parse_players(data: dict) -> dict[int, dict]:
    return {int(p["player_id"]): parse_player(p) for p in data.get("players", [])}


def consensus_info(data: dict, ids: list[int], grp: str, label: str) -> dict:
    """How many experts the consensus used, plus any warning worth showing in Data status.

    `ids` is the expert filter that was requested; an empty list means the full consensus.
    """
    warnings = []
    used = {int(x) for x in (data.get("experts_available") or {}).get("included", [])}
    if ids and used and used != set(ids):
        warnings.append(f"{grp}: {label} used {len(used)} of {len(ids)} requested experts "
                        f"(not used: {sorted(set(ids) - used)})")
    experts = len(used) if used else (len(ids) if ids else _int(data.get("total_experts")))
    limit = _int(data.get("limit")) or 0
    players = len(data.get("players", []))
    if limit and players < limit:
        warnings.append(f"{grp}: {label} returned {players} players (limit {limit}); "
                        "players not in that list show as unranked")
    return {"experts": experts, "warnings": warnings, "type_name": data.get("ranking_type_name")}
