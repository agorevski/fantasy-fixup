"""MCP server for the FantasyPros lineup advisor.

Exposes each step of the fantasy-lineup skill as a tool, so the skill calls tools instead of
running raw Python. Wraps fp_advisor.py; all analysis logic stays there.

Tools:
    check_config        Step 0: which .env settings are present (never returns values)
    run_weekly          Step 2: weekly lineup analysis (optional week override)
    run_ros             Step 2: rest-of-season analysis
    list_league_teams   Step 4: list teams from the captured league (no key returned)
    save_team           Step 4: save the chosen team id and league key to .env
    list_snapshots      Step 5: saved weekly snapshots used for the FLEX week-over-week check

Stdout is the MCP transport, so every call that prints is wrapped in a capture.

Long-running tools (run_weekly, run_ros) stream each stage from fp_advisor as an MCP progress
notification, plus a heartbeat during quiet stretches. Progress is only sent when the client
passes a progress token; otherwise the tool just returns its report.
"""

import asyncio
import contextlib
import io
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import Context, FastMCP

import fp_advisor as fpa

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

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
    """Report which required .env settings are present. Never returns the values."""
    return {k: bool(os.environ.get(k, "").strip())
            for k in ("FP_API_KEY", "FP_LEAGUE_KEY", "FP_TEAM_ID", "FP_SEASON")}


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
    """List saved weekly snapshots, which the FLEX week-over-week check compares against."""
    files = sorted(p.name for p in fpa.HISTORY.glob("weekly-*.json")) if fpa.HISTORY.exists() else []
    return "\n".join(files) if files else "no snapshots saved yet"


if __name__ == "__main__":
    mcp.run()
