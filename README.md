# NumpadControl Library

Ready-made profiles for [NumpadControl](https://github.com/youssefahmed2017/numpad-control): official
starters from the maintainers, and profiles shared by the community.

A profile says what each numpad key does (tap, hold, double tap, and with the layer key held) and which
app it switches on for. Every file here imports into NumpadControl as it is.

## Use a profile

1. Find one in [`profiles/`](profiles/) (or search [`index.json`](index.json)).
2. Download the `.json` file (open it on GitHub → **Download raw file**).
3. In NumpadControl: **Profile ⋯ → Import profile…** and pick the file.
4. Read the summary the app shows before adding it. Lines marked **⚠** run programs, press keys for you,
   run code or power the PC off.

> **Profiles run on your computer as you.** Official profiles are reviewed by the maintainers. Community
> profiles are checked automatically and by a reviewer, but read the import summary every time anyway.

A profile with a **window match** (like OBS or VS Code) switches on by itself while that app is focused,
and leaves every other key to your Default profile. A **general** profile (no match, like *Media and
volume*) never switches on by itself: after importing, copy its keys into Default or give it a match.

## Official profiles

| Profile | For | Needs |
|---|---|---|
| [Streaming (OBS)](profiles/official/obs-streaming.json) | OBS: go live, record, replay, mic | OBS WebSocket server on |
| [Media and volume](profiles/official/media-and-volume.json) | general: play, skip, volume, mic | |
| [Editing](profiles/official/editing.json) | general: copy, paste, undo, save, screenshots | |
| [VS Code](profiles/official/vscode.json) | VS Code / VSCodium, layer key = debugger | |
| [Web browser](profiles/official/web-browser.json) | Firefox, Chrome, Edge, Brave: tabs, history, zoom | |

## Repository layout

```
profiles/
  official/<name>.json             maintained here
  community/<github-name>/<name>.json   shared by people (one folder each)
schema/
  profile.schema.json              JSON Schema for editors and CI
  actions.json                     NumpadControl's actions, keys and limits (snapshot of the app)
tools/nclib.py                     validate profiles, build index.json, start a new profile
tests/                             validator tests and fixtures
index.json                         catalog of every profile (generated, don't edit)
.github/                           CI, pull request and issue templates
```

## The file format

It is exactly NumpadControl's export format, plus a `meta` block for the library (the app ignores it):

```jsonc
{
  "$schema": "../../schema/profile.schema.json",   // editor completion; ignored by the app
  "format": "numpadcontrol-profile",
  "version": 1,
  "app_version": "0.3.1",
  "meta": {
    "author": "your-github-name",
    "description": "What it's for, and anything to set up first.",
    "tags": ["streaming", "obs"],
    "platforms": ["windows", "linux"],             // windows, linux, hyprland
    "requires": ["OBS WebSocket server on"],       // optional
    "min_app_version": "0.3.1",                    // optional
    "homepage": "https://…"                        // optional
  },
  "profile": {
    "name": "Streaming (OBS)",
    "match": "obs,com.obsproject.Studio,obs64",    // Linux window classes + Windows program names, no .exe
    "bindings": {
      "7": { "tap":  { "action": "obs_toggle_streaming", "params": {} } },
      "5": { "tap":  { "action": "mic_mute", "params": {} },
             "hold": { "action": "press_keys", "params": { "keys": "ctrl+shift+m" } } }
    },
    "layer_bindings": {}
  }
}
```

- **Keys:** `NumLock` `/` `*` `Backspace` `0`–`9` `-` `+` `Enter` `.` `000` `00` (`000` and `00` are
  tap-only), plus extra keys added in Learn mode, such as `KEY_TAB`.
- **Slots:** `tap`, `hold` and `double`. A binding is `action` and `params`, with optional `rapid` (bool) and
  `turbo` (1–60 presses a second).
- **Actions:** see [`schema/actions.json`](schema/actions.json) for every id and its settings.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short:

```sh
python tools/nclib.py new your-github-name my-profile   # or export from the app and add meta
python tools/nclib.py validate
```

Then open a pull request. Only Python 3.9+ is needed, with no packages.

## License

[GPL-3.0](LICENSE). Profiles you contribute are shared under the same license.
