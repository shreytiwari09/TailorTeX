# TailorTeX

**Tailor your LaTeX resume to every job description, without breaking your template or inventing anything.**

Set up your profile once (your resume, your GitHub, portfolio, LinkedIn and notes), then paste any job description and get back *your own* `.tex` file with the job's keywords worked into the right places, a compiled PDF, ATS recommendations, and an honest report of what changed and why. Every new skill, tool and number is checked in code against what you can actually back up.

Built for **HackDevengers 2.0** (19–20 September 2026).

**Try it without signing up:** run the app and click *Try the demo with a sample resume* on the landing page. It opens the real app in a temporary workspace with a sample resume and background; you only add your own model key. Demo workspaces are deleted after two days.

## Run it in two minutes (for reviewers)

You need Docker and nothing else. No account, no configuration, no API keys of ours.

```sh
git clone https://github.com/shreytiwari09/TailorTex.git
cd TailorTex
docker compose up --build      # first build takes a few minutes: it includes TeX Live and the embedding model
```

1. Open **http://localhost:8000** and click **Try the demo with a sample resume**. That opens the real app with a sample resume and background, no sign-up.
2. When it asks for a model key, paste one of your own. A free Google Gemini key works: https://aistudio.google.com/app/apikey (Groq also has a free tier). Keys are encrypted in the local database and never leave your machine except to the provider you chose.
3. Paste any job description, and read the result: the ATS score before and after, every change with the reason and what backs it, a live PDF, and a panel for the skills the job wants that your resume doesn't show.

Prefer to run it from source? `make setup && make dev`, then open http://localhost:5173 (needs Python 3.11+, Node 20+, and Docker for the database).

**Before you start, three things worth knowing**

- **You need a model key to run a tailoring.** Without one you can explore the demo, but nothing gets tailored. Any of Gemini, Groq, OpenAI, Anthropic, OpenRouter, Mistral or DeepSeek works; the provider is detected from the key. Or set `TAILORTEX_API_KEY` in a `.env` file (copy `.env.example`) to supply one for everyone using your instance.
- **Free tiers are small.** Google's free Gemini allowance is roughly 20 requests per model per day, and one tailoring plus a few chat turns can use a good share of it. TailorTeX retries when a provider is busy and switches to another model of the same provider when a daily allowance runs out, and it tells you when that happens. If you still hit the limit, use a key from Groq (free tier), or wait for the daily reset. A new key from the same Google project doesn't help, because the limit is per project.
- **The first build is slow, and later starts are fast.** `docker compose up --build` downloads TeX Live and the embedding model, which takes a few minutes (longer on Apple Silicon or Windows, where the image may run under emulation). After that it starts in seconds. Your data lives in a Docker volume and survives restarts. `docker compose down -v` wipes it.

**A five-minute tour**

1. Click **Try the demo**, add your model key when asked, and open **My context** to see the sample resume and background.
2. Paste any job description on **New tailoring** and watch the pipeline run.
3. On the result page, read the ATS score before and after, tick or untick changes to watch the estimate move, then **Apply my choices** to rebuild the PDF.
4. In the panel for skills the job asks for that your resume doesn't show, tick the ones you have and add them to your Skills lines in one click. Tell the assistant about anything you actually built, and it writes a bullet or a new project from your own words.
5. Download the PDF, the `.tex`, or open it in Overleaf.

**Troubleshooting**

| You see | Why, and what to do |
|---|---|
| "Rate limit or quota reached" | The free daily allowance for that model is used up. The app tries other models first; if it still fails, wait for the reset or use another provider's key. |
| "Provider is busy (503)" | The provider is overloaded, not your key. TailorTeX retries and then falls back to another model. Try again in a minute. |
| No PDF, only `.tex` | LaTeX isn't installed (running from source). Docker includes it; from source, install TinyTeX (see Quick start). |
| "Your resume doesn't compile" | The source has an error. The app offers a one-click fix for common ones, and repairs a broken original before tailoring. |
| Port 8000 or 5432 already in use | Stop the other service, or pick another port: `PORT=8010 docker compose up` (Docker) or `make start PORT=8010` (from source). |
| Stuck or odd state after an upgrade | `docker compose down -v && docker compose up --build` starts from a clean database. |

**Sign-in on a fresh clone.** The Firebase settings are public identifiers kept in a git-ignored `.env`, so they are not in this repository, and you don't need them. With none set, the app uses its own email and password sign-up (passwords stored as scrypt hashes, session cookie in the browser), and the demo button needs no sign-in at all. Everything else behaves the same. To use Google sign-in and verified-email accounts as the hosted version would, see [Sign-in](#sign-in).

