# TailorTeX

**Tailor your LaTeX resume to every job description, without breaking your template or inventing anything.**

Paste a job description and get back *your own* `.tex` file with the job's keywords worked into the right places, a compiled PDF, and an honest report of what changed and why. Every new skill, tool and number is checked in code against your real experience before it reaches your resume.

Built for **HackDevengers 2.0** (19–20 September 2026).

---

## The problem

Recruiters search an ATS by keyword, and job titles and skills have to match the posting. So every application needs a tailored resume. LaTeX users have two bad options today:

- **Edit by hand for every job.** Slow, and easy to miss the keywords that matter.
- **Paste the resume into an AI chat.** It regenerates the whole file: the template breaks, it often doesn't compile, and it happily invents skills ("Kubernetes") and metrics ("improved performance by 40%") the candidate can't defend in an interview.

## What TailorTeX does

- **LaTeX in, LaTeX out.** Your template stays byte-for-byte intact. Only bullets, the summary and skills lines change, and every change is a precise edit at a known position.
- **Always compiles.** The model never writes LaTeX. It returns edit operations in plain text, and TailorTeX writes the LaTeX itself with an escaper that can't produce broken markup.
- **Never invents.** Validators check every edit: a bullet can only mention tools and numbers from its own job entry or from evidence you provided. Rejected edits go back to the model with the reason.
- **Honest ATS checks.** Keyword coverage and parse health are measured on the text extracted from the compiled PDF, the way an ATS reads it, not on a made-up score.
- **Evidence you control.** Import your public GitHub repos, list skills you can defend, or add facts. Job keywords without evidence are shown to you, never slipped in.
- **Review everything.** Word-level diff for every change with the reason and evidence behind it. Keep, revert or edit each one, then rebuild the PDF.
- **Bring your own key** from Google Gemini, Groq, OpenAI, Anthropic, OpenRouter, Mistral or DeepSeek. The provider is detected from the key; models are listed live.
- **Learns from use.** A Thompson-sampling bandit learns which tailoring strategy works for which kind of job from what people keep and revert, and it remembers each user's writing style.

## Quick start

Needs **Python 3.11+**, **Node 20+**, and **TeX Live** for PDF compiling (TinyTeX is enough: `curl -sL https://yihui.org/tinytex/install-bin-unix.sh | sh`; without it you still get the tailored `.tex`).

```sh
git clone https://github.com/shreytiwari09/TailorTex.git
cd TailorTex
make setup   # Python venv + backend deps, frontend deps, creates .env
make dev     # backend on :8000, frontend on http://localhost:5173
```

Open http://localhost:5173, click **Try it with a sample resume**, paste a model key in step 1 and press **Tailor my resume**. Gemini and Groq have free tiers. To give everyone who uses your server a default key, set `TAILORTEX_API_KEY` in `.env`.

Other commands:

| Command | What it does |
|---|---|
| `make test` | 72 backend tests (including real LaTeX compiles), frontend type-check and lint |
| `make start` | Build the frontend and serve the whole app from the backend on :8000 |
| API docs | http://localhost:8000/docs (interactive, from FastAPI) |

## How it works

```
 your .tex ──► parse ──► sections, entries, bullets, skills lines (each with an ID and exact span)
                              │                         education and "other" sections are locked
 job description ──► analyze (LLM) ──► title, must-have and nice-to-have keywords
                              │
                     gap analysis ──► on your resume / backed by evidence / no evidence
                              │
      ┌─────────── for each strategy the bandit picks (1 or 3, in parallel) ───────────┐
      │  plan (LLM): edit operations in plain text: rewrite, add, drop, reorder         │
      │  validate (code): no unsupported skill, name or number; locked; length; stuffing│
      │  retry: rejected edits go back to the model with the reason (up to 2 times)     │
      │  apply: splice edits into their spans; the rest of the file is untouched        │
      │  compile: TeX Live with the template's own engine, safety checks, timeout       │
      │  fit: over the page limit? drop the least relevant bullet and recompile         │
      │  score: keyword coverage and parse health on the PDF text ──► reward            │
      └──────────────────────────────── keep the best ─────────────────────────────────┘
```

### The guardrails, enforced in code

