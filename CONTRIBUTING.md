# Contributing to AI Quick Chat

Thanks for your interest in improving the project!

## Getting started

```bash
git clone <your-fork-url>
cd AIQuickChat_glm5.3
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt -r requirements-dev.txt
```

## Workflow

1. Create a branch for your change: `git checkout -b feature/my-feature`.
2. Make your changes — keep the code style of the surrounding files.
3. Run the checks before committing:

   ```bash
   ruff check .
   pytest
   ```

4. Commit and open a Pull Request against `main`.

## Guidelines

- **Bug fixes** — describe the problem and how the fix works in the PR text.
- **New features** — open an issue first to discuss the approach.
- **UI changes** — must respect the existing theming system (`ui/widgets.py`,
  `THEMES` dict); never hardcode colors in windows.
- **Tests** — new logic in `local_websearch/`, `utils/` or `api/` should come
  with offline pytest tests (no network, no microphone in CI).
- **Secrets** — never commit API keys or tokens; the app stores them in the
  Windows Credential Manager at runtime.
- Keep `requirements.txt` (runtime) and `requirements-dev.txt` (dev/CI)
  separate.

## Commit style

Short imperative subject line (`Fix hotkey rollback on conflict`), details in
the body if non-trivial.
