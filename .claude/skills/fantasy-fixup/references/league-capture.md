# League capture and team selection (Steps 3 and 4)

Use this only when `FP_LEAGUE_KEY` or `FP_TEAM_ID` is missing. Skip it if Step 0 showed both values present.

The public API does not expose the league roster, so the league key must be captured from the browser once. The user must run these commands in their own terminal and sign in themselves. The skill cannot do the sign-in.

## Step 3: Capture the league

1. Start the proxy in one terminal:
   `! cd ~/GIT/FantasyProsFixer && .venv/bin/mitmdump -s src/fantasy_lineup/capture_addon.py -p 8081`
   The first run creates mitmproxy's CA certificate in `~/.mitmproxy/`.
2. The first time only, trust that certificate. In Keychain Access, open `~/.mitmproxy/mitmproxy-ca-cert.pem`, set it to **Always Trust**, and restart Chrome. This is a root-level trust change. Remove it after capture, and say so.
3. Launch a separate Chrome profile through the proxy:
   `! "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --proxy-server=http://127.0.0.1:8081 --user-data-dir=/tmp/fp-chrome https://www.fantasypros.com/accounts/signin/`
4. The user signs in, opens their **league roster / My Team** page and the **matchup** page, then presses Ctrl-C in the proxy terminal.
5. Finish the capture:
   - If the source is `web` and the approach is `mitmproxy`, call `set_web_session` with `mitmproxy`. It turns the capture into the website session and deletes `var/capture/auth.json`.
   - Otherwise, delete the capture yourself: `rm -f var/capture/auth.json`. The API analysis does not need it.
6. Tell the user to stop the proxy and remove the mitmproxy certificate from Keychain.
7. Call `list_league_teams` (Step 4) to save the key.

If the proxy shows `Client TLS handshake failed ... does not trust the proxy's certificate`, the certificate trust in step 2 is not set. Ask the user to re-check it.

## Step 4: Pick the team

1. Call `list_league_teams`. It returns the league name and each team's ID and name. It does not return the key.
2. Ask the user which team is theirs with AskUserQuestion, using the team names. Do not guess.
3. Call `save_team` with the chosen team ID. This writes `FP_LEAGUE_KEY` and `FP_TEAM_ID` to `.env`, with mode 600.