| Rule | Example it blocks |
|---|---|
| A bullet only names tools, skills and proper nouns from **its own entry** or **evidence it cites** | Moving "Redis" from your Finch Payments job into your internship bullet |
| Numbers must come from **the same bullet**, its heading, or cited evidence | Attaching "78%" from your testing bullet to a latency claim |
| Evidence scope: confirmed skills only go into skills lines and the summary; GitHub repos only into projects | Claiming your side-project's Kubernetes at an employer |
| Locked sections can't change; entries keep at least one bullet | "Add Harvard to education" hidden in a job posting |
| Bullets stay within the template's length budget | Overflowing lines that push the resume to two pages |
| A job keyword appears at most 3 times across bullets | Keyword stuffing that semantic screeners penalize |
| Model text containing LaTeX is rejected; all text goes through the escaper | `\textbf{}`, stray `&`, `%` or `$` breaking the compile |

Keyword matching understands tech names: K8s = Kubernetes, Postgres = PostgreSQL, `C` doesn't match `C++`, `Java` doesn't match `JavaScript`, and "spark interest" isn't Spark.

### ATS checks on the compiled PDF

Selectable text · no ligature glyphs ("ﬁnancial" isn't "financial") · no icon-font garbage · email and phone readable near the top · standard section headings · single-column reading order. Source lint catches missing `\pdfgentounicode`, FontAwesome icons and two-column layouts, with a one-click fix where possible.

### Supported templates

Jake's Resume and its many variants, Awesome-CV, moderncv, and generic `article` resumes that use `\section` and `itemize`. Custom bullet and heading macros are recognized from their `\newcommand` definitions. The default template in `backend/tailortex/templates/jake/` is an ATS-safe version of Jake's Resume (MIT License).

## Layout

```
backend/
  tailortex/
    latex/      scanner with exact offsets, LaTeX <-> plain text, resume parser, span editor
    ats/        keyword matching and synonyms, coverage, gap chips, title match, parse health, lint
    validate/   the no-invention rules
    compile/    TeX Live runner: engine detection, safety checks, page count, PDF text, page fill
    llm/        bring-your-own-key client for 7 providers, prompts, output schemas
    learn/      strategy arms, Thompson-sampling bandit, feedback reward, style memory
    pipeline/   the tailoring run and the rebuild after review
    reward/     the reward function (layer 0 of the learning loop)
    api/        FastAPI app (REST + server-sent events) and GitHub evidence import
  tests/        pytest: 72 tests, including real LaTeX compiles and a mock-model pipeline run
frontend/       React + Vite + TypeScript single-page app
docs/           product plan and development log
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/config` | Providers, whether LaTeX is installed, whether the server has a key |
| `POST /api/models` | Check a key and list the provider's chat models, with a recommended default |
| `POST /api/parse` | What TailorTeX sees in a `.tex`: sections, entries, bullets, locks, lint |
| `POST /api/compile` | Compile a `.tex` safely; returns the PDF, pages and errors with line numbers |
| `POST /api/tailor` | The full run, streamed as server-sent events; the last event is the result |
| `POST /api/rebuild` | Re-apply the changes you kept or edited, recompile and re-measure |
| `POST /api/evidence/github` | List a user's public repos, or import chosen ones as evidence |
| `POST /api/feedback` | Keep / revert / edit decisions: rewards the bandit and updates style memory |

## Security and privacy

- **Keys** are sent with each request, used in memory for that request, and never stored or logged. "Remember on this device" keeps a key in your browser only.
- **Your resume and job description** go only to the model provider you choose.
- **Compiling LaTeX runs code**, so documents that write files, run shell commands, read files outside the project or run Lua are refused before TeX starts. TeX runs with shell escape off, paranoid file access, a fresh temp folder and a timeout.
- **Job descriptions and READMEs are untrusted data.** A prompt injection can only produce edit operations, and the validators block anything unsupported.

## Roadmap

- Docker image and a public deployment
- Accounts and per-job history, PDF/DOCX import into the default template
- Chrome extension to capture job descriptions, application tracker with callbacks as a learning signal
- A small open model fine-tuned on accepted edits (SFT, then preference training), so tailoring works without a key

## About this project

The product plan and research in [docs/PLAN.md](docs/PLAN.md) were written before the hackathon. All code in this repository was written during the HackDevengers 2.0 window; the commit history shows how it was built, and [docs/DEVLOG.md](docs/DEVLOG.md) records each decision and why it was made.
