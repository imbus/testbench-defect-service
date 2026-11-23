import asyncio
import json
from unittest.mock import MagicMock

import pytest
from sanic import Sanic

from testbench_defect_service import docs


@pytest.mark.unit
def test_docs_blueprint_serves_swagger_ui_routes() -> None:
    app = Sanic("test_docs_routes")
    app.blueprint(docs.docs_router)
    app.router.finalize()

    paths = {"/" + route.path for route in app.router.routes}
    assert {"/docs", "/docs/swagger", "/docs/openapi.json", "/docs/swagger-config"} <= paths


@pytest.mark.unit
def test_swagger_page_is_rendered_with_title() -> None:
    response = asyncio.run(docs.swagger_ui(MagicMock()))

    assert response.status == 200
    assert response.body is not None
    assert response.content_type is not None
    assert response.content_type.startswith("text/html")
    body = response.body.decode()
    assert "<title>OpenAPI Swagger</title>" in body
    assert "__HTML_TITLE__" not in body
    assert "/static/swagger-ui/swagger-initializer.js" in body


@pytest.mark.unit
def test_openapi_spec_is_served_from_bundled_file() -> None:
    response = asyncio.run(docs.openapi_spec(MagicMock()))

    assert response.status == 200
    assert response.body == docs.OPENAPI_SPEC_PATH.read_bytes()


@pytest.mark.unit
def test_swagger_config_matches_previous_defaults() -> None:
    response = asyncio.run(docs.swagger_config(MagicMock()))

    assert response.body is not None
    assert json.loads(response.body) == {
        "apisSorter": "alpha",
        "operationsSorter": "alpha",
        "docExpansion": "full",
    }
