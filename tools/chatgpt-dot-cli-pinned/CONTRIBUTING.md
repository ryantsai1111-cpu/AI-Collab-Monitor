# Contributing to chatgpt-dot-cli

中文：歡迎用中文開 issue 或 merge request。

Thanks for helping. Bug reports, fixes, and docs changes are all welcome.

## Development setup

Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://gitlab.com/aa22396584/chatgpt-dot-cli.git
cd chatgpt-dot-cli
uv venv
uv pip install -e ".[mcp]"
.venv/bin/python -m unittest discover -s tests
```

Windows (PowerShell): `.venv\Scripts\python.exe -m unittest discover -s tests`.

## Ground rules

- Tests use fakes. They never call chatgpt.com and never read a real `~/.codex/auth.json`.
- Every HTTP call goes through the allow list in `chatgpt_dot/api.py`. Do not add an endpoint that pauses, deletes, connects, or changes settings; those are out of scope.
- Never commit tokens, cookies, credential files, account, chat, or bot ids, message text, emails, IP addresses, host names, or absolute local paths. Use fake values in tests and docs.
- Keep the English and 中文 sections of the README in sync.
- A bug fix comes with a test that fails without it.
- One topic per merge request. Describe how you tested it.

## CI

GitLab CI runs the tests on Linux for every push and on Windows for merge requests (manual), tags, and `main`. A fork uses GitLab.com shared runners by default. Set the `LINUX_RUNNER_TAG` and `WINDOWS_RUNNER_TAG` CI/CD variables to use other runners. There is no macOS CI; maintainers test macOS locally.

## Release process (maintainers)

1. Bump `version` in `pyproject.toml` and `__version__` in `chatgpt_dot/__init__.py`, then run `uv lock`.
2. Update the install pins (`@vX.Y.Z`) in both README sections.
3. Add a `## vX.Y.Z` heading (exactly that, no date) at the top of `CHANGELOG.md`. The release job copies that section into the GitLab Release.
4. Merge to `main` and wait for a green pipeline.
5. Tag `vX.Y.Z` on `main` and push the tag. The tag pipeline checks that the tag matches `pyproject.toml`, builds the wheel and sdist, and creates the GitLab Release.

Never move or delete a published tag. Fix forward with a new version.
