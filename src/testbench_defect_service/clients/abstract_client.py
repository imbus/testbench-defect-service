from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from testbench_defect_service.models.defects import (
    Defect,
    DefectID,
    DefectWithAttributes,
    Protocol,
    ProtocolledDefectSet,
    ProtocolledString,
    Results,
    Settings,
    SyncContext,
    UserDefinedAttribute,
)


class AbstractDefectClient(ABC):
    """Base class for defect management system clients.

    This abstract class defines the interface for integrating with various defect
    management systems (e.g., Jira, JSONL). All implementations must conform to
    the API3 Defect Management API specification.

    Subclasses must:
    - Set CONFIG_CLASS to their specific config model type (e.g., JiraDefectClientConfig)
    - Implement all abstract methods
    - Raise appropriate exceptions for error conditions (NotFound, ServerError, ValidationError)
    - Handle authentication and authorization through the principal in Defect objects

    Exception Guidelines:
    - Raise sanic.NotFound for missing resources (projects, defects)
    - Raise sanic.ServerError for client/server errors
    - Raise pydantic.ValidationError for invalid data
    """

    # Subclasses must override this to specify their config model type
    CONFIG_CLASS: ClassVar[type[BaseModel] | None] = None

    @abstractmethod
    def __init__(self, config: BaseModel):
        """Initialize the defect client with validated configuration.

        Args:
            config: Validated configuration object (type specified by CONFIG_CLASS)
        """

    @abstractmethod
    def check_login(self, project: str | None) -> bool:
        """Check whether the current credentials are valid.

        Args:
            project (str | None): Optional project identifier to scope the credential check.
                    If None, validates general system access.

        Returns:
            bool: True if credentials are valid, False otherwise.
        """

    @abstractmethod
    def get_settings(self) -> Settings:
        """Retrieve defect management system settings and metadata.

        Returns:
            Settings: object containing system name, description, and readonly status.
        """

    @abstractmethod
    def get_projects(self) -> list[str]:
        """Get list of all available project identifiers.

        Returns:
            list[str]: List of projects that the authenticated user can access.
        """

    @abstractmethod
    def get_control_fields(self, project: str | None) -> dict[str, list[str]]:
        """Return the allowed values for all defect control fields
        (status, priority, classification).

        Args:
            project (str | None): Optional project identifier. If None, returns system-wide control fields.

        Returns:
            dict[str,list[str]]: Dictionary mapping each field name to its list of valid values.
            Example: {"status": ["Open", "Closed"], "priority": ["High", "Low"]}
        """  # noqa: E501

    @abstractmethod
    def get_defects(self, project: str, sync_context: SyncContext) -> ProtocolledDefectSet:
        """Return all defects for a project together with a sync protocol.

        Args:
            project (str): Project identifier.
            sync_context (SyncContext): Synchronization context containing sync options and filtering criteria.

        Returns:
            ProtocolledDefectSet: object containing defects and operation protocol messages.
        """  # noqa: E501

    @abstractmethod
    def get_defects_batch(
        self, project: str, defect_ids: list[DefectID], sync_context: SyncContext
    ) -> ProtocolledDefectSet:
        """Return a specific set of defects by their IDs.

        Args:
            project (str): Project identifier.
            defect_ids (list[DefectID]): List of defect IDs to retrieve.
            sync_context (SyncContext): Synchronization context for filtering and options.

        Returns:
            ProtocolledDefectSet: object containing the requested defects and protocol messages.
        """

    @abstractmethod
    def create_defect(
        self, project: str, defect: Defect, sync_context: SyncContext
    ) -> ProtocolledString:
        """Create a new defect in the specified project.

        Args:
            project (str): Project identifier where the defect will be created.
            defect (Defect): Defect data including all required fields.
            sync_context (SyncContext): Synchronization context for creation options.

        Returns:
            ProtocolledString: object containing the ID of the created defect and an operation protocol.
        """  # noqa: E501

    @abstractmethod
    def update_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        """Update an existing defect with new data.

        Args:
            project (str): Project identifier containing the defect.
            defect_id (str): Unique identifier of the defect to update.
            defect (Defect): Defect object carrying the updated field values.
            sync_context (SyncContext): Synchronization context for update options.

        Returns:
            Protocol: object containing the operation result and any messages.
        """

    @abstractmethod
    def delete_defect(
        self, project: str, defect_id: str, defect: Defect, sync_context: SyncContext
    ) -> Protocol:
        """Delete an existing defect.

        Args:
            project (str): Project identifier containing the defect.
            defect_id (str): Unique identifier of the defect to delete.
            defect (Defect): Defect object carrying principal/authorization information.
            sync_context (SyncContext): Synchronization context for deletion options.

        Returns:
            Protocol: object containing the operation result and any messages.
        """

    @abstractmethod
    def get_defect_extended(
        self, project: str, defect_id: str, sync_context: SyncContext
    ) -> DefectWithAttributes:
        """Return a defect together with its extended system-specific attributes.

        Args:
            project (str): Project identifier containing the defect.
            defect_id (str): Unique identifier of the defect.
            sync_context (SyncContext): Synchronization context used to determine which attributes to include.

        Returns:
            DefectWithAttributes: object containing the full defect data plus extended attributes.
        """  # noqa: E501

    @abstractmethod
    def get_user_defined_attributes(self, project: str | None) -> list[UserDefinedAttribute]:
        """Return the user-defined field definitions for a project.

        Args:
            project (str | None): Optional project identifier. If None, returns system-wide definitions.

        Returns:
            list[UserDefinedAttribute]: List of user-defined attribute definitions including their value types and constraints.
        """  # noqa: E501

    @abstractmethod
    def before_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        """Run pre-synchronization setup and validation hooks.

        Called once before a sync operation begins. Implementations may use this
        to acquire locks, validate state, or perform any required setup.

        Args:
            project (str): Project identifier to synchronize.
            sync_type (str): Type of synchronization operation being started.
            sync_context (SyncContext): Synchronization context and options.

        Returns:
            Protocol: object containing pre-sync validation results and messages.
        """

    @abstractmethod
    def after_sync(self, project: str, sync_type: str, sync_context: SyncContext) -> Protocol:
        """Run post-synchronization cleanup and finalization hooks.

        Called once after a sync operation completes. Implementations may use this
        to release locks, persist state, or perform any required cleanup.

        Args:
            project (str): Project identifier that was synchronized.
            sync_type (str): Type of synchronization operation that completed.
            sync_context (SyncContext): Synchronization context and options.

        Returns:
            Protocol: object containing post-sync results and messages.
        """

    @abstractmethod
    def supports_changes_timestamps(self) -> bool:
        """Return whether the defect management system supports change timestamps.

        Returns:
            bool: True if change tracking with timestamps is supported, False otherwise.
        """

    @abstractmethod
    def correct_sync_results(self, project: str, body: Results) -> Results:
        """Review and correct proposed synchronization changes before they are applied.

        Allows the defect management system to filter, adjust, or reject individual
        sync actions in the proposed change set.

        Args:
            project (str): Project identifier for the sync operation.
            body (Results): Proposed sync actions for local and remote changes.

        Returns:
            Results: object with corrected/validated sync actions.
        """
