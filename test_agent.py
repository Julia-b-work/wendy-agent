"""Tests for Wendy: the tools, the agent loop, and the MCP-facing functions.

Run with: python -m unittest test_agent
"""

import os
import subprocess
import tempfile
import unittest
import agent
import anthropic
import tools

from types import SimpleNamespace
from unittest import mock

def tool_response():
    return SimpleNamespace(content=[
        SimpleNamespace(type="tool_use", name="list_files", id="t1", input={"directory": "."})
    ])

def text_response(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

class TestListFiles(unittest.TestCase):

    def test_sorted_and_skips_hidden(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ["zeta.txt", "alpha.txt", "mid.txt"]:
                open(os.path.join(d, name), "w").close()
            os.makedirs(os.path.join(d, ".hidden"))
            open(os.path.join(d, ".hidden", "secret.txt"), "w").close()
            out = agent.list_files(d)

            expected = [
                    os.path.join(d, "alpha.txt"),
                    os.path.join(d, "mid.txt"),
                    os.path.join(d, "zeta.txt"),
            ]
            self.assertEqual(out.splitlines(), expected)
            self.assertNotIn("secret.txt", out)

    def test_caps_at_100(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(105):
                open(os.path.join(d, f"f{i:03}.txt"), "w").close()
            out = agent.list_files(d)
        self.assertEqual(len(out.splitlines()), 100)


class TestReadFile(unittest.TestCase):

    def test_returns_contents(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "hello.txt")
            with open(p, "w") as f:
                f.write("I am testing!")
            self.assertEqual(agent.read_file(p), "I am testing!")

    def test_missing_file(self):
        self.assertEqual(
                agent.read_file(
                    "/no/such/file.txt"),
                "File not found: /no/such/file.txt",)


class TestSearch(unittest.TestCase):

    def test_finds_match(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "wendy.py"), "w") as f:
                f.write("def main():\n  test = 1\n")
            out = agent.search("test", root=d)

        self.assertIn("test", out)
        self.assertIn("wendy.py:2", out)

    def test_survive_binary(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "smth.bin"), "wb") as f:
                f.write(b"\xff\xfe\xfa\x00")

            out = agent.search("anything", root=d)
        self.assertEqual(out, "")

class TestNudgeMessage(unittest.TestCase):
    def test_formats(self):
        out = agent.NUDGE_MESSAGE.format(n=10)
        self.assertIn("10", out)
        self.assertIn("answer", out)


class FakeMessages:

    def __init__(self, response):
        self.responses = list(response)
        self.calls = []
    
    def create(self, **kwargs):
        self.calls.append({"messages": list(kwargs["messages"])})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

class FakeClient:

    def __init__(self, responses):
        self.messages = FakeMessages(responses)

class TestRunAgent(unittest.TestCase):

    def test_answers_without_tools(self):
        fake = FakeClient([text_response("working!")])
        self.assertEqual(agent.run_agent("q", client=fake), "working!")

    def test_human_stop(self):
        fake = FakeClient([tool_response()] * 10)
        with mock.patch("builtins.input", return_value="n"):
            out = agent.run_agent("q", client=fake)
        self.assertEqual(out, "Stopped by user after 10 steps.")

    def test_human_continues_then_stops(self):
        fake = FakeClient([tool_response()] * 20)
        with mock.patch("builtins.input", side_effect=["y", "n"]) as m:
            out = agent.run_agent("q", client=fake)
        self.assertEqual(out, "Stopped by user after 20 steps.")
        self.assertEqual(m.call_count, 2)   

    def test_nudge_injected_at_step_11(self):
        fake = FakeClient([tool_response()] * 12)
        with mock.patch("builtins.input", return_value="y"):
            agent.run_agent("q", max_steps=12, client=fake)

        nudge = agent.NUDGE_MESSAGE.format(n=agent.STEP_LIMIT)
        def has_nudge(call):
            return any(
                    m.get("role") == "user" and m.get("content") == nudge
                    for m in call["messages"]
            )

        self.assertFalse(has_nudge(fake.messages.calls[9]))
        self.assertTrue(has_nudge(fake.messages.calls[10]))


    def test_justification_does_not_crash(self):
        mixed = SimpleNamespace(content=[
            SimpleNamespace(type="text", text="I need to look at the files"),
            SimpleNamespace(type="tool_use", name="list_files", id="t1", input={"directory": "."}),
        ])
        fake = FakeClient([mixed, text_response("found it")])
        self.assertEqual(agent.run_agent("q", client=fake), "found it")



class TestRunTool(unittest.TestCase):

    def test_dispatches_correctly(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "test.txt"), "w").close()
            out = agent.run_tool("list_files", {"directory": d})

        self.assertIn("test.txt", out)

    def test_unknown_tool(self):
        out = agent.run_tool("garbage", {})
        self.assertEqual("Unknown tool: garbage", out)

    def test_crash_is_contained(self):
        with mock.patch.object(agent, "list_files", side_effect=RuntimeError("BOOM!")): 
            out = agent.run_tool("list_files", {"directory": "."})
            self.assertIn("crashed", out)

    def test_missing_input_key(self):
        out = agent.run_tool("read_file", {})
        self.assertIn("crashed", out)