**Not deployed.** There is no hosted instance: it runs locally or in Docker. Nothing here is a mock: the parser, validators, LaTeX compiler and ATS scoring all run for real, and `make test` runs 440 backend tests, including real LaTeX compiles (and real PostgreSQL when `TAILORTEX_TEST_DATABASE_URL` is set).

---

## The problem

Recruiters search an ATS by keyword, and job titles and skills have to match the posting. So every application needs a tailored resume. LaTeX users have two bad options today:

- **Edit by hand for every job.** Slow, and easy to miss the keywords that matter.
- **Paste the resume into an AI chat.** It regenerates the whole file: the template breaks, it often doesn't compile, and it happily invents skills ("Kubernetes") and metrics ("improved performance by 40%") the candidate can't defend in an interview.


## What TailorTeX does

- **LaTeX in, LaTeX out.** Your template stays byte-for-byte intact. Only bullets, the summary and skills lines change, and every change is a precise edit at a known position.
- **Always compiles.** The model never writes LaTeX. It returns edit operations in plain text, and TailorTeX writes the LaTeX itself with an escaper that can't produce broken markup.
- **Never invents.** Validators check every edit: a bullet can only mention tools and numbers from its own job entry or from your context. Rejected edits go back to the model with the reason, and you see them.
- **Honest ATS checks.** One score, everywhere. Keyword coverage and parse health are measured on the text extracted from the compiled PDF, the way an ATS reads it, alongside writing quality that holds whatever the job is: strong openers, results, bullet length, consistent dates, a readable contact line. Each run ends with prioritized recommendations.
- **A permanent profile per person.** Sign in once. Your details, reference resume, model key (encrypted) and every tailored resume are saved, so you can generate resumes for different jobs again and again.
- **A knowledge base the model draws on.** GitHub link (every public repository; you pick which ones count if you have more than ten), portfolio link, LinkedIn PDF and free-text notes become entries in PostgreSQL with pgvector embeddings. A blank line starts a new note, so a pasted post stays whole. For each job, TailorTeX finds the entries closest in meaning (so "event streaming" finds your Kafka note) and only adds what those entries back.
- **Finds what your own material already shows, by meaning.** A job asks for "Generative AI"; your resume says "RAG-powered LLM pipeline". Each unmatched skill is searched for across your resume and context by meaning, and a match counts only if the model can quote your own words back exactly. A named tool, product or certification still has to be named — a related one proves nothing.
- **Tells you exactly what is missing, and what each one is worth.** Everything the job asks for that nothing of yours shows is listed together with its ATS value. Tick the ones you have and they go onto your Skills lines in one click — a plain edit to your `.tex`, no model involved. For work you actually did, say so in your own words: it writes a bullet from what you said, or the LaTeX for a whole new project in your resume's own style, and nothing you didn't say can appear in it.
- **Review everything.** Word-level diff for every change, with the reason, what backs it, and what it is worth (`+4.4%`). Keep, revert or edit each one, watch the estimate move, then rebuild the PDF.
- **Bring your own key** from Google Gemini, Groq, OpenAI, Anthropic, OpenRouter, Mistral or DeepSeek. The provider is detected from the key; models are listed live. When a provider is busy, or a model's free daily allowance is gone, TailorTeX says so plainly and moves to another model of the same provider rather than losing the run.
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

Settings (all optional) are in [.env.example](.env.example): `DATABASE_URL`, `APP_SECRET`, the `FIREBASE_*` sign-in settings (see below), a shared `TAILORTEX_API_KEY` for the demo, and the TeX location.


## Sign-in

Sign-in goes through **Firebase Authentication**: Continue with Google, or email and password with a verified address (Firebase sends the verification and password-reset emails). The browser signs in with Firebase and sends the ID token to the server, which checks it against Google's public keys (signature, expiry, project, verified email) and then issues its **own** session cookie (HttpOnly, only a hash stored). Firebase is only the front door; **all data stays in PostgreSQL**. A first sign-in with an email that already has an account links to it.

