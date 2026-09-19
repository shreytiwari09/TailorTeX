# TailorTeX

Tailor your LaTeX resume to every job description, without breaking your template or inventing anything.

- **LaTeX in, LaTeX out.** Your own template stays byte-for-byte intact; only bullets, summary and skills change.
- **Compiles every time.** The model returns edit operations in plain text, and TailorTeX writes the LaTeX itself.
- **Never invents.** Validators check every new skill, tool and number against your own evidence.
- **Honest ATS checks** on the text extracted from the compiled PDF.
- **Bring your own key** from OpenAI, Anthropic, Google, Groq, Mistral, DeepSeek or OpenRouter.

## Docs

- [docs/PLAN.md](docs/PLAN.md): the product and technical plan
- [docs/DEVLOG.md](docs/DEVLOG.md): what has been built, every decision and why, and where it lives

## Layout

```
backend/    FastAPI backend: the tailoring engine (LaTeX parsing, validators, ATS checks, LLM layer,
            learning loop) plus the REST API. Python, see backend/README.md.
frontend/   React + Vite frontend that talks to the backend over REST.
python/     Evaluation and (later) training tools, separate from the backend package.
docs/       Plan and development log.
```

## Run it locally

Needs Python 3.11+, Node 20+, and TeX Live for PDF compiling (TinyTeX is enough: `curl -sL https://yihui.org/tinytex/install-bin-unix.sh | sh`).

```sh
make setup   # Python venv + backend deps, frontend deps, creates .env from .env.example
make dev     # backend on :8000, frontend on http://localhost:5173
```

Open http://localhost:5173 and click **Try it with a sample resume**. You'll need a model key: paste one in the page (Gemini and Groq have free tiers), or put it in `.env` as `TAILORTEX_API_KEY` so the server uses it for everyone.

Other commands: `make test` (backend tests, frontend type-check and lint) and `make start` (build the frontend and serve the whole app from the backend on :8000). The API docs are at http://localhost:8000/docs.

## What you get from a run

- **Live progress:** each stage streams in as it happens, including edits the guardrails blocked and why.
- **Before → after scores:** must-have and nice-to-have keyword coverage, job-title match, and ATS parse health, measured on the text extracted from the compiled PDF.
- **Every change, reviewable:** a word-level diff for each rewritten, added, removed or reordered bullet, with the model's reason and the evidence it cites. Revert any change and rebuild the PDF.
- **Guardrail log:** every refused edit (invented skill, invented number, keyword stuffing, locked section) and every job keyword left out for lack of evidence.
- **Evidence import:** pull your public GitHub repos in as evidence, list skills you can defend, or add free-text facts.
- **Output:** download the `.tex` and PDF (named `First_Last_Company_Role.pdf`), copy the LaTeX, or open it straight in Overleaf.
