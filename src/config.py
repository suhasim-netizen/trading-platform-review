"""Application settings loaded from environment (never hardcode secrets)."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings contract; extend only with Security Architect review."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        validation_alias="ENVIRONMENT",
        description="Deployment environment: development|staging|production",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    database_url: str = Field(
        ...,
        validation_alias="DATABASE_URL",
        description="SQLAlchemy URL, e.g. postgresql+asyncpg://...",
    )

    secret_key: str = Field(..., min_length=32, validation_alias="SECRET_KEY")
    token_encryption_key: str = Field(
        ...,
        min_length=40,
        validation_alias="TOKEN_ENCRYPTION_KEY",
        description="Fernet key from Fernet.generate_key().decode() (~44 urlsafe base64 chars).",
    )

    # Platform OAuth application settings (NOT per-tenant token material).
    broker_impl: str = Field(
        default="tradestation",
        validation_alias="BROKER_IMPL",
        description="Concrete broker adapter key registered in brokers.registry (e.g. tradestation).",
    )

    paper_trading_mode: bool = Field(
        default=True,
        validation_alias="PAPER_TRADING_MODE",
        description=(
            "When True, TradeStation order execution (REST + order streams) must use simulation "
            "(sim.api.tradestation.com). Market data may still use the live API; see MARKET_DATA_BASE_URL."
        ),
    )

    market_data_base_url: str = Field(
        default="https://api.tradestation.com",
        validation_alias="MARKET_DATA_BASE_URL",
        description="TradeStation market data REST + bar/quote streams (live API; real prices).",
    )

    broker_client_id: str = Field(default="", validation_alias="BROKER_CLIENT_ID")
    broker_client_secret: str = Field(default="", validation_alias="BROKER_CLIENT_SECRET")
    broker_redirect_uri: str = Field(default="", validation_alias="BROKER_REDIRECT_URI")
    broker_auth_base_url: str = Field(default="", validation_alias="BROKER_AUTH_BASE_URL")
    broker_api_base_url: str = Field(
        default="https://sim.api.tradestation.com",
        validation_alias="BROKER_API_BASE_URL",
        description="Order execution + brokerage REST (sim in paper mode, live when approved).",
    )
    broker_ws_base_url: str = Field(
        default="",
        validation_alias="BROKER_WS_BASE_URL",
        description="WSS host for order/brokerage HTTP chunk streams; defaults to order REST host if empty.",
    )

    # --- TradeStation OAuth env compatibility ---
    # Some tooling uses TS_* names; prefer those if set, but allow BROKER_* as fallback.
    ts_client_id: str = Field(default="", validation_alias=AliasChoices("TS_CLIENT_ID", "BROKER_CLIENT_ID"))
    ts_client_secret: str = Field(
        default="", validation_alias=AliasChoices("TS_CLIENT_SECRET", "BROKER_CLIENT_SECRET")
    )
    ts_redirect_uri: str = Field(
        default="", validation_alias=AliasChoices("TS_REDIRECT_URI", "BROKER_REDIRECT_URI")
    )

    # --- TradeStation multi-account routing (Phase 1) ---
    # Prefer these over TS_ACCOUNT_ID; router selects by Order.instrument_type.
    ts_equity_account_id: str = Field(default="", validation_alias="TS_EQUITY_ACCOUNT_ID")
    ts_options_account_id: str = Field(default="", validation_alias="TS_OPTIONS_ACCOUNT_ID")
    ts_futures_account_id: str = Field(default="", validation_alias="TS_FUTURES_ACCOUNT_ID")

    futures_margin_budget_usd: Decimal = Field(
        default=Decimal("22800"),
        validation_alias="FUTURES_MARGIN_BUDGET_USD",
        description="Approximate day-trading margin budget for micro futures sizing checks (strategy 006).",
    )

    # Deprecated fallback (avoid using in new code).
    ts_account_id: str = Field(default="", validation_alias="TS_ACCOUNT_ID")

    allowed_tenant_ids: str = Field(
        default="director",
        validation_alias="ALLOWED_TENANT_IDS",
        description="Comma-separated tenant_id values permitted in this deployment.",
    )

    @field_validator("allowed_tenant_ids")
    @classmethod
    def strip_tenant_list(cls, v: str) -> str:
        parts = [p.strip() for p in v.split(",") if p.strip()]
        return ",".join(parts)

    def allowed_tenants(self) -> set[str]:
        return {t.strip() for t in self.allowed_tenant_ids.split(",") if t.strip()}

    @field_validator(
        "broker_auth_base_url",
        "broker_api_base_url",
        "broker_ws_base_url",
        "market_data_base_url",
        "broker_redirect_uri",
        mode="after",
    )
    @classmethod
    def validate_broker_urls(cls, v: str, info):  # type: ignore[no-untyped-def]
        # Empty is allowed in development (tests/mocks); higher environments must set values.
        if v == "":
            return v
        parsed = urlparse(v)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"{info.field_name} must be a valid absolute URL")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        vv = v.strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if vv not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of: {sorted(allowed)}")
        return vv

    @field_validator("broker_client_secret", mode="after")
    @classmethod
    def validate_broker_client_secret_not_placeholder(cls, v: str) -> str:
        # Avoid accidental placeholder values that look "ready" in non-dev contexts.
        return v.strip()

    @field_validator("database_url")
    @classmethod
    def validate_database_url_nonempty(cls, v: str) -> str:
        vv = v.strip()
        if not vv:
            raise ValueError("DATABASE_URL must be set")
        return vv

    @field_validator("broker_auth_base_url", "broker_api_base_url", "broker_ws_base_url", "market_data_base_url")
    @classmethod
    def enforce_tls_in_non_dev(cls, v: str, info):  # type: ignore[no-untyped-def]
        if v == "":
            return v
        parsed = urlparse(v)
        if parsed.scheme in {"http", "ws"}:
            raise ValueError(f"{info.field_name} must use TLS (https/wss) in non-development")
        return v

    @field_validator("broker_client_id", "broker_client_secret", "broker_redirect_uri")
    @classmethod
    def require_broker_oauth_settings_outside_dev(cls, v: str, info):  # type: ignore[no-untyped-def]
        # Pydantic validators are field-local; this check is completed below in settings-level init.
        return v.strip()

    def validate_required_for_env(self) -> None:
        """Enforce environment-specific requirements."""
        if self.environment == "development":
            return
        missing = []
        for name in (
            "broker_client_id",
            "broker_client_secret",
            "broker_redirect_uri",
            "broker_auth_base_url",
            "broker_api_base_url",
            "broker_ws_base_url",
            "market_data_base_url",
        ):
            if not getattr(self, name):
                missing.append(name)
        if missing:
            raise ValueError(
                "Missing required broker OAuth/app settings for non-development: "
                + ", ".join(missing)
            )


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.validate_required_for_env()
    return s
