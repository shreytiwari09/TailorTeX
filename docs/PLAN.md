# TailorTeX plan

The product and technical plan. The research and product thinking here was written on 18 September 2026, before HackDevengers 2.0 started. All code in this repository was written during the 24-hour hackathon window. What was built, and the decisions made while building it, are recorded in [DEVLOG.md](DEVLOG.md).

## Context

Rewriting a resume for every application is slow. TailorTeX is a web app you set up once with your LaTeX resume, GitHub, portfolio, LinkedIn and projects. After that, for each job you paste the job description (JD) and get back a tailored `.tex` file that compiles without errors, plus the PDF, with as many of the JD's keywords as it can truthfully include.

Decisions so far:
- It's a **product for other people**, not just a personal tool.
- v1 is a **web app only**. The Chrome extension moves to v2.
- It takes **LaTeX in and gives LaTeX out**. No Overleaf account link is needed; there's an optional "Open in Overleaf" button.
- **Users bring their own key from any provider:** OpenAI, Anthropic, Google Gemini, Groq, Mistral, DeepSeek or OpenRouter. The key is used only for that user's requests.
- **The product gets better as people use it, through a reinforcement-learning loop** (§5).

Priorities: **(1) ease of use, (2) the best ATS results you can get honestly.**

---

## 1. Research: what already exists and what to take from each

| Product | What it does | What we take | What it lacks that we'll cover |
|---|---|---|---|
| **Teal** (4.9★ extension) | Job tracker, resume builder, tailoring | Each job is one workspace: JD, resume version and status together | Not LaTeX |
| **Jobscan** | The best keyword-match scoring | A clear match report: hard skills, soft skills, title match | Only scores, with 5 free scans a month; doesn't rewrite |
| **Rezi** | Audit against 23 metrics; missing keywords ranked by priority as you type | Missing keywords ranked by priority | Uses its own builder, not your template |
| **Simplify / Jobright** | Autofill on 100+ job portals, JD capture from the page | JD capture from the page (v2 extension) | Not LaTeX |
| **ResumeTailor AI, ResuTex, JobShinobi** | Hosted services that tailor LaTeX resumes (the closest competitors) | Flow: upload .tex or Overleaf zip, paste JD, get .tex and PDF | Don't pull in GitHub or portfolio evidence; no stated no-fabrication guarantee; no BYOK; don't learn from use |
| **ApplyTeX** (open source) | Splits the .tex into addressable statements, splices edits back by character span, locks some sections, keeps an evidence ledger, enforces one page and retries with a more compact version | **Core architecture pattern** | Built as a personal tool |
| **sanjaesuresh/resume-tailor** (open source) | No-fabrication check enforced in code, rejects bad output instead of repairing it, Tectonic, reads schema.org JobPosting plus Greenhouse, Lever and Ashby adapters | **Validators in code, not in the prompt. Compile in Docker, not on serverless.** | Invite-only personal tool |
| **Resume-Matcher** (27k★, open source) | Master resume, tailoring, cover letters, 100+ LLMs | The master-profile idea; supporting many providers | Not LaTeX-native |
| **anushibinj/resume-tailor** | Lists skill gaps with an "Add to resume" button; works with any OpenAI-compatible endpoint | **The user decides on each gap, not the model** | - |

**Where this product stands out:**
1. **Native LaTeX.** It keeps your own template and look and edits only the bullets, byte for byte, instead of regenerating the whole file.
2. **An evidence bank** built from your resume, GitHub, portfolio and LinkedIn. It can **swap in the projects that fit the job best**, not just reword the ones already there.
3. **Two guarantees, enforced in code:** the output always compiles, and it never invents skills, employers or numbers. These hold **no matter which model the user picks**.
4. **Honest ATS checks** run on the text actually extracted from the PDF, not on a made-up "ATS score".
5. **Any key, any provider.** It costs us little to run and your data only goes to the provider you chose.
6. **It learns.** Every accept, reject and edit improves its strategies overall and personalizes it to each user.

---

## 2. What "ATS maxing" really means, based on the research

