-- Let profiles and Hunt-specific member overrides use every concrete Manzil
-- theme palette except the neutral gray/dark scales. `stone` remains accepted
-- for existing rows but is no longer offered by the UI.

alter table user_profiles
    drop constraint user_profiles_default_color_check,
    add constraint user_profiles_default_color_check check (
        default_color in (
            'dusky', 'brick', 'orange', 'ochre', 'olive', 'moss', 'teal',
            'cyan', 'blue', 'indigo', 'violet', 'plum', 'pink', 'stone'
        )
        or default_color ~ '^#[0-9A-F]{6}$'
    );
