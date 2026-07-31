-- VC-6 — offline forks made visible (DESIGN §9.7, plan §7.2).
--
-- Nothing is ever discarded on a conflict. Two people answering the same item
-- while one of them is offline both land; append-only means neither write is
-- lost, and the only real question is which value the checklist should *show*.
-- This view answers "where did the history fork, and which branches are
-- competing", so the UI can put both in front of a human instead of picking.
--
-- A fork is two or more rows claiming the same parent through `prev_entry_id`
-- **and disagreeing about the answer**: each author believed they were
-- overwriting the same row, which is exactly what happens when a queued write
-- flushes after somebody else has moved on.
--
-- Branches that agree are not a conflict, and requiring disagreement is not a
-- convenience — it is what the word means. Two members who both mark a Check
-- "problem" while offline have nothing to decide, and prompting them would
-- teach people to dismiss the picker. It also makes the view immune to a
-- duplicate replay: a queued write that flushes just as the tab navigates can
-- be restored from storage and sent twice, and the second copy carries the same
-- parent as the first. Byte-identical branches are agreement no matter what
-- produced them, so that appends a redundant row to history and nothing more.
--
-- It is *open* until some later row descends from one of the branches. That
-- covers both endings deliberately:
--   • the picker resolves it — appending a row whose `prev_entry_id` is the
--     chosen branch, which is the same write shape as any other answer, so
--     resolution needs no special route and no mutable column; and
--   • somebody simply answers the item again afterwards, having seen the
--     current value. The identity has moved on under its own steam, and
--     nagging about a fork the newest author already overwrote would be noise.
-- Either way the losing branch stays in `visit_entries` and stays readable.
create view visit_entry_conflicts with (security_invoker = true) as
with fork as (
    select prev_entry_id as parent_id
    from visit_entries
    where prev_entry_id is not null
    group by prev_entry_id
    having count(distinct (value, coalesce(answer_text, ''))) > 1
),
open_fork as (
    select f.parent_id
    from fork f
    where not exists (
        select 1
        from visit_entries branch
        join visit_entries descendant on descendant.prev_entry_id = branch.id
        where branch.prev_entry_id = f.parent_id
    )
)
-- One option per distinct answer, earliest first: a picker listing the same
-- value twice asks the reader to choose between a thing and itself.
select distinct on (open_fork.parent_id, branch.value, coalesce(branch.answer_text, ''))
    branch.id,
    branch.visit_id,
    branch.item_key,
    branch.is_custom,
    branch.visit_unit_id,
    branch.owner_user_id,
    branch.author_user_id,
    branch.value,
    branch.answer_text,
    branch.note,
    branch.created_at,
    open_fork.parent_id as fork_parent_id
from open_fork
join visit_entries branch on branch.prev_entry_id = open_fork.parent_id
order by open_fork.parent_id, branch.value, coalesce(branch.answer_text, ''), branch.created_at, branch.id;

comment on view visit_entry_conflicts is
    'One row per distinct competing answer of an unresolved Visit fork (VC-6). '
    'Group by fork_parent_id to get the branches of one conflict. '
    'security_invoker so base-table RLS still applies (DESIGN §8.3). '
    'Resolve by appending an entry whose prev_entry_id is the chosen branch.';

-- The view looks rows up by prev_entry_id in both halves; without this it is a
-- sequential scan of every answer on every Visit in the database.
create index visit_entries_prev_entry_idx
    on visit_entries (prev_entry_id) where prev_entry_id is not null;
