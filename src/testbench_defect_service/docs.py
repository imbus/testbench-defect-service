"""Swagger UI and OpenAPI spec routes.

Serves the bundled ``openapi.yaml`` and Swagger UI under ``/docs``. This replaces
sanic-ext's OpenAPI extension, which pulled in PyYAML: PyYAML has no wheels for every
supported Python version, and building it from source needs a C compiler on Windows.
"""

from pathlib import Path

from sanic import Blueprint, response
from sanic.request import Request

_PACKAGE_DIR = Path(__file__).parent
OPENAPI_SPEC_PATH = _PACKAGE_DIR / "openapi.yaml"
SWAGGER_HTML_PATH = _PACKAGE_DIR / "static" / "swagger-ui" / "index.html"
SWAGGER_HTML_TITLE = "OpenAPI Swagger"
SWAGGER_UI_CONFIGURATION = {
    "apisSorter": "alpha",
    "operationsSorter": "alpha",
    "docExpansion": "full",
}


async def swagger_ui(request: Request) -> response.HTTPResponse:
    page = SWAGGER_HTML_PATH.read_text(encoding="utf-8")
    return response.html(page.replace("__HTML_TITLE__", SWAGGER_HTML_TITLE))


async def openapi_spec(request: Request) -> response.HTTPResponse:
    return await response.file(OPENAPI_SPEC_PATH)


async def swagger_config(request: Request) -> response.HTTPResponse:
    return response.json(SWAGGER_UI_CONFIGURATION)


# Registered via add_route (not decorators) so the handlers stay plain, typed coroutines.
docs_router = Blueprint("docs", url_prefix="/docs")
docs_router.add_route(swagger_ui, "", methods=["GET"], name="index")
docs_router.add_route(swagger_ui, "/swagger", methods=["GET"], name="swagger")
docs_router.add_route(openapi_spec, "/openapi.json", methods=["GET"], name="openapi_spec")
docs_router.add_route(swagger_config, "/swagger-config", methods=["GET"], name="swagger_config")
