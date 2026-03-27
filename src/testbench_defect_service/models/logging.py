from typing import Literal

from pydantic import BaseModel, Field

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class ConsoleLoggingConfig(BaseModel):
    log_level: LogLevel = "INFO"
    log_format: str = "%(asctime)s %(levelname)8s: %(message)s"


class FileLoggingConfig(BaseModel):
    log_level: LogLevel = "INFO"
    log_format: str = "%(asctime)s - %(levelname)8s - %(name)s - %(message)s"
    file_path: str = "testbench-defect-service.log"


class LoggingConfig(BaseModel):
    console: ConsoleLoggingConfig = Field(default_factory=ConsoleLoggingConfig)
    file: FileLoggingConfig = Field(default_factory=FileLoggingConfig)
