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

## 18. The result page: saying what happened

**Found by the user,** looking at a finished run: "it's too cluttered, I don't know what's happening, and it isn't even doing anything when I click Keep."

**The dead button.** Every change starts kept, so the Keep pill was already lit. Pressing it set the state it was already in: the counter didn't move, nothing was marked, and "Rebuild with my choices" stayed greyed out. Three pills sat side by side where one was always a no-op. Now there's a **state** ("In your resume" / "Not used") next to a single **action** ("Remove" / "Put it back"), plus Edit. Every button press changes something. The rebuild indexing was checked while I was in there and is right: a change's `id` is its index in `ops`, so removing the third change drops the third op.

**The dead-end bar.** The bottom bar showed "7 of 7 changes kept" beside a disabled button, with nothing saying why it was disabled. It now says what state you're in — "All 7 changes are in your resume. Remove any you don't want." — and offers the action that does make sense: Download PDF, or Open in Overleaf when there's no PDF. The rebuild button only appears once there's something to rebuild.

**Nothing said what had happened.** The page opened with five tiles of percentages. There's now a plain paragraph at the top: "6 bullets rewritten and 1 bullet added in your resume, each one checked against your resume and your context. That took the job's must-have keywords from 37% to 58% of the list. 2 further edits were refused because nothing you have backs them." Under it, one line saying what to do next, which changes with the state of the run: fix the resume if it doesn't compile, look at the high-priority ATS items if there are any, otherwise review and download.

**Empty tiles explain themselves.** Parse health and Pages are blank whenever the resume doesn't compile; they said "not compiled", which reads like a bug. They now say "needs a PDF", and the tooltips say why. Title alignment showing 0% now says "No title matches" and its tooltip says TailorTeX never rewrites a job title, so only you can move that number.

**Less jargon.** Blocked edits showed "rewrite s1.k3 · attempt 1 · sent back to the model". The internal ids are gone; what's left is the rule, the sentence explaining it, and the text that was refused.

**The duplicate warning is gone.** The compile failure was printed twice, once in the summary and once as its own banner.

## 19. "Why isn't it near 100% ATS?"

**Asked by the user** of a run that scored 58% on must-have keywords. The answer was in the run's own data: the job (Generative AI Engineer) lists nine must-haves, and four of them — TensorFlow, PyTorch, Scikit-Learn, Statistics — appear nowhere in the resume, the notes, the LinkedIn text or any of the three public repositories. The model proposed adding "Generative AI" to the skills line and the validator refused it for the same reason.

So 58% was the tool working: **the honest ceiling for that pairing is about 56%**, and the only ways up are real ones — use a keyword in a bullet instead of only listing it (a listed-only term scores 60%), or add evidence for something you can actually defend.

That was invisible on the page, which showed a number and left the person to guess. The result now says it in the summary: "4 of the 9 must-have keywords (TensorFlow, PyTorch, Scikit-Learn, Statistics) are nowhere in your resume or your context, so they were left out instead of invented. Everything you can actually back is already in: 56% is the most this job can score until you add proof of those." Terms that are only in the skills list are named too, since moving them into a bullet is free points.

**A score near 100% on a job you don't match is the failure mode**, not the goal: it means the resume claims things that fall apart in the interview. Saying so on the page is better than letting the number look like a bug.

## 20. Tailoring may not lower the score it exists to raise

**Found by the user:** "I see you removed a few bullets from the old resume, thereby decreasing the ATS."

They were right, and the cause was structural. The page-fit loop picks the bullet to drop by
`(_relevance, -bullet_count, -length)` — a weighted count of job terms in that one bullet — and fit drops
are appended **after** validation, so nothing checks them at all. Coverage is measured only once the loop
has finished. Once the zero-relevance bullets run out it simply takes the current minimum, which can be the
only bullet that mentions a must-have. Worse, `reward()` returned a hard `0.0` for anything over the page
limit, so an over-long candidate was worthless no matter how good its coverage: the loop had to keep cutting.

