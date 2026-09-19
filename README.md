# TailorTeX

**Tailor your LaTeX resume to every job description, without breaking your template or inventing anything.**

Set up your profile once (your resume, your GitHub, portfolio, LinkedIn and notes), then paste any job description and get back *your own* `.tex` file with the job's keywords worked into the right places, a compiled PDF, ATS recommendations, and an honest report of what changed and why. Every new skill, tool and number is checked in code against what you can actually back up.

Built for **HackDevengers 2.0** (19–20 September 2026).

**Try it without signing up:** run the app and click *Try the demo with a sample resume* on the landing page. It opens the real app in a temporary workspace with a sample resume and background; you only add your own model key. Demo workspaces are deleted after two days.

---

## The problem

Recruiters search an ATS by keyword, and job titles and skills have to match the posting. So every application needs a tailored resume. LaTeX users have two bad options today:

- **Edit by hand for every job.** Slow, and easy to miss the keywords that matter.
- **Paste the resume into an AI chat.** It regenerates the whole file: the template breaks, it often doesn't compile, and it happily invents skills ("Kubernetes") and metrics ("improved performance by 40%") the candidate can't defend in an interview.


## What TailorTeX does

- **LaTeX in, LaTeX out.** Your template stays byte-for-byte intact. Only bullets, the summary and skills lines change, and every change is a precise edit at a known position.
- **Always compiles.** The model never writes LaTeX. It returns edit operations in plain text, and TailorTeX writes the LaTeX itself with an escaper that can't produce broken markup.
- **Never invents.** Validators check every edit: a bullet can only mention tools and numbers from its own job entry or from your context. Rejected edits go back to the model with the reason, and you see them.
- **Honest ATS checks.** Keyword coverage and parse health are measured on the text extracted from the compiled PDF, the way an ATS reads it. Each run ends with prioritized recommendations.
- **A permanent profile per person.** Sign in once. Your details, reference resume, model key (encrypted) and every tailored resume are saved, so you can generate resumes for different jobs again and again.
- **A knowledge base the model draws on.** GitHub link, portfolio link, LinkedIn PDF and free-text notes become entries in PostgreSQL with pgvector embeddings. For each job, TailorTeX finds the entries closest in meaning (so "event streaming" finds your Kafka note) and only adds what those entries back.
- **Review everything.** Word-level diff for every change with the reason and what backs it. Keep, revert or edit each one, then rebuild the PDF.
- **Bring your own key** from Google Gemini, Groq, OpenAI, Anthropic, OpenRouter, Mistral or DeepSeek. The provider is detected from the key; models are listed live.
- **Learns from use.** A Thompson-sampling bandit learns which tailoring strategy works for which kind of job from what people keep and revert, and it remembers each person's writing style.

## The product flow

Landing and sign-in → **About you** → **Resume and model** → **Your context** → dashboard of tailored resumes → **New tailoring** (paste the job, live pipeline) → **Result** (scores, changes, ATS recommendations, keyword matrix, guardrails, PDF and LaTeX) → export as PDF, `.tex`, or Overleaf. **My context** and **Settings** are always one click away. The screens follow a design made in Google Stitch (see [docs/FRONTEND_SPEC.md](docs/FRONTEND_SPEC.md) for the brief).

## Quick start

Needs **Python 3.11+**, **Node 20+**, **Docker** (for the database), and **TeX Live** for PDF compiling (TinyTeX is enough: `curl -sL https://yihui.org/tinytex/install-bin-unix.sh | sh`; without it you still get the tailored `.tex`).

```sh
git clone https://github.com/shreytiwari09/TailorTex.git
cd TailorTex
make setup   # Python venv + backend deps, frontend deps, creates .env
make dev     # starts PostgreSQL in Docker, the backend on :8000, the app on http://localhost:5173
```

Open http://localhost:5173, create an account, and follow the four setup steps. You need a model key (Gemini and Groq have free tiers).

**Or everything in Docker** (no Python, Node or LaTeX needed; the image includes TeX Live and the embedding model):

```sh
docker compose up --build    # or: make docker     then open http://localhost:8000
```

No configuration is needed. The secret that encrypts saved model keys is generated on first start and kept in the data volume; set `APP_SECRET` in `.env` for a hosted deployment where that volume doesn't persist. Without a database the app falls back to a simpler no-login demo page that keeps everything in the browser.

| Command | What it does |
|---|---|
| `make test` | Backend tests (including real LaTeX compiles and, with `TAILORTEX_TEST_DATABASE_URL`, real PostgreSQL), frontend type-check and lint |
| `make start` | Build the frontend and serve the whole app from the backend on :8000 |
| `make db` | Start just the database |
| API docs | http://localhost:8000/docs (interactive, from FastAPI) |

