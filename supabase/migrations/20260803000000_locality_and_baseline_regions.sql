-- Locality columns on properties + state-qualified utility baseline regions (DESIGN v3.11).

alter table properties
    add column state text,
    add column county text,
    add constraint properties_state_code_check
        check (state is null or state ~ '^[A-Z]{2}$');

-- Regenerable cache: legacy metro-keyed rows cannot be migrated safely.
truncate table utility_baselines;

alter table utility_baselines drop constraint utility_baselines_pkey;
alter table utility_baselines rename column metro to region_name;

alter table utility_baselines
    add column geo_level text not null,
    add column state text not null,
    add constraint utility_baselines_geo_level_check
        check (geo_level in ('city', 'county', 'state')),
    add constraint utility_baselines_state_code_check
        check (state ~ '^[A-Z]{2}$'),
    add constraint utility_baselines_region_name_check
        check (btrim(region_name) <> ''
            and (geo_level <> 'state' or region_name = state)),
    add primary key (geo_level, state, region_name, beds_bucket, utility);
