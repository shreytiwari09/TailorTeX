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

## 9. "About you": LinkedIn, portfolio, GitHub, skills and facts

**What:** Step 3 became "About you", the context TailorTeX uses to suggest what each job's resume should include. Five sources: LinkedIn, portfolio, GitHub, skills you can defend, and facts. After a run, a Suggestions tab lists what from your background matches the job: what this version added, what could still be added, and job keywords nothing backs up ("Do you have these?").

**Decisions:**
- **LinkedIn through its own PDF export, not a profile link.** LinkedIn blocks apps from reading profiles and its terms forbid scraping. "Save to PDF" on a profile is one click and official; pasting the profile text works too.
- **Portfolio pages are fetched safely.** Only http(s); every host (including redirects) is resolved first and private, loopback, link-local and cloud-metadata addresses are refused, so a URL can't be used to probe the server's network. Pages rendered entirely by JavaScript can be pasted as text instead.
- **Extraction can't invent either.** The user's model splits the text into roles, projects, achievements and skills, and then every item is checked against the source: sentences with numbers or names the source doesn't contain are dropped, and so are skills it doesn't mention. Without a key, the text is split into paragraphs with known skills picked out, and the app says so.
- **Evidence scope carries over:** LinkedIn items describe your roles and can back bullets anywhere; portfolio and GitHub items back projects, the summary and skills lines.

## 10. Just paste your links; LinkedIn posts

**What:** "About you" now starts with one box: paste your links and press Add. GitHub profile links import your top repositories automatically (your own repos, most stars first, then most recent), repo links import that repo, and any other link is read as a portfolio page. LinkedIn is one file dropped in one place: the PDF from its Save to PDF button, or its data export ZIP, which also carries your posts. Skills, facts, pasted text and hand-picking repos moved under "More ways to add context".

**Why:** Uploading and ticking things in five tabs was too much work for context that should take seconds.

**Why LinkedIn still needs a file:** a LinkedIn link can't be read by an app. LinkedIn shows profiles only to signed-in people and blocks automated requests, its terms forbid scraping, and "Sign in with LinkedIn" only shares your name, email and photo. So when someone pastes a LinkedIn link, the app says so and points at the one-file route, with a button that opens their profile.

**Posts:** "Save to PDF" leaves out posts, and posts are often where people announce projects, launches and wins. LinkedIn's data export includes them (Shares.csv). Only the profile, positions, projects, skills, certifications, honors, publications and posts files are opened; messages and connections are never read. The user's model keeps only posts about the person's own work, and every extracted item is checked against the post text. Pasted posts add up across pastes.

## 11. Four inputs, a notes box, and "Delete my data"

**What:** "About you" is now exactly four things: a GitHub link, a portfolio link, a LinkedIn PDF, and "Anything else about you", a free-text box where each line becomes one fact (IDs `n1`, `n2`, ...). The extra tabs (skills, facts, pasted text, repo picking, the LinkedIn data export) left the interface; the endpoints stay for later. The footer has a "Delete my data" button that clears everything in the browser and deletes this browser's style memory and strategy statistics on the server (`POST /api/forget`).

