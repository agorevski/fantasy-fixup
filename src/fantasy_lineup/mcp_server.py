"""MCP server for the FantasyPros lineup advisor.

Exposes each step of the fantasy-lineup skill as a tool, so the skill calls tools instead of
running raw Python. Wraps advisor.py; all analysis logic stays there.

Tools:
    check_config        Step 0: which .env settings are present (never returns values)
    current_source      Step 0: which data source runs ('api' or 'web'), from FP_SOURCE in .env
    set_source          Choose the data source; writes FP_SOURCE to .env
    set_web_session     Web source only: set up the logged-in session by approach
                        ('mitmproxy' imports the browser capture; 'login' uses .env credentials)
    run_weekly          Step 2: weekly lineup analysis (optional week override)
    run_ros             Step 2: rest-of-season analysis
    list_league_teams   Step 4: list teams from the captured league (no key returned)
    save_team           Step 4: save the chosen team id and league key to .env
    list_snapshots      Step 5: saved weekly snapshots used for the FLEX week-over-week check

The run tools read FP_SOURCE from .env on every call, so changing the source takes effect without a
restart.

Stdout is the MCP transport, so every call that prints is wrapped in a capture.

Long-running tools (run_weekly, run_ros) stream each stage from advisor as an MCP progress
notification, plus a heartbeat during quiet stretches. Progress is only sent when the client
passes a progress token; otherwise the tool just returns its report.
"""

import asyncio
import contextlib
import io
import os
import threading
import time

from dotenv import load_dotenv
from mcp.server.fastmcp import Context, FastMCP

from fantasy_lineup import advisor as fpa
from fantasy_lineup.paths import ENV_FILE

load_dotenv(ENV_FILE)


def _reload_env() -> None:
    """Re-read .env so FP_SOURCE and the league settings track edits made while the server runs."""
    load_dotenv(ENV_FILE, override=True)

HEARTBEAT_SECONDS = 5  # send "still working" if no stage update arrives within this window

mcp = FastMCP("fantasy-lineup")


_CAPTURE_LOCK = threading.Lock()  # redirect_stdout swaps a process-wide global, so captures must not overlap


def _capture(fn, *args) -> tuple[str, str | None]:
    """Run fn, returning (printed output, error message or None). Errors are returned, not raised."""
    out, err = io.StringIO(), io.StringIO()
    with _CAPTURE_LOCK, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            fn(*args)
            problem = None
        except SystemExit as exc:
            problem = str(exc.code) if exc.code not in (None, 0) else None
        except Exception as exc:  # report to the caller instead of crashing the server
            problem = f"{type(exc).__name__}: {exc}"
    progress = err.getvalue().strip()
    text = out.getvalue()
    if progress:
        text = progress + "\n\n" + text
    return text, problem


@mcp.tool()
def check_config() -> dict[str, bool]:
    """Report which .env settings are present, and whether the web session is saved. Never returns values."""
    _reload_env()
    from fantasy_lineup import web
    presence = {k: bool(os.environ.get(k, "").strip())
                for k in ("FP_API_KEY", "FP_LEAGUE_KEY", "FP_TEAM_ID", "FP_SEASON", "FP_SOURCE",
                          "FANTASYPROS_USERNAME", "FANTASYPROS_PASSWORD")}
    presence["web_session_saved"] = web.session_saved()
    return presence


@mcp.tool()
def current_source() -> str:
    """Which data source the run tools use: 'api' (public API, default) or 'web' (FantasyPros website)."""
    _reload_env()
    try:
        return fpa.source_name()
    except SystemExit as exc:
        return f"ERROR: {exc.code}"


@mcp.tool()
def set_source(source: str) -> str:
    """Set FP_SOURCE in .env to 'api' or 'web'. Ask the user which source they want first."""
    value = source.strip().lower()
    if value not in ("api", "web"):
        return "ERROR: source must be 'api' or 'web'"
    fpa.set_env({"FP_SOURCE": value})
    _reload_env()
    return f"FP_SOURCE set to {value}"