To turn it on, create a Firebase project, enable the Google and Email/Password providers, register a web app, and put its `firebaseConfig` values in `.env` as `FIREBASE_PROJECT_ID`, `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN` and `FIREBASE_APP_ID` (step by step in [docs/DEVLOG.md](docs/DEVLOG.md), section 14). These values are public identifiers, and no service-account key is needed. When they aren't set, the app falls back to its own email and password sign-up, so a fresh clone still works. The demo needs no sign-in either way.

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
| Dropping a bullet may not remove the last mention of a skill the job requires | A page-fit drop that lowers the very score it is raising |

Keyword matching understands tech names: K8s = Kubernetes, Postgres = PostgreSQL, `C` doesn't match `C++`, `Java` doesn't match `JavaScript`, and "spark interest" isn't Spark. A skill **you** state about yourself, or tick from the job's own list, is your edit to your own resume and is applied as given; text the model writes is never marked that way, and a test fails if it ever is.

### ATS checks on the compiled PDF

Selectable text · no ligature glyphs ("ﬁnancial" isn't "financial") · no icon-font garbage · email and phone readable near the top · standard section headings · single-column reading order. Source lint catches missing `\pdfgentounicode`, FontAwesome icons and two-column layouts, with a one-click fix where possible.

### Templates, and how far it has been tested

Jake's Resume and its many variants, Awesome-CV, moderncv, and generic `article` resumes that use `\section` and `itemize`. Custom bullet and heading macros are recognized from their `\newcommand` definitions. Skills sections are read whether they are labelled lines (`\textbf{Languages:} ...`), bullet-separated lines, a description list, a table row, or a plain comma-separated paragraph with no label at all.

`backend/tests/corpus/` holds thirteen resumes written in deliberately different ways — an article-class nursing CV, a marketing resume built from tables, custom finance macros, a two-page academic CV, a description-list engineering resume, a photo header, accented names, moderncv and Awesome-CV — and ten job analyses from different trades, including one that says almost nothing and one that tries to give instructions. Every resume is measured against every job, and three rules hold for all of them: the parser never crashes, an edit that changes nothing changes nothing byte for byte, and anything a rewrite would silently damage (italics, monospace, small caps, math, forced breaks, unusual accents) is locked with a reason instead of being edited.

The default template in `backend/tailortex/templates/jake/` is an ATS-safe version of Jake's Resume (MIT License).

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
| `GET /api/profile/context`; `POST /api/profile/context/links`, `/github`, `/linkedin`; `PATCH`/`DELETE /api/profile/context/{id}` | Your knowledge base |
| `POST /api/runs` (streamed), `GET /api/runs`, `GET/DELETE /api/runs/{id}`, `POST /api/runs/{id}/rebuild` | Tailor from your stored profile and context; history |
| `POST /api/runs/{id}/skills` | Add skills you ticked from the job's list to your Skills lines. No model call, so it works without a key |
| `POST /api/runs/{id}/chat` | Say anything about a skill in your own words; it works out what you mean and drafts it |
| `POST /api/runs/{id}/answers` | Draft bullets from what you told us about skills the job wants |

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

- **Sign-in** goes through Firebase when it is configured, so passwords never reach this server. In the built-in fallback, passwords are scrypt hashes. **Session tokens** are stored as SHA-256 hashes, and sign-in is rate limited.
- **Model keys** are encrypted at rest and never returned by the API. In the no-login demo a key stays in your browser.
- **Compiling LaTeX runs code**, so documents that write files, run shell commands, read files outside the project or run Lua are refused before TeX starts. TeX runs with shell escape off, paranoid file access, a fresh temp folder and a timeout.
- **Web pages you add are fetched safely:** only http(s), and private, loopback and cloud-metadata addresses are refused, including after redirects.
- **Job descriptions, READMEs and LinkedIn text are untrusted data.** A prompt injection can only produce edit operations, and the validators block anything unsupported. Extracted context is checked against its source text too.
- Every account only ever reads its own rows; there are tests for it.

## Roadmap

- Creating a Skills section in a resume that has none, and carrying italics and monospace through a rewrite instead of locking the bullet.
- Application tracking (interviewing, archived) on the dashboard, and callbacks as a learning signal.
- The new design for the no-login demo, a dark theme, and mobile polish.
- A small open model fine-tuned on accepted edits, so tailoring works without a key.
- Chrome extension to capture job descriptions.

## About this project

The product plan and research in [docs/PLAN.md](docs/PLAN.md) were written before the hackathon. All code in this repository was written during the HackDevengers 2.0 window; the commit history shows how it was built, and [docs/DEVLOG.md](docs/DEVLOG.md) records each decision and why it was made.