1. **Parseability comes first.** A LaTeX PDF can fail silently:
   - Ligatures: "fi" and "fl" come out as a single glyph, so a search for "financial" misses. Fix with `\input{glyphtounicode}` and `\pdfgentounicode=1`, plus `\usepackage[T1]{fontenc}` and `\usepackage{cmap}`. With XeLaTeX, use `Ligatures=NoCommon`.
   - FontAwesome icons in the contact line extract as garbage. Replace them with plain labels.
   - Two-column templates (AltaCV, Deedy) and tables used for layout scramble the reading order. Use a single column.
   - Use standard headings (Experience, Projects, Skills, Education). Put dates on the same line as the title. Keep contact info in the body, not in a header or footer.
2. **Most ATSs don't auto-rank you. Recruiters search by keyword.** Greenhouse routes applications to humans with scorecards and doesn't rank them by algorithm. Workday weights **job title match** heavily. Semantic screeners such as Eightfold and Phenom **penalize keyword stuffing**. So:
   - Use the JD's exact wording wherever your evidence supports it.
   - Include both the acronym and the full form once, e.g. "Amazon Web Services (AWS)".
   - Put keywords **in context inside bullets** as well as in the Skills section.
   - Align the headline or title with the target role, truthfully.
3. **No tricks.** Hidden white text and keyword dumps show up in the parsed text and backfire.
4. **A human reads it next.** Use quantified bullets in an XYZ style and put the most relevant items first. Stick to one page for under about 10 years of experience. Name the file `First_Last_Company_Role.pdf`.

---

## 3. User flows (priority: ease of use)

**One-time setup (aim for under 10 minutes; every step except the resume can be skipped):**
1. Sign in with Google or GitHub.
2. **Paste any API key.**
   - The provider is detected from the key's prefix: `sk-ant-` Anthropic, `sk-or-` OpenRouter, `gsk_` Groq, `AIza` Google, `sk-` OpenAI. A dropdown lets you override it.
   - The key is checked with a tiny test call.
   - Then pick a model. We mark a recommended default per provider, based on our eval results, and show an estimated cost per resume.
3. Upload your resume in one of these forms:
   - a `.tex` file
   - an Overleaf project `.zip` (Menu → Download Source)
   - a PDF or DOCX, which the app converts into its ATS-safe default template, based on Jake's Resume (MIT license)
4. Connect sources:
   - **GitHub** username: public API data (repos, languages, READMEs, stars). You pick which repos matter.
   - **Portfolio** URL: fetched and its main content extracted.
   - **LinkedIn**: upload the "Save to PDF" export or the data archive. **No scraping**, since it breaks LinkedIn's terms of service and is fragile.
   - **Extra projects**: free text and links.
5. **Review the evidence bank.** Facts are grouped by role and project, with a chip showing each fact's source. You edit them, then tick "skills I can defend in an interview".
6. The master resume compiles and an **ATS lint report** appears with one-click fixes: preamble unicode lines, icon removal, standard headings, two-column warning. Compile errors in your original file are fixed automatically, and you approve the diff.

**Each job (aim for about 3 clicks and under 60 seconds):**
1. Paste the JD text or a job URL. Greenhouse, Lever and Ashby URLs use their public APIs; other sites use schema.org JobPosting JSON-LD, and if that fails you paste the text.
2. See the **gap chips**:
   - ✅ already in your resume
   - ➕ you have evidence but it isn't in the resume yet (added automatically)
   - ❓ no evidence ("Do you have this? Yes / No"). It's never added unless you confirm.
3. Click **Generate**. Progress streams as it runs: analyzing, rewriting, compiling, checking.
4. You get a side-by-side diff, a PDF preview, and a before/after match report. From there you can:
   - **Copy the LaTeX**, download the `.tex`, or download the PDF
   - **Open in Overleaf**, which uses Overleaf's public `/docs` "snip" API
5. **Give feedback on each bullet: ✓ keep, ✗ revert, ✎ edit, ↻ regenerate.** This takes one click and is what drives the learning loop in §5. There's also an optional steer such as "emphasize backend". Every version is saved under that job.

---

## 4. Architecture

