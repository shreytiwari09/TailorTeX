# TailorTeX: frontend design brief

> Built: the app in `frontend/src/app/` follows this brief and the Stitch design made from it. This file stays as the record of what was asked for.

Use this to design the app in Google Stitch. Paste **"1. Global brief"** first, then paste **one screen section at a time** (each starts with a one-line prompt you can use as is). The last section ("For developers") is not needed for design.

---

## 1. Global brief

**Product.** TailorTeX tailors a person's LaTeX resume to every job description. Their own template stays intact, it always compiles to a PDF, and nothing is invented: every new skill, tool or number is checked against the person's real background. It also gives honest ATS (applicant tracking system) advice.

**How it works for the user.** They sign in once, build a permanent profile of themselves (details, reference resume, and a private knowledge base from GitHub, portfolio, LinkedIn and notes). After that, for each job they paste the job description and get a tailored resume, a PDF, and prioritized ATS recommendations, in about a minute.

**Who uses it.** Students and engineers applying to many jobs, who already keep their resume in LaTeX (usually on Overleaf). Comfortable with tech, short on time, allergic to fluff.

**Design principles**
- **Calm and trustworthy.** This tool touches people's career. Clean, generous whitespace, no gimmicks, no stock-photo hero.
- **One thing per screen.** Each page has a single primary action. Setup is a guided flow of separate pages, not one long form.
- **Don't over-explain.** Labels are short. Anything that needs explaining gets a small **"i" info icon** that opens a popover (content is listed under each screen). Never add paragraphs of help text.
- **Show proof.** The product's value is trust, so make "checked" states visible: green ticks, "kept as is" locks, "blocked: not in your background" markers, before/after numbers.
- **Fast feeling.** Skeletons and live progress instead of spinners. Autosave with a small "Saved" indicator.
- **Responsive.** Works on a phone (single column) and on desktop. Light and dark themes.

**Voice.** Plain, short, second person. "Add your GitHub", not "Please provide your GitHub repository URL". No exclamation marks, no emoji.

**Colour and type (decide freely).** One confident accent colour (currently indigo `#4f46e5`), neutral greys, semantic colours: green = supported/kept, amber = warning, red = blocked/error. A clean sans (Inter or similar) and a monospace for LaTeX. Corners 10 to 14 px, soft shadows.

**Navigation.** Signed-out: a slim top bar with the logo. Signed-in: top bar with logo, "Resumes", "My context", and an avatar menu (Settings, Sign out). Onboarding hides the nav and shows "Step N of 4".

**Reusable components** (design each once): top bar, stepper ("Step 2 of 4" with a progress line), card, input with label and inline validation, textarea, file drop zone, primary/secondary/ghost buttons, "i" info popover, status pill (green/amber/red/grey), chip (removable), tabs, toast, empty state, skeleton, score tile (big number + delta + small bar), diff view (word-level red strike/green highlight), confirmation dialog.

---

## 2. Screens

Screens in flow order. **Onboarding runs once; the rest are the everyday product.**

### S1. Landing / sign in
> *Prompt:* "A minimal sign-in page for a resume tailoring tool. One headline, a Continue with Google button, an email option, and a quiet 'Try the demo' link."

- **Headline:** "Tailor your LaTeX resume to every job." Sub: "Your template stays intact. Nothing gets invented."
- **Actions:** `Continue with Google` (primary) · `Use email instead` (expands email + password, with "Create account" / "Sign in" toggle) · `Try the demo` (text link, no account).
- **Below, three tiny proof points** (icon + 4 words): "Template untouched" · "Always compiles" · "Nothing invented".
- **States:** loading on the button; error under the field ("Wrong email or password", "That email already has an account").
- **"i" on Try the demo:** "Explore with a sample resume and background. Nothing is saved."

### S2. Onboarding 1 of 4: About you
> *Prompt:* "A friendly onboarding step asking for a person's basic details: name, headline, location, phone, public email and profile links. Stepper at the top, one Continue button."

