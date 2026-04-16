# Agent Notes

- Use the `conda` `base` environment for commands in this repository by default.
- In fresh shells, load the user's zsh config before using `conda` commands: `source ~/.zshrc >/dev/null 2>&1 && ...`.
- Prefer running Python-related commands as `conda run -n base python ...` when interpreter choice matters.
- For long-running commands like `uvicorn` and long ingest runs, prefer `conda run --no-capture-output -n base ...` so logs and clickable local URLs show up immediately in the terminal.
- Interactive PDF selection is opt-in. By default, startup and ingest load all PDFs. Use `QUIZLET_SELECT_PDFS=1` for app startup or `python -m app.ingest ... --select-pdfs` when you explicitly want the selector.
- Prefer repository commands in the form `cd /Users/crystal/Documents/quizlet && source ~/.zshrc >/dev/null 2>&1 && ...` so `conda` is available in new sessions.
- If a tool behaves differently across Python versions, verify from the `base` environment first.
- When giving the user terminal commands, provide copy-paste-ready commands that include `cd /Users/crystal/Documents/quizlet && ...` so they can run them immediately.

## Repo Context

- This repo is a local FastAPI study app that ingests PDFs from `pdfs/` into `data/app.db` and `data/cache/`.
- The safest refresh flow after adding or replacing PDFs is `cd /Users/crystal/Documents/quizlet && source ~/.zshrc >/dev/null 2>&1 && conda run -n base python -m app.ingest pdfs --rebuild`.
- `python3` from the system shell may point to an incompatible interpreter or missing packages. Prefer `conda run -n base python ...` for ingest, tests, and app utilities.
- The user confirmed Miniconda is installed in zsh and `base` is the expected environment for this repo.
- As of 2026-04-04, `pdfs/[보안][과제] 약물구조카드 매일보기.pdf` has a dedicated parser: structure pages become multiple-choice questions, the underlined drug name on the paired answer page becomes the correct answer, and distractors come from other drug names. Current ingest result is 126 questions, 126 approved, 0 issues.
- When a newly added PDF looks under-parsed, check `/review`, inspect the generated cache JSON in `data/cache/`, and consider a PDF-specific parser adjustment or the NotebookLM workflow instead of assuming ingest failed.
