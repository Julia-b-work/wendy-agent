"""Claim verification for Wendy.

verify_claim never asserts a claim is "true". It locates the code a claim is
about, runs small deterministic checks against the source, and reports exactly
which lines support or contradict each check.

Scope: verifiers inspect the located function's *own* source, not the bodies of
functions it calls. "X caches" is only supported when X itself writes a file; a
helper it delegates to is out of scope (that would need call-graph analysis).
The notes on each finding try to say "direct"/"in this function" so this
boundary is visible rather than hidden.
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from wendy.tools import find_definition, _symbol_chunks, read_file, semantic_search

SUPPORTED = "supported"
CONTRADICTED = "contradicted"
NOT_FOUND = "not_found"

INCONCLUSIVE = "inconclusive"

# English words a target extractor might mistake for a real name.
_STOPWORDS = {"the", "a", "an", "this", "that", "it", "and", "or", "of", "to"}


@dataclass
class Finding:
    """One check's result against a located piece of code"""
    check: str
    verdict: str
    subject: str
    file: str
    lines: list[int]
    note: str


@dataclass
class Verdict:
    """the full result of verifying one claim"""
    claim: str
    subject: Optional[str]
    findings: list[Finding] = field(default_factory=list)
    summary: str = INCONCLUSIVE
    confidence: float = 0.0


SIGNAL_KEYWORDS = {
    "step limit": ["bounded_loop", "constant_value"],
    "max steps": ["bounded_loop"],
    "retry": ["retries"],
    "retries": ["retries"],
    "backoff": ["retries"],
    "cache": ["writes_file"],
    "caches": ["writes_file"],
    "index": ["writes_file"],
    "write": ["writes_file"],
    "writes": ["writes_file"],
    "call": ["calls_function"],
    "calls": ["calls_function"],
    "error": ["handles_error"],
    "errors": ["handles_error"],
    "exception": ["handles_error"],
    "import": ["imports_module"],
    "imports": ["imports_module"],
    "uses": ["uses_named_constant", "imports_module"],
}

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _looks_like_code_to_me(word):
    """True if `word` is a plausible function/class name, not prose."""
    if len(word) < 2 or _IDENTIFIER.fullmatch(word) is None:
        return False
    return "_" in word or any(c.isupper() for c in word)


def _extract_subject(claim):
    """Return the first code-like identifier in the claim, or None."""
    for token in claim.split():
        word = token.strip(".,;:!?()[]\"'")
        if _looks_like_code_to_me(word):
            return word
    return None


def decompose(claim):
    """Turn a claim into a subject candidate and the verifiers its wording implies."""
    lowered = claim.lower()
    signals = []
    for keyword, verifiers in SIGNAL_KEYWORDS.items():
        if re.search(r"\b" + re.escape(keyword) + r"\b", lowered):
            signals.extend(verifiers)

    seen = set()
    unique = []
    for v in signals:
        if v not in seen:
            seen.add(v)
            unique.append(v)

    return {"subject": _extract_subject(claim), "signals": unique}


@dataclass
class Located:
    """A definition locate() found: its name, file, start line, and source."""
    name: str
    file: str
    start_line: int          # 1-based line the definition starts on
    lines: list[str]         # the definition's source, split into lines
    module_lines: list[str]  # the whole file's lines (for module-level checks)


def locate(subject, root="."):
    """Find where `subject` is defined and return its source, or None.

    When several files define the same name (e.g. a function and its thin MCP
    wrapper), it keeps the longest definition: a real implementation is almost
    always longer than the one-line passthrough that delegates to it.
    """
    result = find_definition(subject, root)
    if result.startswith("No definition found"):
        return None
    candidates = []
    for line in result.splitlines():
        path = line.split(":")[0]
        for name, start_line, text in _symbol_chunks(path):
            if name == subject:
                candidates.append((name, path, start_line, text.splitlines()))
    if not candidates:
        return None
    name, path, start_line, lines = max(candidates, key=lambda c: len(c[3]))
    return Located(
        name=name,
        file=path,
        start_line=start_line,
        lines=lines,
        module_lines=read_file(path).splitlines(),
    )


def _finding(check, located, verdict, lines, note):
    """Build a Finding with the shared fields filled in."""
    return Finding(
        check=check,
        verdict=verdict,
        subject=located.name,
        file=located.file,
        lines=lines,
        note=note,
    )


def _scan(lines, base, predicate):
    """Absolute line numbers of `lines` where `predicate(line)` is True.

    `base` is the absolute line of `lines[0]`: start_line for a function's own
    source, 1 for a whole file.
    """
    return [base + i for i, line in enumerate(lines) if predicate(line)]


