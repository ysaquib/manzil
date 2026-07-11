-- P2-6: ratings are one integer from 1 through 5.
alter table ratings add constraint ratings_value_check check (rating between 1 and 5);

-- Friendly identity for direct RLS-backed collaboration reads. Nullable keeps
-- pre-P2 members valid; P2-8 adds the editing surface.
alter table hunt_members add column display_name text check (
    display_name is null or char_length(btrim(display_name)) between 1 and 80
);
