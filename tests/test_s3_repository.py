"""Checks S3Repository against a fake S3 client (no AWS, no boto3 needed)."""
import io
import json
import os
import unittest
from unittest import mock

from app import handler
from app.repository import ItemExistsError, ItemNotFoundError, S3Repository


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self, page_size=2):
        self.objects = {}
        self.page_size = page_size

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise FakeClientError("404")
        return {}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start:start + self.page_size]
        response = {"Contents": [{"Key": k} for k in page]}
        if start + self.page_size < len(keys):
            response["IsTruncated"] = True
            response["NextContinuationToken"] = str(start + self.page_size)
        return response

    def delete_object(self, Bucket, Key):
        del self.objects[Key]


class S3RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.s3 = FakeS3()
        self.repo = S3Repository("bucket", client=self.s3)

    def test_create_get_round_trip(self):
        self.repo.create({"item_id": "1", "name": "A", "quantity": 2})
        self.assertIn("items/1.json", self.s3.objects)
        self.assertEqual(self.repo.get("1"), {"item_id": "1", "name": "A", "quantity": 2})

    def test_create_duplicate_raises(self):
        self.repo.create({"item_id": "1", "name": "A"})
        with self.assertRaises(ItemExistsError):
            self.repo.create({"item_id": "1", "name": "B"})

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.repo.get("nope"))

    def test_list_follows_pagination(self):
        for i in range(5):
            self.repo.create({"item_id": str(i), "name": "n%d" % i})
        self.assertEqual(sorted(i["item_id"] for i in self.repo.list()), ["0", "1", "2", "3", "4"])

    def test_update_merges_fields(self):
        self.repo.create({"item_id": "1", "name": "A", "quantity": 2})
        self.assertEqual(self.repo.update("1", {"quantity": 5})["quantity"], 5)
        self.assertEqual(self.repo.get("1")["name"], "A")

    def test_update_and_delete_missing_raise(self):
        with self.assertRaises(ItemNotFoundError):
            self.repo.update("x", {"name": "B"})
        with self.assertRaises(ItemNotFoundError):
            self.repo.delete("x")

    def test_delete_removes_object(self):
        self.repo.create({"item_id": "1", "name": "A"})
        self.repo.delete("1")
        self.assertEqual(self.s3.objects, {})

    def test_other_errors_are_not_swallowed(self):
        class Broken(FakeS3):
            def get_object(self, Bucket, Key):
                raise FakeClientError("AccessDenied")

        with self.assertRaises(FakeClientError):
            S3Repository("bucket", client=Broken()).get("1")

    def test_full_crud_through_handler(self):
        def call(method, path, body=None):
            event = {"rawPath": path, "requestContext": {"http": {"method": method}}}
            if body is not None:
                event["body"] = json.dumps(body)
            result = handler.lambda_handler(event, None, repository=self.repo)
            return result["statusCode"], json.loads(result["body"])

        status, item = call("POST", "/items", {"name": "Oscilloscope", "quantity": 3})
        self.assertEqual(status, 201)
        path = "/items/" + item["item_id"]
        self.assertEqual(call("GET", path)[1]["quantity"], 3)
        self.assertEqual(call("PUT", path, {"quantity": 2})[1]["quantity"], 2)
        self.assertEqual(call("GET", "/items")[1]["count"], 1)
        self.assertEqual(call("DELETE", path)[0], 200)
        self.assertEqual(call("GET", path)[0], 404)


class RepositorySelectionTests(unittest.TestCase):
    def tearDown(self):
        handler._repository = None

    def test_bucket_name_selects_s3(self):
        handler._repository = None
        with mock.patch.dict(os.environ, {"BUCKET_NAME": "b"}, clear=True), \
                mock.patch("app.handler.S3Repository") as s3_repo:
            handler._get_repository()
            s3_repo.assert_called_once_with("b")

    def test_missing_configuration_fails_clearly(self):
        handler._repository = None
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                handler._get_repository()


if __name__ == "__main__":
    unittest.main()
