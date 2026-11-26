"""Storage access for the inventory API (DynamoDB, with an S3 fallback).

boto3 is imported lazily so the module (and the unit tests) work without it;
inside Lambda it is provided by the base image.
"""
import json


class ItemNotFoundError(Exception):
    """The requested item does not exist."""


class ItemExistsError(Exception):
    """An item with the same item_id already exists."""


def _is_conditional_failure(exc):
    error = getattr(exc, "response", {}).get("Error", {})
    return error.get("Code") == "ConditionalCheckFailedException"


class DynamoRepository:
    """CRUD operations on the InventoryItems table (partition key: item_id)."""

    def __init__(self, table_name, table=None):
        if table is None:
            import boto3  # provided by the Lambda base image

            table = boto3.resource("dynamodb").Table(table_name)
        self._table = table

    def create(self, item):
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(item_id)",
            )
        except Exception as exc:
            if _is_conditional_failure(exc):
                raise ItemExistsError(item["item_id"]) from exc
            raise
        return item

    def get(self, item_id):
        response = self._table.get_item(Key={"item_id": item_id})
        return response.get("Item")

    def list(self):
        items = []
        kwargs = {}
        while True:
            response = self._table.scan(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return items
            kwargs["ExclusiveStartKey"] = last_key

    def update(self, item_id, fields):
        names = {}
        values = {}
        assignments = []
        for index, (field, value) in enumerate(fields.items()):
            names["#f%d" % index] = field  # "name" is a DynamoDB reserved word
            values[":v%d" % index] = value
            assignments.append("#f%d = :v%d" % (index, index))
        try:
            response = self._table.update_item(
                Key={"item_id": item_id},
                UpdateExpression="SET " + ", ".join(assignments),
                ConditionExpression="attribute_exists(item_id)",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
        except Exception as exc:
            if _is_conditional_failure(exc):
                raise ItemNotFoundError(item_id) from exc
            raise
        return response["Attributes"]

    def delete(self, item_id):
        try:
            self._table.delete_item(
                Key={"item_id": item_id},
                ConditionExpression="attribute_exists(item_id)",
            )
        except Exception as exc:
            if _is_conditional_failure(exc):
                raise ItemNotFoundError(item_id) from exc
            raise


_S3_MISSING = {"404", "NoSuchKey", "NotFound"}


def _is_s3_missing(exc):
    error = getattr(exc, "response", {}).get("Error", {})
    return str(error.get("Code")) in _S3_MISSING


class S3Repository:
    """Same interface as DynamoRepository, storing each item as a JSON object.

    Fallback store for sandboxes that do not allow DynamoDB:
    object key = items/<item_id>.json
    """

    _PREFIX = "items/"

    def __init__(self, bucket_name, client=None):
        if client is None:
            import boto3  # provided by the Lambda base image

            client = boto3.client("s3")
        self._s3 = client
        self._bucket = bucket_name

    def _key(self, item_id):
        return "%s%s.json" % (self._PREFIX, item_id)

    def _put(self, item):
        self._s3.put_object(
            Bucket=self._bucket,
            Key=self._key(item["item_id"]),
            Body=json.dumps(item).encode("utf-8"),
            ContentType="application/json",
        )

    def _exists(self, item_id):
        try:
            self._s3.head_object(Bucket=self._bucket, Key=self._key(item_id))
            return True
        except Exception as exc:
            if _is_s3_missing(exc):
                return False
            raise

    def create(self, item):
        if self._exists(item["item_id"]):
            raise ItemExistsError(item["item_id"])
        self._put(item)
        return item

    def get(self, item_id):
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=self._key(item_id))
        except Exception as exc:
            if _is_s3_missing(exc):
                return None
            raise
        return json.loads(response["Body"].read())

    def list(self):
        items = []
        kwargs = {"Bucket": self._bucket, "Prefix": self._PREFIX}
        while True:
            response = self._s3.list_objects_v2(**kwargs)
            for entry in response.get("Contents", []):
                body = self._s3.get_object(Bucket=self._bucket, Key=entry["Key"])["Body"]
                items.append(json.loads(body.read()))
            if not response.get("IsTruncated"):
                return items
            kwargs["ContinuationToken"] = response["NextContinuationToken"]

    def update(self, item_id, fields):
        item = self.get(item_id)
        if item is None:
            raise ItemNotFoundError(item_id)
        item.update(fields)
        self._put(item)
        return item

    def delete(self, item_id):
        if not self._exists(item_id):
            raise ItemNotFoundError(item_id)
        self._s3.delete_object(Bucket=self._bucket, Key=self._key(item_id))
