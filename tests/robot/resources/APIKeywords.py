import json  # noqa: N999
from base64 import b64encode
from typing import Any

import requests  # type: ignore
from assertionengine import AssertionOperator, verify_assertion
from robot.api import logger


class APIKeywords:
    ROBOT_LIBRARY_SCOPE = "TEST"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8000",
        username: str = "admin",
        password: str = "admin",
    ):
        self.base_url = base_url
        self.username = username
        self.password = password

    @property
    def headers(self):
        if not self.username and not self.password:
            return {}

        auth_credentials = f"{self.username}:{self.password}"
        base64_encoded_auth = b64encode(auth_credentials.encode()).decode("utf-8")
        return {"Authorization": f"Basic {base64_encoded_auth}"}

    def set_credentials(self, username: str | None = None, password: str | None = None):
        if username is not None:
            self.username = username
        if password is not None:
            self.password = password

    def get_check_login(
        self,
        project: str | None = None,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.get(
            f"{self.base_url}/check-login",
            params={"project": project},
            headers=self.headers,
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def get_settings(
        self,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.get(f"{self.base_url}/settings", headers=self.headers, timeout=10)
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def get_projects(
        self,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.get(f"{self.base_url}/projects", headers=self.headers, timeout=10)
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def get_project_control_fields(
        self,
        project: str,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.get(
            f"{self.base_url}/projects/control-fields",
            headers=self.headers,
            params={"project": project},
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def get_project_defects(
        self,
        project: str,
        body=None,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.post(
            f"{self.base_url}/projects/{project}/defects",
            headers=self.headers,
            data=body,
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def post_project_defect_batch(
        self,
        project: str,
        body=None,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.post(
            f"{self.base_url}/projects/{project}/defects/batch",
            data=body,
            headers=self.headers,
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def post_project_defect_create(
        self,
        project: str,
        body=None,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.post(
            f"{self.base_url}/projects/{project}/defects/create",
            data=body,
            headers=self.headers,
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def put_project_defect_update(
        self,
        project: str,
        defect_id: str,
        body=None,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.put(
            f"{self.base_url}/projects/{project}/defects/{defect_id}/update",
            data=body,
            headers=self.headers,
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def post_project_defect_delete(
        self,
        project: str,
        defect_id: str,
        body=None,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.post(
            f"{self.base_url}/projects/{project}/defects/{defect_id}/delete",
            data=body,
            headers=self.headers,
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def get_project_extended_defects(
        self,
        project: str,
        defect_id: str,
        body=None,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.post(
            f"{self.base_url}/projects/{project}/defects/{defect_id}/extended",
            headers=self.headers,
            data=body,
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def get_project_udfs(
        self,
        project: str,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.get(
            f"{self.base_url}/projects/udfs",
            headers=self.headers,
            params={"project": project},
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def post_project_sync_before(
        self,
        project: str,
        body=None,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.post(
            f"{self.base_url}/projects/{project}/sync/before",
            data=body,
            headers=self.headers,
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def post_project_sync_after(
        self,
        project: str,
        body=None,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.post(
            f"{self.base_url}/projects/{project}/sync/after",
            data=body,
            headers=self.headers,
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def get_supports_changes_timestamps(
        self,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.get(
            f"{self.base_url}/supports-changes-timestamps", headers=self.headers, timeout=10
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def post_correct_defects(
        self,
        project: str,
        body=None,
        assertion_operator: AssertionOperator | None = AssertionOperator.validate,
        assertion_expected: Any | None = "value.status_code == 200",
    ):
        response = requests.post(
            f"{self.base_url}/projects/{project}/defects/correct",
            data=body,
            headers=self.headers,
            timeout=10,
        )
        self._log_response(response)
        return verify_assertion(response, assertion_operator, assertion_expected, "Response")

    def _log_response(self, response):
        response_dict = {
            "url": response.url,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "encoding": response.encoding,
            "elapsed_time": response.elapsed.total_seconds(),
            "text": response.text,
            "json": response.json()
            if "application/json" in response.headers.get("Content-Type", "")
            else None,
        }
        logger.trace(json.dumps(response_dict, indent=2))
