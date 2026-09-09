# Blog post outline — Manzil

A writing plan, not a draft. Every section below states **what it does for the
reader**, **the beats inside it**, **how to write it**, and **what to leave out**.
Facts are sourced from `DESIGN.md`, its §20 Decision Log, `IMPLEMENTATION.md`,
and the code, so the numbers here can be used verbatim.

---

## 0. Before you write a word: the spine

**The spine of this post is trust, not automation.**

The weak version of this story is "I got tired of a spreadsheet so I built an
app, here is my stack." Every developer has that post. The strong version is
this: *you did not need software that found apartments. You needed to believe a
number.* A rent figure you cannot verify is worse than no figure, because you
will act on it. Every architectural decision in Manzil descends from that one
problem, and if you make trust the spine, the design decisions stop reading as
resume padding and start reading as **forced moves**.

Test every paragraph against the spine: *does this advance the question "can I
believe this number?"* If not, cut it or move it to a footnote. This single
filter will keep the post from becoming a feature tour, which is the failure
mode this project is most exposed to, because there are a *lot* of features.

**The governing line to plant early and pay off late** — it is already the
project's own words, from `DESIGN.md` §2.5, and it is the best sentence you have:

> The critical path stays boring; the ambition lives where failure is survivable.

**Audience:** working engineers who have built side projects, plus the subset of
hiring managers who actually read. Assume they know what a queue is. Do not
assume they know what a Unit Group is — that is *your* vocabulary and you have to
teach it, once, cheaply.

**Target length:** 2,500–3,500 words. This project could support 10,000 and that
is exactly the trap. The Decision Log is 200+ entries; the post gets maybe eight
of them. Ruthlessness here is the whole craft.

**Voice:** past tense, first person, plain. Specific numbers instead of
adjectives. Short paragraphs. Let the reader watch you being wrong — every
section where you admit a mistake is a section they will believe.

---

## 1. Cold open — the number that was wrong (150–200 words)

**Purpose:** buy the next thirty seconds. Do not open with "I was apartment
hunting." Open inside a concrete failure.

**Beats:**

1. One scene, present-tense-feeling: a listing said one price. The same unit on
   another site said a different one. Neither included the fees, and the fees
   were behind "contact us."
2. The spreadsheet you were maintaining by hand, one row per listing, and the
   moment you realized you could not tell which rows were still true.
3. The stakes, stated flatly and once: a lease deadline. Real money, a real
   decision, a real date. Do not be dramatic about it — the flatness *is* the
   drama.
4. Land the thesis in one sentence: **the problem was never finding listings, it
   was trusting them.**

**How to write it:** shortest paragraphs in the post. No stack, no tooling, no
"I decided to build." The reader should not yet know this is an engineering post.

**Cut:** any mention of AI, agents, or LLMs. Naming the technology in the first
200 words tells the reader the tech is the point, and it is not.

---

## 2. Why I built it — the spreadsheet that went stale (350–450 words)

**Purpose:** convert your annoyance into a *structural* problem the reader
recognizes. Anyone can be annoyed. You want them thinking "oh — that's actually
hard."

**Beats (one paragraph each):**

1. **Listing sites are hostile to comparison, and it is not accidental.** Three
   concrete hostilities, drawn from `DESIGN.md` §2.1: fees hide behind "contact
   us"; the same unit appears at different prices across sites; the true all-in
   monthly cost is never the headline number. Give a real example of the price
   discrepancy if you have one — this is the single most persuasive paragraph
   available to you.
2. **The spreadsheet was the honest attempt, and it failed for an interesting
   reason.** Not "it was tedious" — everyone says that. Say the sharper thing:
   *it went stale silently.* A wrong cell looks exactly like a right cell. That
   is the real defect, and it is the one that survives into the product as the
   stale-badge and TTL work later.
3. **What you actually wanted.** Frame as a deceptively small ask: paste a URL,
   get back a row you can believe, with every number traceable to where it came
   from. Note in one clause that this sounds like a scraper and is not one — the
   scraping is the easy 10%.
