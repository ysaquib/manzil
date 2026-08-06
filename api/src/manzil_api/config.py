"""Global API settings (IMPLEMENTATION §1 env table, Phase 1 plan §4.1).

Pydantic `BaseSettings`, read once at import. Module-level settings (per the
fastapi-best-practices split) live in each domain package when they appear; this
is the app-wide global config only.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # Supabase — anon key is RLS-safe; service role is held ONLY for the
    # in-process worker loop (Phase 1 budget option, §1.5), never exposed.
    supabase_url: str = Field(alias="SUPABASE_URL")
    supabase_anon_key: str = Field(alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(alias="SUPABASE_SERVICE_ROLE_KEY")

    # Direct Postgres — the in-process worker loop's asyncpg pool.
    database_url: str = Field(alias="DATABASE_URL")

    # Demo Mode (DM-5, DESIGN §16). The project's JWT signing secret, used to
    # mint a short-lived demo viewer token. Deliberately NOT a GoTrue session:
    # a token with no session behind it cannot be used to change the shared
    # account's password or email, enrol MFA, or sign every other visitor out.
    # Empty disables demo-session issuance entirely, which is the safe default
    # for any deployment that has not set it.
    supabase_jwt_secret: str = Field(default="", alias="SUPABASE_JWT_SECRET")
    demo_session_ttl_seconds: int = Field(default=1800, alias="MANZIL_DEMO_TTL")
    # Salt for the truncated client-key HMAC. Without it no per-caller ceiling
    # is applied; the global ceiling still is.
    demo_client_key_salt: str = Field(default="", alias="MANZIL_DEMO_KEY_SALT")
    # Trusted reverse-proxy hops. `request.client.host` is the proxy on Render,
    # and X-Forwarded-For is caller-controlled, so the count must be explicit
    # rather than guessed from the header's length.
    demo_trusted_proxy_hops: int = Field(default=0, alias="MANZIL_DEMO_PROXY_HOPS")

    # `local` | `staging` | `production` — gates OpenAPI docs exposure.
    environment: Environment = Field(default="local", alias="API_ENVIRONMENT")

    # Comma-separated frontend dev origins for CORS.
    cors_origins: str = Field(default="http://localhost:5173", alias="API_CORS_ORIGINS")
    frontend_url: str = Field(default="http://localhost:5173", alias="MANZIL_FRONTEND_URL")

    # In-process worker loop toggle (DESIGN §5 default). Set false only after a
    # separate worker process is deployed and validated per IMPLEMENTATION §8.
    worker_inprocess: bool = Field(default=True, alias="MANZIL_WORKER_INPROCESS")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def docs_enabled(self) -> bool:
        return self.environment in ("local", "staging")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
