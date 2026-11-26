import base64
import json
import unittest
from decimal import Decimal

from app.handler import lambda_handler
from app.repository import ItemExistsError, ItemNotFoundError


class InMemoryRepository:
    """Same interface as DynamoRepository, backed by a dict."""

    def __init__(self):
        self.items = {}

    def create(self, item):
        if item["item_id"] in self.items:
            raise ItemExistsError(item["item_id"])
        self.items[item["item_id"]] = dict(item)
        return item

    def get(self, item_id):
        return self.items.get(item_id)

    def list(self):
        return [dict(item) for item in self.items.values()]

    def update(self, item_id, fields):
        if item_id not in self.items:
            raise ItemNotFoundError(item_id)
        self.items[item_id].update(fields)
        return dict(self.items[item_id])

    def delete(self, item_id):
        if item_id not in self.items:
            raise ItemNotFoundError(item_id)
        del self.items[item_id]


def make_event(method, path, body=None, item_id=None, base64_body=False):
    event = {
        "version": "2.0",
        "rawPath": path,
        "requestContext": {"http": {"method": method, "path": path}},
    }
    if item_id:
        event["pathParameters"] = {"item_id": item_id}
    if body is not None:
        raw = body if isinstance(body, str) else json.dumps(body)
        if base64_body:
            raw = base64.b64encode(raw.encode()).decode()
            event["isBase64Encoded"] = True
        event["body"] = raw
    return event


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()

    def call(self, *args, **kwargs):
        result = lambda_handler(make_event(*args, **kwargs), None, repository=self.repo)
        return result["statusCode"], json.loads(result["body"])

    def create(self, **fields):
        status, body = self.call("POST", "/items", fields or {"name": "Multimeter"})
        self.assertEqual(status, 201)
        return body

    # --- Create -------------------------------------------------------
    def test_create_returns_201_with_defaults(self):
        item = self.create(name="Multimeter")
        self.assertEqual(item["name"], "Multimeter")
        self.assertEqual(item["quantity"], 0)
        self.assertEqual(item["min_stock"], 0)
        self.assertTrue(item["item_id"])
        self.assertTrue(item["updated_at"])
        self.assertIn(item["item_id"], self.repo.items)

    def test_create_requires_name(self):
        status, body = self.call("POST", "/items", {"quantity": 2})
        self.assertEqual(status, 400)
        self.assertIn("name is required", body["details"])

    def test_create_rejects_negative_or_non_integer_quantity(self):
        for bad in (-1, 1.5, "3", True):
            status, _ = self.call("POST", "/items", {"name": "X", "quantity": bad})
            self.assertEqual(status, 400, bad)

    def test_create_rejects_invalid_json_and_missing_body(self):
        self.assertEqual(self.call("POST", "/items", "{not json")[0], 400)
        self.assertEqual(self.call("POST", "/items")[0], 400)
        self.assertEqual(self.call("POST", "/items", "[1, 2]")[0], 400)

    def test_create_accepts_base64_body(self):
        status, body = self.call("POST", "/items", {"name": "Probe"}, base64_body=True)
        self.assertEqual(status, 201)
        self.assertEqual(body["name"], "Probe")

    # --- Read ---------------------------------------------------------
    def test_get_existing_item(self):
        item = self.create(name="Oscilloscope", quantity=3)
        status, body = self.call("GET", "/items/" + item["item_id"], item_id=item["item_id"])
        self.assertEqual(status, 200)
        self.assertEqual(body["quantity"], 3)

    def test_get_missing_item_returns_404(self):
        status, _ = self.call("GET", "/items/nope", item_id="nope")
        self.assertEqual(status, 404)

    def test_get_item_id_falls_back_to_path_when_no_path_parameters(self):
        item = self.create(name="Cable")
        status, _ = self.call("GET", "/items/" + item["item_id"])
        self.assertEqual(status, 200)

    def test_list_returns_items_sorted_by_name(self):
        self.create(name="b-item")
        self.create(name="a-item")
        status, body = self.call("GET", "/items")
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 2)
        self.assertEqual([i["name"] for i in body["items"]], ["a-item", "b-item"])

    def test_decimal_values_from_dynamodb_serialize_as_numbers(self):
        self.repo.items["x"] = {"item_id": "x", "name": "N", "quantity": Decimal("5")}
        status, body = self.call("GET", "/items/x", item_id="x")
        self.assertEqual(status, 200)
        self.assertEqual(body["quantity"], 5)
        self.assertIsInstance(body["quantity"], int)

    # --- Update -------------------------------------------------------
    def test_update_changes_only_given_fields(self):
        item = self.create(name="Resistor", quantity=10, location="Shelf A")
        status, body = self.call(
            "PUT", "/items/" + item["item_id"], {"quantity": 7}, item_id=item["item_id"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["quantity"], 7)
        self.assertEqual(body["location"], "Shelf A")
        self.assertEqual(body["name"], "Resistor")

    def test_update_requires_at_least_one_field(self):
        item = self.create(name="Fuse")
        status, _ = self.call("PUT", "/items/x", {}, item_id=item["item_id"])
        self.assertEqual(status, 400)

    def test_update_rejects_empty_name(self):
        item = self.create(name="Fuse")
        status, _ = self.call("PUT", "/items/x", {"name": "  "}, item_id=item["item_id"])
        self.assertEqual(status, 400)

    def test_update_missing_item_returns_404(self):
        status, _ = self.call("PUT", "/items/nope", {"quantity": 1}, item_id="nope")
        self.assertEqual(status, 404)

    # --- Delete -------------------------------------------------------
    def test_delete_then_get_returns_404(self):
        item = self.create(name="Breadboard")
        status, body = self.call("DELETE", "/items/x", item_id=item["item_id"])
        self.assertEqual(status, 200)
        self.assertEqual(body["deleted"], item["item_id"])
        self.assertEqual(self.call("GET", "/items/x", item_id=item["item_id"])[0], 404)

    def test_delete_missing_item_returns_404(self):
        status, _ = self.call("DELETE", "/items/nope", item_id="nope")
        self.assertEqual(status, 404)

    # --- Routing and errors ------------------------------------------
    def test_unknown_route_returns_404(self):
        self.assertEqual(self.call("GET", "/other")[0], 404)

    def test_unsupported_method_returns_405(self):
        self.assertEqual(self.call("PATCH", "/items")[0], 405)
        self.assertEqual(self.call("POST", "/items/abc", {"name": "x"}, item_id="abc")[0], 405)

    def test_stage_prefix_in_path_is_ignored(self):
        status, _ = self.call("GET", "/prod/items")
        self.assertEqual(status, 200)

    def test_unexpected_error_returns_500_without_details(self):
        class BrokenRepository(InMemoryRepository):
            def list(self):
                raise RuntimeError("secret detail")

        result = lambda_handler(make_event("GET", "/items"), None, repository=BrokenRepository())
        self.assertEqual(result["statusCode"], 500)
        self.assertNotIn("secret", result["body"])


if __name__ == "__main__":
    unittest.main()
