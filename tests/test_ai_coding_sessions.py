import json
import os
import fcntl
from pathlib import Path
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import textwrap
import time
import unicodedata
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "ai-coding-sessions"
BASH = shutil.which("bash") or "/usr/bin/bash"
STUB = textwrap.dedent("""\
    import json
    import os
    from pathlib import Path
    import sys
    import time

    command = Path(sys.argv[0]).name
    if command == "tmux":
        with open(os.environ["TEST_TMUX_LOG"], "a") as log:
            log.write(json.dumps(sys.argv[1:]) + "\\n")
        if sys.argv[1] == "info":
            sys.exit(int(os.environ.get("TEST_TMUX_EXIT", "0")))
        if sys.argv[1] == "list-panes":
            for i in range(int(os.environ.get("TEST_PANE_COUNT", "1"))):
                target = os.environ.get("TEST_TARGET", "sample:" + str(i) + ".0")
                window = os.environ.get("TEST_WINDOW", "sample")
                directory = os.environ.get("TEST_DIR", "/tmp/project")
                label = os.environ.get("TEST_LABEL", target)
                print(f"{target}|{100+i}|{window}|{directory}|%{5+i}|{label}")
        elif sys.argv[1] == "capture-pane":
            if os.environ.get("TEST_CAPTURE_FAIL"):
                sys.exit(1)
            if os.environ.get("TEST_STATES"):
                print("PANE=" + sys.argv[-1])
            print(os.environ.get("TEST_SCREEN", "PRIVATE_SESSION_TEXT"))
    elif command == "ps":
        if not os.environ.get("TEST_NO_AGENTS"):
            for i in range(int(os.environ.get("TEST_PANE_COUNT", "1"))):
                print(f"{200+i} {100+i} codex\\n{100+i} 1 bash")
    elif command == "herdr":
        Path(os.environ["TEST_HERDR_CALLED"]).touch()
        assert sys.argv[1:] == ["agent", "explain", "--file", "/dev/stdin", "--agent", "codex", "--json"]
        screen = sys.stdin.read().strip()
        assert screen
        if os.environ.get("TEST_DETECTOR_FAIL"):
            sys.exit(1)
        if os.environ.get("TEST_DETECTOR_SLEEP"):
            time.sleep(10)
        if os.environ.get("TEST_STATES"):
            index = int(screen.splitlines()[0].removeprefix("PANE=%")) - 5
            state = json.loads(os.environ["TEST_STATES"])[index]
            print(json.dumps({"state": state, "matched_rule": {"id": "fixture_" + state}}))
        else:
            print(os.environ["TEST_DETECTION"])
""")


class StatusPOCTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for command in ("tmux", "ps", "herdr"):
            path = self.root / command
            path.write_text(f"#!{sys.executable}\n" + STUB)
            path.chmod(0o755)
        self.called = self.root / "herdr-called"
        self.tmux_log = self.root / "tmux-calls"
        self.env = {
            **os.environ,
            "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
            "TEST_HERDR_CALLED": str(self.called),
            "TEST_TMUX_LOG": str(self.tmux_log),
            "TEST_DETECTION": json.dumps({
                "state": "working",
                "matched_rule": {"id": "screen_working_fallback", "state": "working"},
                "manifest_version": "test-version",
            }),
        }

    def run_script(self, *args, input_text="q", **env):
        return subprocess.run(
            [BASH, str(SCRIPT), *args],
            env={**self.env, **env}, input=input_text, text=True,
            capture_output=True, timeout=8,
        )

    def status(self, **env):
        result = self.run_script("--json", **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("PRIVATE_SESSION_TEXT", result.stdout + result.stderr)
        return json.loads(result.stdout)[0]

    def test_explicit_rule_states_and_metadata(self):
        for state in ("idle", "working", "blocked"):
            with self.subTest(state=state):
                row = self.status(TEST_DETECTION=json.dumps({
                    "state": state, "matched_rule": {"id": "test_rule", "state": state},
                    "manifest_version": "test-version",
                }))
                self.assertEqual(row["status"], state)
                self.assertEqual(row["pane"], "%5")
                self.assertEqual(row["target"], "sample:0.0")
                self.assertEqual(row["label"], "sample:0.0")
                self.assertEqual(row["manifest_version"], "test-version")

    def test_label_defaults_to_session_window_pane_but_is_independent_of_target(self):
        row = self.status(TEST_LABEL="custom-label")
        self.assertEqual(row["target"], "sample:0.0")
        self.assertEqual(row["label"], "custom-label")

    def test_custom_label_format_is_passed_to_tmux_list_panes(self):
        result = self.run_script("--json", AI_CODING_SESSIONS_LABEL_FORMAT="#{window_name}")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.tmux_log.read_text().splitlines()]
        list_panes_call = next(call for call in calls if call[0] == "list-panes")
        self.assertEqual(list_panes_call[-1].rsplit("|", 1)[-1], "#{window_name}")

    def test_picker_displays_custom_label_instead_of_target(self):
        result = self.run_script(TEST_LABEL="my-custom-label", TMUX="test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("my-custom-label", result.stdout)
        self.assertNotIn("sample:0.0", result.stdout)

    def test_idle_fallback_preserves_herdr_state_and_evidence(self):
        row = self.status(TEST_DETECTION=json.dumps({
            "state": "idle", "matched_rule": None,
            "fallback_reason": "default_known_agent_idle_fallback",
        }))
        self.assertEqual(row["status"], "idle")
        self.assertEqual(row["detected_status"], "idle")
        self.assertEqual(row["reason"], "default_known_agent_idle_fallback")

    def test_skipped_snapshot_preserves_unknown(self):
        row = self.status(TEST_DETECTION=json.dumps({
            "state": "unknown", "matched_rule": {"id": "viewer"},
            "skip_state_update": True,
        }))
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(row["reason"], "detection_skipped")

    def test_capture_failure_does_not_call_detector(self):
        self.assertEqual(self.status(TEST_CAPTURE_FAIL="1")["reason"], "capture_failed")
        self.assertFalse(self.called.exists())

    def test_empty_screen_does_not_call_detector(self):
        self.assertEqual(self.status(TEST_SCREEN=" \n ")["reason"], "empty_screen")
        self.assertFalse(self.called.exists())

    def test_detector_failure_and_timeout_are_unknown(self):
        for variable in ("TEST_DETECTOR_FAIL", "TEST_DETECTOR_SLEEP"):
            with self.subTest(variable=variable):
                row = self.status(**{variable: "1"})
                self.assertEqual(row["status"], "unknown")
                self.assertEqual(row["reason"], "detector_failed")

    def test_invalid_or_multiple_results_are_unknown(self):
        for output in ("not json", "", "null", "{}", '{"state":"done"}', '{}\n{}'):
            with self.subTest(output=output):
                row = self.status(TEST_DETECTION=output)
                self.assertEqual(row["status"], "unknown")
                self.assertEqual(row["reason"], "invalid_detector_output")

    def test_no_agents_returns_empty_json(self):
        result = self.run_script("--json", TEST_NO_AGENTS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])
        self.assertFalse(self.called.exists())

    def test_table_has_status_and_rule_without_prompt(self):
        result = self.run_script("--status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("working", result.stdout)
        self.assertIn("screen_working_fallback", result.stdout)
        self.assertNotIn("Select (", result.stdout)

    def test_default_switcher_shows_status(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Select (1-1)", result.stdout)
        self.assertIn("STATUS", result.stdout)
        self.assertIn("working", result.stdout)
        self.assertTrue(self.called.exists())
        self.assertNotIn("\033[", result.stdout)

    def test_switcher_can_refresh_status(self):
        result = self.run_script(input_text="rq")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("AI sessions (1)"), 2)

    def test_picker_selects_full_target_after_truncation(self):
        target = "very-long-session-name-for-a-project:0.0"
        result = self.run_script(input_text="1", TEST_TARGET=target, TMUX="test", COLUMNS="64")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.tmux_log.read_text().splitlines()]
        self.assertIn(["switch-client", "-t", target], calls)
        self.assertIn(["select-pane", "-t", target], calls)

    def test_picker_pages_without_changing_selection_numbers(self):
        result = self.run_script(input_text="n4", TEST_PANE_COUNT="5", LINES="11", COLUMNS="64", TMUX="test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Page 1/2", result.stdout)
        self.assertIn("Page 2/2", result.stdout)
        calls = [json.loads(line) for line in self.tmux_log.read_text().splitlines()]
        self.assertIn(["select-pane", "-t", "sample:3.0"], calls)

    def test_picker_fits_narrow_and_wide_terminals(self):
        for width in (40, 64, 100, 200):
            with self.subTest(width=width):
                result = self.run_script(COLUMNS=str(width), TEST_TARGET="very-long-session-name:0.0",
                    TEST_WINDOW="\U0001f916 " + "\u754c" * 30, TEST_DIR="/tmp/" + "\u754c" * 40)
                self.assertEqual(result.returncode, 0, result.stderr)
                for line in result.stdout.splitlines():
                    cells = sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in line)
                    self.assertLessEqual(cells, width, line)
                self.assertIn("-" * width, result.stdout)

    def test_json_status_filter_keeps_only_matching_panes(self):
        result = self.run_script("--json", "--filter", "blocked", TEST_PANE_COUNT="3",
            TEST_STATES=json.dumps(["idle", "blocked", "working"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target"], "sample:1.0")
        self.assertEqual(rows[0]["status"], "blocked")

    def test_json_status_filter_without_matches_returns_empty_array(self):
        result = self.run_script("--json", "--filter=blocked")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_filtered_picker_selects_matching_pane(self):
        result = self.run_script("--filter", "blocked", input_text="1", TMUX="test", TEST_PANE_COUNT="3",
            TEST_STATES=json.dumps(["idle", "working", "blocked"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Filter: blocked", result.stdout)
        calls = [json.loads(line) for line in self.tmux_log.read_text().splitlines()]
        self.assertIn(["select-pane", "-t", "sample:2.0"], calls)

    def test_status_letter_changes_filter_and_selection_mapping(self):
        result = self.run_script(input_text="w1", TMUX="test", TEST_PANE_COUNT="3",
            TEST_STATES=json.dumps(["idle", "blocked", "working"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Filter: working", result.stdout)
        calls = [json.loads(line) for line in self.tmux_log.read_text().splitlines()]
        self.assertIn(["select-pane", "-t", "sample:2.0"], calls)

    def test_empty_filter_can_return_to_all(self):
        result = self.run_script("--filter", "blocked", input_text="aq")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No blocked sessions.", result.stdout)
        self.assertIn("Filter: all", result.stdout)
        self.assertIn("AI sessions (1)", result.stdout)

    def test_refresh_preserves_selected_filter(self):
        result = self.run_script(input_text="wrq")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("Filter: working"), 2)

    def test_each_status_letter_selects_the_correct_pane(self):
        states = ["idle", "blocked", "working", "unknown"]
        for index, key in enumerate("ibwu"):
            with self.subTest(key=key):
                result = self.run_script(input_text=key + "1", TMUX="test", TEST_PANE_COUNT="4", TEST_STATES=json.dumps(states))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Filter: " + states[index], result.stdout)
                calls = [json.loads(line) for line in self.tmux_log.read_text().splitlines()]
                self.assertEqual(calls[-1], ["select-pane", "-t", f"sample:{index}.0"])

    def test_filter_menu_opens_text_search_and_combines_filters(self):
        result = self.run_script(input_text="bfsSAMPLE:2\n1", TMUX="test", TEST_PANE_COUNT="3",
            TEST_STATES=json.dumps(["blocked", "working", "blocked"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("s search", result.stdout)
        self.assertIn("Search: SAMPLE:2", result.stdout)
        calls = [json.loads(line) for line in self.tmux_log.read_text().splitlines()]
        self.assertEqual(calls[-1], ["select-pane", "-t", "sample:2.0"])

    def test_text_search_matches_directory_and_window_case_insensitively(self):
        for text in ("ALPHA WINDOW", "BETA PROJECT"):
            with self.subTest(text=text):
                result = self.run_script("--json", "--search", text, TEST_WINDOW="Alpha Window", TEST_DIR="/tmp/Beta Project")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(json.loads(result.stdout)), 1)

    def test_text_search_does_not_treat_globs_as_wildcards(self):
        result = self.run_script("--json", "--search", "*")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_refresh_preserves_text_search(self):
        result = self.run_script(input_text="fsproject\nrq")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("Search: project"), 2)

    def test_clear_restores_all_sessions(self):
        result = self.run_script("--filter", "blocked", "--search", "missing", input_text="cq")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No matching sessions.", result.stdout)
        self.assertIn("Filter: all", result.stdout)
        self.assertIn("working", result.stdout)

    def test_filter_menu_can_select_status(self):
        result = self.run_script(input_text="fB1", TMUX="test", TEST_PANE_COUNT="2", TEST_STATES=json.dumps(["idle", "blocked"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.tmux_log.read_text().splitlines()]
        self.assertEqual(calls[-1], ["select-pane", "-t", "sample:1.0"])

    def test_invalid_filter_is_rejected(self):
        for args in (("--filter", "bogus"), ("--filter",), ("--search",)):
            with self.subTest(args=args):
                result = self.run_script(*args)
                self.assertEqual(result.returncode, 2)
                self.assertTrue("filter" in result.stderr or "search" in result.stderr)

    def test_small_terminal_does_not_render_an_oversized_table(self):
        result = self.run_script(COLUMNS="28", LINES="6")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Resize to at least", result.stdout)
        self.assertNotIn("STATUS", result.stdout)
        self.assertLessEqual(len(result.stdout), 28)

    def test_picker_redraws_on_resize_without_a_keypress(self):
        master, slave = pty.openpty()
        process = None

        def resize(rows, columns):
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
            if process is not None:
                process.send_signal(signal.SIGWINCH)

        def read_until(needle):
            output = b""
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    output += os.read(master, 65536)
                if needle.encode() in output:
                    return output.decode()
            self.fail("Missing " + needle + " in " + output.decode(errors="replace"))

        try:
            resize(18, 200)
            process = subprocess.Popen([BASH, str(SCRIPT)], stdin=slave, stdout=slave, stderr=slave,
                env={**self.env, "TEST_PANE_COUNT": "12", "NO_COLOR": "1"}, start_new_session=True)
            initial = read_until("q quit:")
            self.assertIn("-" * 200, initial)
            resize(12, 40)
            narrow = read_until("1-12 | f menu")
            self.assertIn("Page 1/3", narrow)
            resize(6, 28)
            read_until("Resize to at least 36x9")
            resize(20, 120)
            restored = read_until("q quit:")
            self.assertIn("Page 1/1", restored)
            os.write(master, b"q")
            self.assertEqual(process.wait(timeout=3), 0)
        finally:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            os.close(master)
            os.close(slave)

    def test_missing_herdr_only_blocks_status_mode(self):
        (self.root / "herdr").unlink()
        for command in ("sort", "basename", "wc"):
            (self.root / command).symlink_to(shutil.which(command))
        result = self.run_script("--status", PATH=str(self.root))
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires herdr", result.stderr)
        result = self.run_script(PATH=str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Select (1-1)", result.stdout)
        self.assertIn("unknown", result.stdout)

    def test_unavailable_tmux_does_not_pollute_json_stdout(self):
        result = self.run_script("--json", TEST_TMUX_EXIT="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("tmux is not running", result.stderr)


if __name__ == "__main__":
    unittest.main()
