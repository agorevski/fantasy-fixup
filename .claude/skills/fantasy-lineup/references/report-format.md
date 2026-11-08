# Report format (Step 8)

The tool output is already ordered and mostly in markdown tables. Keep its order, tighten the wording, and add explanations. Put actions first. Do not bury them under data.

## 1. Do this in Yahoo

A numbered list, copied from the tool's **Do this in Yahoo** section, in order:

- `START <player> at <slot>, bench <player> (<reason>) (+X.X proj pts)`
- `ADD <player> / DROP <player>`: recommended moves only.
- Any `EMPTY SLOT`, with what to do about it.

If there are no actions, say that the current lineup is already the best legal lineup. Then give the projected points line (current vs recommended) and the matchup line (opponent, FantasyPros win probability, stance).

## 2. Data status

Copy the tool's Data status bullets and the experts-per-consensus line. Say plainly what was missing and what that means, for example "role evidence unavailable: API rate limited, so moves stay provisional".

## 3. Lineup

The tool's **Recommended lineup** table: one row per slot, with weekly rank and its expert range, projection, grade, opponent, ROS rank, and bye/injury/lock. Then the bench. Then **Close calls**, one line each with both projections, the choice, and the reason.

## 4. Moves

- The moves table for recommended moves.
- For each recommended or provisional move, an **Evidence** block with one line per item: breadth, two-horizon, availability, role, matchup. Cite FantasyPros news with its date. Write `not checked` where the tool said so.
- Label provisional moves "do not act yet" and name what is missing. If you promoted one under the promotion rule, say so and cite the items.
- **Held** moves: gate name and reason, one line each.
- The **Net change** and **Trend** lines.

## 5. Ahead and optional

- **Byes and injuries ahead.** Any slot gaps in the next 3 weeks.
- **Streaming options (QB/K/DST)**, labeled as ungated (see [pick-rules.md](pick-rules.md) section 8).
- **Free agents to watch.** At most 3 per group, preferring rising players (positive trend) with low ownership.
- **Last week's grade**, if `grade_week` ran: the advice gain and the points left on the bench.

## Closing

Do not make roster changes. Tell the user to make the moves in Yahoo, and suggest when to check again (see "Timing" in SKILL.md). Then state the caveats in [caveats.md](caveats.md) that apply.