**The rule now:** a bullet may only be dropped if every **must-have** keyword it carries is still shown in
some bullet or the summary afterwards. Nice-to-haves may fall back to the skills list, since they only score
0.6 there anyway.

- `ats/coverage.py`: `zones_after(doc, ops)` computes the two scoring zones as they *will* read once a set of
  operations is applied — rewrites substituted, drops removed, additions included — with no apply/re-parse
  round trip, so it is cheap enough to call inside the validator. `coverage_loss(...)` names the terms a
  candidate operation would cost.
- The page fit now builds an ordered list of *permitted* drops (`_fit_candidates`) and walks it, instead of
  re-picking the same blocked bullet.
- The validator refuses a model `drop` or `drop_entry` with a new `coverage` rule, in words the model can act
  on: "Dropping s1.e0.b3 would remove the only mention of 'Celery', which this job requires. Rewrite it to
  make room instead." The existing retry loop feeds that back, so it self-corrects.
- **A per-operation guard isn't enough.** A drop can look safe because a second bullet still carries the term,
  and then a rewrite later in the same plan strips that one too. So the finished plan is also checked as a
  whole (`_check_coverage`), and the last operation that cost a must-have is rejected — the same shape as the
  existing stuffing check. A person's own hand-edit (`source="user"`) is never the culprit: their wording wins.
- `reward()` replaces the hard zero over the page limit with `total * 0.5 ** pages_over`, which keeps the
  ordering (shorter still wins) without making every long candidate identically worthless.
- The `bold` arm, which actively tells the model to drop bullets, now says "never the only bullet that
  mentions a must-have", so retries aren't spent on predictable rejections.

On the user's own resume and job, this protects exactly two bullets — between them they carry every must-have
that resume can back.

## 21. The ATS rules the tool actually knows

The planning prompt had exactly one line of writing guidance: "Start each bullet with a strong past-tense
verb, keep its metric, and make the result clear." Everything else it knew was about *this* job's keywords.
So a resume could gain keywords and still be full of "Responsible for maintaining the payments API".

[docs/ATS.md](ATS.md) now writes down what actually raises a score — what an ATS really is (a database with a
search box, so extractable text comes first), why a term in a bullet is worth 1.0 and the same term in a
skills list 0.6, how to write a bullet (what/how/result, strong verbs, tools named in the sentence, quantified,
60-220 characters, no first person, past tense, varied verbs), and the document rules (standard headings, one
column, no tables, contact details in the body, no icon fonts, ligature fix, consistent dates). It ends with a
table mapping every rule to the module that enforces it, and a test fails if the two drift apart.

The same rules go to the model as `ATS_RULES`, injected into the planning prompt **after** the numbered
guardrails, so "quantify the result" is read as subordinate to "never invent" — and the rule itself says so:
*"Quantify by KEEPING a number that is already in this entry or in evidence you cite. Rule 1 still wins."*
About 230 extra tokens on a prefix-stable prompt, and no extra model calls.

The honesty section is the part worth keeping: every other rule is presentation, and none of them is a licence
to add something the person didn't do. A score near 100% on a job you don't match is a failure, not a win.

## 22. Measuring how well the resume is written, not just how well it matches

Everything the tool scored was about *this* job: keyword coverage, title alignment, parse health. So a
resume could gain keywords and still be full of "Responsible for maintaining the payments API". The user
asked for the general improvements too — "things which generally increase ATS regardless of the JD".

`ats/quality.py` measures ten of them on the parsed LaTeX alone. **No PDF needed**, unlike every
`parse_health` check, so a resume that doesn't compile still gets useful feedback: bullets opening with a
verb doing work, quantified results, saying how or what changed, length, third person, tense agreement,
dated entries, contact details, single-column layout, and varied opening verbs.

