"""Prepare a private input for the pinned Python/Go OpenAPI Generator."""

import json
import sys
from pathlib import Path


def preserve_item_nullability(node: object) -> None:
    """Keep bare non-null items distinct from nullable property schemas.

    In 7.10.0, adding an unrelated endpoint can make the default nullable
    simplification leak into bare array items (string or free-form object).
    Explicit false disambiguates those items without disabling simplification
    of genuinely nullable properties. Do not touch refs/compositions: that also
    changes inline model deduplication and therefore existing public type names.
    This is generator-only; the published native OpenAPI stays unchanged.
    """
    if isinstance(node, dict):
        items = node.get("items")
        if isinstance(items, dict) and items.get("type") in ("string", "object"):
            if set(items) <= {"type", "additionalProperties"}:
                items["nullable"] = False
        for value in node.values():
            preserve_item_nullability(value)
    elif isinstance(node, list):
        for value in node:
            preserve_item_nullability(value)


if __name__ == "__main__":
    specification = json.loads(Path(sys.argv[1]).read_text())
    preserve_item_nullability(specification.get("components", {}).get("schemas", {}))
    Path(sys.argv[2]).write_text(json.dumps(specification, indent=2) + "\n")