4. **The second motive, stated honestly.** You wanted to learn multi-agent
   systems, and you wanted to learn them against a real problem with a real
   deadline instead of a toy. Say this plainly. Readers can smell a
   retrofitted justification, and admitting the learning motive up front buys
   you enormous credibility for §7, where you will admit what that ambition
   actually cost.

**How to write it:** this section earns the whole post. Slow down here. Concrete
> abstract, every time.

**Cut:** feature lists, competitor comparison ("why not Zillow's compare tool"),
and any defense of building it yourself. Nobody needs the justification.

---

## 3. The rule I set before writing code (300–400 words)

**Purpose:** this is your differentiator. Most side-project posts have no
governing constraint. Yours does, it is written down and dated, and it is the
reason the project shipped.

**Beats:**

1. **Name the tension.** A tool you must trust and a deadline you cannot move,
   versus an architecture you wanted to learn that is famously good at eating
   schedules. State it as the trap it is.
2. **State the rule**, quoted from your own design doc — the "critical path
   stays boring" line. Then unpack it in one sentence: the shipping pipeline is
   a hand-rolled state machine, and the ambitious multi-agent work lives behind a
   flag, in one directory, judged by evals, where failure is survivable.
3. **Show the enforcement, not just the intent.** This is what makes it real
   rather than a nice sentiment: you wrote the risk down as a numbered register
   entry (R11: "learning track starving shipping"), with a hard gating rule —
   a learning milestone starts only after the shipping milestone it depends on is
   green, and **the lease deadline wins every conflict.** Sibling risk R10 is
   scope creep itself, mitigated by a backlog section explicitly described as
   *a parking lot, not a promise.*
4. **The forward promise.** One line: "I will tell you at the end whether the
   rule held." It did, in a way that is both a success and an admission — set the
   hook now, pay it off in §7.

**How to write it:** confident and unfussy. You are not claiming to have invented
process. You are claiming that one written constraint, decided early, did more
work than any framework you picked.

**Cut:** general advice about scope creep. Stay inside your own project.

---

## 4. How I worked — the design doc as the contract (350–450 words)

**Purpose:** the second differentiator, and the one most readers will not have
seen done at this scale on a personal project. It is also the natural, non-braggy
place to talk about building with AI coding agents.

**Beats:**

1. **The document came first and stayed authoritative.** `DESIGN.md` owns
   *intent*; `IMPLEMENTATION.md` owns *mechanics*; the code owns exact
   interfaces. When code and design disagree, that is a conflict to be flagged,
   not silently resolved. State the authority order explicitly — it is unusual
   and it is the load-bearing idea.
2. **The glossary as a hard contract.** Hunt, Property, Listing, Source, Floor
   Plan, Unit Group, Criterion, Rubric, Gate, Extraction, Override, Job, Stage,
   Checkpoint. Fourteen terms with exact meanings, used verbatim in code, with a
   standing rule against inventing synonyms. Explain *why* this matters more than
   it sounds: "unit" and "floor plan" and "listing" are casually
   interchangeable in English and catastrophically different in a schema. Getting
   this wrong is how you end up merging two buildings into one row.
3. **The Decision Log.** Every material change appends a dated entry with
   rationale and the sections it touched. 200+ entries between late June and late
   August. The honest payoff: **you can no longer remember why half of these
   decisions were made, and you do not have to.** Pick one entry and quote it as
   a specimen — a good candidate is the day you reversed an earlier decision, so
   the reader sees the log catching you changing your mind.
4. **Building with agents.** This is why the document discipline existed at all:
   parallel Claude and Codex sessions worked in the same checkout, and a design
   doc plus a strict glossary is the only thing that keeps several agents (and
   you, at 1am) from drifting into three different names for the same concept.
5. **The incident.** Tell it, briefly and without spin: an agent mistook another
   session's repo-wide formatting run for hook noise and reverted it wholesale.
   59 files were pure formatting. Three were not. A real mutable-default bugfix
   was destroyed and had to be recovered from another agent's session log. The
   result is now a standing rule in `AGENTS.md`: *never revert what you did not
   write.* This anecdote is worth 500 words of theorizing about AI-assisted
   development.

