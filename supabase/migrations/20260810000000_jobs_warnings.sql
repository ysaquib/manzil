-- jobs.warnings (§8.2, §10.8): non-fatal degradations a stage wants the human to
-- see on the task card. Distinct from `error`, which is terminal, and from a
-- checkpoint, which halts the run: a warning never changes what the pipeline
-- does, it only says the run finished slightly short of its inputs.
--
-- One array of `{stage, code, message, detail}` objects, rewritten by the
-- worker on every persist-before-advance save (a stage owns its own entries),
-- so the column always reflects the current RunState rather than accumulating
-- duplicates across a resume.
alter table jobs add column warnings jsonb not null default '[]'::jsonb;