Settings (all optional) are in [.env.example](.env.example): `DATABASE_URL`, `APP_SECRET`, `GOOGLE_CLIENT_ID` (adds a "Continue with Google" button), a shared `TAILORTEX_API_KEY` for the demo, and the TeX location.


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
    ats/        keyword matching and synonyms, coverage, gap chips, title match, parse health, lint, recommendations
    validate/   the no-invention rules
    compile/    TeX Live runner: engine detection, safety checks, page count, PDF text, page fill
    llm/        bring-your-own-key client for 7 providers, prompts, output schemas
    learn/      strategy arms, Thompson-sampling bandit, feedback reward, style memory
    pipeline/   the tailoring run and the rebuild after review
    reward/     the reward function (layer 0 of the learning loop)
    evidence/   background sources: GitHub, LinkedIn PDF, portfolio pages, notes, verified extraction
    db/         PostgreSQL + pgvector: profiles, sessions, context entries with embeddings, saved runs
    api/        FastAPI app: guest endpoints (main.py) and the signed-in product (account.py)
  tests/        pytest, including real LaTeX compiles, a mock-model pipeline run and a real PostgreSQL
frontend/
  src/app/      the product: routes, sign-in state, Tailwind design tokens, the screens
  src/          the simple no-database demo page (its own entry, demo.html)
docs/           product plan, development log, frontend design brief
```

## API

Guest (no account, everything in the request):

| Endpoint | Purpose |
|---|---|
| `GET /api/config` | Providers, whether LaTeX is installed |
| `POST /api/models` | Check a key and list the provider's chat models |
| `POST /api/parse`, `/api/lint/fix`, `/api/compile` | What TailorTeX sees in a `.tex`, one-click fixes, safe compile |
| `POST /api/tailor` | The full run, streamed as server-sent events; the last event is the result |
| `POST /api/rebuild`, `/api/feedback` | Re-apply kept and edited changes; keep/revert decisions train the bandit |

Signed in (session cookie):

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/signup`, `/signin`, `/google`, `/demo`, `/signout`; `GET /api/auth/me`, `/config` | Accounts |
| `GET/PUT /api/profile`, `PUT /api/profile/resume`, `/model`, `/notes`, `/skills`; `DELETE /api/profile` | Your details, reference resume, encrypted model key, notes, skills; delete everything |
| `GET /api/profile/context`; `POST /api/profile/context/links`, `/linkedin`; `PATCH`/`DELETE /api/profile/context/{id}` | Your knowledge base |
| `POST /api/runs` (streamed), `GET /api/runs`, `GET/DELETE /api/runs/{id}`, `POST /api/runs/{id}/rebuild` | Tailor from your stored profile and context; history |

## Where your data is stored

| What | Where | For how long |
|---|---|---|
| Account, details, reference resume, notes, confirmed skills | PostgreSQL (`profiles`) | Until you delete your account |
| Your model API key | PostgreSQL, **encrypted** (Fernet, key from `APP_SECRET` or a generated secret). Never sent back to the browser: the API only says a key is saved and shows its last four characters | Until you remove it or delete your account |
| Context entries (GitHub, portfolio, LinkedIn, notes) and their embeddings | PostgreSQL with pgvector (`evidence_items`) | Until you delete them or your account |
| Tailored resumes (job description, `.tex`, PDF, report) | PostgreSQL (`runs`) | Until you delete them or your account |
| Sessions | An HttpOnly cookie in your browser; PostgreSQL keeps only a hash of the token | 30 days, or until you sign out |
| Style memory and strategy statistics | `data/` on the server (a Docker volume), under your anonymous profile ID | Deleted with your account (the anonymous strategy totals stay) |
| LinkedIn PDF and web pages you point it at | Server memory while they are read; only the extracted entries are kept | Discarded straight away |
| **Demo workspace** ("Try the demo") | The same tables, as a profile with no email or password, holding the sample resume. Your model key, if you add one, is encrypted like any other | Deleted automatically two days after it is created |
| **No-database fallback demo** | Your browser only (`localStorage`) | Until you clear it |

Your resume, job description and context are sent to the model provider you choose, and your GitHub username to GitHub's public API. Nothing else leaves the server, and request bodies are never logged. **Delete my account** in Settings removes everything above.

## Security and privacy

- **Passwords** are stored as scrypt hashes; **session tokens** as SHA-256 hashes. Sign-in is rate limited.
- **Model keys** are encrypted at rest and never returned by the API. In the no-login demo a key stays in your browser.
- **Compiling LaTeX runs code**, so documents that write files, run shell commands, read files outside the project or run Lua are refused before TeX starts. TeX runs with shell escape off, paranoid file access, a fresh temp folder and a timeout.
- **Web pages you add are fetched safely:** only http(s), and private, loopback and cloud-metadata addresses are refused, including after redirects.
- **Job descriptions, READMEs and LinkedIn text are untrusted data.** A prompt injection can only produce edit operations, and the validators block anything unsupported. Extracted context is checked against its source text too.
- Every account only ever reads its own rows; there are tests for it.

## Roadmap

- Firebase Authentication (Google and email link) in place of the built-in sign-in. A working version is on the `firebase-auth` branch.
- Application tracking (interviewing, archived) on the dashboard, and callbacks as a learning signal.
- The new design for the no-login demo, a dark theme, and mobile polish.
- A small open model fine-tuned on accepted edits, so tailoring works without a key.
- Chrome extension to capture job descriptions.

## About this project

The product plan and research in [docs/PLAN.md](docs/PLAN.md) were written before the hackathon. All code in this repository was written during the HackDevengers 2.0 window; the commit history shows how it was built, and [docs/DEVLOG.md](docs/DEVLOG.md) records each decision and why it was made.
