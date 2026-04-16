from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import urllib3
from jira import JIRA, Issue, JIRAError
from jira.resources import Field, Project
from sanic import NotFound

from testbench_defect_service.clients.jira.config import JiraDefectClientConfig
from testbench_defect_service.clients.jira.defect_mapping_service import DefectToJiraMapper
from testbench_defect_service.clients.jira.utils import (
    ensure_issuetype_format,
    iso8601_to_unix_timestamp,
)
from testbench_defect_service.log import logger
from testbench_defect_service.models.defects import Defect, Login


class JiraClient:
    def __init__(self, config: JiraDefectClientConfig, principal: Login | None = None):
        self.config = config
        self._options: dict[str, Any] = {"verify": self.config.ssl_verify}
        if self.config.ssl_verify is False:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        if self.config.client_cert is not None:
            self._options["client_cert"] = self.config.client_cert
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
        logger.debug("Connecting with shared credentials (auth_type=%s)", self.config.auth_type)
        if self.config.auth_type == "basic":
            return JIRA(
                server=self.config.server_url,
                options=self._options,
                basic_auth=(self.config.username or "", self.config.password or ""),
                max_retries=self.config.max_retries,
                timeout=self.config.timeout,
            )
        if self.config.auth_type == "token":
            return JIRA(
                server=self.config.server_url,
                options=self._options,
                token_auth=self.config.token,
                max_retries=self.config.max_retries,
                timeout=self.config.timeout,
            )
        if self.config.auth_type == "oauth1":
            return JIRA(
                server=self.config.server_url,
                options=self._options,
                oauth={
                    "access_token": self.config.oauth1_access_token,
                    "access_token_secret": self.config.oauth1_access_token_secret,
                    "consumer_key": self.config.oauth1_consumer_key,
                    "key_cert": self.config.oauth1_key_cert,
                },
                max_retries=self.config.max_retries,
                timeout=self.config.timeout,
            )
        raise NotImplementedError(f"Unsupported auth_type {self.config.auth_type}")

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

    def fetch_all_custom_fields(self, project: str | None) -> list[dict[str, Any]]:  # noqa: C901, PLR0911, PLR0912
        if self.use_issuetypes_endpoint:
            if project:
                fields_dict = {}
                logger.debug("_fetch_project_issue_fields: Use issuetypes endpoint")
                issue_types = self.jira.project_issue_types(project, maxResults=100)
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
                            f"Error fetching issue fields for issue type {issue_type.id}: {e}"
                        )
                        return []
                return list(fields_dict.values())
            try:
                return self.jira.fields()
            except JIRAError as e:
                logger.debug(f"Error fetching custom fields: {e}")
                return []
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

            # Return only customfields
            custom_fields = [{"id": fid, **details} for fid, details in fields.items()]
            logger.info("Found %d custom fields for project '%s'", len(custom_fields), project)
            return custom_fields
        except JIRAError as e:
            logger.error("Error fetching custom fields for project '%s': %s", project, e)
            return []

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

    def create_issue(self, project_key: str, defect: Defect) -> Issue:
        try:
            mapper = DefectToJiraMapper(self.jira)
            if self.use_issuetypes_endpoint:
                project_fields = self.fetch_project_issue_fields(project_key=project_key)
                issue_fields = mapper.map_defect_to_jira_data_center_issue(defect, project_fields)
            else:
                issue_metadata = self.fetch_issues_fields(project=project_key)
                issue_fields = mapper.map_defect_to_jira_issue(
                    defect=defect, issue_metadata=issue_metadata
                )
            issue_fields = issue_fields.get("fields", issue_fields)
            issue_fields["project"] = project_key
            issue = self.jira.create_issue(issue_fields, True)
            logger.info("Created issue '%s' in project '%s'", issue.key, project_key)
            self.transition_issue_status(issue, defect)
            if defect.references:
                self.add_attachments(issue, defect.references)
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
        issue.delete()
        logger.info("Successfully deleted issue '%s'", issue_key)

    def update_issue(self, project_key: str, issue: Issue, defect: Defect) -> None:
        try:
            mapper = DefectToJiraMapper(self.jira)
            if self.use_issuetypes_endpoint:
                project_fields = self.fetch_project_issue_fields(project_key=project_key)
                update_fields = mapper.map_defect_to_jira_data_center_issue(defect, project_fields)[
                    "fields"
                ]
            else:
                issue_metadata = self.fetch_issues_fields(project=project_key)
                update_fields = mapper.map_defect_to_jira_issue(
                    defect, issue_metadata=issue_metadata
                )["fields"]
                ensure_issuetype_format(update_fields, issue_metadata)
            update_fields.pop("attachment", None)
            issue.update(fields=update_fields)
            logger.info("Updated issue '%s' in project '%s'", issue.key, project_key)
            self.transition_issue_status(issue, defect)
            if defect.references:
                self.add_attachments(issue, defect.references)
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

    def fetch_project_issue_fields(self, project_key: str) -> list[Field]:
        fields_dict: dict[str, Field] = {}

        try:
            if self.use_issuetypes_endpoint:
                logger.debug("_fetch_project_issue_fields: Use issuetypes endpoint")
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