- **Fields:** Full name (required) · Headline ("Backend engineer") · Location · Phone · Public email (prefilled from sign-in) · Links: LinkedIn, GitHub, Portfolio, Other (add more).
- **Actions:** `Continue` (primary) · `Skip for now` (optional fields only; name required).
- **"i" on the page title:** "Used to name your files and personalize suggestions. We never change the contact details inside your LaTeX."
- **"i" on Links:** "We read GitHub and your portfolio in the next steps. LinkedIn works differently; you'll see why there."

### S3. Onboarding 2 of 4: Resume and model
> *Prompt:* "A setup step with two sections: paste the LaTeX source of a resume with a live check of what was recognized, and connect an AI model with an API key. Clear success states."

**Resume section**
- **Big paste box** (monospace) with placeholder "Paste your resume's LaTeX, from \documentclass to \end{document}". Buttons: `Paste from clipboard` · `Upload .tex`.
- **Small how-to under the box:** "In Overleaf: click in the editor, Ctrl/⌘ A, then Ctrl/⌘ C." (one line)
- **Live result card once pasted:** template name pill ("Jake's Resume"), "4 sections · 11 bullets · 14 editable", link "Show what we see" (opens an outline: sections, entries, bullets; locked ones show a lock icon and "kept as is").
- **Warnings** (amber notes with a fix button where possible): "Looks like only part of the file", "Your resume loads other files from Overleaf (sections/x.tex)", "Includes an image; remove?", "Custom class not available; we can tailor it but can't compile here".
- **"i" on the title:** "Only bullets, the summary and skills lines change. Education, headers and everything else stay exactly as written."

