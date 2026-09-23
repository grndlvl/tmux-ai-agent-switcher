# TODO

## Separate the Herdr coupling

Herdr is a separate, not-yet-public project of the maintainer's. The status
picker (`--status`/`--json`) currently shells out to it directly and expects
its specific CLI shape (`herdr agent explain --file - --agent <name> --json`)
and JSON schema (`state`, `matched_rule`, `fallback_reason`,
`skip_state_update`, `manifest_version`). That's fine as an optional runtime
dependency (already gated behind a `command -v herdr` check — see
`explain_pane_status` in `bin/ai-coding-sessions`), but it's a private
implementation detail leaking into a public tool. Tracked separately so the
core switcher never grows a hard dependency on it:

- [ ] Publish Herdr as its own public repo, or document an alternative
      detector protocol other tools could implement.
- [ ] Extract the Herdr-specific invocation (`explain_pane_status`) behind a
      documented, swappable interface (e.g. a `--detector <cmd>` flag or a
      convention any executable can satisfy) instead of hardcoding `herdr`.
- [ ] Document the expected detector input/output contract independently of
      Herdr's internals, so third parties can write their own detector.
- [ ] Once Herdr is public, link to it from the README instead of describing
      it as "not yet public."
- [ ] Add a CI job (or test fixture) that exercises the picker with *no*
      detector on `PATH` as the default/primary path, not just as a fallback
      case, to keep the "optional" guarantee honest over time.
