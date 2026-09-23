# tmux-ai-sessions

List and switch between AI coding agent sessions (Claude Code, Codex, opencode,
Gemini, and any agent you add) running in `tmux`, from a single popup picker.

Finds every pane running a known agent process across all your tmux sessions —
even nested under a shell or wrapper — and lets you jump to it, filter by
status, or search by pane/window/directory text.

## Install

```sh
git clone https://github.com/grndlvl/tmux-ai-sessions.git
cd tmux-ai-sessions
./bin/ai-coding-sessions --install
```

`--install` adds a `prefix + a` keybinding to `~/.config/tmux/tmux.conf` (or
`~/.tmux.conf`) that opens the picker in a popup, and reloads tmux if it's
running. You can also bind it manually:

```tmux
bind-key a display-popup -E -w 90% -h 80% "/path/to/bin/ai-coding-sessions"
```

Requires `bash` and `tmux`. No other runtime dependencies for the core
picker.

## Usage

Open the picker (via the keybinding, or run the script directly), then:

- `1`-`N` — jump to that session
- `f` — open the filter menu (`i`dle / `b`locked / `w`orking / `u`nknown / `a`ll)
- `s` — text search across pane, agent, window, and directory
- `c` — clear all filters
- `r` — refresh
- `n` / `p` — next / previous page
- `q` — quit

```
$ ai-coding-sessions --help
```
shows the full option list, including `--standalone` (switch an attached
tmux client from outside tmux — handy for a launcher or hotkey daemon),
`--filter`, and `--search`.

### Adding agents

Edit the `AGENTS` array at the top of `bin/ai-coding-sessions`:

```sh
AGENTS=(
  "claude:claude"
  "claude-code:claude"
  "codex:codex"
  "opencode:opencode"
  "npm exec @googl:gemini"
)
```

Each entry is `process_name:display_name`. Find the process name with
`ps -eo pid=,comm= | grep <agent-name>` while the agent is running in a pane.

### Pane label

The PANE column defaults to tmux's native `session:window.pane` target
syntax. Override it with any [tmux format string](https://man7.org/linux/man-pages/man1/tmux.1.html#FORMATS)
— for example, to show just the window name:

```sh
AI_CODING_SESSIONS_LABEL_FORMAT='#{window_name}' ai-coding-sessions
```

or edit `PANE_LABEL_FORMAT` at the top of `bin/ai-coding-sessions` to change
the default. This only changes what's displayed — pane selection and
switching always address panes by `session:window.pane` internally, so any
format string is safe here.

## Optional: live status via Herdr

The picker can additionally show a live `working` / `idle` / `blocked` /
`unknown` status per pane, using [Herdr](https://herdr.dev/) as an external
agent-state detector. This is entirely optional — the switcher works with no
status column at all if Herdr isn't installed.

Status mode requires `herdr`, `jq`, and `timeout` on `PATH`:

```sh
ai-coding-sessions --status   # one-shot status table
ai-coding-sessions --json     # same snapshot as JSON
```

If any of those three commands is missing, `--status`/`--json` fail with a
clear error, and the normal switcher continues to work without a status
column (falls back to `unknown`). See [`TODO.md`](TODO.md) for plans to
decouple this further.

## Development

```sh
python3 -m unittest tests.test_ai_coding_sessions -v
```

The test suite stubs `tmux`, `ps`, and `herdr` on `PATH`, so it needs no
real tmux session or Herdr install to run.

## License

MIT — see [LICENSE](LICENSE).
