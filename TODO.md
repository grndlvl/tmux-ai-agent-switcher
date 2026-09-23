# TODO

## Decouple the Herdr integration

[Herdr](https://herdr.dev/) is a separate, independent project — not part of
this repo. The status picker (`--status`/`--json`) currently shells out to it
directly and hardcodes its specific CLI shape
(`herdr agent explain --file - --agent <name> --json`) and JSON schema
(`state`, `matched_rule`, `fallback_reason`, `skip_state_update`,
`manifest_version`) inside `explain_pane_status` in `bin/ai-coding-sessions`.
It's already an optional runtime dependency (gated behind a `command -v
herdr` check — the switcher works fine with no status column if it's
missing), but the tight coupling to one detector's exact interface should be
loosened so this isn't Herdr-specific forever:

- [ ] Extract the Herdr invocation behind a documented, swappable interface
      (e.g. a `--detector <cmd>` flag or a convention any executable can
      satisfy), so other detectors could plug in.
- [ ] Document the expected detector input/output contract independently of
      Herdr's internals, so third parties can write a compatible detector
      without reading Herdr's source.
- [ ] Track Herdr's output schema for compatibility as it evolves (pin a
      minimum supported version, or handle schema changes gracefully).
- [ ] Add a CI job (or test fixture) that exercises the picker with *no*
      detector on `PATH` as the default/primary path, not just as a fallback
      case, to keep the "optional" guarantee honest over time.
