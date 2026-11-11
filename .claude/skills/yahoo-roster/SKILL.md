---
name: yahoo-roster
description: Make roster changes in the Yahoo Fantasy app on the user's Android phone over ADB. Moves players between starting slots and the bench on the Team tab, and swaps players (claim one, drop one) from the Players tab. Use when the user asks to change, move, start, bench, add, drop, or swap players in their Yahoo Fantasy roster on the phone. Every roster change needs the user's explicit confirmation of the exact move.
---

# yahoo-roster

Drives the Yahoo Fantasy app through `scripts/yf.py`. The script reads compact, label-based screen summaries, so you never parse raw XML.

## Rules

- **Confirm before every roster change.** Show the user the exact moves (who goes in, who goes out, from which slot). Run only after a clear yes. Roster-changing recipe steps are marked `[CHANGES ROSTER]` and do nothing without `--confirmed`.
- **Read first.** Run `screen` before tapping. Tap only labels you saw in the current screen output.
- **Stop on the first surprise.** If a step fails or a dialog you did not expect appears, stop, show the screen summary, and ask. Do not guess.
- **Verify after every change.** Run `screen --grep <player>` and confirm the result matches the plan.
- Do not use `input` directly or edit raw XML. Use `yf.py` only.

## Commands

Run from the repo root. Always use `python3 -I`.

```
S=.claude/skills/yahoo-roster/scripts/yf.py
python3 -I $S devices                       # which phone is used
python3 -I $S launch                        # open Yahoo Fantasy
python3 -I $S screen [--grep TEXT] [--max N]   # '*' marks clickable; use --grep to save tokens
python3 -I $S tap "LABEL" [--exact] [--nth N]  # exit 2 = not found, 3 = ambiguous
python3 -I $S wait "LABEL" [--timeout 10]      # exit 4 = timed out
python3 -I $S swipe up|down
python3 -I $S tapxy X Y                        # raw coordinates, for unlabeled controls
python3 -I $S key back|home|enter
python3 -I $S run RECIPE.json --set player="NAME" [--confirmed]
python3 -I $S run recipes/move-player-to-slot.json --set league="Emo Rage Nerd Core" --set player="P. Mahomes" --set slot_desc="QB slot"
```

Set `YF_SERIAL` to the phone's adb serial. If it is unset, the first attached device with the Yahoo app is used.

## Reference

Full read-only map of the app's tabs, menus, and labels, plus the Sunday restrictions: [references/app-map.md](references/app-map.md). Read it before any new flow.

## Recipes

`recipes/` holds JSON step lists. `read-players-tab.json` is read-only and safe to run with `--confirmed`. Steps marked `"mutates": true` are roster changes. They print as `[CHANGES ROSTER]` and never run without `--confirmed` after the user approves the exact plan.

## Tested (2026-11-08, Sunday, read-only)

Every command was run on the Pixel 8 Pro: `devices`, `launch`, `screen --grep`, `tap` (found, not found exit 2, ambiguous exit 3, exact), `wait` (found, timeout exit 4), `type` (rejects unsafe text, exit 1), `swipe` up and down, tab navigation, and `run` (dry run, confirmed read-only run, mutation gate, missing parameter exit 1). No roster change was made. Not tested: `type` with valid text, `key`, and any roster-changing step.

## Status

| Flow | State |
|---|---|
| Read the Team tab (slots, bench header) | Works |
| Open a player card from the Team tab | Works (`Close` returns) |
| Open the Players tab; list `Claim` buttons | Works |
| Move a player into a starting slot (Team tab) | Works (`recipes/move-player-to-slot.json`). The unlabeled button left of each player's name opens a "Move Player" sheet; its row with content description `QB slot` (or the target slot) moves the player in and benches the current starter. Used on 2026-11-11 to start P. Mahomes over D. Prescott (verified on the Team tab). |
| Swap players (Players tab: claim, then choose a drop) | **Not yet mapped.** The `Claim` button opens a flow whose drop-selection screen and confirm button are unknown. No recipe yet. Do not run it |

Do not run a roster change until its recipe has been checked with a dry run and the user has confirmed the exact move.

## Unlabeled controls

Some controls have no text (the row button by each player's name). Use the recipe ops `tap_handle` (taps the button left of a named player) and `tap_desc` (taps an element by content description), or the command `tapxy X Y` for raw coordinates. Coordinates shift with scroll position, so prefer the recipe ops.
