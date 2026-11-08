# Report format (Step 7)

Use markdown tables. Give the user the full lineup, the position-by-position decision, and the reasons behind each move.

Start with the **Data status** section from the tool output, so the user sees what was and was not used.

## Lineup table

One row per roster player, grouped by position, starters first.

| Position | Slot | Player (team) | Weekly rank | Bye / injury | Expert median | Action | Why (reporting) |
|---|---|---|---|---|---|---|---|

- Cover QB, RB/WR/TE (FLEX), K, and DST. Include every bench player.
- **Action** is one of: `Start`, `Sit (bench)`, `Start over <name>`, `Add <name> / Drop <name>`, or `Hold`.
- For QB, K, and DST, the action is the best-ranked healthy, non-bye player at that position.
- Write `unchecked` in the injury column when injury data was not fetched for that player.
- Write `not on cheat sheet` in the rank column for players the cheat sheet does not list.

## Week-over-week FLEX table

| Slot | This week's pick | Rank now | Last week's starter | Rank now | Result |
|---|---|---|---|---|---|

- Result is `IMPROVED` or `NO IMPROVEMENT`.
- Mark any player marked `[no longer available]`.

## Moves table

Include only moves that pass the rules in [pick-rules.md](pick-rules.md).

| Add | Drop | Position | Rank change | Expert split | Week-over-week | Reporting |
|---|---|---|---|---|---|---|

## Player notes

For each player you recommend moving, give one or two sentences on why. Draw from the research in [research.md](research.md) (if done) and the cheat-sheet and expert data. Name the source and date. Say when the reporting is thin or was not checked.

## Closing

Do not make roster changes. Tell the user which moves to make in Yahoo. Then state the caveats in [caveats.md](caveats.md) that apply to these results.
