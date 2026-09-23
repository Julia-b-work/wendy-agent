# Changelog

All notable changes to this project are recorded here. Versions follow
[Semantic Versioning](https://semver.org/): MAJOR.MINOR.PATCH.

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
