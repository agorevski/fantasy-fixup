# Configuration (Steps 0 and 1)

Run this before any tool that calls the API, the website, or the league feed. Run it every time the skill is invoked, even when the user seems to be in a hurry. Skip only the confirmation prompt, as described below.

## Step 0: Confirm configuration

1. Call `check_config`. It reports which settings are present, without values, and whether the web session is saved. Call `current_source` to get the active source.
   - If the tool itself fails, tell the user to check that the MCP server is connected: `.mcp.json` is present, and `.venv` has `requirements.txt` installed.

2. **Choose the source only if `FP_SOURCE` is missing.** Ask with AskUserQuestion: "Which data source?"
   - `FantasyPros website (recommended)`: sets `FP_SOURCE=web`. It ranks every rostered player. With `FP_API_KEY` also set, it adds practice reports, news, and recent points from the public API.
   - `Public API`: sets `FP_SOURCE=api`. The free tier's in-season rankings may be waiver-wire lists that leave out rostered players.
   - Call `set_source` with the answer.

3. **If the source is `web` and the session is not saved or not logged in, set up the session.** Ask with AskUserQuestion: "How should the website session be set up?" The first option is the default.
   - `Capture with mitmproxy (default)`: the user signs in through the proxied browser (see [league-capture.md](league-capture.md)). Once the capture exists, call `set_web_session` with `mitmproxy`. The capture also provides the league key, so run this in the same capture.
   - `Log in with .env credentials`: call `set_web_session` with `login`. This opens a visible browser that signs in with `FANTASYPROS_USERNAME` and `FANTASYPROS_PASSWORD`. If the site shows a verification check, the user completes it in that window. If sign-in fails, offer the mitmproxy approach.
   - Do not read or print the `.env` credentials. Do not type them into chat.
   - If `FANTASYPROS_USERNAME` or `FANTASYPROS_PASSWORD` is missing, do not offer the login option. Name the missing variable.

4. **If all required settings are present, skip the confirmation prompt.** Do not ask with AskUserQuestion. List the settings as present and go straight to the run.

5. **Otherwise, ask for confirmation.** Show the check result as a list of settings marked present or missing. Then ask with AskUserQuestion, for example: "Are your configurations set and ready? (`FP_API_KEY` in `.env` is required for the API source and recommended for the web source; `FP_LEAGUE_KEY` and `FP_TEAM_ID` are required for the roster; `FP_SEASON` defaults to 2026.)"
   - Options: `All set, continue`, `Need to fix .env first (stop here)`.

6. Do not proceed unless the user confirms. If the user confirms but a required setting is still missing, stop and name it.
   - **`FP_API_KEY` missing on the web source:** not an error. Say that injuries come from the site's table (no practice reports), and that moves will lack role evidence and stay provisional.
   - **`FP_API_KEY` missing on the API source:** tell the user to add `FP_API_KEY=<your key>` to `.env`. They can copy the line from `.env.example` and fill it in. Do not ask them to paste the key into chat, and do not write it anywhere except `.env`.
   - **`FP_LEAGUE_KEY` or `FP_TEAM_ID` missing:** go to [league-capture.md](league-capture.md).
   - **`FP_SEASON` blank or missing:** not an error. The code defaults to 2026.
   - **Web source without a session:** handled by step 3 above.

## Step 1: Check tools

1. Call `check_config`. If the MCP tools are not available, stop and tell the user the `fantasy-lineup` server is not connected.
2. mitmproxy is needed only for the one-time league capture, which is required only when `FP_LEAGUE_KEY` or `FP_TEAM_ID` is missing.
   - If it is missing, say so and ask before installing. Once the user agrees, run `.venv/bin/pip install mitmproxy`. This installs into the project venv only.