class TestTruncate(unittest.TestCase):

    def test_short_text_unchanged(self):
         self.assertEqual(tools.truncate("make my day", limit=20), "make my day")

    def  test_long_text_trucated(self):
        out = tools.truncate("x" * 100, limit=20)
        self.assertTrue(out.startswith("x" * 20))
        self.assertIn("[truncated]", out)

    def test_truncates_large_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "large.txt")
            with open(p, "w") as f:
                f.write("x" * (tools.MAX_RESULT_CHARS + 1000))
            out = agent.read_file(p)
        self.assertIn("[truncated]", out)


class TestNoiseFiltering(unittest.TestCase):

    def test_is_binary_test_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "somth.txt")
            with open(p, "w") as f:
                f.write("plain text")
            self.assertFalse(tools.is_binary(p))

    def test_is_binary_null_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "slop.bin")
            with open(p, "wb") as f:
                f.write(b"hello\x00world")
            self.assertTrue(tools.is_binary(p))

    def test_list_files_skips_binary_and_ignored_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "code.py"), "w").close()
            with open(os.path.join(d, "blob.bin"), "wb") as f:
                f.write(b"\x00\x01\x02")
            os.makedirs(os.path.join(d, "node_modules", "pkg"))
            open(os.path.join(d, "node_modules", "pkg", "dep.js"), "w").close()

            out = agent.list_files(d)

        self.assertIn("code.py", out)
        self.assertNotIn("blob.bin", out)
        self.assertNotIn("node_modules", out)


class FakeRateLimitError(anthropic.RateLimitError):
    
    def __init__(self, message="rate limited"):
        Exception.__init__(self, message)

class FakeAuthError(anthropic.AuthenticationError):

    def __init__(self, message="bad key"):
        Exception.__init__(self, message)

class TestApiErrors(unittest.TestCase):
    
    def test_auth_error_does_not_retry(self):
        fake = FakeClient([FakeAuthError()])
        with mock.patch("time.sleep"):
            out = agent.run_agent("q", client=fake)
        self.assertIn("Authentication error", out)
        self.assertEqual(len(fake.messages.calls), 1)

    def test_retryable_error_then_success(self):
        fake = FakeClient([FakeRateLimitError(), text_response("recovered")])
        with mock.patch("time.sleep"):
            out = agent.run_agent("q", client=fake)
        self.assertEqual(out, "recovered")
        self.assertEqual(len(fake.messages.calls), 2)

    def test_retryable_error_exhausts_retries(self):
        fake = FakeClient([FakeRateLimitError()] * 3)
        with mock.patch("time.sleep"):
            out = agent.run_agent("q", client=fake)
        self.assertIn("API error after retries", out)
        self.assertEqual(len(fake.messages.calls), 3)


class TestRepoMap(unittest.TestCase):

    def test_shows_tree_and_skips_hidden(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "a.txt"), "w").close()
            os.makedirs(os.path.join(d, "src"))
            open(os.path.join(d, "src", "main.py"), "w").close()
            os.makedirs(os.path.join(d, ".hidden"))
            open(os.path.join(d, ".hidden", "secret.txt"), "w").close()

            out = tools.repo_map(d)

        self.assertIn("a.txt", out)
        self.assertIn("main.py", out)
        self.assertNotIn("secret.txt", out)


class TestGitTools(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        repo = self.tmp.name

        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

        with open(os.path.join(repo, "a.txt"), "w") as f:
            f.write("hello\n")
        subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

        self._old_cwd = os.getcwd()
        os.chdir(repo)
        self.addCleanup(os.chdir, self._old_cwd)

    def test_git_log(self):
        out = tools.git_log()
        self.assertIn("initial", out)

    def test_git_blame(self):
        out = tools.git_blame("a.txt")
        self.assertIn("hello", out)

    def test_git_diff(self):
        with open("a.txt", "w") as f:
            f.write("changed\n")
        out = tools.git_diff()
        self.assertIn("changed", out)

    def test_git_error_not_a_repo(self):
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                out = tools.git_log()
            finally:
                os.chdir(self._old_cwd)
        self.assertIn("git error", out)