@mcp.tool()
async def set_web_session(approach: str) -> str:
    """Web source only. Set up the logged-in session the website needs.

    approach 'mitmproxy' (default): import the cookies from the browser capture (var/capture/auth.json).
    approach 'login': sign in with FANTASYPROS_USERNAME / FANTASYPROS_PASSWORD from .env in a visible
    browser window, so the user can finish any verification check.
    Never returns credentials or cookie values.
    """
    from fantasy_lineup import web
    _reload_env()
    if approach not in ("mitmproxy", "login"):
        return "ERROR: approach must be 'mitmproxy' or 'login'"

    def go():
        if approach == "mitmproxy":
            web.import_capture_session()
        else:
            web.login_with_env()

    text, problem = await asyncio.to_thread(_capture, go)
    if problem:
        return f"{text}\nERROR: {problem}".strip()
    return f"Session saved via {approach}. Logged in: {web.session_logged_in()}"


async def _capture_streaming(ctx: Context, fn, *args) -> tuple[str, str | None]:
    """Run _capture(fn) in a worker thread, forwarding its status lines to the client as progress.

    The analysis blocks on HTTP and sleeps, so it cannot run on the event loop. Status lines cross
    back to the loop through call_soon_threadsafe, and this coroutine sends them in order.
    """
    loop = asyncio.get_running_loop()
    updates: asyncio.Queue[str] = asyncio.Queue()

    def emit(msg: str) -> None:
        loop.call_soon_threadsafe(updates.put_nowait, msg)

    def work():
        fpa.status_sink.set(emit)  # set in the worker's own context, so it cannot leak to other calls
        return _capture(fn, *args)

    task = asyncio.ensure_future(asyncio.to_thread(work))
    started = time.monotonic()
    step = 0
    while not task.done():
        getter = asyncio.ensure_future(updates.get())
        await asyncio.wait({task, getter}, timeout=HEARTBEAT_SECONDS, return_when=asyncio.FIRST_COMPLETED)
        if getter.done():
            msg = getter.result()
        else:
            getter.cancel()
            msg = f"still working ({int(time.monotonic() - started)}s elapsed)"
        step += 1
        await ctx.report_progress(step, message=msg)
    # Lines emitted just before the worker finished were queued ahead of its completion; flush them.
    while not updates.empty():
        step += 1
        await ctx.report_progress(step, message=updates.get_nowait())
    return task.result()


async def _run(ctx: Context, kind: str, week: int | None) -> str:
    _reload_env()

    def go():
        res = fpa.run_and_save(kind, week)
        fpa.report(res)
    text, problem = await _capture_streaming(ctx, go)
    if problem:
        return f"{text}\nERROR: {problem}"
    return text


@mcp.tool()
async def run_weekly(ctx: Context, week: int | None = None) -> str:
    """Run the weekly lineup analysis and return the report. Week defaults to the current NFL week.

    Cheat-sheet rankings and the roster are required. Injuries and per-expert picks are optional;
    if they are missing the report says so in its Data status section.
    """
    return await _run(ctx, "weekly", week)


@mcp.tool()
async def run_ros(ctx: Context) -> str:
    """Run the rest-of-season analysis and return the report. Secondary product; run only when asked."""
    return await _run(ctx, "ros", None)


@mcp.tool()
def list_league_teams() -> str:
    """List the league and its teams from the captured league feed. Does not return the league key."""
    text, problem = _capture(fpa.discover, None)
    return text + (f"\nERROR: {problem}" if problem else "")


@mcp.tool()
def save_team(team_id: str) -> str:
    """Save the user's team id (and the league key from the capture) to .env. Ask the user which team first."""
    text, problem = _capture(fpa.discover, team_id)
    return text + (f"\nERROR: {problem}" if problem else "")


@mcp.tool()
def list_snapshots() -> str:
    """List saved weekly snapshots, which the FLEX week-over-week check compares against. Shows the source of each."""
    lines = []
    for source in ("api", "web"):
        hist = fpa.history_dir(source)
        if hist.exists():
            lines += [f"{source}: {p.name}" for p in sorted(hist.glob("weekly-*.json"))]
    return "\n".join(lines) if lines else "no snapshots saved yet"


if __name__ == "__main__":
    mcp.run()