`reward.WEIGHTS` already reserved 0.10 for `bullet_quality` and nothing ever filled it, so it had been a
constant 0.5 for every candidate and cancelled out. It now carries this score, which is what makes the
general rules actually bite: with keyword coverage tied, the better-written candidate wins.

**Tuning it against the sample resume caught four checks that were wrong, not the resume:**
- An enumerated verb list will always have holes ("Containerized", "Backfilled"), so any past-tense verb
  counts and only the genuinely weak openers are rejected.
- A result is phrased many ways: ", ending the missed run", "that removed race conditions", "which cut
  latency". Matching only "resulting in" flagged good bullets.
- `structure` required a strong opener too, charging one sentence twice for a fault `action_verb` already
  counted.
- Date formats only have to agree *within* a section: a project dated "2024" beside a job dated
  "Aug. 2021 - May 2025" is ordinary resume style.

**Two things worth knowing:**
- `validate.metrics()` is deliberately greedy because it decides what a bullet may not invent. Measuring
  quantification needs the opposite bias, so `result_metrics()` drops version numbers: "Python 3" and
  "Django 4.2" say nothing about impact, while "40%", "900ms" and "1,200 merchants" do.
- The length ceiling can't be `doc.bullet_budget`, which is 1.15x the longest bullet already present — a
  long bullet would raise its own ceiling and never read as long. It is a fixed 60-240 characters.

Failing checks become recommendations in a new **Writing** group, quoting up to three of the offending
bullets, and a check the resume passes is never mentioned. The shipped template scores 0.97, and a test
fails if it ever drops below 0.9 — a canary for a new check being too harsh.

**Note:** absolute reward values shift with this change, so a run saved before it isn't comparable. The
bandit compares arms within a context, so its learning is unaffected.

## 23. What a change is worth

The result page had percentages but no way to answer "is this worth doing?". The user wanted each suggestion
to say how much ATS it would add. `ats/gain.py` computes that from the weights the reward already uses, so
there is one definition of the score in the codebase rather than two that can drift apart.

**The formula.** A must-have is worth `0.40 x its weight / the weight of every must-have`; a nice-to-have
draws on 0.15 the same way. Moving a keyword from *missing* to *in a bullet* earns the whole share; from
*only in the skills list* to *in a bullet* earns 40% of it (1.0 vs 0.6); losing it costs exactly what
gaining it earns. With must-haves weighted 3, 3, 2, 2, 1 (sum 11), adding the first is `0.40 x 3 / 11 = +10.9%`.

**It is checked against the real scoring function**, not against a restatement of its formula: a test builds
`TermCoverage` items, runs them through `coverage_scores`, and asserts the measured change matches
`term_gain` for every must-have.

**Three numbers on the result:**
- `ats.before` / `ats.after`: one composite score using the reward weights, and **not gated on page count**
  unlike `reward()` — a two-page resume still has a real keyword score, and this number is for showing people.
- `changes[i].gain` and `.terms`: what each change already made is worth. Walked in order with a running
  picture of the resume, so a keyword added by two changes is credited to the first only and the figures can
  be summed without double counting. A change that removes a term's last mention scores negative.
- `gains.gaps`: what each keyword nothing backs would add *if the person could back it*, biggest first. On the
  user's own run: Generative AI +4.5%, TensorFlow, PyTorch, Scikit-Learn and Statistics +3.8% each, Computer
  Vision +3.0%; together up to +22.7%. That list is what the "needs your input" panel will offer.

Gap gains are independent estimates, not additive across a whole set, so the interface will say "up to".

## 24. Asking for what the resume doesn't show

**The direction change.** The tool used to drop any job keyword it couldn't prove and say nothing useful about
it: a real run scored 58% because four of nine required skills appeared nowhere in the person's material. The
user's point was that the goal is a resume as close to the job as *honestly* possible, and an honest way to
close a gap is to ask the person for the missing material, not to stay quiet.

