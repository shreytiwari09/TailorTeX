# TailorTeX development log

What was built during HackDevengers 2.0, the decisions made along the way, and why. The product plan is in [PLAN.md](PLAN.md). New entries go at the end.

## 1. Stack and structure

**What:** A Python backend (FastAPI) holding the whole tailoring engine, and a React + Vite + TypeScript frontend that talks to it over REST. One repository, one `Makefile`.

**Why:** LaTeX parsing, validation and compiling are text and process work that Python handles well, and FastAPI gives streaming responses and interactive API docs for free. The frontend stays a thin client, so every guarantee lives in one place, the backend, where it can be tested.

## 2. LaTeX engine (`backend/tailortex/latex/`)

**What:** A scanner that finds commands, arguments and environments with exact character offsets; conversion between LaTeX and plain text; a parser that splits a resume into sections, entries, bullets and skills lines, each with an ID like `s1.e0.b2`; and an editor that applies edit operations.

**Decisions:**
- **Comments are masked, not removed.** The masked copy has the same length as the source, so every offset found in it is valid in the original. That is what makes byte-exact edits possible.
- **Templates are recognized from their own definitions.** A one-argument `\newcommand` whose body contains `\item` is a bullet macro; a macro with two or more arguments between bullets is an entry heading. Awesome-CV and moderncv macros that live in class files are known by name. Generic resumes fall back to one entry per `itemize` list, headed by the text just before it.
- **The model never writes LaTeX.** `plain_to_latex` is the only path from model text to the file: it escapes every special character, emits only `\textbf{}` and a few symbol commands, and folds characters pdfLaTeX can't typeset. A property test runs 500 random strings through it.
- **Only touched spans are rebuilt.** Entries whose bullets are added, dropped or reordered are rebuilt from their bullets with the original whitespace between them; everything else is copied unchanged. No edits gives a byte-identical file, tested on four templates.
- **Locked by default:** education and unrecognized sections (awards, publications) can't be edited, and bullets containing links or unusual commands are locked rather than flattened.

## 3. ATS checks, validators and reward

**What:** Keyword matching with synonyms and tech-aware word boundaries, coverage scoring, gap chips, job-title alignment, parse-health checks on PDF text, source lint with one-click fixes, the validators, and the reward function.

**Decisions:**
- **Coverage rewards context.** A keyword used in a bullet scores 1, one only in the skills list scores 0.6, and a keyword that can't be found in the PDF's extracted text scores 0, because an ATS can't see it.
- **Validation is scoped, not global.** An early design allowed any term found anywhere on the resume. That would let the model move "Redis" from one job into another job's bullet, which is a fabrication even though Redis is on the resume. So a bullet may only use terms from its own entry or from evidence it cites, and numbers only from the same bullet. Evidence is scoped too: "skills I can defend" can go into skills lines and the summary but not into a specific job; GitHub projects can back project bullets but not employer bullets.
- **Short and ambiguous names are case-sensitive.** "Go", "R" and "TS" only match in that casing, and everyday words like spark, react and express only count when capitalized.
- **Loose synonym groups were split** (Docker ≠ containers, Git ≠ version control, Agile ≠ Scrum) so coverage reflects what a recruiter's keyword search would actually find.

## 4. Compiler (`backend/tailortex/compile/`)

**What:** Runs TeX Live with the engine the template expects (pdfLaTeX by default, XeLaTeX for fontspec or Awesome-CV, LuaLaTeX for Lua templates) and returns the PDF, page count, extracted text, how full the last page is, and errors with line numbers.

**Decisions:**
- **Refuse dangerous documents before TeX runs:** `\write18`, `\openout`, `\directlua`, `\openin`, piped `\input`, and file access outside the project folder. TeX also runs with shell escape off, `openin_any=p` / `openout_any=p`, a fresh temp folder, a timeout, and CPU and memory limits on Linux.
- **TeX Live, not Tectonic,** because Tectonic only runs XeTeX and fails on the `\pdfgentounicode` line that keeps PDF text searchable.
- **Page fill from `pdftotext -tsv`** word positions; the form-feed character pdftotext writes at page breaks is not counted as garbage (a test caught this).
- **Missing packages are installed on demand** with `tlmgr` when running on TinyTeX.

## 5. Model layer (`backend/tailortex/llm/`)

