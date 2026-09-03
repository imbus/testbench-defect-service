from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib.parse import urlparse

import requests
import urllib3
from jira import JIRA, Issue, JIRAError
from jira.resources import Field, Project
from sanic import NotFound

from testbench_defect_service.clients.jira.config import (
    AUTH_OAUTH2_2LO,
    JiraDefectClientConfig,
    is_oauth2,
)
from testbench_defect_service.clients.jira.defect_mapping_service import DefectToJiraMapper
from testbench_defect_service.clients.jira.jira_oauth import (
    BODY_FORMAT_FORM,
    GRANT_CLIENT_CREDENTIALS,
    GRANT_REFRESH_TOKEN,
    JiraAuthExpiredError,
    configure_oauth2_runtime,
    data_center_token_url,
    get_valid_jira_token_sync,
)
from testbench_defect_service.clients.jira.utils import (
    ensure_issuetype_format,
    iso8601_to_unix_timestamp,
)
from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import Defect, Login, SyncContext

_JIRA_GATEWAY_BASE = "https://api.atlassian.com/ex/jira/{cloud_id}"
_TENANT_INFO_PATH = "/_edge/tenant_info"

# Jira Server/Data Center answers ``issue/createmeta/{key}/issuetypes`` with one of these
# statuses both when the project key is unknown and when the authenticated account may not
# create issues in it.  The project key is always resolved from the configuration before we
# reach that call, so missing write access is by far the more likely cause.
_MISSING_WRITE_ACCESS_STATUSES = (
    HTTPStatus.BAD_REQUEST,
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
)


def jira_error_summary(error: JIRAError) -> str:
    """Return a compact one-line summary of a ``JIRAError`` without the header dump."""
    parts = [f"status={error.status_code}"]
    url = getattr(error, "url", None)
    if url:
        parts.append(f"url={url}")
    text = (getattr(error, "text", None) or "").strip()
    if text:
        parts.append(text.splitlines()[0])
    return " ".join(parts)


def _missing_write_access_hint(project: str | None) -> str:
    """Return a human-readable hint about missing write access on a Jira project."""
    return (
        f"The authenticated Jira account is most likely missing write access to project "
        f"'{project}' (the 'Create Issues' permission, which Jira requires to expose the "
        f"create metadata of a project). Grant that permission in the project's permission "
        f"scheme and verify that the project key is correct."
    )


