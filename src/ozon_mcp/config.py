"""Runtime configuration loaded from environment variables.

Credentials are wrapped in pydantic.SecretStr so they cannot leak via
accidental repr/print/log.dump of the Config object. Pull the raw value
only at the call site that builds the auth header.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OZON_",
        case_sensitive=False,
        extra="ignore",
    )

    client_id: SecretStr | None = None
    api_key: SecretStr | None = None
    performance_client_id: SecretStr | None = None
    performance_client_secret: SecretStr | None = None

    log_level: str = "INFO"

    def has_seller_credentials(self) -> bool:
        return bool(self.client_id and self.api_key)

    def has_performance_credentials(self) -> bool:
        return bool(self.performance_client_id and self.performance_client_secret)

    def seller_client_id(self) -> str:
        if self.client_id is None:
            raise RuntimeError("seller credentials not configured")
        return self.client_id.get_secret_value()

    def seller_api_key(self) -> str:
        if self.api_key is None:
            raise RuntimeError("seller credentials not configured")
        return self.api_key.get_secret_value()

    def perf_client_id(self) -> str:
        if self.performance_client_id is None:
            raise RuntimeError("performance credentials not configured")
        return self.performance_client_id.get_secret_value()

    def perf_client_secret(self) -> str:
        if self.performance_client_secret is None:
            raise RuntimeError("performance credentials not configured")
        return self.performance_client_secret.get_secret_value()