**How to write it:** matter-of-fact. The temptation is to editorialize about AI
coding; resist it. Describe what you did, describe what broke, describe the rule
that came out of it. The reader will draw the conclusions.

**Cut:** tooling advocacy, prompt tips, model comparisons. Wrong post.

---

## 5. The stack, and the three choices that mattered (250–350 words)

**Purpose:** the reader wants this and will skim for it. Give it to them fast,
then spend the words on the *decisions* rather than the list.

**Beats:**

1. **The list, compressed to a few lines** — do not table it, do not justify each
   item: React 18 + Vite + TypeScript with Mantine on the front; FastAPI +
   Pydantic v2 for the API; a Python 3.12 asyncio worker; Supabase for Postgres,
   Auth, Storage, and Realtime; OpenRouter as the single LLM gateway; Langfuse
   for tracing; Cloudflare Pages + Render for hosting.
2. **Choice one: Postgres is the queue.** No Celery, no Redis. A durable job
   queue using `SELECT ... FOR UPDATE SKIP LOCKED`, with worker heartbeats and a
   five-minute orphan reclaim. The reason is the one worth stating: **a job you
   can debug with plain SQL at 2am is worth more than a job system with better
   ergonomics.** One stateful system, not two.
3. **Choice two: every model call goes through one seam.** No provider SDK is
   imported anywhere outside a single `llm/` package; the whole app talks to
   `call_structured`, `call_agent`, `call_vision`. This started as tidiness and
   paid off concretely: the project began as an all-Anthropic baseline, moved
   extraction and verification to a Gemini model on bench evidence, and later
   moved the whole workhorse tier — and none of that touched a stage. Mention
   that image classification round-tripped to a local ONNX model and back to a
   remote one when it OOM'd the $7 Render instance; the seam absorbed that too.
4. **Choice three: Langfuse from the first call.** Tracing was a day-one
   requirement, not an observability retrofit, with an explicit rule that an
   untraced call is a bug. State the payoff in one clause: you always knew what
   a listing cost, which is what made the cost work in §6.5 possible at all.

**How to write it:** every stack item that is *not* one of the three gets at most
a clause. The reader is skimming this section and you should let them.

**Cut:** "why Mantine over Tailwind," bundler opinions, TypeScript advocacy.

---

## 6. The hard parts (1,000–1,400 words — the core of the post)

**Purpose:** this is why people will send the post to other people. Structure it
as **problem → what I tried → what it cost → what I shipped**. Every subsection
must end with something the reader can steal.

Six subsections, ordered so each one raises the stakes. Give each an H3 that
states the *problem*, never the solution — "The scoring engine never sees an
LLM" is a spoiler; "The model was going to be wrong sometimes" is a hook.

### 6.1 The model will be wrong, and I still needed a number I could defend

- **Problem:** LLM extraction is good and not reliable, and a rent figure that is
  quietly hallucinated is worse than a missing one, because you will act on it.
- **Solution — the central architectural idea of the whole project:** the LLM
  produces **facts**; only a deterministic engine produces **points**. The scoring
  engine is pure, LLM-free, lives in a domain-blind shared package, and is covered
  by golden tests that assert exact breakdowns.
- **Why it is more than a slogan:** it means you can change your mind about what
  matters without re-extracting anything. Re-scoring a hunt after editing your
  rubric costs **$0**, because no model runs. The rubric is fully user-controlled
  — criteria, options, point deltas, dealbreakers, and hard gates.
- **The detail that shows you thought it through:** a gate firing sets the total
  to the *minimum* of the firing gates' scores, so multiple failures can never
  average upward into something acceptable.
- **Steal-this line:** put the non-determinism at the edges and keep the thing you
  have to defend deterministic and testable.

### 6.2 The same apartment, four websites, four different rents

- **Problem:** identity. One building, many listing sites, many floor plans, many
  units, and syndication feeds echoing the same wrong number across "different"
  sources.
- **Solution stack, briefly:** a pipeline that fans out across sources, verifies
  each extracted value against actual quoted page evidence, then reconciles
  disagreements with a deterministic ladder that stores *which rule resolved it*.