**Flow.** After a run, the keywords nothing backs are listed with what each would add (+4.5%, +3.8%, ...). The
person writes anything about one — a line, a paragraph — and `POST /api/runs/{id}/answers` does the rest:
1. Their words are stored as permanent context, so every later tailoring can use them and pgvector can find
   them by meaning.
2. **One** model call drafts a bullet from each answer (a batch, not one call per answer: a Gemini free key
   allows about twenty a day).
3. Every draft is validated, with the answers in the evidence list.
4. The drafts come back **unapplied**. Nothing in the saved resume changes until the person accepts and the
   ordinary rebuild applies them. Their choices are now stored, so reopening a run shows what they accepted
   rather than every suggestion accepted again.

**Why this doesn't break "never invents".** The person's sentence *is* the evidence, so the checks that were
already there now run against it: a drafted bullet may only name tools and numbers that appear in what they
said or in the entry it lands in. A test has the model add TensorFlow to an answer that only mentions
PyTorch, and an 80% to an answer that says 30%; both are rejected.

**A trap that was avoided.** `Op.source == "user"` skips every fabrication check, which is right for text a
person typed into the diff editor and wrong here, where a model writes the bullet. Drafted operations keep
`source="model"`, and a test asserts it, because the shortcut of marking them user-written would have
silently switched all four checks off.

**Details that mattered.**
- An answer is stored as a `fact`, the only source the validator lets back a bullet in any section (`skill`
  evidence may only reach the skills line; `github` and `portfolio` only projects).
- Ids are `ans1`, `ans2`, ... The notes editor only ever touches `n1`, `n2`, ..., so a notes save can't delete
  an answer. The endpoint refuses (409) rather than return drafts if storing had to renumber, since a bullet
  citing evidence that doesn't exist can't be applied.
