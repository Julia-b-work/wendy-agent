# Changelog

All notable changes to this project are recorded here. Versions follow
[Semantic Versioning](https://semver.org/): MAJOR.MINOR.PATCH.

## [0.1.2] - 2026-09-23

### Added

- **Tool crash safety** — a `run_tool()` dispatcher wraps every tool call in a
  safety net, so a crashing tool returns an error message instead of killing
  the run.
- **Truncation** — tool results are capped at `MAX_RESULT_CHARS` (8000) with a
  visible `...[truncated]` marker, so large files or listings can't blow up the
  context window.
- **Noise filtering** — `list_files` and `search` skip binary files (via a
  null-byte check) and ignored directories (`node_modules`, `.git`, `.venv`,
  etc.).
- **`requirements.txt`** — pinned minimum dependencies.

### Changed

- Test suite expanded to 22 tests covering the dispatcher, truncation, and
  noise filtering.

## [0.1.1] - 2026-09-23

### Added

- **Step limit with human-in-the-loop** — the loop now stops and asks the user
  to continue after `STEP_LIMIT` (10) tool-using turns, and prompts Claude to
  justify itself on the next turn before continuing.
- **Test suite** — 12 unit tests in `test_agent.py` covering the tools and the
  loop, using `unittest` with a fake client (no API calls).

### Changed

- **`search` accepts a `root` argument** — it searches a given directory
  instead of always `"."`, so it's testable like `list_files`.
- **Testable `run_agent`** — the client is now created lazily (`get_client()`),
  and `run_agent` accepts optional `client` and `max_steps` arguments so tests
  can inject a fake client.

## [0.1.0] - 2026-09-23

Initial release: a codebase Q&A agent built on Claude's tool-use API.

### Added

- **Tool-use loop** — `run_agent()` keeps a `messages` list as conversation
  memory, calls the Claude API with the available tools, and executes any tool
  Claude requests until it answers in plain text.
- **Three tools** — `list_files` (walk a directory, skipping hidden dirs),
  `read_file` (read a file, with a `FileNotFoundError` fallback), and `search`
  (find a string across the project, returning `path:line: content` matches).
- **CLI with step visibility** — the question is read from `sys.argv[1]`, and
  every loop step and tool call is printed as it happens.