- **The one detail to feature:** reconciliation counts **syndication families,
  not domains.** Five sites carrying the same feed get one vote, not five. This is
  the kind of specific that makes readers trust everything else you say.
- **What identity actually cost you:** be honest that the first data model was
  wrong. It resolved facts by "latest row wins," and that had to be torn out and
  replaced with an append-only, source-scoped substrate where every resolved value
  keeps its lineage back to the candidate claims it came from. That was a whole
  numbered work series, not a refactor. Say so.
- **Escape hatch as a feature:** an admin `split_property` operation existed from
  day one, because a bad automatic merge corrupts shared data and you need to be
  able to undo it.

### 6.3 Scraped pages are attacker-controlled input

- **Problem:** you are feeding arbitrary internet HTML into a model that can call
  tools. State the threat plainly — a page can *say things to your model*.
- **Solution, three layers:**
  - Extraction stages get **zero tools.** This is a security control, not an
    optimization: the worst case for an injected page becomes a bad *value*, never
    an *action*.
  - Every value must carry a genuine evidence quote from the page, audited by a
    separate verification pass; implausible numbers are caught by bands.
  - The fetcher, not URL validation, is the SSRF boundary: one policy module
    resolves and screens every fetch before connecting, tier 1 pins the resolved
    IP, and redirect chains are re-screened.
- **The framing to use:** you did not eliminate prompt injection. You *demoted*
  it — from "compromise" to "one bad field that other sources outvote." That is
  an honest and more interesting claim than a security win.

### 6.4 Sites that do not want to be read

- **Problem:** anti-bot walls on exactly the aggregators with the best coverage.
- **Solution:** a three-tier ladder climbed **per domain, not per fetch** — plain
  HTTP, then a real headless browser, then a managed unblocker — with a per-domain
  registry recording what each site needs, and a deliberately tier-diverse source
  slate so a blocked domain costs one slot instead of the run.
- **The posture, stated once and not defended at length:** personal, low-volume,
  never a public service; one good source is sufficient by design.
- **The bug worth telling:** production submissions failed with what looked like
  the target page's error, when in fact the *unblocker provider* was refusing
  **you** — a misconfigured provider returning HTTP 400 on every request while the
  system dutifully reported it as the listing site's status. The fix was
  conceptual, not textual: a partially configured tier is not a degraded tier,
  it is an off tier. Good, short, universal lesson about error attribution.

### 6.5 It had to be cheap enough that I would actually use it

- **Problem:** per-listing inference cost decides whether you re-run things, and
  a tool you are afraid to re-run is a spreadsheet with extra steps.
- **Numbers to use directly:** naive baseline ~**$0.26** per listing; shipped at
  ~**$0.10–0.12** for a new listing, **under $0.01** for a refresh, and **$0** to
  re-score. Total fixed hosting ~**$7–14/month**.
