"""Lineup legality and the best legal lineup for a league's starting slots. Pure functions, no I/O.

Slots come from the league feed's position string, for example
'QB,RB,RB,WR,WR,WR,TE,WR/RB/TE,WR/RB/TE,DST,K,BN,BN'. A slot accepts a player when any of the
player's positions ('WR' or a multi-position 'WR/RB') is in the slot's list.

The best lineup is a weighted matching: each player has one value whatever slot they fill, so the
players that can be seated together form a matroid and taking them greedily, best first, is optimal.
Each player is seated with an augmenting path, which may shift earlier players between slots but
never unseats them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

BENCH_SLOTS = {"BN", "IR", "IR+", "NA"}

# The slot layout of a standard Yahoo league, used only when the league feed has no position string
DEFAULT_SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "WR/RB/TE", "WR/RB/TE", "K", "DST"]


def parse_slots(positions: str | None) -> list[str]:
    """Starting slots from the league feed's position string. Bench and IR slots are left out."""
    slots = [s.strip().upper() for s in (positions or "").split(",")]
    slots = [s for s in slots if s and s not in BENCH_SLOTS]
    return slots or list(DEFAULT_SLOTS)


def positions_of(pos: str | None) -> set[str]:
    return {p.strip().upper() for p in (pos or "").split("/") if p.strip()}


def slot_accepts(slot: str, pos: str | None) -> bool:
    return bool(positions_of(slot) & positions_of(pos))


def _slot_order(slots: list[str]) -> list[int]:
    """Slot indexes with single-position slots first, so stars fill their own slot before a FLEX."""
    return sorted(range(len(slots)), key=lambda i: (len(positions_of(slots[i])), i))


def assign(players: Iterable[dict], slots: list[str], fixed: dict[int, dict] | None = None) -> dict[int, dict]:
    """Seat players in the given order, keeping each one that still fits. Returns {slot index: player}.

    `fixed` pins players to slot indexes (for example a starter whose game has started); those slots
    are never reassigned.
    """
    owner: dict[int, dict] = dict(fixed or {})
    order = [i for i in _slot_order(slots) if i not in owner]

    def place(p: dict, seen: set[int]) -> bool:
        for i in order:
            if i in seen or not slot_accepts(slots[i], p.get("pos")):
                continue
            seen.add(i)
            current = owner.get(i)
            if current is None or place(current, seen):
                owner[i] = p
                return True
        return False

    for p in players:
        place(p, set())
    return owner


def best_lineup(players: Iterable[dict], slots: list[str], key: Callable[[dict], float | None],
                fixed: dict[int, dict] | None = None) -> dict[int, dict]:
    """The best legal lineup: players sorted by key (lower is better) and seated greedily.

    Players whose key is None cannot start (on bye, out, locked on the bench) and are skipped, so a
    slot with no eligible player is left empty.
    """
    pinned = {id(p) for p in (fixed or {}).values()}
    ranked = [(k, p) for p in players if id(p) not in pinned and (k := key(p)) is not None]
    ranked.sort(key=lambda kp: kp[0])
    return assign([p for _, p in ranked], slots, fixed)


def fillable(players: Iterable[dict], slots: list[str]) -> bool:
    """True when these players can fill every starting slot (ignoring injuries and byes).

    Used to keep add/drop pairs from leaving the roster without, say, a TE.
    """
    return len(assign(list(players), slots)) == len(slots)


def unfilled(players: Iterable[dict], slots: list[str]) -> list[str]:
    """The slots these players cannot fill."""
    owner = assign(list(players), slots)
    return [slots[i] for i in range(len(slots)) if i not in owner]
