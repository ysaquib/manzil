-- P3-7a: content-addressed, private listing-image storage and hash metadata.

alter table property_images
    add column source_url text,
    add column content_hash text,
    add column width integer,
    add column height integer,
    add column byte_size integer,
    add column created_at timestamptz not null default now();

create unique index property_images_property_hash_uidx
    on property_images (property_id, content_hash)
    where content_hash is not null;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('property-images', 'property-images', false, 20971520, array['image/webp'])
on conflict (id) do update set
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

-- Authenticated users may read gallery objects. Table RLS decides which image
-- paths the UI learns; writes/deletes remain service-role-only.
create policy property_images_storage_authenticated_select
    on storage.objects for select to authenticated
    using (bucket_id = 'property-images');