- **The levers, ranked, with the one that mattered called out:** prompt caching
  on stable prefixes; **content-hash gating**, without which refreshes silently
  become 80% of the bill; an HTML cleaning pipeline that cuts tokens 5–10× before
  a model sees anything (with a price-retention guard that rejects a cleaning
  pass that dropped the page's rendered prices — a lovely small detail); and
  vision discipline — up to 120 candidate photos classified at ≤384px by a cheap
  model, but at most three high-confidence kitchens sent at ~1024px to the
  expensive one.
- **Steal-this line:** cost control was an architecture decision (hash gating),
  not a prompting decision. Nobody prompt-engineers their way out of a refresh
  loop.

### 6.6 Making it public was harder than making it work

- **Problem:** the whole codebase was written under the assumption that only two
  trusted people would ever hold accounts. Putting a live demo on the internet
  converts every one of those assumptions into a live security control. This is
  literally logged as a High risk in your own register.
- **Solution, and the sentence that carries it:** the demo is **enforced in the
  database, not the app** — because a read-only account holds a real session in an
  untrusted browser, and you must assume that token gets driven straight at
  Postgres with your API bypassed entirely.
- **The two details to actually tell:**
  - **The demo user has no auth account row at all.** You tried the two obvious
    designs first — a real account with a restricted token, and the same account
    *banned* — and discovered empirically against a running stack that both still
    permitted changing the password. A ban blocks password sign-in and nothing
    else. The only durable answer was for the subject to not exist.
  - **The front door locked and the side door open.** Cleaned page text was
    correctly revoked on the table everyone would think to check — and the same
    page bodies sat readable in the job payload column, several thousand
    characters of it, retrievable with an ordinary member's token. Tell this one
    fully. It is the most useful paragraph in the post for a working engineer,
    because it is not a mistake anyone avoids by being careful; it is one you
    avoid by *going looking for the second copy of your data.*
- **One more, if you have room:** the kill switch lives in the row-level security
  policy rather than the API, and toggling it bumps a generation counter that is
  minted into every token — so re-enabling after an incident does not silently
  hand access back to the sessions that were live before it.

---

## 7. What actually happened (200–300 words)

**Purpose:** pay off the cold open. Keep it short — the resolution wants less
space than the problem, always.

**Beats:**

1. **You found the apartment.** Say it plainly and early in the section. Then
   give the specifics that make it land: what the tool actually did for the
   decision. Did it kill a listing you liked on an all-in cost you would not have
   computed? Did it surface a fee? Did two people rating the same floor plan
   change your mind? *You know the real anecdote — use it, because this is the
   only paragraph in the post that proves the thing worked.*
2. **The unglamorous evidence.** The spreadsheet was retired mid-project — that
   was a formal exit criterion, not a vibe. A second real person joined and used
   it. The tour checklist got run on a phone, in an apartment, with someone else.
3. **What survived after the lease was signed.** It is publicly viewable in
   read-only demo mode at manzil.yusufsaquib.com, and it is open source under
   AGPL-3.0. Scale, in one line: ~78k lines of Python, ~48k of TypeScript, 84
   migrations, 62 tables, 21 pipeline stages.
4. **The honest counterweight — put it here, not buried:** for one apartment
   search, this is an absurd amount of software, and you know it. Say it before
   the reader does. It disarms the entire skeptical reading of the post, and it
   sets up §8, where the learning motive from §2 gets its actual accounting.

**How to write it:** resist the victory lap. The most convincing version is
understated.

---

## 8. What I learned (400–500 words)

**Purpose:** the section people quote. Four or five lessons, each two to four
sentences. **A lesson that could have been learned without building this project
does not belong here.** "Start small" is not a lesson. "Scope creep is real" is
not a lesson.

**Candidates — pick four or five, keep them in this order:**

1. **Determinism is the trust mechanism, not better prompts.** You did not make
   the model more reliable; you made its output non-authoritative. The scoring
   engine cannot be wrong in a way you cannot reproduce. Prompt quality was a
   second-order concern the whole time.
2. **Provenance beat accuracy.** The feature that made the tool usable was not
   getting numbers right the first time — it was being able to see, on every
   value, which source claimed it, what it quoted, which rule resolved the
   conflict, and whether a human had overridden it. Overrides are append-only and
   even a "revert" is a new null-valued row rather than a deletion, so the
   history is never destroyed. A wrong value you can see the reasoning for is
   fixable; a right value you cannot audit is still not trustworthy.
3. **Write the design down when you are working with agents — the doc is the
   interface.** Not because documentation is virtuous, but because parallel
   agents and a tired human at 1am need the same fixed vocabulary or you get three
   names for one concept and a schema that encodes the confusion permanently. The
   glossary was worth more than any individual technical decision.
4. **Security assumptions have a blast radius you cannot see until someone
   untrusted holds a session.** Every "only trusted people have accounts"
   shortcut came due at once. Reference the two-copies-of-the-data lesson: the
   control you wrote is not the control you have until you have gone looking for
   the second copy.
5. **The most useful thing I did was write down what I was allowed to skip.**
   The rule from §3 held — but be precise about *how* it held, because this is the
   post's most honest moment. The shipping pipeline is a boring, resumable state
   machine and it works. The ambitious multi-agent track is still **empty**: the
   directory exists, the flag exists, the eval harness exists, and not one
   milestone of it has been started, because a shipping milestone was always more
   urgent. That is not a failure of the plan. **That is the plan working exactly
   as designed** — the guardrail was written specifically to produce that outcome,
   and it did. Also note the debt you took knowingly and recorded rather than
   hid: an acceptance evidence tail you formally waived to unblock a dependency,
   written down as debt instead of quietly reclassified as passed.

**How to write it:** each lesson is a claim, then the evidence from your own
project, then stop. No "in conclusion." No advice to the reader about their
career.

---

## 9. Close (100–150 words)

**Purpose:** land, do not summarize.

**Beats:**

1. Return to the cold open. The two prices from the first paragraph — resolve
   them, or say what the tool would now show you about them. This callback is the
   single most effective structural move available and costs you three sentences.
2. One line on what you would do differently, stated without hedging. Choose one
   real thing (a candidate: getting the identity model right the first time would
   have saved an entire work series).
3. Links, plainly: live demo, repo, and — this is your best asset and most people
   will not have one — the design doc and its 200-entry decision log, offered as
   the thing to read if the reader wants to see how the decisions were actually
   made. Do not oversell it; one sentence.

**Do not** end with "let me know what you think" or a call to action.

---

## Appendix A — Story mechanics

**The four-callback skeleton.** Set up in §1, pay off in §9: the two prices.
Set up in §2, pay off in §8: the learning motive. Set up in §3, pay off in §8.5:
the guardrail rule. Set up in §2's "silently stale," pay off in §6.5: hash
gating and TTLs. If you land all four the post will feel *designed* rather than
assembled, and readers will not be able to say why.

**Tension, not chronology.** Do not narrate the project month by month. §6's
subsections should each raise the stakes: wrong values → wrong identity →
hostile input → hostile infrastructure → cost → exposure. That ordering moves
from "software is hard" to "the internet is adversarial" to "and then I put it
online," which is a genuine escalation.

**One villain, sustained.** The villain is not listing sites. The villain is
**the plausible wrong number.** It appears in the spreadsheet (§2), in
hallucinated extraction (§6.1), in syndicated echoes (§6.2), in injected pages
(§6.3), in a misattributed provider error (§6.4), and in a stale cache (§6.5).
Name it once in §2 and let the reader recognize it each time it returns.

**Concreteness ratio.** Aim for at least one hard number, quoted line, or named
mechanism per paragraph in §§5–6. Vague technical writing is the default failure
mode and specificity is the whole cure.

---

## Appendix B — Assets worth making

- **One pipeline diagram.** The stage sequence — validate → fetch → extract →
  dedupe → discover → fan out per source → verify → reconcile → images → vision
  → enrich → score. One image, no styling ambition. It replaces 300 words.
- **Two screenshots, maximum.** The overview table with a score breakdown open
  (shows determinism and provenance at once), and one shot showing a conflict
  between sources being resolved. Pull them from the live demo so you are not
  leaking your real hunt.
- **One small numbers table**, if you want a skimmable anchor: naive cost vs.
  shipped cost vs. refresh vs. re-score.
- **Do not** include code snippets longer than five lines. There is no snippet in
  this project that carries the story better than a plain sentence does.

---

## Appendix C — The cut list

Things that are genuinely interesting and still do not belong in this post. If
they hurt to lose, they are follow-up posts, and several would be good ones.

- The visit checklist workstream — 248 template items, offline-first sync,
  presence, conflict forks that require actual disagreement, tour findings that
  can propose a fee edit. **This is its own post**, and a better standalone one
  than any three paragraphs you could give it here.
- The admin panel, ghost view, and audit trail.
- Refresh TTL classes, backoff curves, and the scheduler.
- The image pipeline's classification-vs-quality split and the ONNX round trip.
- Every migration-ordering, CI, and release-versioning war story.
- Email ownership split between the auth provider and the app.
- Realtime, presence, and the ref-counted channel bug.
- Model bench results and per-stage pins. Possibly a post; definitely not four
  paragraphs here.

**The test for anything on this list:** does it advance "can I believe this
number?" If it only advances "look how much I built," it is cut.
