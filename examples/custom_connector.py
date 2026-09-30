"""Server-registered connector example; never load code from a report package."""
from reportbuilder.data import register_connector


class ExampleConnector:
    def introspect(self, config):
        return {"objects": [{"schema": None, "object": "orders", "type": "table", "columns": [
            {"column": "name", "type": "string", "nullable": False},
            {"column": "amount", "type": "integer", "nullable": False},
        ]}], "capabilities": {"read_only": True}, "verified": False}

    def read(self, config, object_mapping, columns, limit):
        if object_mapping["object"] != "orders":
            raise ValueError("Unknown object")
        rows = [{"name": "Example", "amount": 100}]
        return [{key: row[key] for key in columns} for row in rows[:limit]]


register_connector("example_orders", ExampleConnector())
