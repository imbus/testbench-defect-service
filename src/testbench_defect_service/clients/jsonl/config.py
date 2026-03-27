from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class SyncCommandConfig(BaseModel):
    scheduled: str | None = Field(default=None, description="Scheduled command")
    manual: str | None = Field(default=None, description="Manual command")
    partial: str | None = Field(default=None, description="Partial command")


class PhaseCommands(BaseModel):
    presync: SyncCommandConfig | None = Field(default=None, description="Pre-sync commands")
    postsync: SyncCommandConfig | None = Field(default=None, description="Post-sync commands")


class ProjectConfig(BaseModel):
    readonly: bool | None = Field(default=None, description="Whether the project is read-only")
    control_fields: dict[str, list[str]] | None = Field(
        default=None,
        description="Control fields for the project",
        json_schema_extra={
            "item_label": "Control Field",
            "key_label": "Control field",
            "add_prompt": "Would you like to add a control field for this project?",
            "add_another_prompt": "Add another control field for this project?",
        },
    )
    supports_changes_timestamps: bool | None = Field(
        default=None, description="Whether the project supports change timestamps"
    )
    attributes: list[str] | None = Field(default=None, description="Attributes for the project")
    commands: PhaseCommands | None = Field(default=None, description="Commands for the project")


class JsonlDefectClientConfig(BaseModel):
    name: str = Field(
        default="JSONL",
        description="Name of the JSONL client",
        json_schema_extra={"skip_if_wizard": True},
    )
    description: str = Field(
        default="JSONL client for managing defect records stored in a File.",
        description="Description of the JSONL client",
        json_schema_extra={"skip_if_wizard": True},
    )
    defects_path: Path = Field(..., description="Path to your JSONL defects directory")
    readonly: bool = Field(default=False, description="Whether the client is read-only")
    control_fields: dict[str, list[str]] = Field(
        ...,
        description="Control fields for the JSONL client",
        json_schema_extra={
            "item_label": "Control Field",
            "key_label": "Control field",
            "add_prompt": "Would you like to add a control field?",
            "add_another_prompt": "Add another control field?",
        },
    )
    supports_changes_timestamps: bool = Field(
        default=True, description="Whether the client supports change timestamps"
    )
    attributes: list[str] = Field(
        default_factory=lambda: ["title", "status"], description="Attributes for the JSONL client"
    )
    commands: PhaseCommands | None = Field(
        default=None, description="Commands for the JSONL client"
    )

    projects: dict[str, ProjectConfig] = Field(
        default_factory=dict,
        description="Project-specific configuration overrides",
        json_schema_extra={
            "item_label": "Project Configuration",
            "key_label": "Project Key",
            "add_prompt": "Would you like to add a project-specific configuration?",
            "add_another_prompt": "Add another project configuration?",
        },
    )

    @field_validator("defects_path", mode="after")
    @classmethod
    def validate_defects_path(cls, defects_path: Path) -> Path:
        if not defects_path.exists():
            raise FileNotFoundError(f"defects_path not found: '{defects_path.resolve()}'.")
        return defects_path