class JiraConnectionError(ConnectionError):
    """Jira connection/authentication failure that preserves the HTTP status code.

    Subclasses the builtin ``ConnectionError`` (an ``OSError``) so existing
    ``except ConnectionError`` handlers keep working unchanged, but additionally
    carries the originating HTTP status code (e.g. 401, 403) so callers can map
    it to the correct response — 401 Unauthorized vs 403 Forbidden — instead of
    flattening every auth failure into a single generic error.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class JiraProjectFieldsError(JIRAError):
    """Raised when the field metadata of a Jira project cannot be read.

    Subclasses ``JIRAError`` so every existing ``except JIRAError`` handler — including the
    application-wide Sanic handler — keeps working unchanged, but renders as a single
    actionable sentence instead of the raw request/response dump that ``JIRAError.__str__``
    produces.  The originating error stays available as ``cause`` (and as ``__cause__``).
    """

    def __init__(self, message: str, cause: JIRAError) -> None:
        super().__init__(text=message, status_code=cause.status_code, url=cause.url)
        self.message = message
        self.cause = cause

    def __str__(self) -> str:
        return self.message


class JiraClient:
    def __init__(self, config: JiraDefectClientConfig, principal: Login | None = None):
        self.config = config
        if self.config.ssl_verify is False:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._proxies: dict[str, str] | None = None
        if self.config.proxy_url:
            self._proxies = {
                "http": self.config.proxy_url,
                "https": self.config.proxy_url,
            }
        self._options: dict[str, Any] = self._build_jira_options()
        self._uses_gateway: bool = False
        self._gateway_url: str | None = None
        if principal:
            self.jira = self._connect_user(principal)
        else:
            self.jira = self._connect()
        # The following flags determine which Jira API endpoints to use
        self.use_issuetypes_endpoint = (not self.jira._is_cloud) and (
            self.jira._version >= (8, 4, 0)
        )
        self.use_manual_pagination = not self.jira._is_cloud
        logger.info(
            "Connected to Jira %s (version %s, cloud=%s)",
            config.server_url,
            self.jira._version,
            self.jira._is_cloud,
        )

    @property
    def site_url(self) -> str:
        """Return the human-facing Jira site URL (always the configured server_url).

        This is the URL to use for building browser links, display URLs, and any
        URL embedded in responses shown to the user.  It is distinct from the
        internal gateway URL used when connecting via the Atlassian API gateway
        for scoped API tokens.
        """
        return self.config.server_url.rstrip("/")

    def _connect_user(self, principal: Login) -> JIRA:
        logger.debug(
            "Connecting with user-specific credentials (auth_type=%s)", self.config.auth_type
        )
        if self.config.auth_type == "basic":
            return JIRA(
                server=self.config.server_url,
                options=self._options,
                basic_auth=(principal.username, principal.password),
                max_retries=self.config.max_retries,
                timeout=self.config.timeout,
            )
        if self.config.auth_type == "token":
            return JIRA(
                server=self.config.server_url,
                options=self._options,
                token_auth=principal.password,
                max_retries=self.config.max_retries,
                timeout=self.config.timeout,
            )
        if self.config.auth_type == "oauth1":
            logger.warning(
                "OAuth1 does not support per-user authentication; "
                "falling back to shared credentials"
            )
            return self._connect()
        raise NotImplementedError(f"Unsupported auth_type {self.config.auth_type}")

    def _connect(self) -> JIRA:
        """Connect to Jira using the configured authentication.

        Connection strategy:
        1. Create a JIRA instance against ``config.server_url``.
        2. Verify authentication via ``/myself`` (for all auth types — the
           JIRA constructor alone is insufficient because ``serverInfo`` is public).
        3. If verification fails with HTTP 401 **and** the instance is Jira Cloud
           **and** ``auth_type`` is ``"basic"``, attempt a gateway connection via
           the Atlassian API gateway (``api.atlassian.com``).  This transparently
           supports scoped API tokens which only work through the gateway.
        4. If all attempts fail, raise ``ConnectionError`` with a clear message.

        Gateway fallback is deliberately restricted to Cloud + basic auth because:
        - ``token`` and ``oauth1`` are only used on Jira Data Center / Server,
          which has no gateway.
        - A 401 on DC basic auth means wrong credentials, not a scoped token.

        For OAuth2, a probe for the Atlassian Cloud ID decides the path up
        front: a cloud_id means Jira Cloud, connected via the gateway; no
        cloud_id means Jira Data Center, connected directly against
        ``config.server_url`` (see ``_connect_direct_oauth2``).
        """
        try:
            if is_oauth2(self.config.auth_type):
                cloud_id = self._fetch_cloud_id()
                if cloud_id:
                    return self._connect_via_gateway(cloud_id)
                logger.info(
                    "No Atlassian Cloud ID found for '%s' — treating the instance as "
                    "Jira Data Center and connecting directly (OAuth2).",
                    self.config.server_url,
                )
                return self._connect_direct_oauth2()

            jira = self._create_jira_instance(self.config.server_url)
        except NotImplementedError:
            raise
        except Exception as e:
            status_code = getattr(e, "status_code", None)
            detail = f"HTTP {status_code}: {e}" if status_code else f"{type(e).__name__}: {e}"
            raise JiraConnectionError(
                f"Could not connect to Jira at '{self.config.server_url}' "
                f"(auth_type='{self.config.auth_type}'): {detail}",
                status_code=status_code,
            ) from e

        try:
            auth_ok = self._verify_connection(jira)
        except JiraConnectionError:
            # Already carries an actionable message and status code (e.g. 403);
            # propagate as-is rather than re-wrapping it generically.
            raise
        except Exception as e:
            status_code = getattr(e, "status_code", None)
            detail = f"HTTP {status_code}: {e}" if status_code else f"{type(e).__name__}: {e}"
            raise JiraConnectionError(
                f"Could not connect to Jira at '{self.config.server_url}' "
                f"(auth_type='{self.config.auth_type}'): {detail}",
                status_code=status_code,
            ) from e

        if auth_ok:
            logger.debug(
                "Connected to Jira at '%s' (auth_type='%s').",
                self.config.server_url,
                self.config.auth_type,
            )
            return jira

        if self.config.auth_type == "basic" and jira._is_cloud:
            logger.info(
                "Direct authentication to '%s' failed (likely a scoped API token). "
                "Attempting connection via Atlassian API gateway.",
                self.config.server_url,
            )
            try:
                return self._connect_via_gateway()
            except ConnectionError as gateway_error:
                raise JiraConnectionError(
                    f"Could not connect to Jira at '{self.config.server_url}' "
                    f"(auth_type='{self.config.auth_type}'): "
                    "Direct authentication failed and gateway fallback also failed: "
                    f"{gateway_error}",
                    status_code=getattr(gateway_error, "status_code", None),
                ) from gateway_error

        raise JiraConnectionError(
            f"Could not connect to Jira at '{self.config.server_url}' "
            f"(auth_type='{self.config.auth_type}'): "
            "Authentication failed (HTTP 401). Please check your credentials.",
            status_code=HTTPStatus.UNAUTHORIZED,
        )

    def _create_jira_instance(self, server: str, token_override: str | None = None) -> JIRA:
        """Create a JIRA instance against *server* using the configured auth."""
        logger.debug(
            "Creating JIRA instance for '%s' (auth_type='%s')", server, self.config.auth_type
        )
        options = self._build_jira_options()
        if self.config.auth_type == "basic":
            return JIRA(
                server=server,
                options=options,
                basic_auth=(self.config.username or "", self.config.password or ""),
                max_retries=self.config.max_retries,
                timeout=self.config.timeout,
            )
        if self.config.auth_type == "token":
            return JIRA(
                server=server,
                options=options,
                token_auth=self.config.token,
                max_retries=self.config.max_retries,
                timeout=self.config.timeout,
            )
        if self.config.auth_type == "oauth1":
            return JIRA(
                server=server,
                options=options,
                oauth={
                    "access_token": self.config.oauth1_access_token,
                    "access_token_secret": self.config.oauth1_access_token_secret,
                    "consumer_key": self.config.oauth1_consumer_key,
                    "key_cert": self.config.oauth1_key_cert,
                },
                max_retries=self.config.max_retries,
                timeout=self.config.timeout,
            )
        if is_oauth2(self.config.auth_type):
            token = token_override or self.config.token
            return JIRA(
                server=server,
                options=options,
                token_auth=token,
                max_retries=self.config.max_retries,
                timeout=self.config.timeout,
            )
        raise NotImplementedError(f"Unsupported auth_type {self.config.auth_type}")

    def _build_jira_options(self) -> dict[str, Any]:
        """Build the JIRA client ``options`` dict shared by every connection path.

        Used both for the shared/service connection (via ``_create_jira_instance``)
        and for per-user connections (via ``self._options``), so a configured
        ``proxy_url`` applies uniformly to all Jira API traffic.
        """
        options: dict[str, Any] = {"verify": self.config.ssl_verify}
        if self.config.client_cert is not None:
            options["client_cert"] = self.config.client_cert
        if self._proxies is not None:
            options["proxies"] = self._proxies
        return options

    def _verify_connection(self, jira: JIRA) -> bool:
        """Verify that *jira* can authenticate successfully by calling ``/myself``.

        The ``/myself`` endpoint is available on both Jira Cloud and Server/DC
        and requires valid authentication on both.  It is used here because the
        JIRA constructor alone is insufficient — the ``serverInfo`` endpoint used
        during construction is public and returns HTTP 200 regardless of whether
        the credentials are valid.

        Returns ``True`` on success and ``False`` on HTTP 401 (invalid/expired
        credentials — a 401 on Cloud + basic auth also drives the scoped-token
        gateway fallback).  An HTTP 403 (authenticated but not permitted — e.g. a
        scoped API token missing the required user-read scope) is raised as a
        ``JiraConnectionError`` carrying the 403 status so the caller can surface
        a distinct 403 Forbidden response with actionable guidance.  Any other
        error is re-raised so the caller can surface it as a hard failure.
        """
        try:
            jira.myself()
            return True
        except JIRAError as e:
            if e.status_code == HTTPStatus.UNAUTHORIZED:
                logger.debug("Connection verification returned 401 for '%s'.", jira.server_url)
                return False
            if e.status_code == HTTPStatus.FORBIDDEN:
                logger.debug("Connection verification returned 403 for '%s'.", jira.server_url)
                raise JiraConnectionError(
                    f"Access denied by Jira at '{self.config.server_url}' (HTTP 403). "
                    "The credentials are valid but lack the required permissions/scopes "
                    "(e.g. a scoped API token missing the user-read scope). "
                    f"Details: {e}",
                    status_code=HTTPStatus.FORBIDDEN,
                ) from e
            raise

    def _connect_via_gateway(self, cloud_id: str | None = None) -> JIRA:
        """Connect to Jira Cloud through the Atlassian API gateway.

        Uses *cloud_id* when given (already fetched by the caller), otherwise
        fetches it. Creates a JIRA instance against the gateway URL.

        Raises ``ConnectionError`` when the Cloud ID cannot be fetched or the
        gateway connection fails.
        """
        cloud_id = cloud_id or self._fetch_cloud_id()
        if not cloud_id:
            raise ConnectionError(
                f"Could not obtain Atlassian Cloud ID for '{self.config.server_url}'. "
                "Unable to attempt gateway connection for scoped API token."
            )

        gateway_url = _JIRA_GATEWAY_BASE.format(cloud_id=cloud_id)
        logger.info(
            f"Connecting to Jira via Atlassian gateway (scoped API token mode): {gateway_url}"
        )

        if is_oauth2(self.config.auth_type):
            is_2lo = self.config.auth_type.startswith(AUTH_OAUTH2_2LO)
            configure_oauth2_runtime(
                grant_type=GRANT_CLIENT_CREDENTIALS if is_2lo else GRANT_REFRESH_TOKEN,
                refresh_token=None if is_2lo else self.config.oauth2_refresh_token,
                client_id=self.config.oauth2_client_id,
                client_secret=self.config.oauth2_client_secret,
                expires_at=None if is_2lo else self.config.oauth2_expires_at,
            )
            try:
                initial_oauth2_token = get_valid_jira_token_sync(is_first_call=True)
            except JiraAuthExpiredError as exc:
                raise ConnectionError(
                    "Jira OAuth2 authorization expired while establishing the initial connection. "
                    "Please re-run the setup wizard to authorize Jira OAuth2."
                ) from exc
        else:
            initial_oauth2_token = None

        jira = self._create_jira_instance(gateway_url, token_override=initial_oauth2_token)
        if is_oauth2(self.config.auth_type):
            self._patch_session_for_oauth2_token(jira._session)

        if not self._verify_connection(jira):
            raise JiraConnectionError(
                f"Authentication failed against the Atlassian gateway '{gateway_url}'. "
                f"Please verify your credentials for '{self.config.server_url}'.",
                status_code=HTTPStatus.UNAUTHORIZED,
            )

        self._uses_gateway = True
        self._gateway_url = gateway_url
        self._patch_session_for_gateway(jira._session, gateway_url)

        return jira

    def _connect_direct_oauth2(self) -> JIRA:
        """Connect to Jira Data Center directly with OAuth2 (3LO or 2LO).

        Jira DC has no Atlassian gateway: tokens come from
        ``{server_url}/rest/oauth2/1.0/token`` (form-encoded bodies) and API
        requests go straight to the configured server URL.  3LO exchanges the
        stored refresh token; 2LO mints tokens via the client_credentials
        grant, which requires the DC instance to support that grant (vanilla
        Jira DC only offers authorization-code flows).
        """
        is_2lo = self.config.auth_type.startswith(AUTH_OAUTH2_2LO)
        token_url = data_center_token_url(self.config.server_url)
        configure_oauth2_runtime(
            grant_type=GRANT_CLIENT_CREDENTIALS if is_2lo else GRANT_REFRESH_TOKEN,
            refresh_token=None if is_2lo else self.config.oauth2_refresh_token,
            client_id=self.config.oauth2_client_id,
            client_secret=self.config.oauth2_client_secret,
            expires_at=None if is_2lo else self.config.oauth2_expires_at,
            token_url=token_url,
            body_format=BODY_FORMAT_FORM,
        )
        try:
            initial_oauth2_token = get_valid_jira_token_sync(is_first_call=True)
        except JiraAuthExpiredError as exc:
            if is_2lo:
                raise ConnectionError(
                    "Jira OAuth2 client_credentials token request failed while establishing "
                    f"the initial connection to '{self.config.server_url}' (treated as Jira "
                    "Data Center). Verify the OAuth2 client id/secret and that the instance "
                    "supports the client_credentials grant — or, if this is a Jira Cloud "
                    f"site, ensure '{self.config.server_url}{_TENANT_INFO_PATH}' is "
                    "reachable so the service can detect Cloud."
                ) from exc
            raise ConnectionError(
                "Jira OAuth2 authorization failed while establishing the initial connection "
                f"to '{self.config.server_url}' (treated as Jira Data Center). Re-run the "
                "setup wizard to authorize Jira OAuth2 — or, if this is a Jira Cloud site, "
                f"ensure '{self.config.server_url}{_TENANT_INFO_PATH}' is reachable so the "
                "service can detect Cloud."
            ) from exc
        except urllib_error.HTTPError as exc:
            if exc.code == HTTPStatus.NOT_FOUND:
                raise ConnectionError(
                    f"Jira OAuth2 token endpoint not found at '{token_url}' (HTTP 404). "
                    "Ensure an incoming OAuth 2.0 application link is configured in Jira "
                    "Data Center — or, if this is a Jira Cloud site, that "
                    f"'{self.config.server_url}{_TENANT_INFO_PATH}' is reachable."
                ) from exc
            raise

        jira = self._create_jira_instance(
            self.config.server_url, token_override=initial_oauth2_token
        )
        self._patch_session_for_oauth2_token(jira._session)

        if not self._verify_connection(jira):
            remedy = (
                "Verify the OAuth2 client id/secret."
                if is_2lo
                else "Please re-run the setup wizard to authorize Jira OAuth2."
            )
            raise JiraConnectionError(
                f"OAuth2 authentication failed against Jira Data Center at "
                f"'{self.config.server_url}'. {remedy}",
                status_code=HTTPStatus.UNAUTHORIZED,
            )
        return jira

    def _patch_session_for_gateway(self, session: Any, gateway_url: str) -> None:
        """Rewrite site-URL requests to the Atlassian gateway at transport level.

        Scoped API tokens are only accepted by the gateway, not by the direct
        Jira Cloud site URL.  Attaching `content` and inline-image URLs are
        always absolute site URLs embedded in API responses.  Patching ``send``
        here means every request that goes through this session — regardless of
        who constructed the URL — is transparently routed to the gateway without
        any caller needing to know about the gateway.
        """
        site_base = self.site_url.rstrip("/")
        gateway_base = gateway_url.rstrip("/")
        original_send = session.send

        def _rewriting_send(request: Any, **kwargs: Any) -> Any:
            if request.url and request.url.startswith(site_base + "/"):
                request.url = gateway_base + request.url[len(site_base) :]
            return original_send(request, **kwargs)

        session.send = _rewriting_send

    def _patch_session_for_oauth2_token(self, session: Any) -> None:
        """Inject a valid OAuth2 bearer token into every Jira HTTP request."""
        original_send = session.send

        def _oauth2_send(request: Any, **kwargs: Any) -> Any:
            try:
                token = get_valid_jira_token_sync()
            except JiraAuthExpiredError as exc:
                raise ConnectionError(
                    "Jira OAuth2 authorization expired. "
                    "Please re-run the setup wizard to authorize Jira OAuth2."
                ) from exc

            if token:
                request.headers["Authorization"] = f"Bearer {token}"
            return original_send(request, **kwargs)

        session.send = _oauth2_send

    def _fetch_cloud_id(self) -> str | None:
        """Fetch the Atlassian Cloud ID for this Jira instance.

        Uses the public ``/_edge/tenant_info`` endpoint which requires no
        authentication and is available on all Jira Cloud sites (including
        those using custom domains).

        Returns the cloud ID string, or ``None`` when the request fails or
        the response does not contain the expected field.
        """
        server_url = self.config.server_url.rstrip("/")
        tenant_info_url = f"{server_url}{_TENANT_INFO_PATH}"
        try:
            response = requests.get(
                tenant_info_url,
                timeout=self.config.timeout,
                verify=self.config.ssl_verify,
                proxies=self._proxies,
            )
            response.raise_for_status()
            data = response.json()
            cloud_id: str | None = data.get("cloudId")
            if not cloud_id:
                logger.warning(
                    f"Tenant info response from '{tenant_info_url}' did not contain 'cloudId'. "
                    f"Response keys: {list(data.keys())}"
                )
                return None
            logger.debug(f"Fetched Atlassian Cloud ID: {cloud_id}")
            return cloud_id
        except requests.RequestException as e:
            logger.warning(f"Could not fetch Atlassian Cloud ID from '{tenant_info_url}': {e}")
            return None
        except (ValueError, KeyError) as e:
            logger.warning(
                f"Unexpected response from '{tenant_info_url}' while fetching Cloud ID: {e}"
            )
            return None

    def fetch_projects(self) -> list[Project]:
        try:
            projects = self.jira.projects()
            logger.info("Fetched %d projects from Jira", len(projects))
            return projects
        except JIRAError as e:
            logger.error("Error fetching projects: %s", e)
            return []

    def fetch_project_statuses(self, project_key: str) -> list[str]:
        """Fetch statuses available for a specific project via the project-specific endpoint.

        Uses ``GET /rest/api/2/project/{projectKey}/statuses`` which returns
        statuses grouped by issue type.  The method collects all unique status
        names across every issue type in the project.

        Args:
            project_key: The Jira project key (e.g. ``"TEST"``).

        Returns:
            A sorted list of unique status names for the given project.
        """
        try:
            issue_types = self.jira._get_json(f"project/{project_key}/statuses")
            status_names: set[str] = set()
            for issue_type in issue_types:
                for status in issue_type.get("statuses", []):
                    name = status.get("name")
                    if name:
                        status_names.add(name)
            logger.info(
                "Fetched %d unique statuses for project '%s'",
                len(status_names),
                project_key,
            )
            return sorted(status_names)
        except Exception as e:
            logger.error("Error fetching project statuses for '%s': %s", project_key, e)
            return []

    @staticmethod
    def _log_issue_types_failure(project: str, error: JIRAError) -> None:
        """Log a rejected ``project_issue_types`` call before the createmeta fallback."""
        if error.status_code in _MISSING_WRITE_ACCESS_STATUSES:
            logger.warning(
                "project_issue_types failed for project '%s' (status=%s). %s "
                "Falling back to createmeta endpoint.",
                project,
                error.status_code,
                _missing_write_access_hint(project),
            )
        else:
            logger.warning(
                "project_issue_types failed for project '%s' (status=%s). "
                "Falling back to createmeta endpoint: %s",
                project,
                error.status_code,
                jira_error_summary(error),
            )
        logger.debug("project_issue_types error for project '%s': %s", project, error)

    @staticmethod
    def _log_project_fields_failure(
        project: str | None,
        issue_types_error: JIRAError | None,
        createmeta_error: JIRAError,
    ) -> str:
        """Log why no field metadata could be read for ``project`` and return that reason.

        When the issuetypes endpoint was rejected first, that rejection is the actual root
        cause — the createmeta fallback merely reports that this Jira version does not offer
        the endpoint any more — so the message names the likely missing project permission
        instead of the raw fallback error.
        """
        if issue_types_error is None:
            message = (
                f"Cannot read the field metadata of project '{project}': "
                f"{jira_error_summary(createmeta_error)}"
            )
            logger.error("%s", message)
            logger.debug("createmeta error for project '%s': %s", project, createmeta_error)
            return message

        if issue_types_error.status_code in _MISSING_WRITE_ACCESS_STATUSES:
            # The hint already names the project, so it stands on its own as the message.
            message = _missing_write_access_hint(project)
        else:
            message = (
                f"Cannot read the field metadata of project '{project}'. "
                f"project_issue_types failed with status {issue_types_error.status_code}."
            )
        logger.error(
            "%s (project_issue_types: %s | createmeta fallback: %s)",
            message,
            jira_error_summary(issue_types_error),
            jira_error_summary(createmeta_error),
        )
        logger.debug(
            "Field metadata errors for project '%s': %s / %s",
            project,
            issue_types_error,
            createmeta_error,
        )
        return message

    def get_all_project_fields(self, project: str | None) -> list[dict[str, Any]]:  # noqa: C901, PLR0912
        """Return the field metadata of ``project`` (all fields when ``project`` is empty).

        Raises:
            JiraProjectFieldsError: if the field metadata cannot be read at all — most
                commonly because
                the account lacks the project permissions Jira requires to expose the create
                metadata.  An empty list means "Jira reported no fields", which is a very
                different situation for the caller, so the two are no longer conflated.
        """
        issue_types_error: JIRAError | None = None
        if self.use_issuetypes_endpoint:
            if project:
                fields_dict = {}
                logger.debug("_fetch_project_issue_fields: Use issuetypes endpoint")
                try:
                    issue_types = self.jira.project_issue_types(project, maxResults=100)
                except JIRAError as e:
                    issue_types_error = e
                    self._log_issue_types_failure(project, e)
                else:
                    for issue_type in issue_types:
                        try:
                            fields_list = self.jira.project_issue_fields(
                                project, issue_type=issue_type.id, maxResults=100
                            )

                            for field in fields_list:
                                field_raw = field.raw
                                field_raw["id"] = field_raw.get("fieldId", "")
                                if "name" not in field_raw:
                                    field_raw["name"] = getattr(field, "name", field_raw["id"])
                                fields_dict[field_raw.get("name")] = field_raw

                        except Exception as e:
                            logger.warning(
                                "Error fetching issue fields for issue type %s in project '%s': %s",
                                issue_type.id,
                                project,
                                e,
                            )

                    if fields_dict:
                        fields_dict["status"] = {
                            "required": True,
                            "name": "Status",
                            "fieldId": "status",
                            "id": "status",
                        }
                        return list(fields_dict.values())

                    logger.warning(
                        "No issue fields returned via issuetypes endpoint for project '%s'; "
                        "falling back to createmeta endpoint",
                        project,
                    )
            if not project:
                try:
                    return self.jira.fields()
                except JIRAError as e:
                    logger.error("Error fetching custom fields: %s", jira_error_summary(e))
                    logger.debug("Error fetching custom fields: %s", e)
                    raise
        try:
            # Get creation metadata for the project
            meta = self.jira.createmeta(projectKeys=project, expand="projects.issuetypes.fields")

            projects = meta.get("projects", [])
            if not projects:
                logger.warning("No projects found in metadata for project '%s'", project)
                return []

            issue_types = projects[0].get("issuetypes", [])
            logger.debug("Processing %d issue types for project '%s'", len(issue_types), project)

            fields = {}
            # gets all the fields from all issueTypes
            for it in issue_types:
                for fid, details in it.get("fields", {}).items():
                    # If field already exists, prioritize the version with required=true
                    if fid in fields:
                        if details.get("required") is True:
                            fields[fid] = details
                    else:
                        fields[fid] = details
            fields["status"] = {
                "required": True,
                "name": "Status",
                "key": "status",
                "hasDefaultValue": False,
            }
            custom_fields = [{"id": fid, **details} for fid, details in fields.items()]
            logger.info("Found %d custom fields for project '%s'", len(custom_fields), project)
            return custom_fields
        except JIRAError as e:
            message = self._log_project_fields_failure(project, issue_types_error, e)
            raise JiraProjectFieldsError(message, issue_types_error or e) from e

    def fetch_issues_fields(self, project: str | None = None) -> dict[str, Any]:
        if self.use_issuetypes_endpoint:
            return {}
        try:
            # Get creation metadata for the project
            if project:
                return self.jira.createmeta(
                    projectKeys=project, expand="projects.issuetypes.fields"
                )
            return self.jira.createmeta(expand="projects.issuetypes.fields")

        except JIRAError as e:
            logger.debug("Error fetching custom fields: %s", e)
            return {}

    def fetch_issues_by_jql(
        self,
        jql_query: str,
        fields: str | None = "*all",
        expand: str | None = None,
        properties: str | None = None,
        max_results: int = 100,
    ) -> list[Issue]:
        try:
            issues: list[Issue] = []
            page_count = 0
            if self.use_manual_pagination:
                start_at = 0
                while True:
                    issues_chunk = self.jira.search_issues(
                        jql_query,
                        startAt=start_at,
                        maxResults=max_results,
                        fields=fields,
                        expand=expand,
                        properties=properties,
                    )
                    page_count += 1
                    issues.extend(list(issues_chunk))
                    if len(issues_chunk) < max_results:
                        # No more pages
                        break
                    start_at += max_results
            else:
                next_page_token = None
                while True:
                    issues_chunk = self.jira.enhanced_search_issues(
                        jql_str=jql_query,
                        nextPageToken=next_page_token,
                        maxResults=max_results,
                        fields=fields,
                        expand=expand,
                        properties=properties,
                    )
                    if issues_chunk:
                        page_count += 1
                        issues.extend(list(issues_chunk))
                    if not issues_chunk or not issues_chunk.nextPageToken:
                        break
                    next_page_token = issues_chunk.nextPageToken
            logger.info("Fetched %d issues in %d page(s) using JQL query", len(issues), page_count)
            return issues
        except JIRAError as e:
            logger.error("Error fetching issues with JQL '%s': %s", jql_query, e)
            return []

    def fetch_issue(
        self,
        issue_id: str,
        fields: str | None = None,
        expand: str | None = None,
        properties: str | None = None,
    ) -> Issue | None:
        try:
            issue = self.jira.issue(issue_id, fields=fields, expand=expand, properties=properties)
            logger.debug("Successfully fetched issue '%s'", issue_id)
            return issue
        except JIRAError as e:
            logger.warning("Error fetching issue '%s': %s", issue_id, e)
            return None

    def create_issue(self, project_key: str, defect: Defect, sync_context: SyncContext) -> Issue:
        try:
            mapper = DefectToJiraMapper(self.jira)
            if self.use_issuetypes_endpoint:
                project_fields = self.fetch_project_issue_fields(project_key=project_key)
                issue_fields = mapper.map_defect_to_jira_data_center_issue(
                    defect, project_fields, sync_context=sync_context
                )
            else:
                issue_metadata = self.fetch_issues_fields(project=project_key)
                issue_fields = mapper.map_defect_to_jira_issue(
                    defect=defect, issue_metadata=issue_metadata, sync_context=sync_context
                )
            issue_fields = issue_fields.get("fields", issue_fields)
            issue_fields["project"] = project_key
            issue = self.jira.create_issue(issue_fields, True)
            logger.info("Created issue '%s' in project '%s'", issue.key, project_key)
            self.transition_issue_status(issue, defect)
            # if defect.references:
            #     self.add_attachments(issue, defect.references)
            return issue
        except JIRAError as exc:
            logger.error("Failed to create issue in project %s: %s", project_key, exc)
            raise ValueError(f"Unable to create Jira issue: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error creating issue in project %s: %s", project_key, exc)
            raise ValueError(f"Failed to create Jira issue due to unexpected error: {exc}") from exc

    def delete_issue(self, issue: Issue) -> None:
        issue_key = issue.key
        logger.info("Deleting issue '%s'", issue_key)
        try:
            issue.delete()
        except JIRAError as exc:
            logger.error("Failed to delete issue '%s': %s", issue_key, exc)
            raise ValueError(f"Unable to delete Jira issue: {exc}") from exc
        logger.info("Successfully deleted issue '%s'", issue_key)

    def update_issue(
        self, project_key: str, issue: Issue, defect: Defect, sync_context: SyncContext
    ) -> None:
        try:
            mapper = DefectToJiraMapper(self.jira)
            if self.use_issuetypes_endpoint:
                project_fields = self.fetch_project_issue_fields(project_key=project_key)
                update_fields = mapper.map_defect_to_jira_data_center_issue(
                    defect, project_fields, sync_context=sync_context
                )["fields"]
            else:
                issue_metadata = self.fetch_issues_fields(project=project_key)
                update_fields = mapper.map_defect_to_jira_issue(
                    defect, issue_metadata=issue_metadata, sync_context=sync_context
                )["fields"]
                ensure_issuetype_format(update_fields, issue_metadata)
            update_fields.pop("attachment", None)
            issue.update(fields=update_fields)
            logger.info("Updated issue '%s' in project '%s'", issue.key, project_key)
            self.transition_issue_status(issue, defect)
            # if defect.references:
            #     self.add_attachments(issue, defect.references)
        except JIRAError as exc:
            logger.error("Failed to update issue in project %s: %s", project_key, exc)
            raise ValueError(f"Unable to update Jira issue: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error update issue in project %s: %s", project_key, exc)
            raise ValueError(f"Failed to update Jira issue due to unexpected error: {exc}") from exc

    def transition_issue_status(self, issue: Issue, defect: Defect) -> None:
        if issue.fields.status.name == defect.status:
            logger.debug(
                "Issue '%s' already at target status '%s', skipping transition",
                issue.key,
                defect.status,
            )
            return
        try:
            transition_id = None
            transitions = self.jira.transitions(issue)
            for transition in transitions:
                if transition["to"]["name"] == defect.status:
                    transition_id = transition["id"]
            if transition_id is not None:
                self.jira.transition_issue(issue, transition_id)
                logger.info(
                    "Transitioned issue '%s' from '%s' to '%s'",
                    issue.key,
                    issue.fields.status.name,
                    defect.status,
                )
            else:
                logger.warning(
                    "Transition not possible: no valid transition found to move issue %s "
                    "to status '%s'. Available transitions: %s",
                    issue.key,
                    defect.status,
                    ", ".join(t["to"]["name"] for t in transitions),
                )
        except ValueError:
            logger.warning(
                "Transition not possible: unable to move issue %s from currentstate to '%s'",
                issue.key,
                defect.status,
            )

    def add_attachments(self, issue: Issue, attachment_list: list[str]) -> None:
        """
        Synchronize attachments between local files and a Jira issue.

        This method orchestrates the complete attachment sync process:
        1. Map local files/URLs to identify new and existing attachments
        2. Sync with Jira by comparing timestamps and removing obsolete attachments
        3. Upload new files that don't exist in Jira

        Args:
            issue: Jira Issue object to attach files to
            attachment_list: List of file paths and/or URLs to sync

        Known Limitations:
            - URLs are preserved as references but never downloaded/uploaded
            - Timestamp comparison only works for local files
            - Uses filename for matching; may conflict with duplicate filenames
        """
        logger.debug("Processing %d attachment(s) for issue '%s'", len(attachment_list), issue.key)
        local_files_map = self.map_attachments(attachment_list)
        initial_count = len(local_files_map)
        # Step 2: Sync with Jira - compare existing attachments, update if newer, delete obsolete
        self.sync_attachments_with_jira(issue, local_files_map)
        # Step 3: Upload new items that remain after sync (not yet in Jira)
        new_uploads = len(local_files_map)
        self.upload_attachments(issue, local_files_map)
        if initial_count > 0 or new_uploads > 0:
            logger.info(
                "Attachment sync complete for issue '%s': %d processed, %d new uploads",
                issue.key,
                initial_count,
                new_uploads,
            )

    def upload_attachments(self, issue: Issue, local_files_map: dict) -> None:
        """
        Upload new attachment files to Jira.

        At this stage, local_files_map contains only files that are new to Jira
        (those not matched during sync_attachments_with_jira).

        Args:
            issue: Jira Issue object to attach files to
            local_files_map: Dict with filename as key and (path_or_url, timestamp) as value.
                            Only Path objects (local files) are uploaded; URLs are ignored.
        """
        for key, (ref_item, _) in local_files_map.items():
            if isinstance(ref_item, Path):
                logger.debug("Uploading new file: %s", key)
                with ref_item.open("rb") as file:
                    self.jira.add_attachment(issue, file)

    def sync_attachments_with_jira(self, issue: Issue, local_files_map: dict) -> None:
        """
        Synchronize local attachment map with existing Jira attachments.

        For each attachment in Jira:
        - If found in local_files_map and is a local file with newer timestamp: delete and re-upload
        - If found in local_files_map but is a URL: keep as-is, remove from map
        - If NOT found in local_files_map: delete as obsolete

        After this step, local_files_map contains only NEW files not yet in Jira.

        Args:
            issue: Jira Issue object
            local_files_map: Dict with filename as key and (path, timestamp) as value.
                            Modified in-place: matched entries are removed.
        """
        if not self.use_issuetypes_endpoint:
            for attachment in issue.fields.attachment:
                filename = attachment.filename

                # If this existing Jira attachment matches a local file
                if filename in local_files_map:
                    ref_path, last_modified_time = local_files_map[filename]

                    # We only perform timestamp comparison for local files
                    if isinstance(ref_path, Path):
                        jira_timestamp = iso8601_to_unix_timestamp(attachment.created)
                        if last_modified_time > jira_timestamp:
                            logger.debug("Updating newer file: %s", filename)
                            self.jira.delete_attachment(attachment.id)
                            with ref_path.open("rb") as file:
                                self.jira.add_attachment(issue, file)

                    del local_files_map[filename]

    def map_attachments(self, attachment_list: list[str]) -> dict:
        """
        Parse and validate attachment list, creating a map of attachments.

        Process:
        1. For each item in attachment_list, determine if it's a URL or file path
        2. URLs (with scheme and netloc) are skipped (not uploaded as attachments)
        3. Local files are validated for existence and stat information collected
        4. Create a map with filename/URL as key and (path_or_url, timestamp) as value

        Args:
            attachment_list: List of file paths and/or URLs (e.g.,
                           ["/local/file.txt", "https://example.com/resource.pdf"])

        Returns:
            dict: Map with format {filename_or_url: (Path_or_str, timestamp)}

        Notes:
            - URLs are completely skipped and not included in the returned map
            - Non-existent files generate warnings and are excluded from the map
            - Filenames are used as keys; duplicate filenames will overwrite
        """
        attachment_info = []
        url_count = 0
        not_found_count = 0
        for attachment in attachment_list:
            # 1. Check if the string is a URL
            parsed = urlparse(str(attachment))
            is_url = bool(parsed.scheme and parsed.netloc)

            # Skip URLs as they are references to external resources and should not be uploaded
            if is_url:
                url_count += 1
                logger.debug("Skipping URL reference: %s", attachment)
                continue

            attachment_path = Path(attachment)
            if not attachment_path.exists():
                not_found_count += 1
                logger.warning("Attachment file not found: %s", attachment_path.resolve())
                continue

            last_modified_time = attachment_path.stat().st_mtime
            attachment_info.append((attachment_path, last_modified_time))

        # Build map: Key is filename (or URL), value is (path_or_url, timestamp)
        local_files_map = {}
        for item, time in attachment_info:
            if isinstance(item, Path):
                local_files_map[item.name] = (item, time)

        logger.debug(
            "Attachment mapping complete: %d valid files, %d URLs skipped, %d not found",
            len(local_files_map),
            url_count,
            not_found_count,
        )
        return local_files_map

    def get_user_id(self, user: str) -> str:
        if self.use_issuetypes_endpoint:
            try:
                users = self.jira.search_users(user=user)
                if not users:
                    logger.warning("No user found for query: %s", user)
                    raise ValueError(f"User '{user}' not found in Jira")
                found_user = users[0]
                user_name = str(getattr(found_user, "name", None) or found_user.key)
                if len(users) > 1:
                    logger.debug(
                        "Multiple users found for query '%s', using first match: %s",
                        user,
                        user_name,
                    )
                else:
                    logger.debug("Resolved user '%s' to name: %s", user, user_name)
                return user_name
            except JIRAError as e:
                logger.error("Error searching for user '%s': %s", user, e)
                raise
            except (IndexError, AttributeError) as e:
                logger.warning("Unable to retrieve name for user '%s': %s", user, e)
                raise ValueError(f"User '{user}' not found or invalid") from e
        try:
            users = self.jira.search_users(query=user)
            if not users:
                logger.warning("No user found for query: %s", user)
                raise ValueError(f"User '{user}' not found in Jira")
            account_id = str(users[0].accountId)
            if len(users) > 1:
                logger.debug(
                    "Multiple users found for query '%s', using first match: %s",
                    user,
                    account_id,
                )
            else:
                logger.debug("Resolved user '%s' to account ID: %s", user, account_id)
            return account_id
        except JIRAError as e:
            logger.error("Error searching for user '%s': %s", user, e)
            raise
        except (IndexError, AttributeError) as e:
            logger.warning("Unable to retrieve accountId for user '%s': %s", user, e)
            raise ValueError(f"User '{user}' not found or invalid") from e

    def fetch_project_issue_fields(self, project_key: str) -> list[Field]:  # noqa: C901
        fields_dict: dict[str, Field] = {}

        try:
            if self.use_issuetypes_endpoint:
                logger.debug("_fetch_project_issue_fields: Use issuetypes endpoint")
                try:
                    issue_types = self.jira.project_issue_types(project_key, maxResults=100)
                    for issue_type in issue_types:
                        try:
                            fields_list = self.jira.project_issue_fields(
                                project_key, issue_type=issue_type.id, maxResults=100
                            )
                            for field in fields_list:
                                fields_dict[field.fieldId] = field
                        except Exception as e:
                            logger.warning(
                                f"Error fetching issue fields for issue type {issue_type.id}: {e}"
                            )
                except JIRAError as e:
                    # Fallback to createmeta endpoint if issuetypes endpoint fails (e.g., 400 error)
                    self._log_issue_types_failure(project_key, e)
                    try:
                        createmeta = self.jira.createmeta(
                            project_key, expand="projects.issuetypes.fields"
                        )
                    except JIRAError as fallback_error:
                        message = self._log_project_fields_failure(project_key, e, fallback_error)
                        raise JiraProjectFieldsError(message, e) from fallback_error
                    issue_types = createmeta["projects"][0]["issuetypes"]
                    for issue_type in issue_types:
                        for field_id, field_data in issue_type["fields"].items():
                            fields_dict[field_id] = Field(
                                options=self.jira._options,
                                session=self.jira._session,
                                raw=field_data,
                            )
            else:
                logger.debug("_fetch_project_issue_fields: Use createmeta endpoint")
                createmeta = self.jira.createmeta(project_key, expand="projects.issuetypes.fields")
                issue_types = createmeta["projects"][0]["issuetypes"]
                for issue_type in issue_types:
                    for field_id, field_data in issue_type["fields"].items():
                        fields_dict[field_id] = Field(
                            options=self.jira._options, session=self.jira._session, raw=field_data
                        )
        except Exception as e:
            logger.debug(f"Error fetching issue fields for project {project_key}: {e}")
            raise

        return list(fields_dict.values())

    def fetch_issue_fields(self, project_key: str, issue: Issue) -> dict[str, Any]:
        if self.use_issuetypes_endpoint:
            try:
                issue_fields = self.fetch_project_issue_fields(project_key)
            except KeyError as exc:
                logger.error(
                    "Unknown project '%s' requested while fetching custom fields", project_key
                )
                raise NotFound(f"Project '{project_key}' is not configured: {exc}") from exc
            fields = {}
            for field in issue_fields:
                fields.update({field.fieldId: field.raw})
            return fields

        try:
            meta = self.fetch_issues_fields(project=project_key)

        except KeyError as exc:
            logger.error("Unknown project '%s' requested while fetching custom fields", project_key)
            raise NotFound(f"Project '{project_key}' is not configured: {exc}") from exc

        projects = meta.get("projects", [])
        if not projects:
            logger.error("No projects found in metadata for project '%s'", project_key)
            raise NotFound(f"No projects found in metadata for project '{project_key}'")
        issue_types = projects[0].get("issuetypes", [])

        fields = {}
        for it in issue_types:
            if it.get("name", "") == str(issue.fields.issuetype):
                fields = it.get("fields", {})
                break
        return fields