def _supported_or_contradicted(check, located, lines, what):
    """A presence check: the feature is either there (supported) or not."""
    if lines:
        return _finding(check, located, SUPPORTED, lines,
                        f"found {what} on {len(lines)} line(s)")
    return _finding(check, located, CONTRADICTED, [], f"no {what} found")


# --- Verifiers --------------------------------------------------------------


def _verify_bounded_loop(located, claim):
    """Detect a loop whose iteration count is capped by a numeric step limit.

    Counts `for ... in range(...)` and a hard-bounded `while <comparison>`.
    Ignores `for x in collection` (bounded by data, not a step limit) and
    `while True`. A `while ... is None ...` bound is conditional -> NOT_FOUND.
    """
    def counter_for(line):
        return line.strip().startswith("for ") and " in range(" in line

    def hard_while(line):
        s = line.strip()
        return (s.startswith("while ")
                and any(op in s for op in ("<", ">", "<=", ">=", "!="))
                and " is None" not in s)

    def conditional_while(line):
        s = line.strip()
        return (s.startswith("while ")
                and any(op in s for op in ("<", ">", "<=", ">=", "!="))
                and " is None" in s)

    counter = _scan(located.lines, located.start_line, counter_for)
    hard = _scan(located.lines, located.start_line, hard_while)
    if counter or hard:
        total = counter + hard
        return _finding("bounded_loop", located, SUPPORTED, total,
                        f"found {len(total)} step-limited loop(s)")
    if _scan(located.lines, located.start_line, conditional_while):
        return _finding("bounded_loop", located, NOT_FOUND, [],
                        "no hard step limit found — loop bound is conditional (`is None` branch)")
    return _finding("bounded_loop", located, CONTRADICTED, [],
                    "no step-limited loop found")


def _verify_retries(located, claim):
    # "sleep(" / "backoff" are behavioral signals; the bare word "retry" would
    # also match constant names like RETRYABLE_ERRORS, so it is not used.
    lines = _scan(located.lines, located.start_line,
                  lambda l: "sleep(" in l.lower() or "backoff" in l.lower())
    return _supported_or_contradicted("retries", located, lines, "retry/backoff")


def _verify_handles_error(located, claim):
    def handles(line):
        s = line.strip()
        return (s.startswith("try:") or s.startswith("except")
                or s == "raise" or s.startswith("raise "))
    lines = _scan(located.lines, located.start_line, handles)
    return _supported_or_contradicted("handles_error", located, lines, "error handling")


def _verify_writes_file(located, claim):
    write_sigs = (".write(", ".save(", "np.save", "json.dump", ".to_csv")
    write_modes = ('"w"', "'w'", '"a"', "'a'", '"wb"', '"ab"')

    def writes(line):
        low = line.lower()
        return any(sig in low for sig in write_sigs) or (
            "open(" in low and any(m in low for m in write_modes)
        )

    lines = _scan(located.lines, located.start_line, writes)
    return _supported_or_contradicted("writes_file", located, lines, "direct file-writing")


def _verify_calls_function(located, claim):
    m = re.search(r"\bcalls?\s+([A-Za-z_][A-Za-z0-9_]*)", claim, re.IGNORECASE)
    if m is None:
        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", claim)
    if m is None or m.group(1).lower() in _STOPWORDS:
        return _finding("calls_function", located, NOT_FOUND, [],
                        "could not tell which function is claimed")
    target = m.group(1)
    lines = _scan(located.lines, located.start_line, lambda l: target + "(" in l)
    if lines:
        return _finding("calls_function", located, SUPPORTED, lines,
                        f"calls {target}() on {len(lines)} line(s)")
    return _finding("calls_function", located, CONTRADICTED, [],
                    f"does not appear to call {target}()")


def _verify_uses_named_constant(located, claim):
    m = re.search(r"\b([A-Z][A-Z0-9_]*)\b", claim)
    if m is None:
        return _finding("uses_named_constant", located, NOT_FOUND, [],
                        "no ALL_CAPS constant named in the claim")
    target = m.group(1)
    lines = _scan(located.lines, located.start_line, lambda l: target in l)
    if lines:
        return _finding("uses_named_constant", located, SUPPORTED, lines,
                        f"uses {target} on {len(lines)} line(s)")
    return _finding("uses_named_constant", located, CONTRADICTED, [],
                    f"does not appear to use {target}")