**What:** One client for seven providers using the user's own key. Six speak the OpenAI-compatible chat API and are called over HTTPS with `httpx`; Anthropic goes through its official Python SDK with structured outputs.

**Decisions:**
- **No sampling parameters.** Several current models reject `temperature`, and variety between candidates comes from different strategies, not randomness.
- **Structured output everywhere, validated with pydantic,** with one repair attempt that shows the model its error. JSON mode is dropped automatically for models that don't support it.
- **Model lists are fetched live** from each provider, because model names change every few months. The same call checks the key. A recommended default is picked from the live list.
- **Keys never appear in errors or logs.** Provider error messages are scrubbed of anything that looks like a key.
- **Prompt layout for caching:** resume and evidence first, job description last. The job description is marked as untrusted data, but the real protection is the validator.

## 6. Pipeline and learning loop

**What:** The full run (parse → compile original → analyze job → gap chips → plan per strategy → validate → retry → apply → compile → page fit → score → pick best) streamed as progress events, plus a rebuild step for after the user reviews changes.

**Decisions:**
- **Rejected edits are shown, not hidden.** The guardrail log is part of the result, because it is the evidence that the tool is honest.
- **Page fitting drops the least relevant bullet** (fewest weighted job keywords, then from the longest entry) and recompiles, keeping at least one bullet per entry.
- **Four strategy arms** (light, balanced, bold, evidence-first) change the instructions, never the rules. A Thompson-sampling bandit chooses between them per (role family, seniority), with a global prior capped at 20 observations and a per-user posterior after 5 runs. A simulation test checks it finds the best arm in at least 16 of 20 seeds.
- **Feedback reward:** kept = 1, reverted = 0, edited = 1 − share of words changed; a run's reward is 80% feedback and 20% the verifiable score.
- **Style memory:** bullets a user keeps or writes become examples, and every few edits the user's own model distills short style rules that go into later prompts.

## 7. API and web app

**What:** FastAPI endpoints for config, model listing, parse and lint, compile, streamed tailoring, rebuild, GitHub evidence import and feedback; and a React app with four input cards (model, resume, evidence, job), a live run log with gap chips, score cards, and tabs for changes, keywords, guardrails, PDF and LaTeX.

**Decisions:**
- **Server-sent events over a POST,** read with `fetch` and a stream reader, so progress appears stage by stage and the final result arrives on the same connection.
- **Same-origin everywhere:** the Vite dev server proxies `/api` to the backend, and in production the backend serves the built app, so there is no CORS setup to get wrong.
- **Review, then rebuild:** each change can be kept, reverted or edited; rebuild re-applies the chosen subset to the original source, recompiles and re-measures. User-written text skips the evidence checks (the user is vouching for it) but still goes through the escaper.
- **Missing keywords are a question, not a silent add:** "I have this" adds the term to the user's confirmed skills for the next run.
- **Checked in a real browser** with headless Chrome driving the full flow (sample → run → review → revert → rebuild, desktop and phone widths) against a scripted model: no console errors.

## 8. Paste from Overleaf, and keys that survive a reload

**What:** Step 2 now leads with pasting LaTeX copied from Overleaf (a paste box, three short copy steps, and a "Paste from clipboard" button); uploading a `.tex` file is a secondary link. The model key is kept for the browser tab across reloads, and on the device when "Remember on this device" is on (now the default).

**Why:** Almost nobody has their resume as a `.tex` file on disk; it lives in an Overleaf project. And the key vanished whenever the page reloaded, because it was only saved when "Remember" was ticked.

**Checks for pasted resumes** (warnings with a plain fix):
- Only part of the file was copied (no `\documentclass` or `\end{document}`).
- The resume loads other files from its Overleaf project (`\input{sections/...}`), which a single paste doesn't include.
- An image (`\includegraphics`) that isn't here; one click removes it.
- A custom document class (such as Awesome-CV's `.cls`) that isn't in TeX Live, checked with `kpsewhich`; the `.tex` is still tailored, and the PDF can be compiled in Overleaf.

**Bug fixed on the way:** the paste box used to disappear after the first character typed into it.

## Test status

73 backend tests pass (`cd backend && ../.venv/bin/pytest -q`), including real pdfLaTeX compiles, the compiler's safety checks, and a full pipeline run with a scripted model. The frontend type-checks, lints clean and builds.
