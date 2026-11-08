# Pick rules (weekly)

Apply these rules in order when building the lineup and the moves. They assume the data model in [data-model.md](data-model.md).

## 1. Byes

A player on a bye this week cannot score. Never start one if a healthy option exists. The output marks them `BYE THIS WEEK`.

- QB, K, and DST "best picks" already skip teams on a bye.
- FLEX candidates on a bye are excluded from the week-over-week check.

## 2. Injuries (bucket 2)

Use the `INJURY:` tag when injury data is present. If the lookup failed or the data is missing, the status is `unchecked`. That is an allowed state, not a reason to stop.

| Status | Action |
|---|---|
| Out, IR, Doubtful, or no practice | Do not start. Bench, or move them if a healthy option exists. |
| Questionable | Start only if no better healthy option exists and the reporting is neutral or positive. Say so in the table. |
| Probable, or Limited then Full | No penalty. |

Injury data covers the roster and the top free agents at each position. For anyone else, check with WebSearch only if time allows, and do not block on it.

## 3. Individual experts (bucket 2)

Each player's `expert_median` and `expert_picks` show how each top expert ranked them. Use them as a tiebreaker or check when present:

- When two players are close in consensus rank, prefer the one that more experts rank higher.
- When the consensus and the expert median disagree, or one expert is far from the rest, name that expert and explain the gap.
- Experts' written commentary is not in the feed. For commentary, use WebSearch (see [research.md](research.md)).

## 4. FLEX (RB/WR/TE) must improve on last week

Each week's FLEX picks must be consistently better than the prior week's.

- Each weekly run saves a snapshot to `var/cache/history/`.
- On the next run, the tool pairs this week's best healthy, non-bye FLEX lineup with last week's actual FLEX starters, best to worst. Both are ranked at **this week's** ranks.
- Each slot is marked `IMPROVED` or `NO IMPROVEMENT`.
- Do not recommend a FLEX move marked `NO IMPROVEMENT`. For such a slot, say so and hold that starter, unless the prior player is marked `[no longer available]`. In that case, say that instead.

## 5. QB, K, and DST are exempt from the week-over-week rule

Start the best-ranked healthy, non-bye player at each position. This is the "Weekly best pick" line in the output.

- Do not hold a QB, K, or DST because last week's pick was better.
- The "Weekly best pick" line does not check injuries. If the top pick is `OUT` in the injury data, use the next healthy player and say why.

## 6. First run in a new period

The first run has no prior snapshot. It saves the baseline and prints `no prior snapshot yet`. Say that the week-over-week check starts next period.
