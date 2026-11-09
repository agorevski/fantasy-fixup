# Decision rules (what the tool computes, and how to explain it)

`run_weekly` applies every rule below in code (`src/fantasy_lineup/decisions.py`). Your job is to report its verdicts and explain them. Do not recompute them by hand, and do not override them, except for the promotion rule in section 5.

## 1. Lineup: the best legal lineup for this week

- Slots come from the league (for this league: QB, RB, RB, WR, WR, WR, TE, 2× WR/RB/TE, K, DST). A player only fills a slot that accepts their position: an RB never fills the TE slot.
- Players are ordered by this week's consensus rank. The best legal set starts.
- **Cannot start:** on bye, ruled out (Out, IR, Doubtful, PUP, suspended, or DNP at every practice), or a bench player whose game has already started.
- **Locked starters** (game started) stay in their slot. Yahoo will not move them.
- A slot nobody on the roster can fill is reported as `EMPTY SLOT`. Point the user to the add/drop moves and the best-available list.
- Start/sit is a weekly decision. It is free to change back, so it is not gated on ROS rankings or on last week's lineup.

## 2. Close calls and the matchup stance

A starter and the best eligible bench player are a **close call** when their FantasyPros projections are less than 1.5 points apart (or their ranks are within about 10%). The tool settles each one as follows:

- A healthy player beats a Questionable one.
- **Stance** comes from FantasyPros' win probability for this matchup:
  - **underdog** (under 40%): the higher ceiling wins (the better best-expert rank, `rank_min`).
  - **favorite** (over 60%): the higher floor wins (the better worst-expert rank, `rank_max`).
  - **neutral**: the better start/sit grade, then the better rank.

Report each close call with both projections and the reason. Tell the user that close calls are judgment calls.

## 3. Injuries

| Status | Effect |
|---|---|
| Out, IR, Doubtful, PUP, suspended, or DNP all week | Cannot start; never added |
| Questionable | Can start; loses close calls to a healthy player |
| Probable, Limited then Full, or no entry | No penalty |

An empty injury entry means none is listed. It does not confirm the player is healthy. `lookup failed` means unchecked.

## 4. Add/drop gates (both sources)

Each pair is tested in this order. The first failure holds the pair, and the held list shows the gate name and the reason.

| Gate | Passes when |
|---|---|
| `legal` | After the swap, the roster can still fill every starting slot. This prevents dropping your last TE, K, or DST. |
| `available` | The incoming player is not out, IR, doubtful, or not practicing. |
| `ros_data` | Both horizons have rankings for the group. |
| `coverage` | The weekly and ROS consensus each used at least 5 experts. Each player is ranked by at least 5 of the weekly experts. |
| `ros_better` | The incoming player's ROS rank beats the outgoing player's (test A). |
| `ros_margin` | By at least 5 ranks or 15% of the outgoing player's ROS rank, whichever is larger. Smaller gaps are noise. |
| `weekly` | The incoming player is no worse this week (test B). A bye or injury counts as worst. |
| `breadth` | A majority of the experts who rank both players prefer the incoming player. |

Moves are evaluated in sequence on the updated roster, so two moves can never combine to empty a slot. Locked players are never offered as drops this week.

## 5. Evidence and verdicts

Each pair that passes the gates carries five evidence items: breadth (count of experts), two-horizon (weekly and ROS ranks), availability, role (dated), and matchup (dated).

- **Role** comes from FantasyPros: recent fantasy points (last 3 weeks) or a FantasyPros news item no more than 14 days old, for both players. This needs `FP_API_KEY`.
- **Matchup** comes from the opponent and FantasyPros' start/sit grade for this week.

| Verdict | Meaning |
|---|---|
| `RECOMMEND` (the "Recommended" section) | All gates and all evidence passed. Act on it. |
| `PROVISIONAL` | All gates passed, but an evidence item is missing, or breadth is weak (one outlier expert flips it). Do not tell the user to act yet. |
| Held | A gate failed. Show it, with the reason, so the user sees what was not recommended. |

**Promotion rule:** you may promote a `PROVISIONAL` move to recommended only when the only missing item is `role`, and you fill it from FantasyPros as described in [research.md](research.md): a dated news item or player-page update for **both** players from the last 14 days. Cite each item. Never promote for missing breadth, a weak breadth result, or a missing weekly confirmation.

## 6. Net change and trend

- **Net change:** the roster's average ROS rank and the recommended lineup's projected points, before and after the recommended moves. If the ROS average would get worse, the tool demotes every move to provisional.
- **Trend:** the starters' average ROS rank now, against the last snapshot's starters, both at this week's ROS ranks. It is informational. Say whether the roster is improving.

## 7. Byes and injuries ahead

The lookahead lists the next 3 weeks in which byes or long-term injuries leave a starting slot with nobody to fill it. Raise these early: a waiver add made today is cheaper than a scramble on Sunday.

## 8. Streaming view (QB, K, DST)

"Best available this week" is the best startable player at each of these positions, on your roster or a free agent. It is **not** gated. A K or DST stream rarely beats a rostered player in ROS rank. If you mention it, label it a streaming option, give the projection gap, and do not present it as a recommended move.

## 9. FLEX vs last week

This is informational only. It never blocks a lineup change. A week that is weaker than last week (because of byes or injuries) still gets the best available lineup.
