# Contributing

Manzil is an open-source **portfolio piece**: a tool I built leveraging AI coding agents for a real hunt, with the design notes and agent pipeline left readable on purpose. I am **not** looking for a contributor community, and I am unlikely to merge drive-by pull requests.

The source is still public under the [GNU Affero GPL v3](LICENSE.md). You can fork it, run it locally, and learn from it. If something in the code or docs is wrong and you want to send a small, focused patch anyway, this file is the contract I will use to read it.

## Try the product first

The hosted app is a read-only Demo Mode session. It cannot create an account or ingest a URL you bring:

**[manzil.yusufsaquib.com](https://manzil.yusufsaquib.com)**

Local setup, tests, and the worker CLI live in the [`README`](README.md).

## Before you write code

1. Read (or have an AI coding agent read) [`DESIGN.md`](DESIGN.md) §1 (how to use the document) and §3 (glossary). Hunt, Property, Listing, Source, Floor Plan, Criterion, Rubric, Gate, and Job have exact meanings. Use them verbatim.
2. Follow the §1 reading path for the area you would touch.
3. Do **not** implement anything in DESIGN.md §18 (Deferred / Backlog) unless the issue is explicitly about pulling that item in.
4. If DESIGN.md and the code disagree on intent, stop. That is a conflict to report, not a license to pick a side.

[`AGENTS.md`](AGENTS.md) is the same rule set coding agents follow in this repo. [`IMPLEMENTATION.md`](IMPLEMENTATION.md) is mechanics and may churn; DESIGN.md still wins on intent.

## What I will actually look at

In roughly this order:

- A demonstrated bug with a failing test, or a doc fix that matches the code
- Security issues reported privately per [`SECURITY.md`](SECURITY.md) — not as a public PR that includes an exploit
- Tiny, isolated correctness patches that do not expand scope

I may or may not look at:

- New features, Rubric ideas, or “while I was here” refactors
- Dependency bumps without a reason that is true in *this* repo
- Restyling the UI away from [`frontend/UI_DESIGN.md`](frontend/UI_DESIGN.md)
- Anything that turns the hosted demo into a public signup or lets a visitor enqueue a Job
- LLM / prompt / model-pin changes without the Phase 0 bench evidence DESIGN.md requires

## How to send a patch

Fork, branch from `master`, keep the diff to one concern.

```bash
uv sync --all-packages
cp infra/.env.example .env   # your keys; never commit them
supabase start
```

Before you open a PR:

```bash
uv run ruff check --fix . && uv run ruff format .
uv run mypy
MANZIL_LLM_MODE=replay uv run pytest
pnpm -C frontend test
```

CI runs those same gates with `MANZIL_LLM_MODE=replay` so a PR never spends tokens. If you changed RLS or membership, say so; the collaboration-security job needs a live Supabase stack and is easy to miss locally.

Please:

- Add or update tests next to the change. Scoring engine changes must update goldens in the same commit, with a one-line why.
- Leave secrets, corpus HTML, and bench labels out of the tree (they are gitignored on purpose).
- Write the PR description as *why*, not a file list. The README and DESIGN.md already explain the architecture.

I may close a PR with a short note and no review. That is not a judgment of the work; it is the maintenance budget this project has.

## Issues

GitHub issues are optional documentation. I do not triage feature requests. Security reports go to email only — see [`SECURITY.md`](SECURITY.md).

## License

By submitting a patch you agree it is licensed under the same [AGPLv3](LICENSE.md) as the rest of the repository.
