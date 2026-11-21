"""Behavior checks for the offline profile renderer."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "skills/github-profile-curator/scripts/render_profile.py"
MODULE = importlib.util.spec_from_file_location("render_profile", SCRIPT)
renderer = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(renderer)


def example():
    return {"owner": "example-owner", "heading": "Service experiments", "projects": [
        {"repo": "retry-demo", "title": "Retry Demo", "description": "Compare synthetic attempt counts."}
    ]}


class RenderTests(unittest.TestCase):
    def test_append_preserves_original_and_builds_only_derived_links(self):
        original = "# Profile\n\nOriginal café.\n".encode()
        result = renderer.render_profile(original, example())
        self.assertTrue(result.startswith(original + b"\n"))
        self.assertIn(b"[Retry Demo](https://github.com/example-owner/retry-demo)", result)
        self.assertEqual(result.count(renderer.START), 1)
        self.assertEqual(result.count(renderer.END), 1)
        self.assertTrue(result.endswith(b"\n"))

    def test_empty_and_no_final_newline_are_idempotent(self):
        for original in (b"", b"# Profile", b"# Profile\n", b"# Profile\n\n"):
            with self.subTest(original=original):
                result = renderer.render_profile(original, example())
                self.assertEqual(renderer.render_profile(result, example()), result)
                self.assertEqual(result.endswith(b"\n"), not original or original.endswith(b"\n"))

    def test_replace_changes_only_marker_block(self):
        prefix, suffix = b"# Profile\n\nKeep me.\n\n", b"\n\n## Other\nKeep this EOF"
        original = prefix + renderer.START + b"\nOld\n" + renderer.END + suffix
        result = renderer.render_profile(original, example())
        self.assertTrue(result.startswith(prefix + renderer.START))
        self.assertTrue(result.endswith(renderer.END + suffix))
        self.assertNotIn(b"\nOld\n", result)
        self.assertEqual(renderer.render_profile(result, example(), "## Missing"), result)

    def test_insert_before_preserves_prefix_and_suffix(self):
        prefix, suffix = b"# Profile\n\nIntro\n", b"## Selected projects\nExisting content\n"
        result = renderer.render_profile(prefix + suffix, example(), "## Selected projects")
        self.assertTrue(result.startswith(prefix + b"\n" + renderer.START))
        self.assertTrue(result.endswith(renderer.END + b"\n\n" + suffix))
        self.assertEqual(renderer.render_profile(result, example(), "## Selected projects"), result)

    def test_insert_at_start(self):
        original = b"## Existing\nKeep\n"
        result = renderer.render_profile(original, example(), "## Existing")
        self.assertTrue(result.startswith(renderer.START))
        self.assertTrue(result.endswith(b"\n\n" + original))

    def test_initial_before_must_be_exact_unique_heading(self):
        for original, heading in (
            (b"## Existing\n", "## Missing"),
            (b"## Existing\n## Existing\n", "## Existing"),
            (b"## Existing \n", "## Existing"),
            (b"Not a heading\n", "Not a heading"),
            (b"## Existing\n", "## Existing\n"),
        ):
            with self.subTest(original=original, heading=heading), self.assertRaises(ValueError):
                renderer.render_profile(original, example(), heading)

    def test_crlf_append_and_replace_keep_crlf(self):
        original = "# Profile\r\n\r\nCafé\r\n".encode()
        result = renderer.render_profile(original, example())
        self.assertTrue(result.startswith(original))
        self.assertNotIn(b"\n", result.replace(b"\r\n", b""))
        spec = example()
        spec["heading"] = "Changed"
        updated = renderer.render_profile(result, spec)
        self.assertTrue(updated.startswith(original))
        self.assertNotIn(b"\n", updated.replace(b"\r\n", b""))
        self.assertEqual(renderer.render_profile(updated, spec), updated)

    def test_malformed_markers_fail_closed(self):
        start, end = renderer.START, renderer.END
        cases = [start, end, end + b"\n" + start, start + b"\n" + end + b"\n" + end,
                 start + b"\n" + start + b"\n" + end,
                 b"<!-- github-profile-curator:start", b"<!-- github-profile-curator:unknown -->",
                 b"inline " + start + b"\n" + end, start + b" suffix\n" + end,
                 start + b"\n" + end + b" suffix"]
        for original in cases:
            with self.subTest(original=original), self.assertRaises(ValueError):
                renderer.render_profile(original, example())

    def test_invalid_spec_shapes_and_names(self):
        cases = [None, [], {}, dict(example(), extra=True), dict(example(), projects={}),
                 dict(example(), projects=[{}]), dict(example(), projects=[dict(example()["projects"][0], url="https://bad")])]
        for owner in ("", "../owner", "user/name", "https://evil", "-name", "name-", "a" * 40, "a--b", 123):
            cases.append(dict(example(), owner=owner))
        for repo in ("", ".", "..", "../repo", "a/b", "a\\b", "%2e%2e", "repo?x=1", "https://evil", "a" * 101, None):
            spec = example()
            spec["projects"][0]["repo"] = repo
            cases.append(spec)
        for spec in cases:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                renderer.render_profile(b"", spec)

    def test_duplicate_repositories_are_case_insensitive(self):
        spec = example()
        spec["projects"].append(dict(spec["projects"][0], repo="RETRY-DEMO"))
        with self.assertRaises(ValueError):
            renderer.render_profile(b"", spec)

    def test_plain_text_and_html_are_literal(self):
        spec = example()
        spec["heading"] = "<script> & [heading]"
        spec["projects"][0]["title"] = "[x](https://evil) `code`"
        spec["projects"][0]["description"] = "<img src=x> **bold** https://evil.test &amp;"
        result = renderer.render_profile(b"", spec).decode()
        self.assertIn("&lt;script&gt; &amp; \\[heading\\]", result)
        self.assertIn(r"\[x\]\(https\:\/\/evil\) \`code\`", result)
        self.assertIn("&lt;img src\\=x&gt;", result)
        self.assertNotIn("<script>", result)
        self.assertNotIn("https://evil", result)
        self.assertEqual(result.count("https://"), 1)

    def test_controls_and_non_text_fields_are_rejected(self):
        for field in ("heading", "title", "description"):
            for value in ("", " ", "a\nb", "a\rb", "a\tb", "a\x00b", "a\u2028b", "a\u202eb", 123):
                spec = example()
                target = spec if field == "heading" else spec["projects"][0]
                target[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    renderer.render_profile(b"", spec)

    def test_does_not_mutate_spec_and_rejects_non_utf8_readme(self):
        spec = example()
        saved = deepcopy(spec)
        renderer.render_profile(b"# Profile", spec)
        self.assertEqual(spec, saved)
        with self.assertRaises(UnicodeError):
            renderer.render_profile(b"\xff", spec)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.readme = Path(self.temp.name) / "README.md"
        self.projects = Path(self.temp.name) / "projects.json"
        self.readme.write_bytes(b"# Profile\r\n")
        self.projects.write_text(json.dumps(example()), encoding="utf-8")

    def run_cli(self, *extra, **kwargs):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), "--readme", str(self.readme),
                               "--projects", str(self.projects), *extra],
                              stderr=subprocess.PIPE, timeout=10, check=False,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), **kwargs)

    def test_success_stdout_and_inputs_unchanged(self):
        before = self.readme.read_bytes(), self.projects.read_bytes()
        result = self.run_cli(stdout=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout, renderer.render_profile(before[0], example()))
        self.assertEqual((self.readme.read_bytes(), self.projects.read_bytes()), before)

    def test_invalid_json_markers_and_missing_file_have_no_stdout(self):
        for raw in (b"{", b'{"owner":"a","owner":"b"}', b'null'):
            self.projects.write_bytes(raw)
            result = self.run_cli(stdout=subprocess.PIPE)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertTrue(result.stderr.startswith(b"error:"))
        self.projects.write_text(json.dumps(example()), encoding="utf-8")
        self.readme.write_bytes(renderer.START)
        result = self.run_cli(stdout=subprocess.PIPE)
        self.assertEqual((result.returncode, result.stdout), (2, b""))
        self.assertIn(b"markers", result.stderr)
        self.readme.unlink()
        result = self.run_cli(stdout=subprocess.PIPE)
        self.assertEqual((result.returncode, result.stdout), (2, b""))
        self.assertTrue(result.stderr.startswith(b"error:"))

    def test_stdout_alias_is_rejected_without_writing(self):
        for path in (self.readme, self.projects):
            saved = path.read_bytes()
            # Append avoids shell truncation before the program can check the descriptor.
            with path.open("ab") as output:
                result = self.run_cli(stdout=output)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"different path", result.stderr)
            self.assertEqual(path.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