**Model section**
- **Provider chips** (Google Gemini, Groq, OpenAI, Anthropic, OpenRouter, Mistral, DeepSeek) with tiny "free tier" tags on Gemini, Groq, OpenRouter, Mistral. Key input (password style, Show/Hide). The provider is detected from the key and its chip lights up.
- **Live check:** spinner → green "Key works · 31 models" → a model dropdown with the recommended one preselected. Red state: "Rejected by Gemini. Check the key."
- **"Get a key" links** per provider (opens the provider's key page).
- **"i" on API key:** "Your key is stored encrypted in your account and used only for your requests. Delete it any time in Settings."

- **Actions:** `Continue` (enabled when resume recognized and key works).

### S4. Onboarding 3 of 4: Build your context
> *Prompt:* "A step where a person connects GitHub, a portfolio site, a LinkedIn PDF and free-text notes so an AI can learn about them. Each source is a card showing what was extracted, with edit and delete."

Four source cards in a grid. Each card: icon, title, one input, status, and after import a list of extracted **entries** (title + one-line text + skill chips; edit and delete per entry).

1. **GitHub**: input "github.com/yourname" → `Read`. Result: "Added 6 repositories" with entries per repo (name, description, languages). A link "Choose different repos".
2. **Portfolio**: input "yourname.dev" → `Read`. Result entries: projects and roles found. Error: "That page needs JavaScript to show its content. Paste its text instead."
3. **LinkedIn**: drop zone "Drop your LinkedIn PDF" with a tiny "How to get it" popover: "On your profile, click More, then Save to PDF." Result entries: roles, projects, skills, certifications.
4. **Anything else**: textarea "One thing per line, in your own words" + `Save` (Ctrl/⌘ Enter). Saved lines appear as entries. Placeholder examples: "Won 2nd place at DevHacks 2025 with a Flutter app".

- **Header progress chip:** "18 entries" (updates live) so the person sees the knowledge base growing.
- **Actions:** `Finish setup` (primary; allowed with zero entries) · `I'll do this later`.
- **"i" on the title:** "This is your private knowledge base. When you tailor a resume, TailorTeX finds the parts of it that fit the job and only adds what's backed here."
- **"i" on LinkedIn:** "LinkedIn doesn't let apps read profiles from a link, so its own PDF export is the reliable way. It's read once and not stored."
- **"i" on Anything else:** "Say where something happened so it lands under the right job. Numbers are used exactly as you write them."

### S5. Onboarding 4 of 4: Done
> *Prompt:* "A short success screen after setup, summarizing what was saved and offering to create the first tailored resume."

- Check icon, "You're set up". Three small stat tiles: `Resume: 14 editable blocks` · `Context: 18 entries` · `Model: Gemini 2.5 Flash`.
- **Actions:** `Tailor my first resume` (primary) · `Go to dashboard`.

### S6. Dashboard
> *Prompt:* "A dashboard for a resume tailoring tool: a prominent New resume button, a profile strip, and a list of past tailored resumes as cards with before/after scores."

- **Profile strip** (top): avatar, name, headline; chips "Resume ✓", "Context · 18 entries", "Model · Gemini". Link `Edit profile`.
- **Primary card:** `New resume` (big).
- **Past resumes grid/list:** each card shows job title, company, date, a before → after must-have percentage ("63% → 87%"), an "ATS 100%" pill, and actions `Open` · `PDF` · `Delete`. Newest first.
- **Empty state:** "No tailored resumes yet" + `Tailor your first resume`.
- **"i" on the percentages:** "Share of the job's must-have keywords found in your resume, measured on the text a parser extracts from the PDF."

### S7. New resume (paste the job)
> *Prompt:* "A focused page with one big text area to paste a job description, a few quiet options, and a single Tailor button. After pressing it, live progress steps appear."

- **Textarea:** "Paste the full job description". Live word count. Optional link input "or paste the job link" (Greenhouse/Lever), if supported later; hide for now.
- **Options (collapsed under "Options"):** Quality: `Fast` / `Best of 3` · Page limit: `Same as my resume` / 1 / 2.
- **Primary:** `Tailor` (disabled until text pasted).
- **Live progress** (replaces the form once running; vertical steps with a check as each completes, plus a one-line detail): 1 Reading your resume · 2 Reading the job · 3 Matching your background ("Using 12 of 18 entries") · 4 Planning edits · 5 Checking every edit ("3 blocked, sent back") · 6 Building the PDF · 7 Fitting to one page · 8 Scoring. A `Cancel` link.
- **"i" on Quality:** "Best of 3 tries three approaches and keeps the best. It uses about three times as many tokens."
- **"i" on Options:** "Page limit defaults to your resume's current length."

### S8. Result (the main screen)
> *Prompt:* "A results page for a tailored resume: a header with job and export actions, five score tiles with before and after, and tabs for Changes, ATS recommendations, Keywords, Guardrails, PDF and LaTeX. Changes are word-level diffs with keep, revert and edit."

- **Header:** job title · company, "6 changes · 3 blocked". Actions: `Download PDF` (primary) · `.tex` · `Copy LaTeX` · `Open in Overleaf`.
- **Score tiles (5):** Must-have keywords, Nice-to-have keywords, Job title match, ATS parse health, Pages. Each: big number, delta chip (+11), before/after bar, tiny caption. **"i" on each** (see below).
- **Tabs**
  - **Changes:** cards, each with a type tag (Rewritten/Added/Removed/Reordered), where ("Experience › Software Engineer"), a word-level diff, one-line reason, evidence chips ("from ledgerly"), and `Keep` · `Revert` · `Edit`. A sticky bar appears when decisions changed: `Rebuild with my choices`.
  - **ATS recommendations (new):** prioritized list, each item: priority pill (High/Med/Low), title ("Add Kubernetes to a bullet"), one-line detail, and an action button when one exists (`Add from my context`, `Confirm I have this`, `Fix in source`). Group headers: Keywords · Title · Format · Space.
  - **Keywords:** table, keyword · must/nice · before/after status (In bullets / Skills only / Missing) · why.
  - **Guardrails:** two lists: "Blocked edits" (rule pill, the refused text, why) and "Left out: no evidence" with `I have this` buttons.
  - **PDF:** embedded viewer.
  - **LaTeX:** read-only code view with copy.
- **Below tabs:** "Suggested from your background": entries from the knowledge base that match the job but aren't on the resume.
- **States:** warnings (amber) at top: "3 pages; limit is 1", "Some structural changes couldn't be applied". Error page if the run failed with a plain message and `Try again`.
- **"i" texts**
  - Must-have keywords: "Share of the job's essential keywords found in your resume. In bullets counts fully; only in the Skills list counts 60%."
  - Nice-to-have: "Same, for the job's preferred extras."
  - Title match: "How closely your job titles match the target title, ignoring words like Senior."
  - ATS parse health: "Checks on the PDF's extracted text: readable text, no broken ligatures, contact details found, standard headings, single-column order."
  - Pages: "Length and how full the last page is."
  - Guardrails: "Every edit is checked in code. Anything not backed by your resume or context is refused."
  - Match figures footnote: "Our own estimate on the PDF's extracted text. Not a score from any ATS vendor."

### S9. My context
> *Prompt:* "A page to manage a person's private knowledge base: filter by source, search, and edit or delete entries. Add-more actions for GitHub, portfolio, LinkedIn and notes."

- **Top:** search box · source filter tabs (All · GitHub · Portfolio · LinkedIn · Notes) with counts · `Add` menu (the four sources from S4).
- **Entries list:** title, source pill, one to two lines of text, skill chips, `Edit` · `Delete`. Inline edit saves and re-indexes ("Updated").
- **Empty state:** "Nothing here yet" + the four add buttons.
- **"i" on the page title:** "TailorTeX searches this by meaning, not just keywords, so 'event streaming' finds your Kafka note."

### S10. Settings
> *Prompt:* "A quiet settings page with sections for profile details, reference resume, AI model key, and a danger zone to delete the account."

- **Profile:** the S2 fields, autosaved.
- **Reference resume:** shows the recognized template and `Replace` (opens the S3 paste flow).
- **Model:** provider, model dropdown, `Change key` (never shows the saved key; shows "Saved · ends …a1b2"), `Remove key`.
- **Account:** email, connected Google, `Sign out`.
- **Danger zone:** `Delete my account and all data` with a confirmation dialog ("This removes your profile, context and every saved resume. It can't be undone.").

### S11. Demo mode
- Same screens with a slim banner: "Demo · sample resume and background · Sign in to save". Nothing persists; the model key field is still required to run.

---

## 3. Global states to design
- **Loading:** skeleton cards for lists; inline spinners only on buttons.
- **Empty:** every list has an empty state with the next action.
- **Errors:** inline for fields; a top banner for page-level; plain language, one fix.
- **Success:** small toast ("Saved") and green ticks; no confetti.
- **Session expired:** modal "Sign in again" that keeps the current page.
- **Offline / server down:** banner "Can't reach TailorTeX. Retrying…".

## 4. Content notes
- App name: **TailorTeX** (capital T, capital T, capital X).
- Never call the model output "AI-generated resume"; call it "tailored resume".
- Terms: "context" = the person's knowledge base; "entry" = one item in it; "guardrails" = the checks that refuse unsupported edits; "must-have" / "nice-to-have" = job keywords.

---

## 5. For developers (not needed for design)

Each screen's data comes from these endpoints (existing endpoints marked ●, new ones ○):

| Screen | Calls |
|---|---|
| S1 | ○ `POST /api/auth/google`, `/auth/signup`, `/auth/signin`, `/auth/signout`, `GET /auth/me` |
| S2 | ○ `GET/PUT /api/profile` |
| S3 | ● `POST /api/parse`, `POST /api/lint/fix`, `POST /api/models` · ○ `PUT /api/profile/model` |
| S4 | ● `POST /api/evidence/links`, `/evidence/profile` · ○ `POST /api/profile/context/{github,portfolio,linkedin,notes}`, `PATCH/DELETE /api/profile/context/{id}` |
| S5, S6 | ○ `GET /api/profile`, `GET /api/runs` |
| S7 | ● `POST /api/tailor` (server-sent events) |
| S8 | ● `POST /api/rebuild`, `/api/feedback` · ○ `GET /api/runs/{id}`, result gains `recommendations[]` |
| S9 | ○ `GET /api/profile/context`, `PATCH/DELETE /api/profile/context/{id}` |
| S10 | ○ `PUT /api/profile`, `PUT/DELETE /api/profile/model`, `DELETE /api/profile` |
| S11 | ● the existing stateless endpoints with the sample from `GET /api/sample` |

Result payload fields used by S8 today: `before`/`after` metrics (`must_have`, `nice_to_have`, `title`, `health`, `checks[]`, `pages`, `page_fill`), `changes[]`, `keywords[]`, `blocked[]`, `left_out[]`, `suggestions[]`, `tex`, `pdf` (base64), `filename`, `warnings[]`, `usage`. Progress events stream as `{type:"progress", stage, status, message}`.
