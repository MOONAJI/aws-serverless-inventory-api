"""DynamoDB access for the inventory API.

boto3 is imported lazily so the module (and the unit tests) work without it;
inside Lambda it is provided by the base image.
"""


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
