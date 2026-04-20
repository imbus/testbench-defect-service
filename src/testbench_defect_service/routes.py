from typing import Any

from sanic import BadRequest, Blueprint, response
from sanic.request import Request

from testbench_defect_service.clients.utils import get_defect_client
from testbench_defect_service.models.defects import (
    BatchDefectRequest,
    DefectRequest,
    Results,
    SyncContext,
    SyncRequest,
)
from testbench_defect_service.utils.auth import protected

router = Blueprint("defect")


def _require_json(request: Request) -> Any:
    body = request.json
    if body is None:
        raise BadRequest("Missing request body. Request body must be valid JSON.")
    return body


@router.route("/", methods=["GET"])
async def redirect_to_docs(request: Request):
    return response.redirect("/docs")


@router.route("/check-login", methods=["GET"])
@protected
async def get_check_login(request: Request):
    project = request.args.get("project")
    defect_client = get_defect_client(request.app)
    return response.json(defect_client.check_login(project))


@router.route("/settings", methods=["GET"])
async def get_settings(request: Request):
    defect_client = get_defect_client(request.app)
    return response.json(defect_client.get_settings().model_dump(mode="json"))


@router.route("/projects", methods=["GET"])
@protected
async def get_projects(request: Request):
    defect_client = get_defect_client(request.app)
    return response.json(defect_client.get_projects())


@router.route("/projects/control-fields", methods=["GET"], unquote=True)
@protected
async def get_projects_control_fields(request: Request):
    project = request.args.get("project")
    defect_client = get_defect_client(request.app)
    return response.json(defect_client.get_control_fields(project=project))


@router.route("/projects/<project:str>/defects", methods=["POST"], unquote=True)
@protected
async def get_projects_defects(request: Request, project: str):
    defect_client = get_defect_client(request.app)
    return response.json(
        defect_client.get_defects(
            project=project,
            sync_context=SyncContext.model_validate(request.json or {}),
        ).model_dump(mode="json")
    )


@router.route("/projects/<project:str>/defects/batch", methods=["POST"], unquote=True)
@protected
async def post_projects_defects_batch(request: Request, project: str):
    body = _require_json(request)
    batch_request = BatchDefectRequest.model_validate(body)
    defect_client = get_defect_client(request.app)
    return response.json(
        defect_client.get_defects_batch(
            project=project,
            defect_ids=batch_request.defectIds,
            sync_context=batch_request.syncContext,
        ).model_dump(mode="json")
    )


@router.route("/projects/<project:str>/defects/create", methods=["POST"], unquote=True)
@protected
async def post_projects_defects_create(request: Request, project: str):
    body = _require_json(request)
    defect_request = DefectRequest.model_validate(body)
    defect_client = get_defect_client(request.app)
    return response.json(
        defect_client.create_defect(
            project=project,
            defect=defect_request.defect,
            sync_context=defect_request.syncContext,
        ).model_dump(mode="json")
    )


@router.route(
    "/projects/<project:str>/defects/<defect_id:str>/update", methods=["PUT"], unquote=True
)
@protected
async def put_projects_defects_update(request: Request, project: str, defect_id: str):
    body = _require_json(request)
    defect_request = DefectRequest.model_validate(body)
    defect_client = get_defect_client(request.app)
    return response.json(
        defect_client.update_defect(
            project=project,
            defect_id=defect_id,
            defect=defect_request.defect,
            sync_context=defect_request.syncContext,
        ).model_dump(mode="json")
    )


@router.route(
    "/projects/<project:str>/defects/<defect_id:str>/delete", methods=["POST"], unquote=True
)
@protected
async def post_projects_defects_delete(request: Request, project: str, defect_id: str):
    body = _require_json(request)
    defect_request = DefectRequest.model_validate(body)
    defect_client = get_defect_client(request.app)
    return response.json(
        defect_client.delete_defect(
            project=project,
            defect_id=defect_id,
            defect=defect_request.defect,
            sync_context=defect_request.syncContext,
        ).model_dump(mode="json")
    )


@router.route(
    "/projects/<project:str>/defects/<defectId:str>/extended", methods=["POST"], unquote=True
)
@protected
async def get_projects_defects_extended(request: Request, project: str, defectId: str):  # noqa: N803
    defect_client = get_defect_client(request.app)
    return response.json(
        defect_client.get_defect_extended(
            project=project,
            defect_id=defectId,
            sync_context=SyncContext.model_validate(request.json or {}),
        ).model_dump(mode="json")
    )


@router.route("/projects/udfs", methods=["GET"], unquote=True)
@protected
async def get_projects_udfs(request: Request):
    project = request.args.get("project")
    defect_client = get_defect_client(request.app)
    return response.json(
        [
            udf.model_dump(mode="json")
            for udf in defect_client.get_user_defined_attributes(project=project)
        ]
    )


@router.route("/projects/<project:str>/sync/before", methods=["POST"], unquote=True)
@protected
async def post_projects_sync_before(request: Request, project: str):
    body = _require_json(request)
    sync_request = SyncRequest.model_validate(body)
    defect_client = get_defect_client(request.app)
    return response.json(
        defect_client.before_sync(
            project=project,
            sync_type=sync_request.syncType,
            sync_context=sync_request.syncContext,
        ).model_dump(mode="json")
    )


@router.route("/projects/<project:str>/sync/after", methods=["POST"], unquote=True)
@protected
async def post_projects_sync_after(request: Request, project: str):
    body = _require_json(request)
    sync_request = SyncRequest.model_validate(body)
    defect_client = get_defect_client(request.app)
    return response.json(
        defect_client.after_sync(
            project=project,
            sync_type=sync_request.syncType,
            sync_context=sync_request.syncContext,
        ).model_dump(mode="json")
    )


@router.route("/supports-changes-timestamps", methods=["GET"], unquote=True)
@protected
async def get_supports_changes_timestamps(request: Request):
    defect_client = get_defect_client(request.app)
    return response.json(defect_client.supports_changes_timestamps())


@router.route("/projects/<project:str>/defects/correct", methods=["POST"])
@protected
async def post_defect_correct(request: Request, project: str):
    body = Results.model_validate(request.json or {})
    defect_client = get_defect_client(request.app)
    corrected = defect_client.correct_sync_results(project=project, body=body)
    return response.json(corrected.model_dump(mode="json"))
