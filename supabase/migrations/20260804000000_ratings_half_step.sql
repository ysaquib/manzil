-- Hunt member ratings: 1..5 in 0.5 steps (docs/superpowers/specs/2026-07-24-half-star-api-ratings-design.md).

alter table ratings drop constraint if exists ratings_value_check;

alter table ratings
    alter column rating type numeric(2, 1) using rating::numeric(2, 1);

alter table ratings add constraint ratings_value_check check (
    rating >= 1
    and rating <= 5
    and (rating * 2) = trunc(rating * 2)
);
