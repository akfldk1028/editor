from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


_SCHEMA_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]*\.schema\.json$")


@lru_cache(maxsize=16)
def _validator(schema_path: str) -> Draft202012Validator:
    path = Path(schema_path)
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_planm_contract(
    product_root: Path,
    schema_name: str,
    value: Any,
) -> None:
    if not _SCHEMA_NAME.fullmatch(schema_name):
        raise ValueError("PLANM schema name is invalid")
    contract_root = (
        product_root.resolve() / "agents" / "planm" / "contracts"
    ).resolve()
    schema_path = (contract_root / schema_name).resolve()
    try:
        schema_path.relative_to(contract_root)
    except ValueError as error:
        raise ValueError("PLANM schema path escapes the contract root") from error
    if not schema_path.is_file():
        raise ValueError(f"PLANM schema is missing: {schema_name}")
    errors = sorted(
        _validator(str(schema_path)).iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path) or "$"
    raise ValueError(
        f"PLANM contract validation failed for {schema_name} at {location}: "
        f"{first.message}"
    )
