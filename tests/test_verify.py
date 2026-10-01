"""Tests for verify: decompose, locate, verifiers, roll_up, verify_claim.

Run with: python -m unittest discover -s tests
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from wendy.verify import (
    Located, Finding, Verdict,
    SUPPORTED, CONTRADICTED, NOT_FOUND, INCONCLUSIVE,
    decompose, locate, check, roll_up, verify_claim, _locate_by_meaning,
    llm_judge, format_verdict,
    _verify_bounded_loop, _verify_retries, _verify_handles_error,
    _verify_writes_file, _verify_calls_function, _verify_uses_named_constant,
    _verify_imports_module, _verify_constant_value,
)


def make_located(lines, module_lines=None, start_line=10, name="foo"):
    return Located(name=name, file="foo.py", start_line=start_line,
                   lines=lines, module_lines=module_lines if module_lines is not None else lines)


def finding(verdict, check="x"):
    return Finding(check=check, verdict=verdict, subject="s", file="f.py", lines=[], note="")


class TestDecompose(unittest.TestCase):

    def test_subject_and_signals(self):
        d = decompose("run_agent has a step limit")
        self.assertEqual(d["subject"], "run_agent")
        self.assertIn("bounded_loop", d["signals"])

    def test_no_subject(self):
        d = decompose("the search is fast")
        self.assertIsNone(d["subject"])
        self.assertEqual(d["signals"], [])

    def test_dedup(self):
        d = decompose("run_agent retries and retry")
        self.assertEqual(d["signals"], ["retries"])


class TestRollUp(unittest.TestCase):

    def test_supported(self):
        self.assertEqual(roll_up([finding(SUPPORTED), finding(NOT_FOUND)]), (SUPPORTED, 0.5))

    def test_contradicted_wins(self):
        self.assertEqual(roll_up([finding(SUPPORTED), finding(CONTRADICTED)]), (CONTRADICTED, 0.5))

    def test_inconclusive(self):
        self.assertEqual(roll_up([]), (INCONCLUSIVE, 0.0))
        self.assertEqual(roll_up([finding(NOT_FOUND)]), (INCONCLUSIVE, 0.0))


class TestBoundedLoop(unittest.TestCase):

    def test_range_for_loop(self):
        f = _verify_bounded_loop(make_located(["def foo():", "    for i in range(10):", "        pass"]), "")
        self.assertEqual(f.verdict, SUPPORTED)
        self.assertEqual(f.lines, [11])

    def test_collection_for_loop_is_not_step_limit(self):
        f = _verify_bounded_loop(make_located(["def foo():", "    for x in items:", "        pass"]), "")
        self.assertEqual(f.verdict, CONTRADICTED)

    def test_while_comparison(self):
        f = _verify_bounded_loop(make_located(["def foo():", "    while x < 10:", "        pass"]), "")
        self.assertEqual(f.verdict, SUPPORTED)

    def test_while_true_is_unbounded(self):
        f = _verify_bounded_loop(make_located(["def foo():", "    while True:", "        pass"]), "")
        self.assertEqual(f.verdict, CONTRADICTED)

    def test_conditional_bound_is_not_found(self):
        loc = make_located(["def foo():", "    while max_steps is None or step < max_steps:", "        pass"])
        f = _verify_bounded_loop(loc, "")
        self.assertEqual(f.verdict, NOT_FOUND)


class TestRetries(unittest.TestCase):

    def test_sleep_signal(self):
        f = _verify_retries(make_located(["def foo():", "    time.sleep(1)", "    return 0"]), "")
        self.assertEqual(f.verdict, SUPPORTED)

    def test_constant_name_is_not_retry(self):
        # "retry" inside a constant name (RETRYABLE_ERRORS) must not count.
        f = _verify_retries(make_located(["def foo():", "    except RETRYABLE_ERRORS:", "        pass"]), "")
        self.assertEqual(f.verdict, CONTRADICTED)


class TestHandlesError(unittest.TestCase):

    def test_try_except(self):
        f = _verify_handles_error(make_located(["def foo():", "    try:", "        x()", "    except Exception:", "        pass"]), "")
        self.assertEqual(f.verdict, SUPPORTED)

    def test_no_handling(self):
        f = _verify_handles_error(make_located(["def foo():", "    return 0"]), "")
        self.assertEqual(f.verdict, CONTRADICTED)


class TestWritesFile(unittest.TestCase):

    def test_open_write(self):
        f = _verify_writes_file(make_located(["def foo():", "    with open('x.txt', 'w') as f:", "        f.write('hi')"]), "")
        self.assertEqual(f.verdict, SUPPORTED)

    def test_no_write(self):
        f = _verify_writes_file(make_located(["def foo():", "    return 0"]), "")
        self.assertEqual(f.verdict, CONTRADICTED)


class TestCallsFunction(unittest.TestCase):

    def test_supported(self):
        f = _verify_calls_function(make_located(["def foo():", "    bar()"]), "foo calls bar()")
        self.assertEqual(f.verdict, SUPPORTED)

    def test_contradicted(self):
        f = _verify_calls_function(make_located(["def foo():", "    return 0"]), "foo calls bar()")
        self.assertEqual(f.verdict, CONTRADICTED)

    def test_stopword(self):
        f = _verify_calls_function(make_located(["def foo():", "    return 0"]), "foo calls the thing")
        self.assertEqual(f.verdict, NOT_FOUND)


class TestUsesNamedConstant(unittest.TestCase):

    def test_supported(self):
        f = _verify_uses_named_constant(make_located(["def foo():", "    return STEP_LIMIT"]), "foo uses STEP_LIMIT")
        self.assertEqual(f.verdict, SUPPORTED)

    def test_contradicted(self):
        f = _verify_uses_named_constant(make_located(["def foo():", "    return 0"]), "foo uses STEP_LIMIT")
        self.assertEqual(f.verdict, CONTRADICTED)


class TestImportsModule(unittest.TestCase):

    def test_supported(self):
        loc = make_located(["def foo():", "    return 0"],
                           module_lines=["import numpy as np", "def foo():", "    return 0"])
        f = _verify_imports_module(loc, "foo uses numpy")
        self.assertEqual(f.verdict, SUPPORTED)
        self.assertEqual(f.lines, [1])

    def test_contradicted(self):
        loc = make_located(["def foo():", "    return 0"],
                           module_lines=["import os", "def foo():", "    return 0"])
        f = _verify_imports_module(loc, "foo uses numpy")
        self.assertEqual(f.verdict, CONTRADICTED)

    def test_constant_is_not_a_module(self):
        loc = make_located(["def foo():", "    return STEP_LIMIT"],
                           module_lines=["STEP_LIMIT = 10", "def foo():", "    return STEP_LIMIT"])
        f = _verify_imports_module(loc, "foo uses STEP_LIMIT")
        self.assertEqual(f.verdict, NOT_FOUND)


class TestConstantValue(unittest.TestCase):

    def test_supported(self):
        loc = make_located(["def foo():", "    return 0"],
                           module_lines=["STEP_LIMIT = 10", "def foo():", "    return 0"])
        f = _verify_constant_value(loc, "foo limit of 10")
        self.assertEqual(f.verdict, SUPPORTED)
        self.assertEqual(f.lines, [1])

    def test_contradicted(self):
        loc = make_located(["def foo():", "    return 0"],
                           module_lines=["STEP_LIMIT = 3", "def foo():", "    return 0"])
        f = _verify_constant_value(loc, "foo limit of 10")
        self.assertEqual(f.verdict, CONTRADICTED)


class TestCheck(unittest.TestCase):

    def test_runs_only_selected_and_skips_unknown(self):
        loc = make_located(["def foo():", "    return 0"])
        findings = check(["bounded_loop", "nonexistent"], loc, "")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].check, "bounded_loop")


class TestLocate(unittest.TestCase):

    def test_finds_definition(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "mod.py"), "w") as f:
                f.write("def real_thing():\n    return 1\n")
            loc = locate("real_thing", root=d)
        self.assertIsNotNone(loc)
        self.assertEqual(loc.name, "real_thing")
        self.assertEqual(loc.start_line, 1)

    def test_prefers_longest_definition(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.py"), "w") as f:
                f.write("def foo():\n    return 1\n")
            with open(os.path.join(d, "b.py"), "w") as f:
                f.write("def foo():\n    a = 1\n    b = 2\n    c = 3\n    return a\n")
            loc = locate("foo", root=d)
        self.assertTrue(loc.file.endswith("b.py"))

    def test_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "mod.py"), "w").close()
            self.assertIsNone(locate("nope", root=d))


class TestVerifyClaim(unittest.TestCase):

    def test_happy_path(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "mod.py"), "w") as f:
                f.write("STEP_LIMIT = 10\n\ndef run_loop():\n    step = 0\n    while step < STEP_LIMIT:\n        step += 1\n")
            v = verify_claim("run_loop has a step limit", root=d)
        self.assertEqual(v.subject, "run_loop")
        self.assertEqual(v.summary, SUPPORTED)
        self.assertTrue(any(f.check == "bounded_loop" and f.verdict == SUPPORTED for f in v.findings))

    def test_no_subject_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "mod.py"), "w").close()
            with mock.patch("wendy.verify.semantic_search", return_value="(no code to search)"):
                v = verify_claim("the search is fast", root=d)
        self.assertEqual(v.summary, INCONCLUSIVE)
        self.assertIsNone(v.subject)


class TestLocateByMeaning(unittest.TestCase):

    def test_parses_name_and_relocates(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "mod.py"), "w") as f:
                f.write("def run_loop():\n    return 1\n")
            with mock.patch("wendy.verify.semantic_search", return_value="0.900  mod.py:1: run_loop"):
                loc = _locate_by_meaning("some claim", root=d)
        self.assertIsNotNone(loc)
        self.assertEqual(loc.name, "run_loop")


class TestConstantAssertion(unittest.TestCase):

    def test_supported(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "mod.py"), "w") as f:
                f.write("STEP_LIMIT = 10\n")
            v = verify_claim("STEP_LIMIT is 10", root=d)
        self.assertEqual(v.summary, SUPPORTED)
        self.assertEqual(v.subject, "STEP_LIMIT")
        self.assertEqual(v.findings[0].lines, [1])

    def test_contradicted(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "mod.py"), "w") as f:
                f.write("STEP_LIMIT = 20\n")
            v = verify_claim("STEP_LIMIT is 10", root=d)
        self.assertEqual(v.summary, CONTRADICTED)

    def test_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "mod.py"), "w").close()
            v = verify_claim("FOO is 5", root=d)
        self.assertEqual(v.summary, INCONCLUSIVE)
        self.assertEqual(v.subject, "FOO")

    def test_equals_variants(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "mod.py"), "w") as f:
                f.write("MAX_RETRIES = 3\n")
            self.assertEqual(verify_claim("MAX_RETRIES = 3", root=d).summary, SUPPORTED)
            self.assertEqual(verify_claim("MAX_RETRIES equals 3", root=d).summary, SUPPORTED)


class TestFormatVerdict(unittest.TestCase):

    def test_includes_line_numbers(self):
        v = Verdict(claim="x", subject="foo", findings=[
            Finding(check="bounded_loop", verdict=SUPPORTED, subject="foo",
                    file="f.py", lines=[10, 20], note="found loops")
        ])
        out = format_verdict(v)
        self.assertIn("lines: 10, 20", out)

    def test_omits_lines_when_empty(self):
        v = Verdict(claim="x", subject="foo", findings=[
            Finding(check="constant_value", verdict=NOT_FOUND, subject="foo",
                    file="f.py", lines=[], note="no numeric value")
        ])
        out = format_verdict(v)
        self.assertNotIn("lines:", out)


class _FakeMessages:
    def __init__(self, text):
        self.text = text

    def create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


class _FakeClient:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


class TestLLMJudge(unittest.TestCase):

    def test_supported(self):
        loc = make_located(["def foo():", "    while x < 10:", "        pass"])
        client = _FakeClient('{"verdict": "supported", "lines": [11], "explanation": "bounded loop"}')
        f = llm_judge("foo has a step limit", loc, client=client)
        self.assertEqual(f.check, "llm_judge")
        self.assertEqual(f.verdict, SUPPORTED)
        self.assertEqual(f.lines, [11])

    def test_contradicted(self):
        loc = make_located(["def foo():", "    return 1"])
        client = _FakeClient('{"verdict": "contradicted", "lines": [], "explanation": "no loop"}')
        f = llm_judge("foo has a step limit", loc, client=client)
        self.assertEqual(f.verdict, CONTRADICTED)

    def test_string_line_numbers_and_inconclusive(self):
        loc = make_located(["def foo():", "    return 1"])
        client = _FakeClient('{"verdict": "inconclusive", "lines": ["2"], "explanation": "unclear"}')
        f = llm_judge("foo does something", loc, client=client)
        self.assertEqual(f.verdict, NOT_FOUND)
        self.assertEqual(f.lines, [2])

    def test_malformed_json_returns_none(self):
        loc = make_located(["def foo():", "    return 1"])
        client = _FakeClient("not json at all")
        self.assertIsNone(llm_judge("foo", loc, client=client))


class TestVerifyClaimLLM(unittest.TestCase):

    def test_use_llm_resolves_inconclusive(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "mod.py"), "w") as f:
                f.write("def run_loop():\n    step = 0\n    while step < 10:\n        step += 1\n")
            client = _FakeClient('{"verdict": "supported", "lines": [3], "explanation": "bounded loop"}')
            v = verify_claim("run_loop is efficient", root=d, use_llm=True, client=client)
        self.assertEqual(v.summary, SUPPORTED)
        self.assertTrue(any(f.check == "llm_judge" for f in v.findings))

    def test_no_llm_stays_inconclusive(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "mod.py"), "w") as f:
                f.write("def run_loop():\n    step = 0\n    while step < 10:\n        step += 1\n")
            v = verify_claim("run_loop is efficient", root=d, use_llm=False)
        self.assertEqual(v.summary, INCONCLUSIVE)
        self.assertFalse(any(f.check == "llm_judge" for f in v.findings))


if __name__ == "__main__":
    unittest.main()
