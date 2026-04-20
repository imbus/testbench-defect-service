import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator
from pydantic.fields import Field


class SyncCommandConfig(BaseModel):
    scheduled: str | None = Field(default=None, description="Scheduled command")
    manual: str | None = Field(default=None, description="Manual command")
    partial: str | None = Field(default=None, description="Partial command")


class PhaseCommands(BaseModel):
    presync: SyncCommandConfig | None = Field(default=None, description="Pre-sync commands")
    postsync: SyncCommandConfig | None = Field(default=None, description="Post-sync commands")


class JiraProjectConfig(BaseModel):
    defect_jql: str | None = Field(None, description="JQL query template for this project")
    attributes: list[str] | None = Field(None, description="Attributes for this project")
    control_fields: list[str] | None = Field(None, description="Control fields for this project")
    readonly: bool | None = Field(None, description="Whether the project is read-only")
    commands: PhaseCommands | None = Field(None, description="Commands for this project")
    show_change_history: bool | None = Field(
        None,
        description=(
            "Determines if the change history since the last sync is shown "
            "in the extended defect view."
        ),
    )
    enable_shared_auth: bool | None = Field(
        None, description="Enable use of a shared service account for Jira authentication."
    )


class JiraDefectClientConfig(BaseModel):
    name: str = Field(default="Jira", json_schema_extra={"skip_if_wizard": True})
    server_url: str = Field(
        ..., description="Jira server URL (e.g., https://your-domain.atlassian.net)"
    )
    auth_type: Literal["basic", "token", "oauth1"] = Field(
        "basic",
        description=(
            "Authentication type: basic (Cloud), token (Self-Hosted), or oauth1 (OAuth 1.0a)"
        ),
    )

    username: str | None = Field(
        None,
        description="Username for basic authentication (Jira Cloud)",
        json_schema_extra={
            "env_var": "JIRA_USERNAME",
            "depends_on": {"auth_type": "basic"},
            "required": True,
        },
    )
    password: str | None = Field(
        None,
        description=(
            "Password for basic auth. "
            "Use an API token on Jira Cloud, account password on Jira Data Center."
        ),
        json_schema_extra={
            "sensitive": True,
            "env_var": "JIRA_PASSWORD",
            "depends_on": {"auth_type": "basic"},
            "required": True,
        },
    )

    token: str | None = Field(
        None,
        description="Personal Access Token for token-based auth (Jira Self-Hosted)",
        json_schema_extra={
            "sensitive": True,
            "env_var": "JIRA_BEARER_TOKEN",
            "depends_on": {"auth_type": "token"},
            "required": True,
        },
    )

    oauth1_access_token: str | None = Field(
        None,
        description="OAuth1 access token",
        json_schema_extra={
            "sensitive": True,
            "env_var": "JIRA_OAUTH1_ACCESS_TOKEN",
            "depends_on": {"auth_type": "oauth1"},
            "required": True,
        },
    )
    oauth1_access_token_secret: str | None = Field(
        None,
        description="OAuth1 access token secret",
        json_schema_extra={
            "sensitive": True,
            "env_var": "JIRA_OAUTH1_ACCESS_TOKEN_SECRET",
            "depends_on": {"auth_type": "oauth1"},
            "required": True,
        },
    )
    oauth1_consumer_key: str | None = Field(
        None,
        description="OAuth1 consumer key",
        json_schema_extra={
            "env_var": "JIRA_OAUTH1_CONSUMER_KEY",
            "depends_on": {"auth_type": "oauth1"},
            "required": True,
        },
    )
    oauth1_key_cert_path: str | None = Field(
        None,
        description="Path to the OAuth1 private key certificate file (.pem)",
        json_schema_extra={
            "env_var": "JIRA_OAUTH1_KEY_CERT_PATH",
            "depends_on": {"auth_type": "oauth1"},
            "required": True,
        },
    )
    oauth1_key_cert: str | None = Field(
        None,
        description="OAuth1 private key certificate content (use oauth1_key_cert_path instead)",
        json_schema_extra={
            "sensitive": True,
            "env_var": "JIRA_OAUTH1_KEY_CERT",
            "depends_on": {"auth_type": "oauth1"},
            "required": False,
            "skip_if_wizard": True,
        },
    )

    verify_ssl: bool = Field(
        True,
        description=(
            "Enable SSL certificate verification for the Jira HTTPS connection. "
            "Set to False only in development/test environments with self-signed certificates "
            "when providing a CA cert file is not possible."
        ),
        json_schema_extra={"env_var": "JIRA_VERIFY_SSL"},
    )
    ssl_ca_cert_path: str | None = Field(
        None,
        description=(
            "Path to a CA certificate or bundle file (.pem/.crt) used to verify the "
            "Jira server's SSL certificate."
        ),
        json_schema_extra={
            "env_var": "JIRA_SSL_CA_CERT_PATH",
        },
    )
    client_cert_path: str | None = Field(
        None,
        description="Path to client certificate file for mutual TLS authentication (.pem or .crt)",
        json_schema_extra={
            "env_var": "JIRA_CLIENT_CERT_PATH",
        },
    )
    client_key_path: str | None = Field(
        None,
        description="Path to client private key file for mutual TLS authentication (.key or .pem). "
        "Only needed when the key is stored separately from the certificate.",
        json_schema_extra={
            "env_var": "JIRA_CLIENT_KEY_PATH",
        },
    )

    defect_jql: str = Field(
        "project = '{project}' AND issuetype in standardIssueTypes()",
        description="JQL query template for fetching defects",
    )
    attributes: list[str] = Field(
        default_factory=lambda: ["title", "status"],
        description="Fields from Jira to display in the extended defect view.",
    )
    control_fields: list[str] = Field(
        default=["priority", "status", "classification"],
        description="Control fields for the Jira client",
    )
    readonly: bool = Field(default=False, description="Whether the client is read-only")
    show_change_history: bool | None = Field(
        None,
        description=(
            "Determines if the change history since the last sync is shown "
            "in the extended defect view."
        ),
    )
    enable_shared_auth: bool | None = Field(
        None, description="Enable use of a shared service account for Jira authentication."
    )
    supports_changes_timestamps: bool = Field(
        default=True, description="Whether the client supports change timestamps"
    )

    timeout: int = Field(
        30,
        description="HTTP request timeout in seconds for Jira API calls",
        ge=1,
    )
    max_retries: int = Field(
        3,
        description="Maximum number of retries for failed Jira API requests",
        ge=0,
        le=10,
    )

    commands: PhaseCommands | None = Field(default=None, description="Commands for the Jira client")
    projects: dict[str, JiraProjectConfig] = Field(
        default_factory=dict,
        description="Project-specific configuration overrides",
        json_schema_extra={
            "item_label": "Project Configuration",
            "key_label": "Project Key",
            "add_prompt": "Would you like to add a project-specific configuration?",
            "add_another_prompt": "Add another project configuration?",
        },
    )

    @property
    def ssl_verify(self) -> str | bool:
        """Return the value for SSL verification passed to the jira package ``options`` dict.

        Returns:
        - ``False`` when ``verify_ssl`` is explicitly disabled.
        - Path string to the CA cert/bundle when ``ssl_ca_cert_path`` is configured.
        - ``True`` (default certifi verification) otherwise.
        """
        if not self.verify_ssl:
            return False
        ca_cert = self.ssl_ca_cert_path or os.getenv("JIRA_SSL_CA_CERT_PATH")
        return ca_cert if ca_cert else True

    @property
    def client_cert(self) -> str | tuple[str, str] | None:
        """Build the client_cert value expected by the jira package ``options`` dict.

        Returns:
        - ``str`` path when only ``client_cert_path`` is set (combined cert+key file).
        - ``(cert, key)`` tuple when both ``client_cert_path`` and ``client_key_path`` are set.
        - ``None`` when no client certificate is configured.
        """
        cert = self.client_cert_path or os.getenv("JIRA_CLIENT_CERT_PATH")
        key = self.client_key_path or os.getenv("JIRA_CLIENT_KEY_PATH")
        if cert and key:
            return (cert, key)
        return cert or None

    @field_validator("oauth1_key_cert_path")
    @classmethod
    def validate_oauth1_key_cert_path_exists(cls, v: str | None) -> str | None:
        """Validate that oauth1_key_cert_path exists if provided."""
        if v is not None and not Path(v).exists():
            raise ValueError(f"OAuth1 private key file not found: '{v}'")
        return v

    @field_validator("ssl_ca_cert_path", "client_cert_path", "client_key_path")
    @classmethod
    def validate_cert_files_exist(cls, v: str | None) -> str | None:
        """Validate that certificate/key files exist if provided."""
        if v is not None and not Path(v).exists():
            raise ValueError(f"Certificate/key file not found: '{v}'")
        return v

    def _validate_basic_auth(self) -> None:
        self.username = self.username or os.getenv("JIRA_USERNAME")
        if not self.username:
            raise ValueError(
                "Jira username must be provided for basic auth (via config or JIRA_USERNAME env)"
            )
        self.password = self.password or os.getenv("JIRA_PASSWORD")
        if not self.password:
            raise ValueError(
                "Jira password must be provided for basic auth (via config or JIRA_PASSWORD env)"
            )

    def _validate_token_auth(self) -> None:
        self.token = self.token or os.getenv("JIRA_BEARER_TOKEN")
        if not self.token:
            raise ValueError(
                "Jira Personal Access Token must be provided for token auth "
                "(via config or JIRA_BEARER_TOKEN env)"
            )

    def _validate_oauth1(self) -> None:
        self.oauth1_access_token = self.oauth1_access_token or os.getenv("JIRA_OAUTH1_ACCESS_TOKEN")
        self.oauth1_access_token_secret = self.oauth1_access_token_secret or os.getenv(
            "JIRA_OAUTH1_ACCESS_TOKEN_SECRET"
        )
        self.oauth1_consumer_key = self.oauth1_consumer_key or os.getenv("JIRA_OAUTH1_CONSUMER_KEY")
        self.oauth1_key_cert_path = self.oauth1_key_cert_path or os.getenv(
            "JIRA_OAUTH1_KEY_CERT_PATH"
        )
        if self.oauth1_key_cert_path:
            try:
                self.oauth1_key_cert = Path(self.oauth1_key_cert_path).read_text(encoding="utf-8")
            except OSError as e:
                raise ValueError(
                    f"Could not read OAuth1 private key from '{self.oauth1_key_cert_path}': {e}"
                ) from e
        else:
            self.oauth1_key_cert = self.oauth1_key_cert or os.getenv("JIRA_OAUTH1_KEY_CERT")
        if not self.oauth1_access_token:
            raise ValueError(
                "Jira Access Token must be provided for OAuth1 "
                "(via config or JIRA_OAUTH1_ACCESS_TOKEN env)"
            )
        if not self.oauth1_access_token_secret:
            raise ValueError(
                "Jira Access Token Secret must be provided for OAuth1 "
                "(via config or JIRA_OAUTH1_ACCESS_TOKEN_SECRET env)"
            )
        if not self.oauth1_consumer_key:
            raise ValueError(
                "Jira consumer key must be provided for OAuth1 "
                "(via config or JIRA_OAUTH1_CONSUMER_KEY env)"
            )
        if not self.oauth1_key_cert:
            raise ValueError(
                "Jira Private Key must be provided for OAuth1 "
                "(via oauth1_key_cert_path / JIRA_OAUTH1_KEY_CERT_PATH "
                "or oauth1_key_cert / JIRA_OAUTH1_KEY_CERT env)"
            )

    @model_validator(mode="after")
    def validate_config(self):
        if self.auth_type == "basic":
            self._validate_basic_auth()
        elif self.auth_type == "token":
            self._validate_token_auth()
        elif self.auth_type == "oauth1":
            self._validate_oauth1()
        return self