**Why:** fewer choices make the step faster, and people have more to say about themselves than any profile holds. One fact per line keeps a number next to the sentence that explains it, so the validator can let a bullet use exactly what the user wrote, and nothing more (a test checks that a note saying "built Kafka consumers" can't be turned into "handling 2M events a day").

**Where data lives** is written up in the README: inputs in the browser, request data in server memory only for that request, and only anonymous style memory and strategy statistics kept on the server.

## 12. From a single screen to a product: accounts, a stored knowledge base, saved resumes

**What:** TailorTeX became a multi-page product. You sign up (email and password, or Google when `GOOGLE_CLIENT_ID` is set), fill in your details, paste the reference resume from Overleaf, add a model key, and build your context. Then you paste a job description and get a tailored resume, its PDF and ATS recommendations, all saved under your account. The no-login guest demo stays as it was (`/demo.html`), with its data in the browser.

**Storage: PostgreSQL with pgvector, one database.** Details that rarely change (name, headline, links, the reference resume, notes, confirmed skills, model settings) are ordinary columns on `profiles`. Background entries (a repo, a LinkedIn role, one note line) are rows in `evidence_items` with a 384-dimension embedding from a small local model (`bge-small-en-v1.5` via fastembed, so nothing about you goes to an embedding service). Tailored resumes are rows in `runs`, with the PDF, so they can be reopened and rebuilt later. Every table cascades from `profiles`, so deleting an account deletes everything.

**Ranking by meaning:** for a job, the entries closest to the job description's embedding are selected (plus your confirmed skills) and passed as evidence. "Event streaming" finds the Kafka note even though the words differ. The validators are unchanged: an entry can only back an edit if it was passed and cited, so a smarter search can't widen what may be claimed.

**Accounts and secrets:**
- Passwords are scrypt hashes. A session is a random token in an HttpOnly cookie; only its SHA-256 is stored.
- The model key is encrypted with Fernet, keyed from `APP_SECRET`. If none is set the server generates one on first start and keeps it (mode 0600) in the data folder, so a fresh `docker compose up` works with no setup. The API never returns the key, only "saved" and the last four characters.
- Google sign-in verifies the ID token against Google's public keys, the audience and the issuer. Tests cover a wrong audience and an expired token.

**ATS recommendations (`ats/recommend.py`):** a prioritized list built in code from the run's own metrics, so it can't make things up: missing must-have keywords (marked "confirm you have this" when nothing backs them, or "use this from your context" when something does), keywords that appear only in the skills list, title mismatch with the wording to use, parse-health failures with the fix, and page space left for one more bullet.

**The interface** is built from a design made in Google Stitch (Tailwind with the design's tokens, Inter and JetBrains Mono, React Router). Copy is kept short; explanations sit behind "i" popovers. I replaced the design's invented claims (fake user counts, stock photos of people) with true copy and a self-drawn example of what a result looks like, and kept the theme light only.

**Firebase Authentication is future scope.** I first switched sign-in to Firebase (server verifies Firebase ID tokens and issues its own session cookie). The decision was to build the MVP with the sign-in we already had and to use Firebase only for auth later, with all data staying in PostgreSQL. The working version is parked on the `firebase-auth` branch, and `main` reverts it (commit `6db4b4f`).

**Bugs found by using it:**
- The phone header clipped "New tailoring" (a hidden class and an inline-flex class on one element); phones now get an icon-only button.
- The single-page-app fallback answered unknown `/api/...` paths with 200 and the home page; they now return 404.
- Bad-key detection: Gemini and OpenRouter accepted any key when listing models; both are now checked properly.
- In Docker, the host `.env` (relative data folder, local TeX settings) overrode the image's settings through `env_file`, which would have put style memory outside the volume. Container settings are pinned in `docker-compose.yml` now. Found by running the container with the `.env` a fresh clone creates.

**Docker:** `docker compose up --build` starts `pgvector/pgvector:pg17` and the app (TeX Live, poppler, and the embedding model baked in so the first search doesn't download 130 MB). `make dev` starts the same database for local development.

## 13. The demo opens the real app

**Found by the user:** "Try the demo" still went to the classic single-page app (dark, all inputs on one screen), which looks nothing like the Stitch design. I had kept it as the guest demo and left it un-restyled, so the first thing a judge might click was the one screen that didn't match.

**Fix:** `POST /api/auth/demo` creates a temporary profile (no email, no password) holding the sample resume, a sample GitHub entry and two notes, marked as onboarded, and signs it in with a two-day cookie. The landing button calls it and opens the New tailoring screen with the sample job description filled in, so the whole product is one interface. The model key is asked for right there ("Add your model key", also shown to anyone signed in without one), because a demo without a key can't run. A banner says it is a demo workspace that is deleted after two days.

**Why a real profile and not a browser-only mode inside the new UI:** the new screens are written against the account API, so a demo profile reuses every one of them with nothing duplicated, and the demo exercises the same storage, ranking and validators as the product. Demo profiles are found by having no email, password or Google ID and are deleted when a server starts and whenever a new demo is opened. A test covers the flow, that a real account can't see a demo's data, and the expiry.

The old page (`/demo.html`) stays only as a fallback for when the server has no database.

## 14. Sign-in through Firebase Authentication

**Decision:** the earlier "Firebase later" call was reversed: sign-in now goes through Firebase Authentication, and only sign-in. The user's words were "we only want auth from firebase", so **every table stays in PostgreSQL**; Firebase never holds resumes, context or keys.

**How it works:**
1. The browser signs in with the Firebase web SDK: Google in a popup, or email and password.
2. Email and password need a verified address. Firebase sends the verification email; the screen says "Check your email" and continues after "I've verified my email". Password reset is Firebase's own email too. Google accounts are verified already.
3. The browser sends the Firebase **ID token** to `POST /api/auth/firebase`. The server checks the signature against Google's public `securetoken` keys, that it was issued for **this** Firebase project (audience and issuer), that it hasn't expired, and that the email is verified. No service-account key is needed, only the project ID.
4. The server finds the person by Firebase UID, else by that verified email (so an existing account is linked, not duplicated), else creates them, and then issues **its own session cookie** (HttpOnly, only the token's hash stored). From then on nothing talks to Firebase; Firebase's state in the browser is in memory only and is signed out straight after the exchange.

**Why our own session and not Firebase's token on every request:** requests stay independent of Firebase (its outage or a token refresh can't sign anyone out mid-run), sign-out really ends the session, and the existing data and privacy tests keep applying unchanged.

**Why a verified email is required:** linking accounts by email is only safe if the person owns the mailbox. Without the check, someone could register a Firebase account with your address and be linked to your profile.

**When Firebase is on it is the only way in:** the built-in sign-up, sign-in and direct Google routes answer 400, so email verification can't be bypassed. When the `FIREBASE_*` settings are empty the app falls back to its own email and password, so a fresh clone works without a Firebase project. Tests cover both, and cover a wrong project, an expired token, an unverified email and a wrong signing key.

**Set up (once):**
1. console.firebase.google.com → **Add project** (Analytics off).
2. **Build → Authentication → Get started → Sign-in method:** enable **Google** (pick a support email) and **Email/Password**.
3. **Project settings (gear) → General → Your apps → Web (`</>`)**: register an app (skip Hosting) and copy `firebaseConfig`.
4. Put `apiKey`, `authDomain`, `projectId` and `appId` in `.env` as `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_PROJECT_ID` and `FIREBASE_APP_ID`, then restart the backend. These are public identifiers.
5. **Authentication → Settings → Authorized domains:** `localhost` is there already; add the deployed domain when there is one.

## 15. When the provider is busy

**Found by the user:** a run stopped with "Google Gemini error (503): This model is currently experiencing high demand." Gemini's free tier sheds load during spikes, and the run gave up after three quick tries about six seconds apart, which is too impatient for a spike that usually lasts under a minute.

**What it does now:**
- **Waits properly.** A busy server (500, 502, 503, 504, 529) is retried four more times, waiting 4, 8, 15 and 25 seconds, plus a little jitter so parallel candidate runs don't retry in lockstep. A `Retry-After` header wins over that schedule, capped at 30 seconds. Rate limits (429) keep two extra tries, since a quota needs a longer wait than a busy server.
- **Says what's happening.** The wait is streamed to the person ("Google Gemini is busy. Trying again in 8 seconds (try 3 of 5)") instead of a progress bar that appears stuck. The client takes an optional `notify` callback; the streaming endpoint passes one that emits a `model` progress event.
- **Moves to a sibling model.** If the chosen Gemini model stays overloaded, the run continues on the next stable Flash model from the same provider (never a preview or experimental build, which are the ones that run out of capacity), and the result carries a warning saying which model was used. Only Gemini: its capacity errors are the common case, and other providers' 5xx are usually real faults.
- **A real error on the sibling is reported, not hidden.** Anything that isn't a busy or missing-model response is raised as it is.
- **The final message is actionable** when everything stays busy: it says TailorTeX already waited and retried, and suggests trying later or picking another model.

**Checked with a scripted provider** (no network, no real waiting): the backoff schedule and `Retry-After`, the notices, the model switch and what it records, 429 versus a bad key, a real error on the sibling, and that the fallback list contains only stable siblings.

## 16. Context that actually helps: whole notes, and every repository

The first real run with a live model scored 26% → 31% must-have coverage, with **0 of 22 job keywords backed by evidence**. The context was the problem, in two ways the user spotted straight away.

**Notes were being shredded.** Every newline started a new entry, so a pasted LinkedIn post became a pile of fragments: "What made this different - every team ha…" is not a fact anyone can write a resume bullet from, and it's what the ranker kept surfacing. Now **a blank line starts a new entry** and single newlines don't, so a pasted post, a paragraph about a project, or a list of related lines stays whole. The entry is named after its first sentence. The limits went from 6 000 characters total and 1 000 a line to 20 000 and 4 000 a block, because posts are long. The editor says so under the box, and the button counts entries, not lines.

**Only six repositories were read.** `best_repos` took the top six by stars, one page of the API, and `import_repos` capped names at eight. Someone with 40 repositories had 34 of them invisible to the tool, including the ones that match the job. Now the list is paged through in full (up to 500), and:
- **10 or fewer: all of them are imported**, no questions.
- **More than 10: the whole list comes back and the person picks**, with stars, language, last push and description, a filter box, and the six strongest pre-ticked. Forks are left out; they aren't your work.
- A pick is the complete set, so choosing again replaces the previous import instead of piling up (`replace_source(..., exact=True)`). A single repo link still only replaces its own entry.

**The cap is GitHub's, not ours.** Reading one repository costs two API calls (languages and README) and anonymous requests are limited to 60 an hour, so a pick is capped at 25 and the UI says so. `GITHUB_TOKEN` on the server raises the limit to 5 000.

**Also fixed:** a stand-in model used to get the full patience schedule of its own, so a run could spend a minute per candidate; it now gets one retry, and the real run that found this took 243 seconds mostly waiting.

## 17. "I changed the key and it still says quota reached"

**Found by the user.** The message said "Wait a minute, or use a different key", and both halves were wrong. Gemini's reply says exactly what happened, and TailorTeX was throwing it away:

```
Quota exceeded for metric: ...generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash
quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier    retryDelay: 38s
```

**Per project, per model, per day.** A new API key made in the same Google Cloud project shares the same allowance, so swapping keys changes nothing — which is exactly what the user saw. Waiting doesn't help either; twenty requests is the whole day. But **each model has its own allowance**, so another model works immediately.

**What it does now:**
- **Reads the quota details** from the body (`QuotaFailure` and `RetryInfo`), not just the `Retry-After` header, which Google doesn't send here.
- **Doesn't wait for a daily allowance.** A per-day 429 returns at once instead of sleeping through the backoff schedule.
- **Switches model on a per-model quota**, the same as for an overloaded one: "gemini-3.8-flash is out of its free allowance for today. Switching to gemini-3.7-flash for this run."
- **Says something true when everything is out:** which model, the size of the allowance, that a new key from the same project shares it, and that another model has its own.
- **A per-minute limit is different** and is waited out for as long as Google asks (`retryDelay`, capped), and the final message gives the real number of seconds.

**Checked against the real thing:** asking for a model whose 20 requests were gone switched to the next one and finished. The tests use Gemini's exact reply, list wrapper and all.

## Test status

124 backend tests pass with a PostgreSQL available (`TAILORTEX_TEST_DATABASE_URL`; the database tests skip without one), including real pdfLaTeX compiles, the compiler's safety checks, a full pipeline run with a scripted model, and account, privacy and ranking tests against real PostgreSQL. CI runs them with a Postgres service. The frontend type-checks, lints clean and builds.
