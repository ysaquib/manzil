-- Migration: private image objects require a Hunt context, for everyone
-- (R2 H5, DESIGN §8.3). Plus the narrowing of demo_context() (R2 M3).
--
-- DESIGN §8.3 has always said: "Floor Plan diagram bytes stay in private Storage
-- and signed-URL access is granted only in an authenticated Hunt context
-- containing that Property." The policy did not do that. It began life
-- bucket-wide (`bucket_id = 'property-images'`, nothing else), which relied on
-- object-path secrecy; v3.54 narrowed it for the demo principal and left every
-- other authenticated subject with the original posture, i.e. able to list and
-- download every image in the project.
--
-- Among two trusted accounts that was a reasonable place to be. It is a
-- DESIGN/code contradiction either way, and the Owner ruled on 2026-08-06 that
-- DESIGN wins: enforce the Hunt context for everyone rather than ratify the
-- global posture. Images can carry more than the structured facts do -- an
-- interior shot is a different kind of disclosure from a rent figure -- and the
-- old policy permitted enumerating the bucket, so an attacker did not even need
-- to guess a content hash.
--
-- The demo case then needs no special branch, which is the pleasant part:
-- `private.member_role()` is already demo-aware, so routing image authorization
-- through it gives the demo principal exactly the Demo Hunt's images and
-- inherits the kill switch for free.
--
-- What is NOT changed: the worker still writes with the service role, which
-- bypasses RLS entirely, so ingestion and `manzil purge-images` are unaffected.
-- Signing happens client-side with the caller's own JWT
-- (`frontend/src/features/listings/api.ts`), so Storage RLS governs who may
-- mint a signed URL -- which is exactly the seam DESIGN §8.3 describes.

create or replace function private.can_read_property_image(object_name text)
returns boolean
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_property uuid;
begin
    -- Keys are `properties/<property_id>/<content_hash>.webp`, written by
    -- stages/image_fetch.py and stages/image_classify.py. Anything else is not
    -- an object this policy knows how to authorize, so it is refused.
    begin
        v_property := (storage.foldername(object_name))[2]::uuid;
    exception when others then
        return false;
    end;

    if v_property is null then
        return false;
    end if;

    -- A Hunt context containing that Property. `member_role()` carries the demo
    -- scoping and the kill switch, so a demo subject reaches only the Demo
    -- Hunt's images and reaches nothing at all once the demo is off or its
    -- configuration stops holding.
    return exists (
        select 1
          from hunt_listings hl
         where hl.property_id = v_property
           and private.member_role(hl.hunt_id) is not null
    ) or private.is_site_admin();
end $$;

comment on function private.can_read_property_image(text) is
  'DESIGN §8.3: signed-URL access to a private image is granted only in an '
  'authenticated Hunt context containing that Property. Applies to every '
  'authenticated subject, not only the demo principal (R2 H5). Unparseable '
  'keys fail closed. Site Admins are admitted for support, and is_site_admin() '
  'is itself demo-aware.';

revoke all on function private.can_read_property_image(text) from public, anon;
grant execute on function private.can_read_property_image(text) to authenticated;

drop policy if exists property_images_storage_authenticated_select on storage.objects;
create policy property_images_storage_authenticated_select
    on storage.objects for select to authenticated
    using (
        bucket_id = 'property-images'
        and private.can_read_property_image(name)
    );

-- The demo-only helper is now subsumed: its Demo-Hunt scoping is what
-- member_role() already applies inside the predicate above. Leaving it in place
-- would be a second, weaker answer to the same question.
drop function if exists private.demo_readable_storage_object(text);

-- ── R2 M3: demo_context() stops publishing the Demo Hunt to everybody ────────
-- It answered `enabled` and `hunt_id` for any authenticated caller. The stated
-- need was "am I demo?", which the frontend asks so it can render read-only
-- affordances. An ordinary member has no use for the Demo Hunt's id and should
-- not be handed it.
create or replace function public.demo_context()
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select case
        when private.demo_identity() = 'none'
        then jsonb_build_object('is_demo', false, 'enabled', false, 'hunt_id', null)
        else jsonb_build_object(
            'is_demo', true,
            'enabled', private.demo_identity() = 'scoped',
            'hunt_id', case
                when private.demo_identity() = 'scoped'
                then (select demo_hunt_id from site_settings)
                else null
            end
        )
    end;
$$;

comment on function public.demo_context() is
  'The only demo metadata a client may read, and only about itself: am I the '
  'demo principal, is my session live, and which Hunt am I looking at. An '
  'ordinary member learns nothing (R2 M3).';