```
frontend/  (React + Vite + TypeScript, a single-page app)
  ├─ key screen (provider detected from the key, live model list), resume, evidence, job
  ├─ live progress (server-sent events), scores, per-change diff with keep / revert / edit
  └─ talks to the backend over REST only
backend/tailortex/  (Python, FastAPI)
  ├─ latex/     scanner with exact offsets, LaTeX <-> plain text, resume parser, span-based editor
  ├─ ats/       term matching with synonyms, coverage, gap chips, title match, parse health, source lint
  ├─ validate/  no invented skills or numbers, locked sections, length, keyword stuffing
  ├─ reward/    reward function (verifiable checks)
  ├─ compile/   TeX Live runner: engine detection, safety checks, timeouts, page count, PDF text
  ├─ llm/       bring-your-own-key client for 7 providers, key detection, prompts, schemas
  ├─ learn/     strategy arms, Thompson-sampling bandit, feedback reward, style memory
  ├─ pipeline/  analyze JD -> plan (N strategies) -> validate/retry -> apply -> compile -> fit -> score
  └─ api/       REST + streaming endpoints; serves the built frontend in production
Docker: one image with TeX Live, poppler, the backend and the built frontend
```

**Why one backend, not a separate compile service:** for a first version one container is simpler to run and deploy. The compile step is isolated behind one module, so it can move to its own service when load needs it.

**TeX Live, not Tectonic.** Tectonic runs only XeTeX, and it fails on standard Overleaf pdfLaTeX resumes: `\pdfglyphtounicode` is undefined, and that's the ATS unicode fix itself. The compiler uses the engine the template expects (pdfLaTeX by default, XeLaTeX or LuaLaTeX when `fontspec` is used), just like Overleaf. Local development can use TinyTeX, and missing packages are installed on demand. Compiling in the browser with WASM (BusyTeX, SwiftLaTeX) is a later cost optimization.

### The tailoring pipeline: how "no errors" and "no lies" are guaranteed

1. **Template profiling (done once at upload).**
   - Parse the `.tex` with unified-latex, keeping character positions.
   - Detect sections and the entry and bullet macros (`\resumeItem`, `\cventry`, `\item` and so on). One LLM call handles unfamiliar templates, and its mapping is checked against the AST.
   - Build **blocks**: `{id, kind: summary|bullet|skills_line|entry, section, span, plainText}`.
   - Mark each block editable (summary, bullets, skills, project selection and order) or **locked** (header and contact, education, employers, titles, dates).