def _verify_imports_module(located, claim):
    m = re.search(r"\b(?:imports?|uses)\s+([A-Za-z0-9_.-]+)", claim, re.IGNORECASE)
    if m is None:
        return _finding("imports_module", located, NOT_FOUND, [],
                        "no module named after import/uses in the claim")
    target = m.group(1).replace("-", "_").strip(".,;:!?")
    if target.lower() in _STOPWORDS:
        return _finding("imports_module", located, NOT_FOUND, [],
                        "could not tell which module is claimed")
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", target):
        return _finding("imports_module", located, NOT_FOUND, [],
                        f"{target} looks like a constant, not a module")

    def imports(line):
        s = line.strip()
        return (s.startswith("import ") or s.startswith("from ")) and target in s

    lines = _scan(located.module_lines, 1, imports)
    if lines:
        return _finding("imports_module", located, SUPPORTED, lines,
                        f"imports {target} on {len(lines)} line(s)")
    return _finding("imports_module", located, CONTRADICTED, [],
                    f"does not appear to import {target}")


def _verify_constant_value(located, claim):
    m = re.search(r"\b(\d+)\b", claim)
    if m is None:
        return _finding("constant_value", located, NOT_FOUND, [],
                        "no numeric value named in the claim")
    value = m.group(1)
    lines = _scan(located.module_lines, 1,
                  lambda l: re.search(r"\b" + value + r"\b", l) is not None)
    if lines:
        return _finding("constant_value", located, SUPPORTED, lines,
                        f"value {value} appears on {len(lines)} line(s)")
    return _finding("constant_value", located, CONTRADICTED, [],
                    f"value {value} does not appear")


_VERIFIERS = {
    "bounded_loop": _verify_bounded_loop,
    "retries": _verify_retries,
    "handles_error": _verify_handles_error,
    "writes_file": _verify_writes_file,
    "calls_function": _verify_calls_function,
    "uses_named_constant": _verify_uses_named_constant,
    "imports_module": _verify_imports_module,
    "constant_value": _verify_constant_value,
}


def check(signals, located, claim):
    """Run the selected verifiers against a located definition, return findings."""
    findings = []
    for signal in signals:
        verifier = _VERIFIERS.get(signal)
        if verifier is not None:
            findings.append(verifier(located, claim))
    return findings


def roll_up(findings):
    """Summarize findings into a (summary, confidence) pair.

    Contradiction wins: if any check is contradicted the whole claim is marked
    contradicted, because "X does A and B" is false if any part is false.
    Confidence is the fraction of checks that point the same way as the summary.
    """
    if not findings:
        return INCONCLUSIVE, 0.0
    supported = sum(1 for f in findings if f.verdict == SUPPORTED)
    contradicted = sum(1 for f in findings if f.verdict == CONTRADICTED)
    total = len(findings)
    if contradicted:
        return CONTRADICTED, contradicted / total
    if supported:
        return SUPPORTED, supported / total
    return INCONCLUSIVE, 0.0


def _locate_by_meaning(claim, root):
    """Fall back to semantic search when the claim names no obvious subject."""
    try:
        result = semantic_search(claim, root, top_k=1)
    except ImportError:
        return None  # sentence-transformers isn't installed; skip the fallback
    if not result or result == "(no code to search)":
        return None
    # semantic_search returns "score  path:line: name"; the name is the last field.
    name = result.splitlines()[0].rsplit(":", 1)[-1].strip()
    return locate(name, root)


# "STEP_LIMIT is 10", "MAX_RETRIES = 3", "X equals 7"
_CONSTANT_ASSERTION = re.compile(r"\b([A-Z][A-Z0-9_]*)\s+(?:is|equals?|==?)\s+(-?\d+)\b")


def _constant_assertion_finding(claim, root):
    """Verify a "NAME is VALUE" claim by finding NAME's assignment in the code.

    Returns a Finding, or None if the claim is not a constant assertion.
    Constants are project-scoped (not functions), so this walks the files
    directly instead of going through locate().
    """
    m = _CONSTANT_ASSERTION.search(claim)
    if m is None:
        return None
    name, value = m.group(1), m.group(2)
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(dirpath, f)
            try:
                with open(path) as fh:
                    for i, line in enumerate(fh, 1):
                        am = re.match(r"\s*" + re.escape(name) + r"\s*=\s*([^#\n]+)", line)
                        if am:
                            actual = am.group(1).strip()
                            if actual == value:
                                return Finding(
                                    check="constant_assertion", verdict=SUPPORTED,
                                    subject=name, file=path, lines=[i],
                                    note=f"{name} = {value}",
                                )
                            return Finding(
                                check="constant_assertion", verdict=CONTRADICTED,
                                subject=name, file=path, lines=[i],
                                note=f"{name} = {actual}, not {value}",
                            )
            except (OSError, UnicodeDecodeError):
                continue
    return Finding(
        check="constant_assertion", verdict=NOT_FOUND,
        subject=name, file="", lines=[],
        note=f"no definition of {name} found",
    )


