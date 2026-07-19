"""Strict stdlib client for Uoink's loopback corpus-read contract v1.

Writer receives the base URL and token from its own configuration or process
environment. It never discovers Uoink by reading Uoink files or SQLite.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from writer.schemas import (
    AssemblyQuery,
    SourceSnapshot,
    UOINK_CONTRACT,
    UOINK_CONTRACT_VERSION,
)

DEFAULT_BASE_URL = "http://127.0.0.1:5179"
UOINK_URL_ENV = "WRITER_UOINK_URL"
UOINK_TOKEN_ENV = "WRITER_UOINK_TOKEN"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_EXCERPT_CHARS = 4000

SEARCH_KEYS = {
    "q",
    "channel",
    "topic",
    "hook_type",
    "platform",
    "source_type",
    "author",
    "date_from",
    "date_to",
    "limit",
    "offset",
}
ITEM_KEYS = {
    "id",
    "title",
    "author",
    "source_type",
    "platform",
    "source_url",
    "captured_at",
    "duration_seconds",
    "credit",
    "facets",
    "preview",
}
CREDIT_KEYS = {"creator", "handle", "source_url"}
ITEM_FACET_KEYS = {
    "topic",
    "hook_type",
    "format",
    "performance_tier",
    "length_bucket",
}
ATTACHMENT_KEYS = {
    "id",
    "kind",
    "role",
    "media_type",
    "label",
    "byte_length",
    "href",
}
FACET_NAMES = {
    "platform",
    "source_type",
    "author",
    "channel",
    "format",
    "performance_tier",
    "length_bucket",
    "topic",
    "hook_type",
}
ASSEMBLY_ITEM_KEYS = {
    "video_id",
    "slug",
    "title",
    "channel",
    "topic",
    "hook_type",
    "format",
    "performance_tier",
    "length_bucket",
    "yoinked_at",
}


class UoinkContractError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 502,
                 retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable


class UoinkUnavailable(RuntimeError):
    """The optional local peer cannot be reached or did not return JSON."""


def _mismatch(message: str) -> UoinkContractError:
    return UoinkContractError("contract_mismatch", message)


def _exact(value: Any, expected: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise _mismatch(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        parts = []
        if missing:
            parts.append("missing " + ", ".join(missing))
        if unknown:
            parts.append("unknown " + ", ".join(unknown))
        raise _mismatch(
            f"{label} has invalid fields: {'; '.join(parts)}")
    return value


def _nullable_string(value: Any, label: str) -> None:
    if value is not None and not isinstance(value, str):
        raise _mismatch(f"{label} must be a string or null")


def _validate_attachment(value: Any) -> None:
    value = _exact(value, ATTACHMENT_KEYS, "attachment")
    for name in ("id", "kind", "role", "media_type", "label", "href"):
        if not isinstance(value[name], str) or not value[name]:
            raise _mismatch(
                f"attachment.{name} must be a non-empty string")
    length = value["byte_length"]
    if isinstance(length, bool) or not isinstance(length, int) or length < 0:
        raise _mismatch(
            "attachment.byte_length must be a non-negative integer")


def _validate_item(value: Any) -> None:
    value = _exact(value, ITEM_KEYS, "item")
    if not isinstance(value["id"], str) or not value["id"]:
        raise _mismatch("item.id must be a non-empty string")
    if not isinstance(value["title"], str):
        raise _mismatch("item.title must be a string")
    for name in (
            "author", "source_type", "platform", "source_url",
            "captured_at"):
        _nullable_string(value[name], f"item.{name}")
    duration = value["duration_seconds"]
    if duration is not None and (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))):
        raise _mismatch(
            "item.duration_seconds must be a number or null")
    credit = _exact(value["credit"], CREDIT_KEYS, "item.credit")
    for name, item in credit.items():
        _nullable_string(item, f"item.credit.{name}")
    facets = _exact(value["facets"], ITEM_FACET_KEYS, "item.facets")
    for name, item in facets.items():
        _nullable_string(item, f"item.facets.{name}")
    if value["preview"] is not None:
        _validate_attachment(value["preview"])


def _validate_search(data: Any) -> None:
    data = _exact(data, {"items", "page"}, "search data")
    if not isinstance(data["items"], list):
        raise _mismatch("search data.items must be a list")
    for item in data["items"]:
        _validate_item(item)
    page = _exact(
        data["page"],
        {"state", "total", "corpus_total", "limit", "offset"},
        "search data.page",
    )
    if page["state"] not in (
            "matches", "no_matches", "empty_corpus"):
        raise _mismatch("search data.page.state is invalid")
    for name in ("total", "corpus_total", "limit", "offset"):
        value = page[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _mismatch(
                f"search data.page.{name} must be non-negative")


def _validate_get(data: Any) -> None:
    data = _exact(
        data, {"item", "content", "attachments"}, "get data")
    _validate_item(data["item"])
    content = _exact(
        data["content"],
        {"available", "media_type", "text", "byte_length", "truncated"},
        "get data.content",
    )
    if not isinstance(content["available"], bool):
        raise _mismatch("get data.content.available must be boolean")
    if content["media_type"] != "text/markdown":
        raise _mismatch(
            "get data.content.media_type must be text/markdown")
    if not isinstance(content["text"], str):
        raise _mismatch("get data.content.text must be a string")
    length = content["byte_length"]
    if isinstance(length, bool) or not isinstance(length, int) or length < 0:
        raise _mismatch(
            "get data.content.byte_length must be non-negative")
    if not isinstance(content["truncated"], bool):
        raise _mismatch("get data.content.truncated must be boolean")
    if not isinstance(data["attachments"], list):
        raise _mismatch("get data.attachments must be a list")
    for attachment in data["attachments"]:
        _validate_attachment(attachment)


def _validate_facets(data: Any) -> None:
    data = _exact(data, {"facets", "date_bounds"}, "facets data")
    facets = _exact(data["facets"], FACET_NAMES, "facets data.facets")
    for name, values in facets.items():
        if not isinstance(values, list):
            raise _mismatch(
                f"facets data.facets.{name} must be a list")
        for value in values:
            value = _exact(
                value, {"value", "label", "count"}, "facet item")
            if not isinstance(value["value"], str) \
                    or not isinstance(value["label"], str) \
                    or isinstance(value["count"], bool) \
                    or not isinstance(value["count"], int) \
                    or value["count"] < 0:
                raise _mismatch(
                    "facet items require strings and non-negative count")
    bounds = _exact(
        data["date_bounds"], {"min", "max"}, "facets date_bounds")
    _nullable_string(bounds["min"], "facets date_bounds.min")
    _nullable_string(bounds["max"], "facets date_bounds.max")


def _validate_taste(data: Any) -> None:
    data = _exact(data, {"markdown", "anchors"}, "taste data")
    if not isinstance(data["markdown"], str):
        raise _mismatch("taste data.markdown must be a string")
    anchors = _exact(
        data["anchors"],
        {"best", "worst", "admired_channels"},
        "taste data.anchors",
    )
    for name in ("best", "worst"):
        if not isinstance(anchors[name], list):
            raise _mismatch(
                f"taste data.anchors.{name} must be a list")
        for item in anchors[name]:
            item = _exact(item, {"id", "title"}, "taste anchor")
            if not isinstance(item["id"], str) \
                    or not isinstance(item["title"], str):
                raise _mismatch(
                    "taste anchors require string id and title")
    if not isinstance(anchors["admired_channels"], list) or any(
            not isinstance(value, str)
            for value in anchors["admired_channels"]):
        raise _mismatch(
            "taste admired_channels must be a list of strings")


def _validate_assemble(data: Any) -> None:
    data = _exact(
        data,
        {
            "filters", "assembled", "audience_questions",
            "self_snapshot", "taste_anchors",
        },
        "assemble data",
    )
    filters = _exact(
        data["filters"],
        {
            "format", "topic", "hook_target", "your_channel",
            "n_examples",
        },
        "assemble data.filters",
    )
    for name in ("format", "topic", "hook_target", "your_channel"):
        _nullable_string(filters[name], f"assemble data.filters.{name}")
    count = filters["n_examples"]
    if isinstance(count, bool) or not isinstance(count, int) \
            or not 1 <= count <= 100:
        raise _mismatch(
            "assemble data.filters.n_examples must be between 1 and 100")
    if not isinstance(data["assembled"], list):
        raise _mismatch("assemble data.assembled must be a list")
    for item in data["assembled"]:
        item = _exact(item, ASSEMBLY_ITEM_KEYS, "assembled item")
        if not isinstance(item["video_id"], str) or not item["video_id"]:
            raise _mismatch(
                "assembled item.video_id must be a non-empty string")
        for name in ASSEMBLY_ITEM_KEYS - {"video_id"}:
            _nullable_string(item[name], f"assembled item.{name}")
    if not isinstance(data["audience_questions"], list):
        raise _mismatch(
            "assemble data.audience_questions must be a list")
    for item in data["audience_questions"]:
        item = _exact(
            item, {"video_id", "question", "likes"},
            "audience question",
        )
        if not isinstance(item["video_id"], str) \
                or not isinstance(item["question"], str) \
                or isinstance(item["likes"], bool) \
                or not isinstance(item["likes"], int):
            raise _mismatch("audience question has invalid values")
    if data["self_snapshot"] is not None \
            and not isinstance(data["self_snapshot"], dict):
        raise _mismatch(
            "assemble data.self_snapshot must be an object or null")
    if data["taste_anchors"] is not None and not isinstance(
            data["taste_anchors"], (str, dict)):
        raise _mismatch(
            "assemble data.taste_anchors must be a string, object, or null")


VALIDATORS = {
    "search": _validate_search,
    "get": _validate_get,
    "facets": _validate_facets,
    "taste": _validate_taste,
    "assemble": _validate_assemble,
}


def validate_envelope(operation: str, payload: Any, *,
                      status: int = 200) -> dict:
    """Validate a complete Uoink v1 response and return its data.

    Contract-declared failures become `UoinkContractError`. Shape or version
    drift also fails closed; Writer does not guess at a new provider shape.
    """
    if operation not in VALIDATORS:
        raise _mismatch(f"unknown Writer corpus operation {operation!r}")
    if not isinstance(payload, dict):
        raise _mismatch("contract response must be an object")
    ok = payload.get("ok")
    expected = (
        {"ok", "contract", "version", "operation", "data"}
        if ok is True
        else {"ok", "contract", "version", "operation", "error"}
    )
    payload = _exact(payload, expected, "contract response")
    if payload["contract"] != UOINK_CONTRACT:
        raise _mismatch(
            f"contract must be {UOINK_CONTRACT}")
    if payload["version"] != UOINK_CONTRACT_VERSION:
        raise _mismatch(
            f"contract version must be {UOINK_CONTRACT_VERSION}")
    if payload["operation"] != operation:
        raise _mismatch(
            f"operation must be {operation}")
    if ok is not True:
        if ok is not False:
            raise _mismatch("contract response.ok must be boolean")
        error = _exact(
            payload["error"],
            {"code", "message", "retryable"},
            "contract error",
        )
        if not isinstance(error["code"], str) \
                or not isinstance(error["message"], str) \
                or not isinstance(error["retryable"], bool):
            raise _mismatch("contract error fields have invalid values")
        raise UoinkContractError(
            error["code"],
            error["message"],
            status=status,
            retryable=error["retryable"],
        )
    VALIDATORS[operation](payload["data"])
    return payload["data"]


def _loopback_base_url(value: str) -> str:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    if parsed.scheme != "http" or parsed.hostname not in {
            "127.0.0.1", "localhost", "::1"}:
        raise ValueError(
            "Uoink URL must be an http loopback address")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError(
            "Uoink URL must contain only scheme, host, and port")
    if parsed.port is None:
        raise ValueError("Uoink URL requires a port")
    return value.rstrip("/")


class UoinkClient:
    def __init__(self, base_url: str, token: str, *,
                 timeout: float = 5.0):
        self.base_url = _loopback_base_url(base_url)
        self.token = str(token or "").strip()
        if not self.token:
            raise ValueError("Uoink token is required")
        self.timeout = max(0.05, min(float(timeout), 30.0))

    @classmethod
    def from_env(cls, *, timeout: float = 5.0) -> "UoinkClient":
        return cls(
            os.environ.get(UOINK_URL_ENV, DEFAULT_BASE_URL),
            os.environ.get(UOINK_TOKEN_ENV, ""),
            timeout=timeout,
        )

    def _request(self, operation: str, path: str, *,
                 method: str = "GET",
                 body: dict | None = None) -> dict:
        data = (
            json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None else None
        )
        headers = {
            "Accept": "application/json",
            "X-Uoink-Token": self.token,
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        status = 200
        try:
            with urllib.request.urlopen(
                    request, timeout=self.timeout) as response:
                status = int(response.status)
                content_type = response.headers.get_content_type()
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            status = int(error.code)
            content_type = error.headers.get_content_type()
            raw = error.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise UoinkUnavailable(
                "Uoink is unavailable on the configured loopback address"
            ) from error
        if content_type != "application/json":
            raise UoinkUnavailable(
                "Uoink returned a non-JSON response")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise UoinkUnavailable(
                "Uoink response exceeded the local safety limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise UoinkUnavailable(
                "Uoink returned invalid JSON") from error
        return validate_envelope(operation, payload, status=status)

    def search(self, **query: Any) -> dict:
        unknown = sorted(set(query) - SEARCH_KEYS)
        if unknown:
            raise ValueError(
                "unknown search fields: " + ", ".join(unknown))
        encoded = urllib.parse.urlencode({
            name: value
            for name, value in query.items()
            if value is not None
        })
        path = "/api/corpus/v1/search"
        if encoded:
            path += "?" + encoded
        return self._request("search", path)

    def get(self, item_id: str) -> dict:
        item_id = str(item_id or "").strip()
        if not item_id or len(item_id) > 200:
            raise ValueError("Uoink item id is invalid")
        encoded = urllib.parse.quote(item_id, safe="")
        return self._request(
            "get", f"/api/corpus/v1/items/{encoded}")

    def facets(self) -> dict:
        return self._request("facets", "/api/corpus/v1/facets")

    def taste(self) -> dict:
        return self._request("taste", "/api/corpus/v1/taste")

    def assemble(self, query: AssemblyQuery) -> dict:
        query.validate()
        return self._request(
            "assemble",
            "/api/corpus/v1/assemble",
            method="POST",
            body=query.to_dict(),
        )

    def attach_source(self, item_id: str) -> SourceSnapshot:
        detail = self.get(item_id)
        item = detail["item"]
        credit = item["credit"]
        creator = str(
            credit.get("creator") or item.get("author") or "").strip()
        title = str(item.get("title") or "").strip()
        source_url = str(
            credit.get("source_url") or item.get("source_url") or "").strip()
        external = bool(source_url) or creator.casefold() not in {
            "", "you", "user",
        }
        credit_parts = ["Source:"]
        if title:
            credit_parts.append(title)
        if creator:
            credit_parts.extend(("by", creator))
        if source_url:
            credit_parts.extend(("--", source_url))
        credit_line = " ".join(credit_parts) if external else ""
        excerpt = str(
            (detail.get("content") or {}).get("text") or "")
        return SourceSnapshot(
            provider="uoink",
            provider_ref=f"uoink://item/{item['id']}",
            title=title,
            creator=creator,
            source_url=source_url,
            credit_line=credit_line,
            excerpt=excerpt[:MAX_EXCERPT_CHARS],
            attached_at=datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            credit_required=external,
        ).validate()
