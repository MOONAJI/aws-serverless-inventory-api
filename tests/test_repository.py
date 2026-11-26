"""Checks DynamoRepository against a fake table (no AWS, no boto3 needed)."""
import unittest

from app.repository import DynamoRepository, ItemExistsError, ItemNotFoundError


class FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError for a failed condition."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeTable:
    def __init__(self):
        self.calls = []
        self.fail_with = None
        self.scan_pages = [{"Items": [{"item_id": "1"}], "LastEvaluatedKey": {"item_id": "1"}},
                           {"Items": [{"item_id": "2"}]}]

    def _record(self, name, kwargs):
        self.calls.append((name, kwargs))
        if self.fail_with:
            raise FakeClientError(self.fail_with)

    def put_item(self, **kwargs):
        self._record("put_item", kwargs)

    def get_item(self, **kwargs):
        self._record("get_item", kwargs)
        return {}

    def scan(self, **kwargs):
        self._record("scan", kwargs)
        return self.scan_pages.pop(0)

    def update_item(self, **kwargs):
        self._record("update_item", kwargs)
        return {"Attributes": {"item_id": "1", "name": "New"}}

    def delete_item(self, **kwargs):
        self._record("delete_item", kwargs)


class DynamoRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.table = FakeTable()
        self.repo = DynamoRepository("InventoryItems", table=self.table)

    def test_create_uses_condition_to_avoid_overwrite(self):
        self.repo.create({"item_id": "1", "name": "A"})
        name, kwargs = self.table.calls[0]
        self.assertEqual(name, "put_item")
        self.assertEqual(kwargs["ConditionExpression"], "attribute_not_exists(item_id)")

    def test_create_duplicate_raises_item_exists(self):
        self.table.fail_with = "ConditionalCheckFailedException"
        with self.assertRaises(ItemExistsError):
            self.repo.create({"item_id": "1", "name": "A"})

    def test_other_errors_are_not_swallowed(self):
        self.table.fail_with = "ProvisionedThroughputExceededException"
        with self.assertRaises(FakeClientError):
            self.repo.create({"item_id": "1", "name": "A"})

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.repo.get("1"))

    def test_list_follows_pagination(self):
        self.assertEqual([i["item_id"] for i in self.repo.list()], ["1", "2"])
        self.assertEqual(self.table.calls[1][1]["ExclusiveStartKey"], {"item_id": "1"})

    def test_update_builds_expression_with_placeholders_for_reserved_words(self):
        result = self.repo.update("1", {"name": "New", "quantity": 4})
        _, kwargs = self.table.calls[0]
        self.assertEqual(kwargs["UpdateExpression"], "SET #f0 = :v0, #f1 = :v1")
        self.assertEqual(kwargs["ExpressionAttributeNames"], {"#f0": "name", "#f1": "quantity"})
        self.assertEqual(kwargs["ExpressionAttributeValues"], {":v0": "New", ":v1": 4})
        self.assertEqual(kwargs["ConditionExpression"], "attribute_exists(item_id)")
        self.assertEqual(result["name"], "New")

    def test_update_and_delete_missing_raise_not_found(self):
        self.table.fail_with = "ConditionalCheckFailedException"
        with self.assertRaises(ItemNotFoundError):
            self.repo.update("1", {"name": "X"})
        with self.assertRaises(ItemNotFoundError):
            self.repo.delete("1")


if __name__ == "__main__":
    unittest.main()
