# What actually raises a resume's ATS score

This is the knowledge TailorTeX applies to every tailoring. Some of it depends on the job you're applying
to; most of it doesn't, and would improve your resume for any job. Everything here is either written into
the model's instructions or measured in code — the table at the end says which, per rule.

## 1. What an applicant tracking system really does

An ATS is a database with a search box. It stores the text extracted from your PDF, and recruiters search
that text by keyword. Most systems do not compute a "match score" at all, and the ones that do don't publish
how. So two things matter, in this order:

1. **Can the text be read?** A resume whose words aren't extractable is invisible no matter how good it is.
2. **Are the job's words in it, in a place that reads like real work?**

That is why TailorTeX measures coverage on the text pulled out of the *compiled PDF*, not on your LaTeX
source: what an ATS sees is what counts.

**Where a keyword sits changes what it's worth.** A term used inside a bullet or your summary scores full
marks; the same term sitting only in a comma-separated Skills list scores 0.6. A recruiter reading "Kubernetes"
in a list learns that you typed it. Reading "migrated 12 services to Kubernetes" tells them you did it, and
semantic screeners weigh it the same way. Moving a term from your Skills list into a bullet is one of the
cheapest real gains available.

**A score near 100% on a job you don't match is a failure, not a win.** It means the resume claims things you
can't defend, and the interview is where that falls apart. TailorTeX would rather show you 58% and tell you
which four skills you have no evidence for.

## 2. Writing a bullet

**What / how / result, in one sentence.** Say what you did, how you did it, and what changed. A bullet with
no outcome is a job description.

> Responsible for maintaining the payments API
> → Cut p95 latency of the payments API from 4.2s to 900ms by adding Redis caching

**Open with a strong past-tense verb.** Built, Led, Shipped, Migrated, Cut, Automated, Designed, Scaled,
Rewrote, Reduced, Launched, Negotiated. Never open with *Responsible for*, *Worked on*, *Helped with*,
*Assisted in*, *Duties included*, or a gerund (*Building…*). Weak openers waste the most-read words on the
line and read as a job description rather than an achievement.

**Vary the verb.** Five bullets starting "Developed" read as one thing done five times.

**Name the tools inside the sentence,** where a screener reads them in use, not as a trailing list
("… using React, Redux, Node, AWS"). The trailing list is also where keyword stuffing starts.

**Quantify the result — by keeping a number you already have.** Numbers are the single biggest difference
between a bullet that lands and one that doesn't: how much faster, how many users, how much saved, how many
services. **TailorTeX will never produce a number for you.** It only keeps one that is already in that bullet,
its heading, or evidence you supplied; anything else is a rejected edit. If you have no number, end on a
concrete outcome in words instead — that is still better than stopping at the task.

**Length: roughly 60–220 characters.** Under 60 and there's no room for a result. Over your template's budget
and the line wraps, pushing the page over.

**No first person.** No *I*, *we*, *my*, *our*. Resume convention drops the subject entirely.

**Past tense,** except the role you currently hold.

## 3. The document itself

**Standard section headings.** Call them *Experience*, *Education*, *Skills*, *Projects*. A parser looks for
those words; "What I've Built" is invisible to it. TailorTeX classifies anything it can't recognize as
"other" and locks it rather than editing it blindly.

**One column, no tables.** Multi-column layouts and `tabular`/`minipage`/`longtable` blocks scramble the
reading order when text is extracted: your job title can end up glued to a date from three rows down.
This is the most common way a beautiful resume becomes an unreadable one.

**No text in headers or footers.** Many parsers skip them entirely, and contact details are what people put
there. Keep your email and phone in the body, near the top.

**Contact details that can be found:** email, phone, and one profile link, in the first few lines.

**No icon fonts for contact details.** FontAwesome glyphs extract as private-use characters or nothing at
all, so "✉ me@example.com" can lose the address. Same for images of text.

**Fix ligatures.** With pdfLaTeX, `\input{glyphtounicode}` and `\pdfgentounicode=1` make "ﬁnancial" extract as
"financial" rather than a single glyph no search will match. TailorTeX detects this and can fix it in one click.

**Consistent dates,** one format throughout (`Jan 2024 – Mar 2025`), on every role and project.

**Length:** one page early-career, two at most later. A page that's only half full looks thin; a page that's
1.1 pages long wastes the whole second sheet.

## 4. The honesty rule

Every rule above is about presentation. None of them is a licence to add something you didn't do.

TailorTeX enforces this in code, not in the prompt: a bullet may only name tools, companies and numbers that
appear in its own entry or in evidence it cites. If the job wants PyTorch and nothing in your resume,
notes, GitHub or LinkedIn mentions PyTorch, the honest answer is that this resume scores lower on that job —
and the fix is for **you** to tell TailorTeX about the PyTorch work you did, so it has something true to
write from.

## 5. Rule → what enforces it

| Rule | Enforced by |
|---|---|
| Keywords measured on extracted PDF text | `ats/coverage.py` `term_coverage(pdf_text=…)` |
| In a bullet 1.0, in the skills list 0.6 | `ats/coverage.py` `CONTEXT_SCORE`, `LISTED_SCORE` |
| Never invent a skill, name or number | `validate/validate.py` `_check_text` |
| Dropping a bullet may not cost a must-have | `validate/validate.py` `_check_coverage`, `ats/coverage.py` `coverage_loss` |
| No keyword more than 3 times | `validate/validate.py` `_check_stuffing` |
| What / how / result, strong verbs, quantified, length, tense, person, verb variety | `llm/prompts.py` `ATS_RULES` |
| Text layer is extractable | `ats/health.py` `text_layer` |
| No ligature glyphs | `ats/health.py` `ligatures`, lint `glyphtounicode` (one-click fix) |
| No icon-font or control characters | `ats/health.py` `garbage`, lint `icons` |
| Contact details near the top | `ats/health.py` `contact`, lint `header_footer` |
| Standard section headings | `ats/health.py` `headings`, `latex/parse.py` `classify_section` |
| Single-column reading order | `ats/health.py` `order`, lint `columns` |
| No images of text | lint `images` (one-click fix) |
| Page count and fill | `reward/reward.py`, `ats/recommend.py` |
