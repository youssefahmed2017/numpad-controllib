#!/usr/bin/env python3
"""numpad-controllib tooling: check profiles, build the catalog, start a new profile.

    python tools/nclib.py validate [FILE ...]      check every profile (or just these files)
    python tools/nclib.py index [--check]          write index.json (--check: fail if it is out of date)
    python tools/nclib.py new AUTHOR SLUG          create profiles/community/AUTHOR/SLUG.json to fill in

Standard library only. The rules mirror NumpadControl's own importer (numpadctl/profile_io.py), using the
action table snapshot in schema/actions.json, so a file that passes here imports in the app without anything
being dropped. On top of that it checks the library's own rules (the "meta" block, file paths) and warns
about things that make a profile less useful to other people (an empty window match, names from the
author's own setup, platform-only actions).
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"
INDEX = ROOT / "index.json"
ACTIONS_FILE = ROOT / "schema" / "actions.json"

FORMAT = "numpadcontrol-profile"
VERSION = 1
PLATFORMS = ("windows", "linux", "hyprland")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
AUTHOR = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")      # a GitHub user name
TAG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WINDOW = re.compile(r"[\w.\-]+")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
EXTRA_KEY = re.compile(r"(?:[a-z0-9_-]+:)?KEY_[A-Z0-9_]+")       # Learn-mode keys: KEY_TAB, hp:KEY_F1
VERSION_STR = re.compile(r"\d+\.\d+\.\d+")
BINDING_FIELDS = {"action", "params", "rapid", "turbo"}
META_FIELDS = {"author", "description", "tags", "platforms", "requires", "min_app_version", "homepage"}


def load_table():
    data = json.loads(ACTIONS_FILE.read_text(encoding="utf-8"))
    data["by_id"] = {a["id"]: a for a in data["actions"]}
    names = set(data["key_names"])
    names |= {chr(c) for c in range(ord("A"), ord("Z") + 1)}
    names |= {str(d) for d in range(10)} | {f"KP{d}" for d in range(10)} | {f"F{n}" for n in range(1, 25)}
    data["key_set"] = names
    return data


T = load_table()
LIM = T["limits"]


class Report:
    """Errors (the file can't go in) and warnings (it can, but tell the author) for one file."""

    def __init__(self, path):
        self.path = path
        self.errors = []
        self.warnings = []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


# ------------------------------------------------------------------ action checks (mirror the app)
def _plain_json(value, depth=0):
    if depth > LIM["max_depth"]:
        raise ValueError("nested too deeply")
    if isinstance(value, str):
        if len(value) > LIM["max_string"]:
            raise ValueError("a value is too long")
    elif isinstance(value, list):
        for v in value:
            _plain_json(v, depth + 1)
    elif isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or len(k) > 200:
                raise ValueError("odd field names")
            _plain_json(v, depth + 1)
    elif not (value is None or isinstance(value, (bool, int, float))):
        raise ValueError("an unexpected kind of value")


def keys_problem(text):
    """None if press_keys would accept `text` on both Linux and Windows, else why not."""
    if not isinstance(text, str):
        return "keys must be text"
    text = re.sub(r"\s*\+\s*", "+", text.strip())
    combos = 0
    for chunk in text.replace(",", " ").split():
        for name in chunk.split("+"):
            key = T["key_aliases"].get(name.lower(), name.upper()) if name else ""
            if not key or key not in T["key_set"]:
                return f"unknown key {name or chunk!r} (examples: ctrl+c, Down, Enter, F5)"
        combos += 1
    if not combos:
        return "no keys set"
    if combos > LIM["max_key_presses"]:
        return f"at most {LIM['max_key_presses']} key presses"
    return None


def check_rule(rule, value):
    kind = rule["rule"]
    if kind == "nonempty":
        return None if isinstance(value, str) and value.strip() else rule.get("message", "empty")
    if kind == "keys":
        return keys_problem(value)
    if kind == "percent":
        try:
            level = int(str(value).strip().rstrip("%"))
        except ValueError:
            return f"volume must be a number, not {value!r}"
        return None if 0 <= level <= 100 else "volume must be between 0 and 100"
    if kind == "seconds":
        try:
            seconds = float(str(value).strip().rstrip("s"))
        except ValueError:
            return f"wait must be a number of seconds, not {value!r}"
        top = LIM["max_wait_seconds"]
        return None if 0 <= seconds <= top else f"wait must be between 0 and {top} seconds"
    if kind == "window":
        if isinstance(value, str) and WINDOW.fullmatch(value.strip()):
            return None
        return f"window class must be a name like kitty or firefox, not {value!r}"
    raise KeyError(f"schema/actions.json uses an unknown rule {kind!r}")


def binding_problems(binding, where, rep, *, as_step=False, depth=0):
    """Check one binding (and, for macros / if_mode, every step inside). Problems go to rep.

    Returns the action ids used, for the summary."""
    used = []
    if not isinstance(binding, dict) or not isinstance(binding.get("action"), str):
        rep.error(f"{where}: not an action")
        return used
    extra = set(binding) - BINDING_FIELDS
    if extra:
        rep.error(f"{where}: unknown field(s) {sorted(extra)} (the app drops them; allowed: {sorted(BINDING_FIELDS)})")
    action_id = binding["action"]
    action = T["by_id"].get(action_id)
    if action is None:
        rep.error(f"{where}: unknown action {action_id[:40]!r} (newer than NumpadControl {T['app_version']}? "
                  "refresh schema/actions.json)")
        return used
    used.append(action_id)
    if as_step and not action["step"]:
        rep.error(f"{where}: {action_id!r} can't be used as a macro step")
    if not as_step and action.get("step_only"):
        rep.warn(f"{where}: {action_id!r} is meant for macro steps; on its own it only waits")
    if action_id == "none":
        rep.warn(f"{where}: the action is (nothing); leave the slot out instead")

    params = binding.get("params", {})
    try:
        _plain_json(params)
    except ValueError as e:
        rep.error(f"{where}: its settings are not usable ({e})")
        return used
    if not isinstance(params, dict):
        rep.error(f"{where}: params must be an object")
        return used
    known = {p["name"] for p in action["params"]}
    for name in sorted(set(params) - known):
        rep.warn(f"{where}: {action_id} has no setting {name!r} (it will be ignored)")

    if "rapid" in binding and not isinstance(binding["rapid"], bool):
        rep.error(f"{where}: rapid must be true or false")
    if "turbo" in binding:
        turbo = binding["turbo"]
        if not (isinstance(turbo, int) and not isinstance(turbo, bool) and 1 <= turbo <= LIM["turbo_max"]):
            rep.error(f"{where}: turbo must be a whole number from 1 to {LIM['turbo_max']}")

    defaults = {p["name"]: p["default"] for p in action["params"]}
    for rule in action.get("checks", []):
        value = params.get(rule["param"], defaults.get(rule["param"]))
        problem = check_rule(rule, value)
        if problem:
            rep.error(f"{where}: {problem}")

    for name in action.get("user_ref", []):
        value = params.get(name)
        if isinstance(value, str) and value.strip():
            rep.warn(f"{where}: {action_id} uses {name}={value!r}, which only exists on the author's setup; "
                     "say so in meta.description")
    for platform in action.get("platforms", []):
        rep.platform_only.add((action_id, platform))

    if action_id == "macro":
        steps = params.get("steps", [])
        used += _steps(steps, f"{where} > macro", rep, allow_empty=False, depth=depth)
    elif action_id == "if_mode":
        then, otherwise = params.get("then", []), params.get("otherwise", [])
        if not then and not otherwise:
            rep.error(f"{where}: if_mode has both branches empty")
        used += _steps(then, f"{where} > if on", rep, allow_empty=True, depth=depth)
        used += _steps(otherwise, f"{where} > otherwise", rep, allow_empty=True, depth=depth)
    return used


def _steps(steps, where, rep, *, allow_empty, depth):
    used = []
    if not isinstance(steps, list):
        rep.error(f"{where}: steps must be a list")
        return used
    if not steps and not allow_empty:
        rep.error(f"{where}: the macro has no steps")
    if len(steps) > LIM["max_macro_steps"]:
        rep.error(f"{where}: a macro can have at most {LIM['max_macro_steps']} steps")
    for i, step in enumerate(steps, 1):
        used += binding_problems(step, f"{where} step {i}", rep, as_step=True, depth=depth + 1)
    return used


def check_layer(layer, label, rep):
    used = []
    if not isinstance(layer, dict):
        rep.error(f"{label}: must be an object of keys")
        return used
    if len(layer) > LIM["max_keys_per_layer"]:
        rep.error(f"{label}: {len(layer)} keys; that is more than a numpad has")
    for key, slots in layer.items():
        if not key or len(key) > 64 or CONTROL.search(key):
            rep.error(f"{label}: a key with a strange name")
            continue
        if key not in T["pad_keys"]:
            if EXTRA_KEY.fullmatch(key):
                rep.warn(f"{label}: key {key!r} is an extra (Learn mode) key; it only works for people who "
                         "added the same key")
            else:
                rep.error(f"{label}: unknown key {key!r} (numpad keys are {', '.join(T['pad_keys'])})")
                continue
        if not isinstance(slots, dict) or not slots:
            rep.error(f"{label} key {key}: must be an object of slots (tap / hold / double)")
            continue
        for slot, binding in slots.items():
            if slot not in T["slots"]:
                rep.error(f"{label} key {key}: unknown slot {str(slot)[:20]!r} (use tap, hold or double)")
                continue
            if slot != "tap" and key in T["tap_only_keys"]:
                rep.error(f"{label} key {key}: {key} can only be tapped")
            used += binding_problems(binding, f"{label} key {key} ({slot})", rep)
    return used


# ------------------------------------------------------------------ library rules
def check_meta(meta, path, rep):
    if not isinstance(meta, dict):
        rep.error("meta: missing (see CONTRIBUTING.md for the fields)")
        return {}
    for name in sorted(set(meta) - META_FIELDS):
        rep.error(f"meta: unknown field {name!r} (allowed: {', '.join(sorted(META_FIELDS))})")
    author = meta.get("author")
    if not isinstance(author, str) or not AUTHOR.fullmatch(author):
        rep.error("meta.author: your GitHub user name")
    desc = meta.get("description")
    if not isinstance(desc, str) or not 10 <= len(desc.strip()) <= 500:
        rep.error("meta.description: 10 to 500 characters saying what the profile is for")
    tags = meta.get("tags")
    if not isinstance(tags, list) or not 1 <= len(tags) <= 8 or not all(isinstance(t, str) and TAG.fullmatch(t) for t in tags):
        rep.error("meta.tags: 1 to 8 lower-case tags like \"streaming\" or \"video-editing\"")
    platforms = meta.get("platforms")
    if not isinstance(platforms, list) or not platforms or not all(p in PLATFORMS for p in platforms):
        rep.error(f"meta.platforms: a list from {list(PLATFORMS)}")
        platforms = []
    requires = meta.get("requires", [])
    if not isinstance(requires, list) or not all(isinstance(r, str) and 0 < len(r) <= 80 for r in requires):
        rep.error("meta.requires: a list of short strings (e.g. \"OBS WebSocket server on\")")
    mav = meta.get("min_app_version")
    if mav is not None and not (isinstance(mav, str) and VERSION_STR.fullmatch(mav)):
        rep.error("meta.min_app_version: a version like \"0.3.1\"")
    home = meta.get("homepage")
    if home is not None and not (isinstance(home, str) and home.startswith("https://")):
        rep.error("meta.homepage: an https:// link")

    for action_id, platform in sorted(rep.platform_only):
        if platform == "hyprland" and "hyprland" not in platforms:
            rep.warn(f"{action_id} only works on Hyprland; add \"hyprland\" to meta.platforms")
        if platform == "hyprland" and "windows" in platforms:
            rep.warn(f"{action_id} does nothing on Windows, but meta.platforms lists windows")
        if platform == "linux" and "windows" in platforms:
            rep.warn(f"{action_id} is Linux-only, but meta.platforms lists windows")

    # where the file lives must agree with the meta
    try:
        rel = path.resolve().relative_to(PROFILES)
    except ValueError:
        return meta
    parts = rel.parts
    if not SLUG.fullmatch(path.stem):
        rep.error(f"file name {path.name!r}: use lower-case words joined by - (e.g. obs-streaming.json)")
    if parts[0] == "official":
        if len(parts) != 2:
            rep.error("official profiles go directly in profiles/official/")
    elif parts[0] == "community":
        if len(parts) != 3:
            rep.error("community profiles go in profiles/community/<your-github-name>/<name>.json")
        elif isinstance(author, str) and parts[1].lower() != author.lower():
            rep.error(f"folder {parts[1]!r} doesn't match meta.author {author!r}")
    else:
        rep.error("profiles go in profiles/official/ or profiles/community/<author>/")
    return meta


def check_file(path):
    """Report for one profile file; rep.summary holds catalog data when it parsed."""
    rep = Report(path)
    rep.platform_only = set()
    rep.summary = None
    raw = path.read_bytes()
    if len(raw) > LIM["max_bytes"]:
        rep.error("the file is too big to be a profile")
        return rep
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        rep.error("the file isn't UTF-8")
        return rep
    if text.startswith("﻿"):
        rep.error("the file starts with a byte-order mark; save it as UTF-8 without BOM")
        text = text[1:]
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as e:
        rep.error(f"not valid JSON ({e})")
        return rep
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        rep.error(f"format must be {FORMAT!r}")
        return rep
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        rep.error("version must be a whole number")
    elif version > VERSION:
        rep.error(f"version {version} is newer than this library understands ({VERSION})")
    for name in sorted(set(data) - {"$schema", "format", "version", "app_version", "profile", "meta"}):
        rep.warn(f"top-level field {name!r} is ignored by the app")
    av = data.get("app_version")
    if av is not None and not (isinstance(av, str) and (av == "" or VERSION_STR.fullmatch(av))):
        rep.error("app_version must be a version like \"0.3.1\"")

    prof = data.get("profile")
    if not isinstance(prof, dict):
        rep.error("the file has no profile in it")
        return rep
    for name in sorted(set(prof) - {"name", "match", "bindings", "layer_bindings"}):
        rep.warn(f"profile.{name} is ignored by the app")
    name = prof.get("name")
    if not isinstance(name, str) or not name.strip():
        rep.error("profile.name: missing")
        name = ""
    elif CONTROL.search(name) or len(name) > LIM["max_name"] or name != name.strip():
        rep.error(f"profile.name: at most {LIM['max_name']} characters, no line breaks or edge spaces")
    match = prof.get("match", "")
    if not isinstance(match, str) or len(match) > LIM["max_match"] or CONTROL.search(match):
        rep.error(f"profile.match: comma-separated window classes, at most {LIM['max_match']} characters")
        match = ""
    classes = [c.strip() for c in match.split(",") if c.strip()]
    if not classes:
        rep.warn("profile.match is empty: imported, it never switches on by itself (people would copy its "
                 "keys into Default). Fine for general-purpose profiles; say so in meta.description")
    for c in classes:
        if c.lower().endswith(".exe"):
            rep.error(f"profile.match: write Windows programs without .exe ({c[:-4]!r})")
        elif not WINDOW.fullmatch(c):
            rep.error(f"profile.match: {c!r} doesn't look like a window class")

    used = check_layer(prof.get("bindings", {}), "bindings", rep)
    used += check_layer(prof.get("layer_bindings", {}), "layer_bindings", rep)
    if not prof.get("bindings") and not prof.get("layer_bindings"):
        rep.error("the profile sets no keys")
    meta = check_meta(data.get("meta"), path, rep)

    counts = {}
    for a in used:
        if a != "none":
            counts[a] = counts.get(a, 0) + 1
    risky = sorted(a for a in counts
                   if T["by_id"][a]["group"] in T["risky_groups"] or a in T["risky_ids"])
    try:
        rel = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        rel = path.as_posix()
    tier = "official" if rel.startswith("profiles/official/") else "community"
    rep.summary = {
        "id": rel.removeprefix("profiles/").removesuffix(".json"),
        "path": rel,
        "tier": tier,
        "name": name,
        "match": classes,
        "author": meta.get("author", ""),
        "description": meta.get("description", ""),
        "tags": meta.get("tags", []),
        "platforms": meta.get("platforms", []),
        "requires": meta.get("requires", []),
        "min_app_version": meta.get("min_app_version", data.get("app_version") or T["app_version"]),
        "keys": len(prof.get("bindings", {}) or {}) + len(prof.get("layer_bindings", {}) or {}),
        "actions": dict(sorted(counts.items())),
        "risky_actions": risky,
    }
    return rep


def all_profiles():
    return sorted(PROFILES.rglob("*.json"))


# ------------------------------------------------------------------ commands
def cmd_validate(args):
    paths = [Path(p) for p in args.files] or all_profiles()
    bad = 0
    for path in paths:
        rep = check_file(path)
        shown = path.resolve().relative_to(ROOT).as_posix() if path.resolve().is_relative_to(ROOT) else str(path)
        status = "FAIL" if rep.errors else ("warn" if rep.warnings else "ok")
        print(f"{status:4}  {shown}")
        for e in rep.errors:
            print(f"      error: {e}")
        if not args.quiet:
            for w in rep.warnings:
                print(f"      warning: {w}")
        if rep.summary and rep.summary["risky_actions"] and not args.quiet:
            print(f"      ⚠ runs programs / presses keys / power: {', '.join(rep.summary['risky_actions'])}")
        bad += bool(rep.errors) or (args.strict and bool(rep.warnings))
    print(f"\n{len(paths)} file(s), {bad} failed")
    return 1 if bad else 0


def build_index():
    entries, failed = [], []
    for path in all_profiles():
        rep = check_file(path)
        (failed if rep.errors else entries).append(rep.summary if not rep.errors else rep.path)
    entries.sort(key=lambda e: (e["tier"] != "official", e["id"]))
    return {
        "format": "numpadcontrol-library-index",
        "version": 1,
        "app_version": T["app_version"],
        "count": len(entries),
        "profiles": entries,
    }, failed


def render_index(index):
    return json.dumps(index, indent=2, ensure_ascii=False) + "\n"


def cmd_index(args):
    index, failed = build_index()
    if failed:
        print("these profiles fail validation and are left out of the index:", file=sys.stderr)
        for p in failed:
            print(f"  {p}", file=sys.stderr)
    text = render_index(index)
    if args.check:
        current = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
        if current != text:
            print("index.json is out of date: run  python tools/nclib.py index", file=sys.stderr)
            return 1
        print(f"index.json is up to date ({index['count']} profiles)")
        return 1 if failed else 0
    INDEX.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote index.json ({index['count']} profiles)")
    return 1 if failed else 0


def cmd_new(args):
    if not AUTHOR.fullmatch(args.author):
        print("AUTHOR must be your GitHub user name", file=sys.stderr)
        return 2
    if not SLUG.fullmatch(args.slug):
        print("SLUG must be lower-case words joined by - (e.g. obs-streaming)", file=sys.stderr)
        return 2
    path = PROFILES / "community" / args.author / f"{args.slug}.json"
    if path.exists():
        print(f"{path.relative_to(ROOT).as_posix()} already exists", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "$schema": "../../../schema/profile.schema.json",
        "format": FORMAT, "version": VERSION, "app_version": T["app_version"],
        "meta": {"author": args.author, "description": "What this profile is for, and anything people must set up first.",
                 "tags": ["general"], "platforms": ["windows", "linux"], "requires": []},
        "profile": {"name": args.slug.replace("-", " ").title(), "match": "",
                    "bindings": {"5": {"tap": {"action": "media_play_pause", "params": {}}}},
                    "layer_bindings": {}},
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"created {path.relative_to(ROOT).as_posix()}: fill it in (or paste in an exported profile), then run "
          "python tools/nclib.py validate")
    return 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="nclib", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="check profiles")
    v.add_argument("files", nargs="*")
    v.add_argument("--strict", action="store_true", help="warnings fail too")
    v.add_argument("-q", "--quiet", action="store_true", help="errors only")
    v.set_defaults(fn=cmd_validate)
    i = sub.add_parser("index", help="build index.json")
    i.add_argument("--check", action="store_true", help="fail if index.json is out of date")
    i.set_defaults(fn=cmd_index)
    n = sub.add_parser("new", help="start a community profile")
    n.add_argument("author")
    n.add_argument("slug")
    n.set_defaults(fn=cmd_new)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
