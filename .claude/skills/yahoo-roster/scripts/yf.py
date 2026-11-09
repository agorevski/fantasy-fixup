#!/usr/bin/env python3
"""Drive the Yahoo Fantasy app over ADB with compact, label-based commands.

Stdlib only. Run as: python3 -I yf.py <command> [args]

Commands:
  devices                       Show the phone this tool will use
  launch                        Start the Yahoo Fantasy app
  screen [--grep S] [--max N]   Compact list of labelled elements on screen
  tap LABEL [--exact] [--nth N] Tap the element whose text/description matches LABEL
  wait LABEL [--timeout S]      Wait until LABEL is on screen (exit 4 on timeout)
  type TEXT                     Type plain text into the focused field
  key back|home|enter           Press a key
  swipe up|down                 Swipe the screen
  run RECIPE [--set k=v ...] [--confirmed]
                                Run a recipe JSON file. Dry run unless --confirmed,
                                and mutating steps run only with --confirmed.

Exit codes: 0 ok, 2 not found, 3 ambiguous, 4 wait timeout, 5 recipe step failed,
            1 other error.

Device: set YF_SERIAL to the adb serial. If unset, the first attached device that
has the Yahoo Fantasy package installed is used.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

PKG = "com.yahoo.mobile.client.android.fantasyfootball"
DUMP_PATH = "/sdcard/yf_ui.xml"
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
SAFE_TEXT = re.compile(r"[A-Za-z0-9 .'\-]{1,40}")
KEYS = {"back": 4, "home": 3, "enter": 66}


def fail(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def adb(*args, serial=None, check=True):
    cmd = ["adb"] + (["-s", serial] if serial else []) + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        fail(f"adb timed out: {' '.join(args)}")
    if check and r.returncode != 0:
        fail(f"adb failed: {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
    return r.stdout


def pick_serial():
    env = os.environ.get("YF_SERIAL")
    if env:
        return env
    devices = []
    for line in adb("devices", check=False).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    for serial in devices:
        if PKG in adb("shell", "pm", "list", "packages", PKG, serial=serial, check=False):
            return serial
    fail("No attached device has the Yahoo Fantasy app. Set YF_SERIAL or pair the phone.", 1)


def screen_size(serial):
    out = adb("shell", "wm", "size", serial=serial)
    sizes = re.findall(r"(\d+)x(\d+)", out)
    if not sizes:
        fail("Could not read screen size from `wm size`.")
    w, h = sizes[-1]
    return int(w), int(h)


def dump(serial):
    """Return the parsed UI hierarchy root. Retries because the dump fails mid-animation."""
    for _ in range(3):
        adb("shell", "uiautomator", "dump", DUMP_PATH, serial=serial, check=False)
        xml = adb("exec-out", "cat", DUMP_PATH, serial=serial, check=False)
        if xml.lstrip().startswith("<?xml"):
            return ET.fromstring(xml)
        time.sleep(0.7)
    fail("uiautomator dump failed. The screen may be animating or showing a secure window.")


def elements(root):
    """Labelled elements, deduplicated, in reading order."""
    seen, out = set(), []
    for node in root.iter("node"):
        label = (node.get("text") or node.get("content-desc") or "").strip()
        m = BOUNDS.fullmatch(node.get("bounds", ""))
        if not label or not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        if x2 <= x1 or y2 <= y1:
            continue
        x, y = (x1 + x2) // 2, (y1 + y2) // 2
        key = (label, x, y)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "label": label,
            "click": node.get("clickable") == "true",
            "x": x,
            "y": y,
        })
    out.sort(key=lambda e: (e["y"] // 20, e["x"]))
    return out


def find(elems, label, exact=False):
    needle = label.casefold()
    hits = [e for e in elems if e["label"].casefold() == needle]
    if not hits and not exact:
        hits = [e for e in elems if needle in e["label"].casefold()]
    hits.sort(key=lambda e: not e["click"])
    return hits


def tap_label(serial, label, exact=False, nth=None):
    elems = elements(dump(serial))
    hits = find(elems, label, exact)
    if not hits:
        return 2, f"not found: {label!r}"
    if nth is None and len(hits) > 1 and len({h["label"] for h in hits}) > 1:
        names = "; ".join(f"{h['label'][:50]!r} at {h['x']},{h['y']}" for h in hits[:6])
        return 3, f"ambiguous: {label!r} matches {len(hits)} elements: {names}. Use --exact or --nth."
    target = hits[(nth or 1) - 1] if nth else hits[0]
    adb("shell", "input", "tap", str(target["x"]), str(target["y"]), serial=serial)
    return 0, f"tapped {target['label'][:60]!r} at {target['x']},{target['y']}"


def cmd_devices(args, serial):
    model = adb("shell", "getprop", "ro.product.model", serial=serial).strip()
    print(f"serial={serial} model={model}")
    return 0


def cmd_launch(args, serial):
    adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1", serial=serial)
    time.sleep(3)
    return 0


def cmd_screen(args, serial):
    root = dump(serial)
    elems = elements(root)
    if args.grep:
        g = args.grep.casefold()
        elems = [e for e in elems if g in e["label"].casefold()]
    print(f"package={root.get('package', '?')}")
    for e in elems[: args.max]:
        mark = "*" if e["click"] else " "
        print(f"{mark} {e['label'][:70]!r} {e['x']},{e['y']}")
    if len(elems) > args.max:
        print(f"... {len(elems) - args.max} more (use --grep)")
    return 0


def cmd_tap(args, serial):
    code, msg = tap_label(serial, args.label, args.exact, args.nth)
    print(msg, file=sys.stderr if code else sys.stdout)
    return code


def cmd_wait(args, serial):
    deadline = time.time() + args.timeout
    while True:
        if find(elements(dump(serial)), args.label):
            print(f"found {args.label!r}")
            return 0
        if time.time() >= deadline:
            print(f"timeout waiting for {args.label!r}", file=sys.stderr)
            return 4
        time.sleep(1)


def cmd_type(args, serial):
    if not SAFE_TEXT.fullmatch(args.text):
        fail("Refusing text: only letters, digits, spaces, and . ' - are allowed (1-40 chars).", 1)
    adb("shell", "input", "text", args.text.replace(" ", "%s"), serial=serial)
    return 0


def cmd_key(args, serial):
    adb("shell", "input", "keyevent", str(KEYS[args.name]), serial=serial)
    return 0


def cmd_swipe(args, serial):
    w, h = screen_size(serial)
    x = w // 2
    y1, y2 = (int(h * 0.8), int(h * 0.3)) if args.direction == "up" else (int(h * 0.3), int(h * 0.8))
    adb("shell", "input", "swipe", str(x), str(y1), str(x), str(y2), "400", serial=serial)
    return 0


def run_recipe(path, params, confirmed, serial):
    """Execute a recipe. Steps: tap, wait, type, key, swipe, launch, sleep.

    A step may set "mutates": true (roster change). Those steps are printed in a dry run
    and only executed when confirmed. Placeholders like {player} come from --set.
    """
    with open(path, encoding="utf-8") as f:
        recipe = json.load(f)

    def fill(value):
        if not isinstance(value, str):
            return value
        try:
            return value.format(**params)
        except KeyError as missing:
            fail(f"recipe needs --set {missing.args[0]}=...", 1)

    steps = recipe["steps"]
    for i, step in enumerate(steps, 1):
        label = fill(step.get("label", ""))
        desc = step["op"] + (f" {label!r}" if label else "")
        if "text" in step:
            desc += f" text={fill(step['text'])!r}"
        if step.get("mutates"):
            desc += "  [CHANGES ROSTER]"
        if not confirmed:
            print(f"{i}. {desc}")
            continue
        print(f"{i}. {desc}")
        op = step["op"]
        if op == "launch":
            cmd_launch(None, serial)
        elif op == "tap":
            code, msg = tap_label(serial, label, step.get("exact", False), step.get("nth"))
            print("   " + msg)
            if code and not step.get("optional"):
                _step_failed(serial, i)
        elif op == "wait":
            args = argparse.Namespace(label=label, timeout=step.get("timeout", 10))
            if cmd_wait(args, serial) and not step.get("optional"):
                _step_failed(serial, i)
        elif op == "type":
            cmd_type(argparse.Namespace(text=fill(step["text"])), serial)
        elif op == "key":
            cmd_key(argparse.Namespace(name=step["name"]), serial)
        elif op == "swipe":
            cmd_swipe(argparse.Namespace(direction=step["direction"]), serial)
        elif op == "sleep":
            time.sleep(float(step.get("seconds", 1)))
        else:
            fail(f"unknown op {op!r} in step {i}", 1)
        time.sleep(float(step.get("pause", 0.8)))
    if not confirmed:
        print("DRY RUN. Nothing was tapped. Show this plan to the user, then re-run with --confirmed.")
    return 0


def _step_failed(serial, index):
    print(f"step {index} failed. Elements currently on screen:", file=sys.stderr)
    for e in elements(dump(serial))[:40]:
        mark = "*" if e["click"] else " "
        print(f"{mark} {e['label'][:70]!r} {e['x']},{e['y']}", file=sys.stderr)
    sys.exit(5)


def cmd_run(args, serial):
    params = {}
    for pair in args.set or []:
        if "=" not in pair:
            fail(f"--set expects k=v, got {pair!r}")
        k, v = pair.split("=", 1)
        if not SAFE_TEXT.fullmatch(v):
            fail(f"--set {k}: value must be letters, digits, spaces, and . ' - (1-40 chars).")
        params[k] = v
    return run_recipe(args.recipe, params, args.confirmed, serial)


def build_parser():
    p = argparse.ArgumentParser(prog="yf.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices")
    sub.add_parser("launch")
    s = sub.add_parser("screen")
    s.add_argument("--grep")
    s.add_argument("--max", type=int, default=60)
    t = sub.add_parser("tap")
    t.add_argument("label")
    t.add_argument("--exact", action="store_true")
    t.add_argument("--nth", type=int)
    w = sub.add_parser("wait")
    w.add_argument("label")
    w.add_argument("--timeout", type=float, default=10)
    ty = sub.add_parser("type")
    ty.add_argument("text")
    k = sub.add_parser("key")
    k.add_argument("name", choices=sorted(KEYS))
    sw = sub.add_parser("swipe")
    sw.add_argument("direction", choices=["up", "down"])
    r = sub.add_parser("run")
    r.add_argument("recipe")
    r.add_argument("--set", action="append", metavar="K=V")
    r.add_argument("--confirmed", action="store_true")
    return p


HANDLERS = {
    "devices": cmd_devices, "launch": cmd_launch, "screen": cmd_screen, "tap": cmd_tap,
    "wait": cmd_wait, "type": cmd_type, "key": cmd_key, "swipe": cmd_swipe, "run": cmd_run,
}


def main():
    args = build_parser().parse_args()
    serial = pick_serial()
    sys.exit(HANDLERS[args.cmd](args, serial))


if __name__ == "__main__":
    main()
