"""Configuration models for TestBench Defect Service."""

from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from testbench_defect_service.models.logging import LoggingConfig

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8030


class DefectServiceConfig(BaseModel):
    """Validated service config loaded from TOML config file."""

    client_class: str = Field(
        default="testbench_defect_service.clients.JsonlDefectClient",
        description="Class path for the defect client to use",
    )
    client_config_path: Path | None = Field(
        default=None,
        description="Optional path to a separate client configuration file",
    )
    client_config: dict | None = Field(
        default=None,
        description="Inline client configuration (alternative to client_config_path)",
    )
    host: str = Field(
        default=DEFAULT_HOST,
        description="Hostname or IP address to bind the service to",
    )
    port: int = Field(
        default=DEFAULT_PORT,
        description="Port number to bind the service to",
    )
    debug: bool = Field(default=False, description="Enable debug mode for the service")
    password_hash: str | None = Field(default=None, description="Password hash for authentication")
    salt: str | None = Field(default=None, description="Salt used for password hashing")
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig, description="Logging configuration for the service"
    )
    ssl_cert: Path | None = Field(
        default=None,
        description="Path to SSL/TLS certificate file for HTTPS support (.crt or .pem)",
        json_schema_extra={"path_type": "file"},
    )
    ssl_key: Path | None = Field(
        default=None,
        description="Path to SSL/TLS private key file for HTTPS support (.key)",
        json_schema_extra={"path_type": "file"},
    )
    ssl_ca_cert: Path | None = Field(
        default=None,
        description="Optional path to CA certificate file for client verification",
        json_schema_extra={"path_type": "file"},
    )
    proxies_count: int | None = Field(
        default=None,
        description="Number of proxy servers in front of the application (for X-Forwarded headers)",
    )
    real_ip_header: str | None = Field(
        default=None,
        description="Header name to use for client IP (e.g., 'X-Real-IP')",
    )
    forwarded_secret: str | None = Field(
        default=None,
        description="Secret token for validating Forwarded header (security measure)",
    )

    @field_validator("client_config_path")
    @classmethod
    def validate_client_config_exists(cls, v: Path | None) -> Path | None:
        if v is not None and not v.exists():
            raise ValueError(f"Client config file not found: '{v}'")
        return v

    @field_validator("ssl_cert", "ssl_key", "ssl_ca_cert")
    @classmethod
    def validate_ssl_files_exist(cls, v: Path | None) -> Path | None:
        """Validate that SSL certificate files exist if provided."""
        if v is not None and not v.exists():
            raise ValueError(f"SSL certificate file not found: '{v}'")
        return v
