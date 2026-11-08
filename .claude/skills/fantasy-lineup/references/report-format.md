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

For a web-source run, use this table instead, one row per move that passed all tests in [pick-rules.md](pick-rules.md) section 7:

| Add | Drop | Weekly rank (in / out) | ROS rank (in / out) | ROS median (in / out) | Experts (ROS / weekly) | Roster ROS avg after | Tests passed |
|---|---|---|---|---|---|---|---|

Then add a **Net change** line: starter ROS average before and after the moves, and whether it is better.

For each recommended move, add an **Evidence** block with the five items from [pick-rules.md](pick-rules.md) section 8: expert breadth (count and which experts), two-horizon agreement, availability, dated role reporting, and dated matchup reporting. Write `not checked` where an item is missing, and list that move as provisional, not recommended.

Also list **held** moves: the candidates that failed a test, with the test name and the reason (for example, `Test C: only 2 of 20 QB experts`). Show held moves, so the user can see what was not recommended and why.

## Player notes

For each player you recommend moving, give one or two sentences on why. Draw from the research in [research.md](research.md) (if done) and the cheat-sheet and expert data. Name the source and date. Say when the reporting is thin or was not checked.

## Closing

Do not make roster changes. Tell the user which moves to make in Yahoo. Then state the caveats in [caveats.md](caveats.md) that apply to these results.