2. **JD analysis** (LLM, structured output). Boilerplate (EEO statements, benefits, pay) is stripped first. The output has: title, seniority, must-have and nice-to-have skills with weights, and their exact phrasings.
3. **Gap analysis** is done in code: normalized JD terms are matched against the evidence bank using a synonym map (K8s ↔ Kubernetes, JS ↔ JavaScript, …) to produce the three kinds of gap chips.
4. **Plan and rewrite** (LLM, structured output, N candidates chosen by the bandit policy, see §5). The model returns **operations, not a new .tex file**:
   - `rewrite(blockId, text)`
   - `drop(blockId)`
   - `reorder(section, ids)`
   - `addBullet(entryId, text, evidenceIds)`
   - `swapProject(outId, inEvidenceId)`

   Text comes back as **plain text with `**bold**` only**, and our own escaper converts it to LaTeX (`& % $ # _ { } ~ ^ \`). **Because the model never writes raw LaTeX, even a weak or cheap model can't break compilation.**
5. **Validators run in code** and reject bad operations:
   - Every tech term, proper noun and number in the new text must exist in the evidence bank, the original block, or the confirmed skills (synonyms allowed).
   - Locked blocks must hash the same as before.
   - Bullets must stay under the template's character budget.
   - Each keyword may appear at most N times.

   A rejected operation goes back to the model with the violation, up to 2 retries. After that, the original bullet is kept.
6. **Scoring and selection.** The reward function (§5) scores each candidate that passed validation, and the one with the highest score is used.
7. **Splice and compile.**
   - Apply edits by replacing spans in descending order, so the untouched source stays byte-identical.
   - Check brace and `\begin`/`\end` balance, then compile.
   - If it still fails, try deterministic fixes first, then an LLM fix using the log and the lines around the error. Maximum 2 tries; if those fail, return the last version that compiled.
8. **Page fit.**
   - `pdfinfo` checks the page count. If it's over the target: drop the lowest-relevance bullet or project, then have the LLM shorten the longest bullets, then recompile.
   - `pdftotext -bbox` checks how full the page is. If it's less than about 85% full, the app may add one more relevant bullet.
9. **ATS check on the final PDF's extracted text:**
   - No ligature or private-use glyphs
   - Email, phone and links found near the top
   - Standard headings in a sane reading order
   - A single-column heuristic based on text x-positions
   - Keyword coverage for must-haves and nice-to-haves, and whether each one appears in context or only in Skills
   - Title alignment

   The result is shown as a clear "match estimate" plus a checklist, not as a fake universal score.

### LLM layer: bring a key from any provider
- **A small client of our own over plain HTTPS** (`httpx`), no provider SDKs. OpenAI, Google Gemini, Groq, Mistral, DeepSeek and OpenRouter all speak the OpenAI-compatible chat API; Anthropic gets its native Messages API. Ollama and other local models come later in a self-host mode, since a hosted server can't reach `localhost`.
- **Structured output everywhere:** JSON mode on OpenAI-compatible APIs, a forced tool call on Anthropic. Every reply is validated against a pydantic schema; a reply that doesn't validate gets one repair retry with the error message.
- **Model lists come live from each provider's API**, because model names change every few months. The same call checks the key without spending tokens. A recommended default is picked per provider from that list.
- **Robustness across providers:** ask for operations and plain text only, so there's no LaTeX for a model to break; the same validators run whatever the model.
- **Key handling:**
  - Keys live only in the user's browser, with an optional "Remember on this device".
  - A key is sent with each request and used in memory for that request only.
  - Keys are **never stored or logged**. Error messages from providers are passed through without the key.
- **Cost estimate per tailored resume:** about $0.06–0.40 on frontier models, and a few cents on Groq, DeepSeek or small OpenRouter models. Best-of-N multiplies it by N, which the user controls.

---

## 5. Learning loop: reinforcement learning in layers

**Constraint:** with users' own keys, we **can't change the weights** of the hosted models they bring. So learning starts in our own layer: which strategy to use, which candidate to pick, and what each user prefers. We train our own model only once there's enough data that users have agreed to share. Each layer below is useful on its own and feeds the next.

**Layer 0: reward function** (`backend/tailortex/reward/`, v1). This is the foundation for every other layer, and most of it can be checked in code:
- **Hard gate:** all validators pass, it compiles, and it's within the page target. Otherwise the reward is 0.
- `R = w1·mustHaveCoverage(in-context) + w2·niceToHaveCoverage + w3·titleAlignment + w4·parseHealth + w5·pageFill + w6·bulletQuality − w7·stuffingPenalty`
- `bulletQuality` is an optional LLM-judge rubric, scored with the user's own model: starts with an action verb, quantified where the evidence allows, specific, under 2 lines.

**Layer 1: best-of-N reranking** (v1). Generate N candidates using different strategy arms or temperatures, score them with R, and show the best. You can also flip to the runner-up. The Quality setting is Fast (N=1) or Best (N=3), because it costs N× on your key.

**Layer 2: capturing feedback and remembering each user's style** (v1).
- Every ✓, ✗, ✎ edit and ↻ regenerate on a bullet is logged as `(context, candidate, action)`, with a normalized edit distance for edits. This is implicit reward.
- **Style memory per user:** accepted and user-edited bullets become few-shot examples. An LLM also periodically distills style rules from them, for example "no summary section", "prefers 'Built' over 'Developed'", "keeps bullets to 1 line". These go into later prompts, so it gets personal without training anything.

**Layer 3: a contextual bandit over strategies** (v1.5). This is online reinforcement learning with a one-step decision, which fits BYOK.
- **Arms** (strategy choices): prompt variant, rewrite strength (light, medium or heavy), bullet style, how aggressively to swap projects, and summary on or off.
- **Context** (what the choice depends on): role family, seniority, provider and model.
- **Reward** per tailored version: bullet acceptance rate − λ·mean edit distance + small bonuses from the Layer 0 score and, in v2, from outcomes.
- **Policy:** Thompson sampling with a global prior shared across all users, plus a posterior per user. Keep 10% exploration and hold off using a per-user posterior until that user has at least 5 tailored versions.
- The bandit decides which strategy the N candidates in Layer 1 use.

**Layer 4: outcome rewards** (v2). The application tracker records each application's status: applied → callback → interview → offer or rejection. Callbacks feed the bandit as a delayed, down-weighted reward, and aggregate analytics show things like "resumes with X had more callbacks". These results depend heavily on the market and the candidate, so they're a small extra signal, never the main one.

**Layer 5: our own trained model** (v3, only with opt-in consent).
- With consent, collect preference pairs: *chosen* is a bullet that was accepted or edited by the user; *rejected* is a discarded candidate or a reverted bullet. Strip personal data first.
- Train an open-weight model of roughly 7–14B parameters (Qwen or Llama class) with QLoRA on Unsloth or TRL, in three steps: **SFT, then DPO** on the preference pairs, **then GRPO** using the Layer 0 reward as a *verifiable reward* (validators, coverage and page fit). This is the RLVR recipe.
- Serve it as a **free "house model"** for users without an API key.
- Start only when there are at least about 5k consented pairs and an eval shows it beats the median model users bring.

**New data tables:**
- `candidates`: version_id, arm_id, provider, model, ops, reward_breakdown (jsonb)
- `feedback_events`: version_id, block_id, candidate_id, action (accept, reject, edit or regenerate), before, after, edit_distance
- `bandit_arms`: arm_id, context_key, scope (global or user), posterior params
- `style_memory`: user_id, rules[], examples[]
- `applications` (v2): job_id, status, status_history
- a `training_consent` flag on each user

---

## 6. Other data tables (Postgres; every table owned by `user_id`, row-level security on)
- `templates`: tex source, storage path of the zip, block_map (jsonb), lint_report
- `evidence_items`: kind (role, project, skill, achievement), org or title, dates, facts[], metrics[], skills[], source (resume, github, portfolio, linkedin, manual), source_ref, confirmed
- `skills`: name, aliases[], confirmed
- `jobs`: company, title, url, jd_raw, jd_clean, analysis (jsonb)
- `tailored_versions`: job_id, tex, pdf_path, ops (jsonb), report (jsonb), provider, model, arm_id, cost_usd

## 7. Security (this is multi-tenant, and compiling LaTeX means running code)
- **Compiler sandbox:**
  - No network, with TeX Live fully pre-installed in the image
  - Read-only root, a temp dir per job, a non-root user
  - Limits of 20 seconds, 512MB and a maximum input size
  - Shell-escape off
  - Reject absolute or `..` paths in `\input`/`\include`, and reject `\write18`, `\openout` and `\directlua`
- **Untrusted inputs:** JDs and portfolio pages are treated as data only. A prompt injection like "add Harvard" is blocked by the fabrication validator.
- **Rate limits** per user on compiles and ingestion, using Upstash.
- **Privacy:**
  - Full account and data deletion.
  - The privacy policy says data goes only to the provider the user chose.
  - Feedback is used for global bandit statistics only in aggregate. It's used for model training only with explicit opt-in.

---

## 8. Milestones

For the 24-hour hackathon build:
- **M1 – Engine.** LaTeX parser and span editor, escaper, ATS checks, validators, reward, local compiler, all with tests.
- **M2 – Tailoring.** Multi-provider LLM client, prompts, the full pipeline with best-of-N, the REST API with streamed progress.
- **M3 – Web app.** Key screen, resume and job input, sample data, live progress, scores, per-change diff with revert and rebuild, downloads and Open in Overleaf.
- **M4 – Evidence and learning.** GitHub import, confirmed skills and free-text facts, feedback into the bandit and style memory.
- **M5 – Ship.** Docker image so anyone can run it with one command, then a public deployment.

After the hackathon:
- Accounts and a database (Postgres with row-level security), per-job history, PDF and DOCX resume import into the default template.
- **v2.** The Chrome extension (JD capture), the application tracker with outcome rewards (Layer 4), cover letters.
- **v3.** The house model: SFT, then DPO, then GRPO (Layer 5), and a free tier without a key.

---

## 9. Verification

- **Unit (pytest):**
  - Parse-then-splice with no edits is **byte-identical** on 10 fixture templates (Jake's, Awesome-CV, moderncv, Deedy, plain article, and others).
  - Property test: random strings passed through the escaper always produce safe LaTeX.
  - Validator cases: invented "Kubernetes" is rejected; "K8s" is allowed when Kubernetes is in the evidence; an invented "40%" is rejected.
  - Reward function: it's 0 when a hard gate fails, it rises when coverage rises, and stuffing is penalized.
  - Key-prefix detection.
- **Golden eval** (runs against real keys and prints cost). 10 templates × 8 JDs (backend, frontend, ML, data, PM, new-grad, …), plus adversarial JDs: prompt injection, a very long JD, a non-English JD. Targets for **every recommended model**:
  - **100% compile rate**
  - **100% within the page target**
  - **0 fabrications in the output**
  - Must-have keyword coverage goes up from before to after
  - Parse health passes on the `pdftotext` output

  The eval also checks that **best-of-3 scores higher than N=1 on average**, and writes the provider quality and cost table used by the model registry.
- **Bandit simulation:** an offline simulator with synthetic users who have hidden preferred arms. Thompson sampling's cumulative regret must grow sublinearly and it must find the best arm within about 30 rounds. This test gates v1.5.
- **Compiler security tests:** `\input{/etc/passwd}`, `\write18{ls}` and the infinite `\def\x{\x}\x` must all be denied or time out.
- **E2E (Playwright):**
  - Sign up → enter an OpenAI key → upload Jake's .tex → paste JD → reject one bullet and regenerate → download the PDF.
  - Assert the PDF text contains the top JD keywords, a `feedback_events` row exists, and style memory was updated.
- **Manual ATS check:**
  - Upload the output to a real Greenhouse or Lever application form, use its "autofill from resume" and check the parsed fields.
  - Cross-check with OpenResume's open-source resume parser.

---

## 10. Risks and open items
- **Quality differs a lot by provider:** small or cheap models rewrite worse. The registry shows eval scores and flags models that aren't recommended.
- **Template variety:** exotic macros may not profile cleanly. Fallback: offer to migrate the content into the default ATS-safe template.
- **LinkedIn and Workday pages block fetching:** paste the text instead (the v2 extension solves this).
- **Cold start for learning:** there's little feedback early on. The global prior and Layer 0 cover that until data builds up.
- **BYOK friction** for non-technical users: onboarding includes a "get a key in 2 minutes" guide for each provider. The house model in v3 removes the need for a key.
- **Name:** "TailorTeX" is a placeholder. Check the name and domain are free before launch.

## Sources
- LaTeX tailoring tools: [ResuMax vs Overleaf](https://resumax.ai/compare/resumax-vs-overleaf), [ResuTex comparison](https://www.resutex.com/blog/best-latex-resume-builder-online), [JobShinobi](https://www.jobshinobi.com/landing/ai-powered-resume-builder-latex)
- General resume builders: [Teal: best AI builders](https://www.tealhq.com/post/best-ai-resume-builders), [Jobscan: best AI builders](https://www.jobscan.co/blog/best-ai-resume-builders/), [Rezi: best AI builders](https://www.rezi.ai/posts/best-ai-resume-builders), [Simplify Copilot](https://simplify.jobs/copilot)
- Open source: [ApplyTeX](https://github.com/ashrith01/applytex), [sanjaesuresh/resume-tailor](https://github.com/sanjaesuresh/resume-tailor), [Resume-Matcher](https://github.com/srbhr/resume-matcher), [anushibinj/resume-tailor](https://github.com/anushibinj/resume-tailor), [Latexy](https://github.com/sanskarpan/Latexy)
- ATS parsing: [LaTeX ATS traps](https://atsverification.com/blog/latex-resume-ats-friendly/), [How recruiters sort in ATS](https://atsverification.com/blog/how-recruiters-sort-candidates-ats-2026/), [Workday/Taleo/Greenhouse](https://apply-mate.com/blog/workday-taleo-greenhouse-ats)
- Overleaf: [Overleaf API (Open in Overleaf)](https://www.overleaf.com/devs), [Git integration (premium)](https://docs.overleaf.com/integrations-and-add-ons/git-integration-and-github-synchronization)
- LinkedIn: [Save profile as PDF](https://www.linkedin.com/help/linkedin/answer/a541960)
- Multi-provider LLM: [AI SDK structured data](https://ai-sdk.dev/docs/ai-sdk-core/generating-structured-data), [AI SDK providers](https://ai-sdk.dev/providers/ai-sdk-providers), [OpenRouter AI SDK provider](https://github.com/OpenRouterTeam/ai-sdk-provider)
- Learning and RL: [Bandit-feedback LLM routing (BaRP)](https://arxiv.org/abs/2510.07429), [PrefPO: preference prompt optimization](https://arxiv.org/pdf/2603.19311), [Unsloth RL/GRPO guide](https://unsloth.ai/docs/get-started/reinforcement-learning-rl-guide), [Fine-tuning guide: SFT → DPO → GRPO](https://futureagi.com/blog/llm-fine-tuning-guide-2025/)
- Browser LaTeX: [BusyTeX WASM](https://github.com/TeXlyre/texlyre-busytex), [SwiftLaTeX](https://github.com/SwiftLaTeX/SwiftLaTeX)