- **A thin answer gets a question, not a bullet.** "I know PyTorch" has no project or outcome to write from,
  so the model returns no operation and one follow-up ("What did you build with PyTorch, and what changed
  because of it?"). A one-line claim is turned away before any model call is spent.
- An answer that never says "PyTorch" doesn't quietly add it to the item's skills just because they were asked.
- The draft sees the resume **as the person has already changed it** while keeping the original block ids, so
  it composes with earlier accepted changes in one rebuild. A draft that lands on a block they already changed
  says it replaces it.
- One repair pass on a rejected draft, then stop: each round costs a call.

**Not built (v1).** There is no operation that creates a whole new entry; only bullets can be added to an
existing one. A brand-new project would need the parser to keep a heading's structure so it can be cloned.
The interface will say this plainly instead of pretending.

## 25. A result page for people, not for the pipeline

**The complaint:** "too much stuff that makes users go nuts: ATS parse health, pages, title alignment, before
and after... I don't know what's happening." The page opened with five score tiles, five tabs, and a button
that did nothing.

**What it is now**, two columns:
- **Left:** one score (`51% -> 60%`, with a dotted "~" while a choice is pending), a plain paragraph of what
  happened and what is left, the changes, the "skills we can't find" panel, and one collapsed *Details*.
- **Right, sticky:** the resume itself, PDF or LaTeX, updating as choices are applied. A spinner overlay shows
  while it rebuilds.

Parse health, pages, title alignment, the keyword matrix, the writing checks and the refused edits all moved
into the collapsed *Details behind the score*. The five tabs are gone.

**Accept, not remove.** Each change is a checkbox; ticked means it is in the resume, with its own `+4.6% ATS`
beside it. The server has already applied and compiled everything, so the PDF and the measured score are
instant. Unticking moves an *estimate* (the measured score plus the worth of what is now in, minus what the
preview already shows) with no round trip, and an **Apply** button rebuilds once. "Review one by one" unticks
everything for people who want true opt-in. I chose this over a literal "nothing applied until you accept" because
that needs the *original* PDF too: either ~250 KB more per saved run, or an extra LaTeX compile every time a run
is opened.

**"Skills the job wants that we can't find"** is where the direction change lives. Each unbacked skill carries
`up to +3.8%`; opening it gives a text box that takes a line or a paragraph and a "where does this belong?"
choice; **Write bullets from my answers** makes one model call for all of them. The drafted bullets appear
*above* the list, unapplied, with "Add to my resume" or "Not this one". The panel says plainly that it only adds
bullets to entries that already exist.

**Bugs found by driving it in a real browser against real Postgres:**
- The button was disabled unless the *person* had a saved key, but a deployment can supply its own
  (`server_key`). The server is the right place to decide, so the client now checks both.
- **A skill the person had just answered was still offered as missing.** The rebuild updated the score but
  `keywords` and `gains.gaps` were snapshots from the original run. `rebuild()` now returns a refreshed keyword
  table and gap list and the run stores them. A regression test pins it.
- My first draft called a hook after an early return (a rules-of-hooks violation) and kept the "what the preview
  reflects" state as JSON strings that had to be re-parsed; both are gone.

**Reopening a run** now shows what the person chose (`accepted_ops` is stored), so a run they trimmed doesn't
come back with every suggestion ticked.

## 26. A resume that won't compile, and a project TailorTeX can't create

**The user's resume didn't compile**, so every run said "your original resume doesn't compile, so PDF checks
are off": no PDF, no readability checks, half the score tiles empty. The error was `There's no line here to
end`, at line 33.

**Cause.** A hand-written header: `\begin{center}` and then `\\[2pt]` as the very first thing inside it. A
line break has to end a line of something, and there was nothing before it. Removing that one line makes it
compile to one page, 84% full, with all six parse checks passing. It is a common mistake in hand-written
headers, so it is handled in three places rather than only in this one file:

1. **Lint, with a one-click fix.** `find_stray_breaks` finds a `\\` that is the first thing after a blank line
   or after `\begin{center|flushleft|flushright|document|...}`, skipping comment lines, and leaves breaks after
   real text alone. It names the line, and the resume editor already shows a "Fix it" button for any fixable
   lint issue, so the person sees it before they ever tailor. The fix removes the whole line, or just the break
   if there was text after it.
2. **Tailoring repairs it.** If the original won't compile and a known fix makes it compile, the run uses the
   repaired file, says so in words ("line 33 starts with a line break with nothing before it to end. We removed
   it in this version so you get a PDF. Remove it from your Overleaf file too."), and stores the *repaired*
   source, because a later rebuild starts from the stored source and would otherwise fail on the same line. A
   repair is only adopted if the fixed file really compiles, so it can't make things worse, and an error we
   don't recognise is reported exactly as before.
3. The user's stored resume was fixed directly (one line removed; the original is kept in their earlier runs).
   They still have to remove it from their Overleaf file, since that is where the resume really lives.

**A new project can't be created, so we write the code.** The parser can edit the bullets of an entry that
exists but can't create an entry, which needs a heading's structure to be cloned. Rather than pretend, "It was
a separate project" in the skills panel asks for a name, dates and technologies and returns **LaTeX to paste
into Overleaf**, in the style the resume already uses:
- `jake`: `\resumeProjectHeading{...}{...}` with `\resumeItemListStart`, for Jake's template and its variants.
- `hfill`: `\textbf{Name} \hfill dates \\`, a `\textit{Tech: ...}` line and an `itemize`, which is exactly how
  the user's own resume writes projects. Judged from the first project already in the file.
- Every piece of text, including the name and the dates, goes through the escaper, and a test feeds it
  `\input{evil}` and `\write18` and compiles the result.

The card gives numbered steps (copy, paste *after your last project*, recompile), a Copy button, a button that
opens the whole resume in Overleaf with the block already inserted, a check that the resume **still compiles**
with it and its **page count against the limit**, what it adds to the ATS score, and a short note on why the
block is ATS-safe.

**It is still checked against what the person said.** A project has no entry to borrow facts from, so its
bullets are validated against *only* their answer plus the name, technologies and dates they gave
(`check_standalone_bullet`): a tool that isn't in there is refused, a number that isn't is refused, and the
dates they typed are allowed as numbers but a different year is not. A refused draft becomes a question, not
silence. One model call still covers every answer, whether it is about an existing job or a new project.

**A dip that wasn't visible.** A real run on the user's account came out at 40.4% -> 40.0%. The keyword guard
was fine; a rewrite had made a bullet read slightly worse (writing quality 95% -> 90%). The score now says so:
"This version scores 0.4% lower than your original. It mostly comes from how the reworded bullets read... Untick
the changes that don't help." A test covers both directions, so it doesn't cry wolf when the score rose.

## 27. "The skills are already in my projects. Why can't it find them?"

**Found by the user,** looking at a panel that listed nine skills with a text box each: "I implemented these in
my projects on GitHub and my earlier resume. If the model reasoned over my context it could find them. Use
vectorization, and remember it's unique for every user."

They were right about the design and partly right about the data. Checked against their real account:

**The vector search was real and it worked.** `BAAI/bge-small-en-v1.5`, 384 dimensions, every entry embedded.
Asked for "Generative AI" it returned the user's own CrewAI agent pipeline (0.70) and RAG-powered LLM pipeline.
But it was only used to choose which entries to *show the model* for the job as a whole. Whether a skill was
*backed* was decided by a plain word match, so "Generative AI", which isn't written anywhere, was "missing", the
model was told not to add it, and the person was asked to prove something their resume already showed.

**The data was thinner than they thought.** Their context held zero GitHub entries (the link was saved, nothing
imported) and one LinkedIn post shredded into 14 fragments, from before notes were split on blank lines. Their
3 public repos (DealFlow360, TailorTex, Arista-App) don't mention TensorFlow, PyTorch or scikit-learn, so for
those there is nothing to find. Both were repaired for their account: the fragments are one entry again and the
repos are imported.

**Semantic support.** For each job skill that isn't written out, `evidence/support.py`:
1. embeds the skill and searches the person's own passages, their context entries and their resume's bullets
   (nobody else's), taking the top four per skill;
2. asks the model once, for all skills together, whether any passage shows the work;
3. accepts an answer only if the model **quotes the person's own words back verbatim** (checked as a substring,
   ignoring case, spacing and bold markers) and the passage is one it was actually shown.

Two rules keep it honest. A **tool, library or product** counts only if the passage *names* it, and this is
checked in code, not taken from the model's `how` field: a model that says "named" about a quote that doesn't
contain "TensorFlow" is refused. A **broad field** (machine learning, generative AI, statistics) can be shown by
describing the work. A related tool proves nothing: LangChain doesn't show PyTorch.

On the user's real data it found exactly one: *Generative AI*, quoting "RAG-powered LLM pipeline" from their
Multimodal Interview Analysis project, and left the tools alone. With it counted as evidence the planner rewrote
that bullet with the job's wording, worth +3.8% ATS where every change had been +0.0%.

**Scoped, so it can't move a skill between jobs.** Something found in one resume entry can back bullets only in
that entry (or the summary and skills lines), enforced in the validator with a new `scope` on the evidence item.
The findings are stored on the run (`inferred_evidence`) and brought back on every rebuild, or a change citing
one would fail to validate when applied.

**The panel became a conversation.** The user's second point: it lists everything and asks for input on all of
it, which is vague. It is now a chat (`SkillChat`): one skill at a time, most valuable first, with the reason
("required, worth up to +5.3% ATS"). Skipping ("no", "haven't", the Skip button) costs no model call, and a
reply too short to write from is asked to say more without one. **The server decides where a reply belongs**,
instead of making the person choose: work done inside an existing job or project becomes a bullet there; a
separate project becomes LaTeX to paste into Overleaf; if the reply names no project and it isn't clear which
entry it belongs to, the assistant asks ("What was the project called, and roughly when?") and the next reply is
combined with the first. A project name, dates or technologies that the model produced but the person never
wrote are dropped: an invented tidy name for their project would be a fabricated fact about their resume.

**A flaw the browser test found:** every reply was saved to context, including the ones that produced nothing, so
an unfinished first reply was kept as `ans1` and the finished one as `ans2`. Only a reply that produced a bullet
or project is saved now.

## 28. First contact with a real model

Everything that turns a typed reply into a bullet had only ever run against a scripted model. Four synthetic
replies (written for the test, not the user's experience, nothing saved) were sent to Gemini, and two of the
four came back wrong. Both were prompt faults, not code faults:

- **"It worked well" became "enabling successful classification".** The rule for a bullet with no number said to
  "end on a concrete outcome in words instead", which pushes a model to make one up. The validator can't catch
  this: no tool, name or number was invented, only a vague overclaim. The rule now says to state a result only
  if one is stated, and otherwise to end on what was built or done. The same wording was in the planning prompt.
- **A reply naming a project, its date, its tool and its accuracy got a question.** The draft prompt told the model a
  new project needs two to four bullets, so a reply that supported one was "too thin". One strong bullet is
  enough, and a follow-up is only for a reply that doesn't say what was built or with what.

After the fixes, against the real model: work inside an existing project became a bullet with the exact numbers
given; a separate named project became new-project code, keeping its name and date; a vague reply got a
question; and "it worked well" got "what problem did it address, and what was its impact?" instead of an
invented result. Tests now assert neither prompt asks for an unstated outcome.

**What this does not settle:** four replies is a smoke test, not an evaluation, and the validator still can't
catch a vague overclaim. That is why every drafted bullet is shown for the person to accept before it goes in.

## 29. "I said add it to my skills and it didn't"

**Reported by the user:** "What's happening in the chat? I told it to add a skill and it still wasn't doing it. Maybe I have
a skill but not a project for it. The system should be intelligent, not hardcoded: do what the user says."

Two separate causes, one visible and one not.

**1. The tool couldn't edit their Skills section at all.** All four of the user's Skills lines were *locked* ("uses LaTeX
formatting inside the list"). Their resume separates skills with `\textbullet{}`. The text layer already converts
`\textbullet{}` to a bullet and back in both directions, but a strict check treated any `{}` as formatting and locked the
line. So there was nothing the tool was allowed to change, whatever the person said, and the chat never said so. A
line that uses `\textbullet{}` or `\textperiodcentered{}` as a separator is now editable, and an edit keeps the line's own
separator (a bulleted line stays bulleted, a comma line stays comma). Checked on the user's resume: an edit round-trips as
`\textbullet{} PyTorch`, compiles, stays at one page. Where a line genuinely can't be edited, the assistant now says so
and gives the exact code to paste, instead of silently doing nothing.

**2. The chat was a script.** Regexes on the client decided whether a message meant "skip", a length rule decided whether it
was too short, and the server insisted on a project name. So "I know PyTorch but I don't have a project for it" matched
"I don't have" and was skipped. Both are gone. Every message now goes to the assistant with the conversation so far and the
list of skills the job wants, and it decides what the person means:

- *they have a skill* (with or without a project) → put it on the Skills line it fits; **no project is asked for**;
- *they describe work* → a bullet on an existing entry, or code for a separate project; both if they said both;
- *they haven't done it or want to skip* → skipped, nothing changed;
- *a question or a remark* → answered, nothing changed, and it doesn't count as dealing with the skill;
- *a skill the job never listed* → treated the same: they decide what goes on their resume.

The assistant only proposes the next skill. It is not asked in the middle of a question, and the person can steer anywhere.

**What stays in code, deliberately.** The model decides what a message means; code does it and checks it. A skill edit is built
in code, not left to the model, so the line keeps its separator and nothing else on it changes. A skill the person's own words
don't contain is refused *on its own*: an added "Kubernetes" doesn't cost them the "PyTorch" they did name. A skill they state
is theirs to state, so it joins **Skills you can defend** (where My context shows it) and not a "fact" entry: an early version
stored "add tensorflow in skills" as a fact, which every later resume would have read as evidence they *used* TensorFlow.

**Bugs the tests and the browser found:** a question marked Statistics "handled", which would have stopped the chat asking about
it; and two skills added one after the other both rewrote the same line, so applying both dropped the second silently. Pending
edits to one line now merge into a single cumulative card, and only the latest version of a line counts.

**Against the real model** (Gemini, the user's own resume, nothing saved): "add tensorflow in skills" added it to Frameworks &
Libraries in their style; "I know PyTorch but I dont have any project for it" added it and asked for no project; "no I haven't
used scikit-learn" skipped it; "why do you keep asking about statistics?" got a real answer and changed nothing.

## Test status

233 backend tests pass with a PostgreSQL available (`TAILORTEX_TEST_DATABASE_URL`; the database tests skip without one), including real pdfLaTeX compiles, the compiler's safety checks, a full pipeline run with a scripted model, and account, privacy and ranking tests against real PostgreSQL. CI runs them with a Postgres service. The frontend type-checks, lints clean and builds.

## 30. Tested against many resumes, not the one it was built around

A corpus of twelve differently written resumes (`backend/tests/corpus/resumes`: article class, tabular
layout, custom macros, two-page academic, description-list skills, photo header, accented text, and
moderncv / awesome-cv styles) plus the Jake template now runs through `tests/test_corpus.py`.

What it found: 13 of 21 inline constructs (italics, monospace, underline, small caps, math with scripts,
forced line breaks, accents outside Latin-1) were silently changed when a bullet was rewritten, because the
text layer reads them but can only write bold back. Fix: a bullet or skills line that contains one of those
is now locked with a reason instead of being edited, so the template is never damaged. The trade-off is
that such a bullet can't be tailored; carrying italics and monospace through a rewrite is the next step.

Still open: skills lines are only detected as editable in labelled-line styles (`\item \textbf{Label:}`,
`\textbullet{}` lines, tabular rows). A plain comma paragraph under a Skills heading falls back to
"paste this code".

## 31. The whole ask at once, and a click that edits the LaTeX

Three complaints, one cause. "Add all of them" added one skill; the reply said it had added them anyway; the
ATS score didn't move. The chat asked the model to decide every addition, and the model returned one skill per
turn, then drip-fed the rest one question at a time.

- **The list comes first.** Every skill the job asks for that the person's material doesn't show is listed
  together, ticked, with what each is worth. The conversation underneath is for work they actually did.
- **Adding them doesn't go through a model at all** (`add_skills`, `POST /runs/{id}/skills`). It is a plain
  edit to their LaTeX: find the right Skills line, keep its separator, skip what the resume already says. So
  it can't half-fail, and it works with no model key.
- **Which line a skill lands on is decided by meaning**, by the same local embedding model that indexes their
  context, so PyTorch doesn't land under "Programming Languages" and no table of what counts as a language or
  a framework is needed for a resume outside software.
- **A reply can no longer claim an addition that didn't happen**: if nothing was added, it says so and why.
- **The estimate moves when a chat change is accepted.** It only counted the suggestions from the run itself,
  so accepting a skills line changed nothing on screen until Apply.

### Why adding a skill changed nothing

The op was written with `evidence=["skills"]`, which exists only while the person's confirmed-skills list
still holds that term. On Apply the resume is rebuilt from the original source and validated again, the
evidence wasn't there, and the op was dropped into a warning nobody reads: no change to the file, no change
to the score, and nothing left after a reload.

A skill the person ticked from the job's own list, or stated in their own words, is their edit to their own
list. It is now stamped `source="user"` with no citation, so it applies on every rebuild. Bullets the model
writes still keep `source="model"` and every fabrication check, and there is a test that says so. The result
page also lost accepted chat changes on reload, because it only restored ops citing an answer; it now restores
anything accepted that wasn't one of the run's own suggestions.
