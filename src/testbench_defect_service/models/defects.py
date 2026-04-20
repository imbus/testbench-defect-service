from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, TypeVar

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, RootModel

MAX_STR_LENGTH = 255


def max_length_255(v: str) -> str:
    return (v[: MAX_STR_LENGTH - 3] + "...") if len(v) > MAX_STR_LENGTH else v


Str_256 = Annotated[str, BeforeValidator(max_length_255)]


class Settings(BaseModel):
    name: Str_256  # validation remove the spaces
    description: str
    readonly: bool


class Login(BaseModel):
    username: str
    password: str


class DefectID(RootModel[str]):
    root: str = Field(..., description="Unique identifier of a defect")


class UserDefinedFieldProperties(BaseModel):
    name: str
    value: str | None = None
    mustField: bool | None = False


class ValueType(Enum):
    STRING = "STRING"
    BOOLEAN = "BOOLEAN"


class ProtocolCode(Enum):
    READ_ACCESS_ERROR = "READ_ACCESS_ERROR"
    INSERT_ACCESS_ERROR = "INSERT_ACCESS_ERROR"
    INSERT_ERROR = "INSERT_ERROR"
    INSERT_SUCCESS = "INSERT_SUCCESS"
    PUBLISH_ACCESS_ERROR = "PUBLISH_ACCESS_ERROR"
    PUBLISH_ERROR = "PUBLISH_ERROR"
    PUBLISH_SUCCESS = "PUBLISH_SUCCESS"
    IMPORT_ERROR = "IMPORT_ERROR"
    IMPORT_SUCCESS = "IMPORT_SUCCESS"
    UPDATE_ERROR = "UPDATE_ERROR"
    UPDATE_SUCCESS = "UPDATE_SUCCESS"
    INVALID_FIELDS = "INVALID_FIELDS"
    INVALID_ATTRIBUTES = "INVALID_ATTRIBUTES"
    DEFECT_NOT_FOUND = "DEFECT_NOT_FOUND"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    NO_DEFECT_FOUND = "NO_DEFECT_FOUND"
    NO_VALID_LICENSE = "NO_VALID_LICENSE"
    NO_FREE_LICENSE = "NO_FREE_LICENSE"
    LICENSE_EXPIRED = "LICENSE_EXPIRED"
    LICENSE_PROBLEM = "LICENSE_PROBLEM"
    INSERT_WARNING = "INSERT_WARNING"
    IMPORT_WARNING = "IMPORT_WARNING"


class DefectSyncOption(Enum):
    USE_SYNC_MASTER = "USE_SYNC_MASTER"
    FORCE_PUBLISH = "FORCE_PUBLISH"
    FORCE_UPDATE = "FORCE_UPDATE"


class DefectFieldSyncOption(Enum):
    ITB = "ITB"
    DMS = "DMS"
    TIMESTAMP = "TIMESTAMP"


class UserDefinedAttribute(BaseModel):
    name: str
    valueType: ValueType
    mustField: bool | None = None
    lastEdited: AwareDatetime | None = None
    stringValue: str | None = None
    booleanValue: bool | None = None


class ExtendedAttributes(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProtocolEntrySuccess(BaseModel):
    code: ProtocolCode | None = None
    message: str | None = None


class ProtocolEntryWarning(BaseModel):
    code: ProtocolCode | None = None
    message: str | None = None


class ProtocolEntryError(BaseModel):
    code: ProtocolCode | None = None
    message: str | None = None


class Defect(BaseModel):
    title: Str_256 | None = None
    description: str | None = None
    reporter: Str_256 | None = None
    status: Str_256
    classification: Str_256
    priority: Str_256
    userDefinedFields: list[UserDefinedFieldProperties] | None = []
    lastEdited: AwareDatetime
    references: list[str] | None = []
    principal: Login


class DefectWithID(Defect):
    id: DefectID


class DefectWithLocalPk(Defect):
    localPk: str


class KnownDefect(DefectWithID):
    localPk: str


class DefectWithAttributes(DefectWithID):
    attributes: ExtendedAttributes


class LocalSyncActions(BaseModel):
    delete: list[KnownDefect] | None = None
    update: list[KnownDefect] | None = None
    create: list[DefectWithID] | None = None


class RemoteSyncActions(BaseModel):
    delete: list[KnownDefect] | None = None
    update: list[KnownDefect] | None = None
    create: list[DefectWithLocalPk] | None = None


class SyncContext(BaseModel):
    iTBProject: str | None = Field(None, description="ITB project name")
    lastSync: datetime | None = None
    statusAttribute: str | None = None
    statusSyncOption: DefectFieldSyncOption | None = None
    priorityAttribute: str | None = None
    prioritySyncOption: DefectFieldSyncOption | None = None
    classAttribute: str | None = None
    classSyncOption: DefectFieldSyncOption | None = None
    serverTime: datetime | None = None
    udaSyncOptions: dict[str, DefectFieldSyncOption] | None = None
    syncOption: DefectSyncOption | None = None
    importNewDefects: bool | None = None


_T = TypeVar("_T", ProtocolEntrySuccess, ProtocolEntryWarning, ProtocolEntryError)


class Protocol(BaseModel):
    successes: dict[str, list[ProtocolEntrySuccess]] | None = {}
    warnings: dict[str, list[ProtocolEntryWarning]] | None = {}
    errors: dict[str, list[ProtocolEntryError]] | None = {}
    generalWarnings: list[ProtocolEntryWarning] | None = []
    generalErrors: list[ProtocolEntryError] | None = []

    @staticmethod
    def _append_entry(
        container: dict[str, list[_T]] | None,
        key: str,
        entry: _T,
    ) -> dict[str, list[_T]]:
        if container is None:
            container = {}
        if key not in container:
            container[key] = []
        container[key].append(entry)
        return container

    def add_success(self, key: str, message: str, protocol_code: ProtocolCode) -> None:
        self.successes = self._append_entry(
            self.successes, key, ProtocolEntrySuccess(code=protocol_code, message=message)
        )

    def add_warning(self, key: str, message: str, protocol_code: ProtocolCode) -> None:
        self.warnings = self._append_entry(
            self.warnings, key, ProtocolEntryWarning(code=protocol_code, message=message)
        )

    def add_error(self, key: str, message: str, protocol_code: ProtocolCode) -> None:
        self.errors = self._append_entry(
            self.errors, key, ProtocolEntryError(code=protocol_code, message=message)
        )

    def add_general_warning(self, message: str, protocol_code: ProtocolCode) -> None:
        if self.generalWarnings is None:
            self.generalWarnings = []
        self.generalWarnings.append(ProtocolEntryWarning(code=protocol_code, message=message))

    def add_general_error(self, message: str, protocol_code: ProtocolCode) -> None:
        if self.generalErrors is None:
            self.generalErrors = []
        self.generalErrors.append(ProtocolEntryError(code=protocol_code, message=message))


class ProtocolledDefectSet(BaseModel):
    value: list[DefectWithID]
    protocol: Protocol


class ProtocolledString(BaseModel):
    value: str = Field(..., description="ID of the newly created defect, if successful")
    protocol: Protocol


class Results(BaseModel):
    local: LocalSyncActions | None = None
    remote: RemoteSyncActions | None = None


class DefectRequest(BaseModel):
    defect: Defect
    syncContext: SyncContext


class BatchDefectRequest(BaseModel):
    defectIds: list[DefectID]
    syncContext: SyncContext


class SyncRequest(BaseModel):
    syncType: str
    syncContext: SyncContext
