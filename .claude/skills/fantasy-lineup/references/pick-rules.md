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

## 7. Web source: net-positive moves only (ROS-gated)

This section applies only when `FP_SOURCE=web`. It is stricter than the weekly rules above. A move is recommended only if it passes every test below. If any test fails, do not recommend it. Say which test failed and hold the player.

**Inputs:** the `run_weekly` output (weekly ranks, bye, injury, expert median) and the `run_ros` output (ROS ranks and ROS expert medians). Both are required. If `run_ros` failed or was not run, make no web-source moves and say why.

**Test A: ROS consensus improves.** For an add/drop or swap, the incoming player's ROS rank must be better (lower) than the outgoing player's ROS rank. The ROS expert median must also be better, not just the consensus rank.

**Test B: weekly consensus does not regress.** The incoming player's weekly rank must be better than or equal to the outgoing player's weekly rank. A player who is better long term but worse this week is a hold, not a move, unless the user asks for a long-term view.

**Test C: enough expert coverage.** Each player must have an expert median built from at least 5 experts, in both the ROS and weekly data. Count the experts from the `experts checked X/Y` field or the `Data status` line. Fewer than 5 means the consensus is too thin to act on. Hold the player and name the coverage shortfall. For example, the latest ROS run used only 2 of 20 QB experts and 3 of 20 FLX experts, so most of its ROS moves would fail this test.

**Test D: no bench-over-starter regression.** Do not start a player whose ROS rank is worse than a healthy bench player's ROS rank at the same position group. If it happens, the rank data says to swap them, so flag the swap as a candidate. Still apply tests A–C before recommending it.

**Test E: roster trend week over week.** The roster must be getting better every week, not just this week. Compare this week's starters with the last saved snapshot:
- Take the average ROS rank of the starting lineup for each position group, and the same for the whole roster, using this week's ROS ranks for both weeks. A lower average is better.
- The proposed moves must not make this average worse.
- If there is no prior snapshot, save the baseline and say so. Do not claim a trend. Only tests A–D can gate the moves on the first run.
- If the average would worsen, do not recommend the move, even if it passes A–D for one player.

**Net-positive summary:** report the net change for the whole lineup after all recommended moves. For example: "Net ROS-rank change: starters avg 31.2 → 28.4 (better)." If the net change is not better, recommend no moves.

**Evidence standard:** passing tests A–E is necessary but not sufficient. Every recommended move also needs the evidence bundle in section 8. A median alone is never the reason for a move.

**Stop conditions:** if coverage fails test C for every player, say that the web consensus is not usable this week. Recommend no changes, and say what the user can do (for example, re-check the website session or try the API source). Do not guess from the weekly data alone.

## 8. Evidence bundle for every move (web source)

Each recommended move must cite these five items. Write `not checked` for any item you could not verify, and say why. A missing item makes the move **provisional**, and provisional moves are listed but not recommended.

1. **Expert breadth, not just the median.** Count the experts who rank the incoming player ahead of the outgoing player, out of the experts who rank both. Require a clear majority (more than half). Use `expert_picks` for the per-expert ranks. Do not let one expert far from the rest drive the result. If removing the single highest or lowest expert flips the result, say so and treat the move as weak.
2. **Two-horizon agreement.** The weekly and ROS data must point the same way. A move that helps only in one horizon is a hold, and the report must name the horizon that disagrees.
3. **Availability.** The injury status, practice status, and bye week for both players, from the output's `INJURY:` and `BYE` tags. An incoming player who is Out, IR, or on bye this week fails this item.
4. **Role evidence (dated).** One dated source for each player's role this week: snap share, target or carry share, depth chart, or QB situation. Use [research.md](research.md) and cite the source and date. If nothing recent turns up, write `no recent reporting found`. That is not a pass on its own, so the move stays provisional.
5. **Matchup or game context (dated).** One dated note on the opponent, game script, or weather for each player. Same rule as item 4.

**Research is required for moves.** This is a deliberate exception to the rule that bucket 2 never blocks. The analysis still runs and the tables still show, but a move cannot become a recommendation without items 4 and 5. Research is limited to the players in the proposed moves, so it stays small.

**Explanations:** for each recommended move, give one line per item: the evidence found, its source, and its date. Example: "Expert breadth: 9 of 14 experts rank Allen ahead of Pitts (experts 317, 454 excluded for missing ROS data). Role: 2 carries and 3 targets last game (source, date)."
