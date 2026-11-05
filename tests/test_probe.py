"""单元测试：不联网，全部用假响应。

    python -m unittest discover -s tests -v
"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from probe_kit import config as cfgmod          # noqa: E402
from probe_kit.probe import ProbeResult         # noqa: E402
from probe_kit.state import State               # noqa: E402


class _FakeResp(io.BytesIO):
    """模拟 urllib 的 response 对象。"""

    def __init__(self, body: bytes, status: int = 200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = _FakeHeaders(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeHeaders(dict):
    def items(self):
        return list(super().items())


class TestStatusMatch(unittest.TestCase):
    def test_exact(self):
        r = ProbeResult(url="x", status=200)
        self.assertTrue(r.matches_status(200))
        self.assertTrue(r.matches_status("200"))
        self.assertFalse(r.matches_status(404))

    def test_wildcard(self):
        r = ProbeResult(url="x", status=204)
        self.assertTrue(r.matches_status("2xx"))
        self.assertFalse(r.matches_status("4xx"))

    def test_range(self):
        r = ProbeResult(url="x", status=302)
        self.assertTrue(r.matches_status("300-399"))
        self.assertFalse(r.matches_status("200-299"))

    def test_none_means_any(self):
        r = ProbeResult(url="x", status=500)
        self.assertTrue(r.matches_status(None))

    def test_no_status_is_false(self):
        r = ProbeResult(url="x", status=None)
        self.assertFalse(r.matches_status(200))


class TestState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "st.json")

    def test_roundtrip(self):
        st = State(self.path)
        st.set("a", sha="deadbeef", status=200)
        st.save()

        st2 = State(self.path).load()
        self.assertEqual(st2.get_sha("a"), "deadbeef")
        self.assertEqual(st2.get("a")["status"], 200)
        self.assertEqual(len(st2), 1)

    def test_missing_file_is_empty(self):
        st = State(os.path.join(self.tmp, "nope.json")).load()
        self.assertEqual(len(st), 0)
        self.assertEqual(st.get_sha("x"), "")

    def test_broken_file_is_empty(self):
        Path(self.path).write_text("{not json", encoding="utf-8")
        st = State(self.path).load()
        self.assertEqual(len(st), 0)

    def test_no_path_is_noop(self):
        st = State(None)
        st.set("a", sha="x")
        st.save()          # 不抛异常即可
        self.assertEqual(len(st), 1)

    def test_overwrite(self):
        st = State(self.path)
        st.set("a", sha="one")
        st.set("a", sha="two")
        self.assertEqual(st.get_sha("a"), "two")


class TestConfig(unittest.TestCase):
    def test_basic(self):
        text = """
[notify]
webhook = "https://example.com/h"

[[targets]]
name = "a"
url = "https://a.com"
expect_status = 200
timeout = 5
watch_content = true
"""
        c = cfgmod.loads(text)
        self.assertEqual(c["notify"]["webhook"], "https://example.com/h")
        self.assertEqual(len(c["targets"]), 1)
        t = c["targets"][0]
        self.assertEqual(t["name"], "a")
        self.assertEqual(t["expect_status"], 200)
        self.assertEqual(t["timeout"], 5)
        self.assertIs(t["watch_content"], True)

    def test_comments_ignored(self):
        c = cfgmod.loads('# top\n[[targets]]\nname = "a" # inline\nurl = "https://a.com"\n')
        self.assertEqual(c["targets"][0]["name"], "a")

    def test_missing_targets_rejected(self):
        with self.assertRaises(cfgmod.ConfigError):
            cfgmod._validate({})

    def test_missing_url_rejected(self):
        with self.assertRaises(cfgmod.ConfigError):
            cfgmod._validate({"targets": [{"name": "a"}]})

    def test_bad_scheme_rejected(self):
        with self.assertRaises(cfgmod.ConfigError):
            cfgmod._validate({"targets": [{"name": "a", "url": "ftp://x"}]})

    def test_duplicate_name_rejected(self):
        with self.assertRaises(cfgmod.ConfigError):
            cfgmod._validate({"targets": [
                {"name": "a", "url": "https://a.com"},
                {"name": "a", "url": "https://b.com"},
            ]})

    def test_unknown_line_raises(self):
        with self.assertRaises(cfgmod.ConfigError):
            cfgmod.loads("[[targets]]\nthis is not valid\n")

    def test_json_config(self):
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "c.json")
        Path(p).write_text(json.dumps({
            "targets": [{"name": "a", "url": "https://a.com"}]
        }), encoding="utf-8")
        c = cfgmod.load_auto(p)
        self.assertEqual(c["targets"][0]["name"], "a")


class TestProbeMocked(unittest.TestCase):
    def test_success(self):
        probe_mod = sys.modules["probe_kit.probe"]

        fake = _FakeResp(b"hello world", 200, {"Content-Type": "text/plain"})
        with mock.patch.object(probe_mod.urllib.request, "build_opener") as bo:
            bo.return_value.open.return_value = fake
            r = probe_mod.probe("https://x.com")
        self.assertTrue(r.ok)
        self.assertEqual(r.status, 200)
        self.assertEqual(r.body_bytes, 11)
        self.assertEqual(len(r.body_sha256), 64)
        self.assertEqual(r.body_text, "hello world")

    def test_http_error_keeps_status(self):
        import urllib.error
        probe_mod = sys.modules["probe_kit.probe"]

        err = urllib.error.HTTPError("https://x.com", 503, "boom", _FakeHeaders(), io.BytesIO(b"err"))
        with mock.patch.object(probe_mod.urllib.request, "build_opener") as bo:
            bo.return_value.open.side_effect = err
            r = probe_mod.probe("https://x.com")
        self.assertTrue(r.ok)
        self.assertEqual(r.status, 503)

    def test_url_error(self):
        import urllib.error
        probe_mod = sys.modules["probe_kit.probe"]

        with mock.patch.object(probe_mod.urllib.request, "build_opener") as bo:
            bo.return_value.open.side_effect = urllib.error.URLError("dns fail")
            r = probe_mod.probe("https://nope.invalid")
        self.assertFalse(r.ok)
        self.assertIn("dns fail", r.error)

    def test_check_target_keyword(self):
        probe_mod = sys.modules["probe_kit.probe"]

        fake = _FakeResp(b"all systems ok", 200)
        with mock.patch.object(probe_mod.urllib.request, "build_opener") as bo:
            bo.return_value.open.return_value = fake
            r, problems = probe_mod.check_target({
                "name": "a", "url": "https://x.com",
                "expect_status": 200, "expect_keyword": "systems",
            })
        self.assertEqual(problems, [])

        with mock.patch.object(probe_mod.urllib.request, "build_opener") as bo:
            bo.return_value.open.return_value = _FakeResp(b"all systems ok", 200)
            r, problems = probe_mod.check_target({
                "name": "a", "url": "https://x.com",
                "expect_status": 200, "expect_keyword": "missing",
            })
        self.assertEqual(len(problems), 1)
        self.assertIn("missing", problems[0])

    def test_check_target_max_ms(self):
        probe_mod = sys.modules["probe_kit.probe"]

        with mock.patch.object(probe_mod.urllib.request, "build_opener") as bo:
            bo.return_value.open.return_value = _FakeResp(b"", 200)
            r, problems = probe_mod.check_target({
                "name": "a", "url": "https://x.com", "max_ms": -1,
            })
        self.assertTrue(any("耗时" in p for p in problems))


if __name__ == "__main__":
    unittest.main(verbosity=2)
