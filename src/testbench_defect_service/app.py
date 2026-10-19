from pathlib import Path

from pydantic import ValidationError
from sanic import Sanic

from testbench_defect_service.config import AppConfig
from testbench_defect_service.exceptions import (
    AppErrorHandler,
    handle_jira_error,
    handle_validation_error,
)
from testbench_defect_service.log import get_logging_dict, logger
from testbench_defect_service.middleware import check_request_auth, log_request, log_response
from testbench_defect_service.routes import router
from testbench_defect_service.utils.dependencies import (
    check_excel_dependencies,
    check_jira_dependencies,
)
from testbench_defect_service.utils.motd import build_client_motd


def register_middlewares(app: Sanic) -> None:
    """Register application middlewares."""
    app.register_middleware(log_request, "request")
    app.register_middleware(check_request_auth, "request")
    app.register_middleware(log_response, "response")  # type: ignore


def register_exception_handlers(app: Sanic) -> None:
    """Register application exception handlers."""
    app.exception(ValidationError)(handle_validation_error)
    try:
        from jira import JIRAError  # noqa: PLC0415

        app.exception(JIRAError)(handle_jira_error)
    except ImportError:
        pass


def check_dependencies(app: Sanic) -> None:
    """Check and validate optional dependencies based on client type."""
    if "ExcelDefectClient" in app.config.CLIENT_CLASS:
        check_excel_dependencies(raise_on_missing=True)

    if "JiraDefectClient" in app.config.CLIENT_CLASS:
        check_jira_dependencies(raise_on_missing=True)


def register_client_motd(app: Sanic, config: AppConfig) -> None:
    """Show the configured reader in Sanic's startup MOTD box."""
    try:
        app.config.MOTD_DISPLAY.update(build_client_motd(config))
    except Exception:
        logger.debug("Could not build the reader MOTD rows", exc_info=True)


def create_app(name: str, config: AppConfig | None = None) -> Sanic:
    """Create and configure the Sanic application."""
    if not config:
        config = AppConfig()

    log_config = get_logging_dict(config.LOG_CONFIG, debug=config.DEBUG)

    # Create Sanic app
    app = Sanic(name, log_config=log_config, error_handler=AppErrorHandler())

    # Apply configuration after Sanic initialization
    app.update_config(config)

    # Validate dependencies
    check_dependencies(app)

    # Summarise the configured reader in the startup MOTD
    register_client_motd(app, config)

    # Setup application
    register_middlewares(app)
    register_exception_handlers(app)
    app.blueprint(router)

    # Serve static assets
    static_path = (Path(__file__).parent / "static/swagger-ui").resolve().as_posix()
    app.static("/static/swagger-ui", static_path)

    return app