_client = None


def _get_client():
    """Return the shared Anthropic client, creating it on first use."""
    global _client
    if _client is None:
        import anthropic
        from dotenv import load_dotenv
        load_dotenv()
        _client = anthropic.Anthropic()
    return _client


def _parse_judge(text):
    """Parse the LLM's JSON reply into (verdict, lines, explanation).

    Returns (None, [], "") when the reply can't be parsed into a known verdict.
    """
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None, [], ""
    raw = str(data.get("verdict", "")).lower()
    if raw == "supported":
        verdict = SUPPORTED
    elif raw == "contradicted":
        verdict = CONTRADICTED
    elif raw == "inconclusive":
        verdict = NOT_FOUND  # "inconclusive" -> not a decisive finding
    else:
        return None, [], ""
    lines = data.get("lines", [])
    if not isinstance(lines, list):
        lines = []
    cleaned = []
    for n in lines:
        try:
            cleaned.append(int(n))
        except (TypeError, ValueError):
            continue
    return verdict, cleaned, str(data.get("explanation", ""))


def llm_judge(claim, located, client=None):
    """Ask Claude whether the located source supports or contradicts the claim.

    Returns a Finding (check="llm_judge"), or None if the call or parse fails.
    The client is injectable so tests can use a fake and never hit the network.
    """
    if client is None:
        client = _get_client()

    numbered = "\n".join(
        f"{located.start_line + i}: {line}" for i, line in enumerate(located.lines)
    )
    prompt = (
        f"Claim: {claim}\n\n"
        f"Code (file {located.file}, definition {located.name}):\n{numbered}\n\n"
        "Does this code support the claim, contradict it, or neither? "
        'Reply with only JSON: {"verdict": "supported"|"contradicted"|"inconclusive", '
        '"lines": [<evidence line numbers>], "explanation": "<one sentence>"}'
    )
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=300,
            system="You verify whether a claim about code is supported by the code shown. Be literal and honest.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
    except Exception:
        return None

    verdict, lines, explanation = _parse_judge(text)
    if verdict is None:
        return None
    return Finding(
        check="llm_judge",
        verdict=verdict,
        subject=located.name,
        file=located.file,
        lines=lines,
        note=explanation,
    )


def verify_claim(claim, root=".", use_llm=False, client=None):
    """Run the full pipeline and return a Verdict.

    Constant assertions ("NAME is VALUE") are project-scoped and checked first.
    Otherwise: decompose -> locate -> check -> roll_up. The semantic fallback
    runs only when the claim names no subject. With use_llm=True, an
    inconclusive result is handed to Claude for a final judgment.
    """
    const = _constant_assertion_finding(claim, root)
    if const is not None:
        summary, confidence = roll_up([const])
        return Verdict(claim=claim, subject=const.subject, findings=[const],
                       summary=summary, confidence=confidence)

    d = decompose(claim)
    # Only fall back to semantic search when no subject name was extracted; a
    # name that isn't a function (e.g. a constant) should not become a random
    # semantically-near function.
    if d["subject"] is None:
        located = _locate_by_meaning(claim, root)
    else:
        located = locate(d["subject"], root)
    if located is None:
        return Verdict(claim=claim, subject=None, summary=INCONCLUSIVE, confidence=0.0)
    findings = check(d["signals"], located, claim)
    summary, confidence = roll_up(findings)
    if use_llm and summary == INCONCLUSIVE:
        judge = llm_judge(claim, located, client=client)
        if judge is not None:
            findings.append(judge)
            summary, confidence = roll_up(findings)
    return Verdict(claim=claim, subject=located.name, findings=findings,
                   summary=summary, confidence=confidence)


def format_verdict(v):
    """Render a Verdict as a readable string for CLI/MCP output."""
    head = f"{v.summary} (confidence {v.confidence:.2f})"
    if v.subject:
        head += f" — subject: {v.subject}"
    if not v.findings:
        return head + "\n  (no findings)"
    lines_out = []
    for f in v.findings:
        s = f"  [{f.verdict}] {f.check}: {f.note}"
        if f.lines:
            s += f"  (lines: {', '.join(str(n) for n in f.lines)})"
        lines_out.append(s)
    return head + "\n" + "\n".join(lines_out)
