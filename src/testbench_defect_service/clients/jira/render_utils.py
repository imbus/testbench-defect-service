import base64
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from jira.resilientsession import ResilientSession
from jira.resources import Issue

from testbench_defect_service.log import logger

MAX_EMBEDDED_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB limit for embedded images
JIRA_ATTACHMENT_URL_PATTERN = re.compile(r"^/rest/api/\d+/attachment/content/(\d+)$")
DEFAULT_INLINE_STYLES_PATH = Path(__file__).parents[2] / "static" / "rendered_fields.css"


def load_inline_styles(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.debug(f"Inline style file not found at {path}; continuing without styles")
        return ""
    except OSError as exc:  # pragma: no cover - edge case
        logger.warning(f"Failed to read inline styles from {path}: {exc}")
        return ""


@lru_cache(maxsize=1)
def _get_inline_styles() -> str:
    """Return cached inline styles, loading from disk only on the first call."""
    return load_inline_styles(DEFAULT_INLINE_STYLES_PATH)


def build_rendered_field_html(
    issue: Issue,
    field_id: str,
    jira_server_url: str,
    *,
    include_head: bool = True,
) -> str:
    """Build HTML for a Jira rendered field."""
    rendered_html = getattr(issue.renderedFields, field_id, "")
    if not rendered_html:
        return wrap_in_html("", include_head=include_head)

    enriched_body = enrich_rendered_html(
        rendered_html,
        issue=issue,
        jira_server_url=jira_server_url,
    )
    return wrap_in_html(enriched_body, include_head=include_head)


def wrap_in_html(body: str, include_head: bool = True) -> str:
    if include_head:
        styles = _get_inline_styles()
        style_tag = f"<style>{styles}</style>" if styles else ""
        head = f"<head>{style_tag}</head>"
    else:
        head = ""
    return f"<html>{head}<body>{body}</body></html>"


def enrich_rendered_html(
    rendered_html: str,
    issue: Issue,
    jira_server_url: str,
) -> str:
    """Normalize Jira rendered HTML for downstream consumers."""
    if not rendered_html:
        return ""
    soup = BeautifulSoup(rendered_html, "html.parser")
    process_task_items(soup)
    process_ins_tags(soup)
    process_del_tags(soup)
    process_image_tags(soup, issue, jira_server_url)
    process_anchor_tags(soup, jira_server_url)
    return str(soup)


def process_task_items(soup: BeautifulSoup):
    """Normalize wiki task markup (-content-) in <li> to strikethrough spans."""
    for li in soup.find_all("li"):
        text_parts = [str(c).strip() for c in li.contents if isinstance(c, str)]
        full_text = "".join(text_parts).strip()

        if full_text.startswith("-") and full_text.endswith("-"):
            # Strip leading/trailing text nodes with markers
            for content in li.contents[:]:
                if isinstance(content, str):
                    cleaned = str(content)
                    if cleaned.lstrip().startswith("-"):
                        cleaned = cleaned.lstrip()[1:]
                    if cleaned.rstrip().endswith("-"):
                        cleaned = cleaned.rstrip()[:-1]
                    content.replace_with(cleaned)  # type: ignore[attr-defined]

            li["style"] = "text-decoration: line-through;"

            # checkmark_span = soup.new_tag("span", style="color: #1868DB; font-size: 12px;")
            # checkmark_span.string = "☑ "
            # li.insert(0, checkmark_span)


def process_ins_tags(soup: BeautifulSoup) -> None:
    """Normalize <ins> tags for consistent underline rendering."""
    for ins_tag in soup.find_all("ins"):
        contents = ins_tag.contents
        if contents:
            span = soup.new_tag("span")
            span["style"] = "text-decoration: underline;"
            span.extend(contents)
            ins_tag.replace_with(span)
        else:
            ins_tag.decompose()


def process_del_tags(soup: BeautifulSoup):
    """Normalize <del> tags for consistent strikethrough rendering."""
    for del_tag in soup.find_all("del"):
        contents = del_tag.contents
        if contents:
            span = soup.new_tag("span")
            span["style"] = "text-decoration: line-through;"
            span.extend(del_tag.contents)
            del_tag.replace_with(span)
        else:
            del_tag.decompose()


def fetch_attachment_info(  # noqa: PLR0911
    issue: Issue, attachment_id: str, attachment_cache: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """Fetch and encode a specific attachment by ID, with caching for duplicate references."""
    if attachment_id in attachment_cache:
        return attachment_cache[attachment_id]

    attachments = getattr(issue.fields, "attachment", []) or []
    if not isinstance(attachments, list):
        return None

    for attachment in attachments:
        if getattr(attachment, "id", None) != attachment_id:
            continue

        mime_type = getattr(attachment, "mimeType", None)
        if not mime_type:
            logger.warning(f"Attachment {attachment_id} missing mimeType metadata")
            return None

        info: dict[str, Any] = {
            "mime_type": mime_type,
            "content_url": getattr(attachment, "content", ""),
            "encoded": None,
        }

        if mime_type.startswith("image/"):
            size = getattr(attachment, "size", None)
            if size and size > MAX_EMBEDDED_IMAGE_SIZE:
                logger.warning(
                    f"Attachment {attachment_id} size ({size} bytes) exceeds "
                    f"maximum allowed size ({MAX_EMBEDDED_IMAGE_SIZE} bytes)"
                )
                attachment_cache[attachment_id] = info
                return info

            try:
                image_bytes = attachment.get()
            except Exception as e:
                logger.debug(f"Could not fetch attachment {attachment_id}: {e}")
                attachment_cache[attachment_id] = info
                return info

            if len(image_bytes) > MAX_EMBEDDED_IMAGE_SIZE:
                logger.warning(
                    f"Attachment {attachment_id} size ({len(image_bytes)} bytes) exceeds "
                    f"maximum allowed size ({MAX_EMBEDDED_IMAGE_SIZE} bytes)"
                )
            else:
                info["encoded"] = base64.b64encode(image_bytes).decode("utf-8")
                logger.debug(
                    f"Successfully processed attachment {attachment_id} ({len(image_bytes)} bytes)"
                )

        attachment_cache[attachment_id] = info
        return info

    logger.warning(f"Attachment {attachment_id} not found in issue attachments")
    return None


def process_image_tags(
    soup: BeautifulSoup,
    issue: Issue,
    jira_server_url: str,
) -> None:
    attachment_cache: dict[str, dict[str, Any]] = {}
    image_cache: dict[str, str | None] = {}

    for img in soup.find_all("img"):
        # Check next sibling and strip existing whitespace
        next_sib = img.next_sibling
        if next_sib and isinstance(next_sib, str):
            cleaned_text = "\xa0" + next_sib.lstrip()
            next_sib.replace_with(cleaned_text)

        src = str(img.get("src", "")).strip()

        if not src:
            img.decompose()
            continue

        if src.startswith("data:"):
            continue

        if src.startswith("cid:"):
            img.attrs.pop("src", None)
            continue

        if handle_attachment_image(img, src, issue, attachment_cache, jira_server_url):
            continue

        if handle_remote_image(img, src, image_cache, issue, jira_server_url):
            continue

        # Unsupported
        logger.warning(f"Removed image with unsupported src: {src}")
        img.attrs.pop("src", None)


def handle_attachment_image(
    img,
    src: str,
    issue: Issue,
    attachment_cache: dict[str, dict[str, Any]],
    jira_server_url: str,
) -> bool:
    attachment_match = JIRA_ATTACHMENT_URL_PATTERN.fullmatch(src)
    if attachment_match:
        attachment_id = attachment_match.group(1)
        attachment_info = fetch_attachment_info(issue, attachment_id, attachment_cache)
        apply_attachment_image(img, attachment_info, attachment_id, jira_server_url)
        return True
    return False


def apply_attachment_image(
    img,
    attachment_info: dict[str, Any] | None,
    attachment_id: str,
    jira_server_url: str,
) -> None:
    if not attachment_info:
        img.attrs.pop("src", None)
        return

    encoded = attachment_info.get("encoded")
    mime_type = attachment_info.get("mime_type") or "image/png"
    if encoded:
        img["src"] = f"data:{mime_type};base64,{encoded}"
        return

    fallback_url = attachment_info.get("content_url") or f"/attachment/{attachment_id}"
    img["src"] = build_absolute_jira_url(fallback_url, jira_server_url)


def handle_remote_image(
    img, src: str, image_cache: dict[str, str | None], issue: Issue, jira_server_url: str
) -> bool:
    # Normalize relative URLs
    if is_relative_url(src):
        src = build_absolute_jira_url(src, jira_server_url)

    if not is_remote_http(src):
        return False

    # Check cache
    if src in image_cache:
        if image_cache[src]:
            img["src"] = image_cache[src]
        return True

    # Try to inline
    if should_inline_remote_image(src, jira_server_url):
        data_uri = fetch_image_as_data_uri(issue, src)
        image_cache[src] = data_uri
        if data_uri:
            img["src"] = data_uri
            return True

    # Use remote URL directly
    image_cache[src] = None
    img["src"] = src
    return True


def process_anchor_tags(soup: BeautifulSoup, jira_server_url: str) -> None:
    for anchor in soup.find_all("a"):
        href = str(anchor.get("href", "")).strip()
        if not href or href.startswith(("http://", "https://", "mailto:")):
            continue
        if href.startswith("#"):
            continue
        if is_relative_url(href):
            anchor["href"] = build_absolute_jira_url(href, jira_server_url)


def build_absolute_jira_url(url: str, jira_server_url: str) -> str:
    """Convert relative Jira URL to absolute using base server URL."""
    if not url:
        return url
    if url.startswith(("http://", "https://")):
        return url
    base = jira_server_url if jira_server_url.endswith("/") else f"{jira_server_url}/"
    relative = url.lstrip("/")
    return urljoin(base, relative)


def is_relative_url(value: str) -> bool:
    if value.startswith(("data:", "mailto:", "cid:", "#")):
        return False
    parsed = urlparse(value)
    return parsed.scheme == ""


def is_remote_http(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def is_trusted_atlassian_host(hostname: str) -> bool:
    trusted_hosts = {"atlassian.net", "atlassian.com", "atl-paas.net"}
    return any(hostname == host or hostname.endswith(f".{host}") for host in trusted_hosts)


def should_inline_remote_image(src: str, jira_server_url: str) -> bool:
    """Only inline images hosted on the same Jira instance or trusted Atlassian CDN hosts.

    Allows:
    - data: URIs
    - Relative URLs
    - Same-host URLs
    - Trusted Atlassian hosts

    Blocks:
    - Any absolute URL pointing to an unknown external host
    """
    try:
        if src.startswith("data:"):
            return True

        parsed = urlparse(src)
        if not parsed.hostname:
            return True

        src_host = parsed.hostname.lower()

        jira_host = urlparse(jira_server_url).hostname
        if jira_host and src_host == jira_host.lower():
            return True

        if is_trusted_atlassian_host(src_host):
            return True

        logger.debug(f"Skipping remote image (untrusted host): {src!r} ")
        return False
    except Exception as e:
        logger.debug(f"Skipping image src {src!r}: failed to parse URL ({e})")
        return False


def fetch_image_as_data_uri(
    issue: Issue,
    url: str,
) -> str | None:
    session: ResilientSession | None = getattr(issue, "_session", None)
    if session is None:
        return None

    try:
        response = session.get(url)
        response.raise_for_status()
    except Exception as e:
        logger.debug(f"Failed to inline image from {url}: {e}")
        return None

    content_type = response.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        return None

    content = response.content
    if len(content) > MAX_EMBEDDED_IMAGE_SIZE:
        logger.debug("Image exceeds max embed size; skipping inline encoding")
        return None

    encoded = base64.b64encode(content).decode("utf-8")
    return f"data:{content_type};base64,{encoded}"
