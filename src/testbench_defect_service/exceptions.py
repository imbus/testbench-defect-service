from __future__ import annotations

try:  # noqa: SIM105
    from jira import JIRAError  # type: ignore[import-not-found]
except ImportError:
    pass
from pydantic import ValidationError
from sanic import Forbidden, NotFound, SanicException, ServerError, response
from sanic.errorpages import exception_response
from sanic.handlers import ErrorHandler
from sanic.request import Request
from sanic.response.types import HTTPResponse

from testbench_defect_service.log import logger
from testbench_defect_service.utils.validation import format_validation_error_details


class AppErrorHandler(ErrorHandler):
    """Routes all error logging through the application logger.

    - Debug mode: logs full traceback via the app logger.
    - Production mode: logs only error message via the app logger.
    - Errors with quiet=True are never logged.
    - JSON responses never include exception frames or extra debug data.
    """

    @staticmethod
    def log(request: Request, exception: Exception) -> None:  # type: ignore[override]
        quiet = getattr(exception, "quiet", False)
        noisy = getattr(request.app.config, "NOISY_EXCEPTIONS", False)
        if quiet and not noisy:
            return
        message = f"{type(exception).__name__}: {exception}"
        extra = {
            "method": request.method,
            "path": request.path,
            "status": getattr(exception, "status_code", 500),
        }
        if request.app.debug:
            logger.error(message, exc_info=exception, extra=extra)
        else:
            logger.error(message, extra=extra)

    def default(self, request: Request, exception: Exception) -> HTTPResponse:
        self.log(request, exception)
        fallback = request.app.config.FALLBACK_ERROR_FORMAT
        return exception_response(
            request,
            exception,
            debug=False,
            base=self.base,
            fallback=fallback,
        )


async def handle_jira_error(request: Request, exception: JIRAError):
    status_code = getattr(exception, "status_code", None)
    sanic_exc: SanicException
    if status_code == NotFound.status_code:
        sanic_exc = NotFound("Not Found")
    elif status_code == Forbidden.status_code:
        sanic_exc = Forbidden("Forbidden")
    else:
        sanic_exc = ServerError(f"Jira service error ({status_code})")
    sanic_exc.__cause__ = exception
    sanic_exc.__suppress_context__ = True
    return request.app.error_handler.default(request, sanic_exc)


async def handle_validation_error(request: Request, exception: ValidationError):
    errors = format_validation_error_details(exception)
    return response.json(
        {
            "description": "Bad Request",
            "status": 400,
            "message": "Validation error",
            "errors": errors,
        },
        status=400,
    )
