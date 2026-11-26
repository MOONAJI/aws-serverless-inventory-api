"""Inventory API: AWS Lambda handler for an API Gateway HTTP API (payload v2.0).

Routes
    POST   /items            create an item
    GET    /items            list items (bonus)
    GET    /items/{item_id}  read one item
    PUT    /items/{item_id}  update fields of an item
    DELETE /items/{item_id}  delete an item
"""
import base64
import binascii
import json
import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.repository import DynamoRepository, ItemExistsError, ItemNotFoundError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_ITEM_PATH = re.compile(r"/items(?:/([^/]+))?/?$")
_TEXT_FIELDS = ("name", "category", "location")
_INT_FIELDS = ("quantity", "min_stock")
_MAX_TEXT = 100

_repository = None


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def _get_repository():
    global _repository
    if _repository is None:
        _repository = DynamoRepository(os.environ["TABLE_NAME"])
    return _repository


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError("Cannot serialize %s" % type(value).__name__)


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_json_default),
    }


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_body(event):
    raw = event.get("body")
    if not raw:
        raise ValidationError(["request body is required"])
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValidationError(["body is not valid base64 text"]) from exc
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(["body is not valid JSON"]) from exc
    if not isinstance(body, dict):
        raise ValidationError(["body must be a JSON object"])
    return body


def _validate(body, partial):
    """Return a clean dict of item fields or raise ValidationError."""
    errors = []
    clean = {}

    for field in _TEXT_FIELDS:
        if field not in body:
            continue
        value = body[field]
        if not isinstance(value, str) or len(value) > _MAX_TEXT:
            errors.append("%s must be a string of at most %d characters" % (field, _MAX_TEXT))
        elif field == "name" and not value.strip():
            errors.append("name must not be empty")
        else:
            clean[field] = value.strip()

    for field in _INT_FIELDS:
        if field not in body:
            continue
        value = body[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append("%s must be a non-negative integer" % field)
        else:
            clean[field] = value

    if not partial and "name" not in body:
        errors.append("name is required")
    if partial and not clean and not errors:
        errors.append("provide at least one of: name, category, quantity, location, min_stock")
    if errors:
        raise ValidationError(errors)
    return clean


def _create_item(event, repository):
    fields = _validate(_parse_body(event), partial=False)
    item = {
        "item_id": str(uuid4()),
        "name": fields["name"],
        "category": fields.get("category", ""),
        "quantity": fields.get("quantity", 0),
        "location": fields.get("location", ""),
        "min_stock": fields.get("min_stock", 0),
        "updated_at": _now(),
    }
    repository.create(item)
    return _response(201, item)


def _get_item(item_id, repository):
    item = repository.get(item_id)
    if item is None:
        raise ItemNotFoundError(item_id)
    return _response(200, item)


def _list_items(repository):
    items = repository.list()
    items.sort(key=lambda entry: entry.get("name", ""))
    return _response(200, {"items": items, "count": len(items)})


def _update_item(event, item_id, repository):
    fields = _validate(_parse_body(event), partial=True)
    fields["updated_at"] = _now()
    return _response(200, repository.update(item_id, fields))


def _delete_item(item_id, repository):
    repository.delete(item_id)
    return _response(200, {"deleted": item_id})


def lambda_handler(event, context=None, repository=None):
    repository = repository or _get_repository()
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "").upper()
    path = event.get("rawPath") or http.get("path", "")

    match = _ITEM_PATH.search(path)
    if not match:
        return _response(404, {"error": "route not found"})
    item_id = (event.get("pathParameters") or {}).get("item_id") or match.group(1)

    try:
        if item_id is None:
            if method == "POST":
                return _create_item(event, repository)
            if method == "GET":
                return _list_items(repository)
        else:
            if method == "GET":
                return _get_item(item_id, repository)
            if method == "PUT":
                return _update_item(event, item_id, repository)
            if method == "DELETE":
                return _delete_item(item_id, repository)
        return _response(405, {"error": "method %s not allowed on this route" % method})
    except ValidationError as exc:
        return _response(400, {"error": "validation failed", "details": exc.errors})
    except ItemNotFoundError:
        return _response(404, {"error": "item not found"})
    except ItemExistsError:
        return _response(409, {"error": "item already exists"})
    except Exception:  # noqa: BLE001 - last-resort guard, details go to CloudWatch
        logger.exception("unhandled error")
        return _response(500, {"error": "internal server error"})
