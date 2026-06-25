from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

import parsehawk.core.domain.schemas as schema_module
from parsehawk.core.domain.schemas import (
    MODE_FIELD_SCHEMA,
    MODE_JSON_SCHEMA,
    MODE_NUEXTRACT_TEMPLATE,
    NUEXTRACT_TYPES,
    field_schema_from_json_schema,
    field_schema_from_nuextract_template,
    json_schema_from_field_schema,
    nuextract_template_from_field_schema,
    validate_authoring_json_schema,
    validate_extraction_schema,
    validate_field_schema,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_field_schema_derives_json_schema_and_nuextract_template() -> None:
    field_schema = {
        "fields": [
            {
                "key": "invoice_number",
                "kind": "scalar",
                "json_type": "string",
                "nuextract_type": "verbatim-string",
                "required": True,
                "nullable": True,
                "description": "Invoice number exactly as printed",
            },
            {
                "key": "status",
                "kind": "enum",
                "json_type": "string",
                "nuextract_type": "enum",
                "enum": ["paid", "open", "overdue"],
                "required": True,
                "nullable": True,
            },
            {
                "key": "vendor_account",
                "kind": "scalar",
                "json_type": "string",
                "nuextract_type": "string",
                "required": True,
                "nullable": False,
                "pattern": "^\\d{10}$",
                "minLength": 10,
                "maxLength": 10,
            },
            {
                "key": "line_items",
                "kind": "array",
                "json_type": "array",
                "nuextract_type": "array",
                "required": False,
                "nullable": False,
                "items": {
                    "kind": "object",
                    "fields": [
                        {
                            "key": "description",
                            "kind": "scalar",
                            "json_type": "string",
                            "nuextract_type": "verbatim-string",
                            "required": True,
                            "nullable": True,
                        },
                        {
                            "key": "total",
                            "kind": "scalar",
                            "json_type": "number",
                            "nuextract_type": "number",
                            "required": True,
                            "nullable": True,
                        },
                    ],
                },
            },
        ]
    }

    result = validate_extraction_schema(mode=MODE_FIELD_SCHEMA, field_schema=field_schema)

    assert result.valid is True
    assert result.field_schema == field_schema
    assert result.json_schema == {
        "type": "object",
        "properties": {
            "invoice_number": {
                "type": ["string", "null"],
                "description": "Invoice number exactly as printed",
                "x-parsehawk": {"semantic": "verbatim-string"},
            },
            "status": {
                "type": "string",
                "enum": ["paid", "open", "overdue", None],
            },
            "vendor_account": {
                "type": "string",
                "pattern": "^\\d{10}$",
                "minLength": 10,
                "maxLength": 10,
            },
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": ["string", "null"],
                            "x-parsehawk": {"semantic": "verbatim-string"},
                        },
                        "total": {"type": ["number", "null"]},
                    },
                    "required": ["description", "total"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["invoice_number", "status", "vendor_account"],
        "additionalProperties": False,
    }
    assert result.nuextract_template == {
        "invoice_number": "verbatim-string",
        "status": ["paid", "open", "overdue"],
        "vendor_account": "string",
        "line_items": [{"description": "verbatim-string", "total": "number"}],
    }


def test_json_schema_mode_imports_nuextract_semantics_and_enums() -> None:
    schema = {
        "type": "object",
        "properties": {
            "buyer": {
                "type": ["string", "null"],
                "x-parsehawk": {"semantic": "verbatim-string"},
            },
            "receipt_id": {
                "anyOf": [
                    {"const": "1", "title": "Invoice"},
                    {"const": "2", "title": "Support request"},
                    {"type": "null"},
                ]
            },
        },
        "required": ["buyer", "receipt_id"],
        "additionalProperties": False,
    }

    result = validate_extraction_schema(mode=MODE_JSON_SCHEMA, json_schema=schema)

    assert result.valid is True
    assert result.field_schema == {
        "fields": [
            {
                "key": "buyer",
                "required": True,
                "nullable": True,
                "kind": "scalar",
                "json_type": "string",
                "nuextract_type": "verbatim-string",
            },
            {
                "key": "receipt_id",
                "required": True,
                "nullable": True,
                "kind": "enum",
                "json_type": "string",
                "nuextract_type": "enum",
                "enum": ["1", "2"],
            },
        ]
    }
    assert result.json_schema == {
        "type": "object",
        "properties": {
            "buyer": {"type": ["string", "null"], "x-parsehawk": {"semantic": "verbatim-string"}},
            "receipt_id": {"type": "string", "enum": ["1", "2", None]},
        },
        "required": ["buyer", "receipt_id"],
        "additionalProperties": False,
    }
    assert result.nuextract_template == {"buyer": "verbatim-string", "receipt_id": ["1", "2"]}


def test_nuextract_template_mode_derives_canonical_schema() -> None:
    template = {
        "store": "verbatim-string",
        "date": "date-time",
        "currency": ["USD", "EUR", "Other"],
        "tags": [["urgent", "paid"]],
        "items": [{"name": "verbatim-string", "price": "number"}],
    }

    result = validate_extraction_schema(
        mode=MODE_NUEXTRACT_TEMPLATE,
        nuextract_template=template,
    )

    assert result.valid is True
    assert result.nuextract_template == template
    assert result.json_schema == {
        "type": "object",
        "properties": {
            "store": {"type": ["string", "null"], "x-parsehawk": {"semantic": "verbatim-string"}},
            "date": {"type": ["string", "null"], "x-parsehawk": {"semantic": "date-time"}},
            "currency": {"type": "string", "enum": ["USD", "EUR", "Other", None]},
            "tags": {
                "type": "array",
                "items": {"type": "string", "enum": ["urgent", "paid"]},
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": ["string", "null"],
                            "x-parsehawk": {"semantic": "verbatim-string"},
                        },
                        "price": {"type": ["number", "null"]},
                    },
                    "required": ["name", "price"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["store", "date", "currency", "tags", "items"],
        "additionalProperties": False,
    }


def test_field_schema_reports_duplicate_keys() -> None:
    result = validate_extraction_schema(
        mode=MODE_FIELD_SCHEMA,
        field_schema={
            "fields": [
                {"key": "total", "kind": "scalar", "json_type": "number"},
                {"key": "total", "kind": "scalar", "json_type": "string"},
            ]
        },
    )

    assert result.valid is False
    assert result.errors[0].code == "duplicate_field_key"


def test_schema_validation_reports_missing_and_unsupported_modes() -> None:
    assert validate_extraction_schema(mode=MODE_JSON_SCHEMA).errors[0].code == "missing_json_schema"
    assert (
        validate_extraction_schema(mode=MODE_FIELD_SCHEMA).errors[0].code == "missing_field_schema"
    )
    assert (
        validate_extraction_schema(mode=MODE_NUEXTRACT_TEMPLATE).errors[0].code
        == "missing_nuextract_template"
    )
    assert validate_extraction_schema(mode="other").errors[0].code == "unsupported_mode"


def test_validate_field_schema_reports_shape_errors() -> None:
    assert validate_field_schema({})[0].code == "invalid_field_schema"

    errors = validate_field_schema(
        {
            "fields": [
                "bad",
                {"key": "", "kind": "scalar", "json_type": "string"},
                {"key": "kind", "kind": "mystery"},
                {"key": "object", "kind": "object"},
                {"key": "array", "kind": "array"},
                {"key": "enum", "kind": "enum", "enum": []},
                {"key": "bad_enum", "kind": "enum", "enum": ["ok", ""]},
                {"key": "bad_scalar", "kind": "scalar", "json_type": "array"},
            ]
        }
    )

    assert {error.code for error in errors} >= {
        "invalid_field",
        "missing_field_key",
        "unsupported_field_kind",
        "missing_child_fields",
        "missing_array_items",
        "missing_enum_choices",
        "invalid_enum_choice",
        "invalid_json_type",
    }


def test_validate_field_schema_reports_invalid_string_constraints() -> None:
    errors = validate_field_schema(
        {
            "fields": [
                {
                    "key": "invoice_number",
                    "kind": "scalar",
                    "json_type": "string",
                    "pattern": 123,
                    "minLength": -1,
                }
            ]
        }
    )

    assert {error.code for error in errors} == {"invalid_pattern", "invalid_minLength"}

    semantic_errors = validate_field_schema(
        {
            "fields": [
                {
                    "key": "invoice_number",
                    "kind": "scalar",
                    "json_type": "string",
                    "nuextract_type": "verbatim-string",
                    "pattern": "^INV-",
                },
                {
                    "key": "email",
                    "kind": "scalar",
                    "json_type": "string",
                    "format": "email",
                },
            ]
        }
    )

    assert [error.code for error in semantic_errors] == [
        "unsupported_string_constraint",
        "unsupported_string_constraint",
    ]

    bounds_errors = validate_field_schema(
        {
            "fields": [
                {
                    "key": "code",
                    "kind": "scalar",
                    "json_type": "string",
                    "minLength": 5,
                    "maxLength": 3,
                },
                {
                    "key": "amount",
                    "kind": "scalar",
                    "json_type": "number",
                    "pattern": "^\\d+$",
                },
            ]
        }
    )

    assert {error.code for error in bounds_errors} == {
        "invalid_string_length_bounds",
        "unsupported_string_constraint",
    }


def test_json_schema_mode_accepts_builder_equivalent_schema_subset() -> None:
    result = validate_extraction_schema(
        mode=MODE_JSON_SCHEMA,
        json_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": "Invoice document",
            "properties": {
                "vendor_account": {
                    "type": "string",
                    "description": "Exactly 10 digits",
                    "pattern": "^\\d{10}$",
                    "minLength": 10,
                    "maxLength": 10,
                },
                "invoice_number": {
                    "type": ["string", "null"],
                    "x-parsehawk": {"semantic": "verbatim-string"},
                },
                "status": {
                    "oneOf": [
                        {"const": "open", "title": "Open"},
                        {"const": "closed", "title": "Closed"},
                        {"type": "null"},
                    ]
                },
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["vendor_account", "invoice_number", "status", "tags"],
            "additionalProperties": False,
        },
    )

    assert result.valid is True
    assert result.json_schema == {
        "type": "object",
        "properties": {
            "vendor_account": {
                "type": "string",
                "description": "Exactly 10 digits",
                "pattern": "^\\d{10}$",
                "minLength": 10,
                "maxLength": 10,
            },
            "invoice_number": {
                "type": ["string", "null"],
                "x-parsehawk": {"semantic": "verbatim-string"},
            },
            "status": {"type": "string", "enum": ["open", "closed", None]},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["vendor_account", "invoice_number", "status", "tags"],
        "additionalProperties": False,
    }


def test_json_schema_mode_accepts_all_nuextract_semantic_types() -> None:
    properties: dict[str, dict[str, Any]] = {}
    for nuextract_type in NUEXTRACT_TYPES:
        key = nuextract_type.replace(":", "_").replace("-", "_")
        if nuextract_type in {"string", "integer", "number", "boolean"}:
            properties[key] = {"type": nuextract_type}
        else:
            properties[key] = {
                "type": "string",
                "x-parsehawk": {"semantic": nuextract_type},
            }

    result = validate_extraction_schema(
        mode=MODE_JSON_SCHEMA,
        json_schema={
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    )

    assert result.valid is True
    assert result.errors == []


def test_parsehawk_extraction_schema_dialect_documents_supported_semantics() -> None:
    dialect = json.loads(
        (REPO_ROOT / "docs/schemas/parsehawk-extraction-schema.schema.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator.check_schema(dialect)
    semantic_enum = dialect["$defs"]["parsehawkExtension"]["properties"]["semantic"]["enum"]
    assert tuple(semantic_enum) == NUEXTRACT_TYPES

    Draft202012Validator(dialect).validate(
        {
            "type": "object",
            "properties": {
                "invoice_number": {
                    "type": ["string", "null"],
                    "x-parsehawk": {"semantic": "verbatim-string"},
                },
                "duration": {
                    "type": "string",
                    "x-parsehawk": {"semantic": "duration"},
                },
                "state": {
                    "type": "string",
                    "x-parsehawk": {"semantic": "region:US"},
                },
                "account_number": {
                    "type": "string",
                    "pattern": "^\\d{10}$",
                    "minLength": 10,
                    "maxLength": 10,
                },
                "total": {"type": "number"},
            },
            "required": ["invoice_number", "duration", "state", "account_number", "total"],
            "additionalProperties": False,
        }
    )


def test_json_schema_mode_rejects_non_builder_schema_features() -> None:
    unsupported_cases = [
        (
            {
                "type": "object",
                "properties": {"age": {"type": "integer", "minimum": 18}},
                "additionalProperties": False,
            },
            "unsupported_json_schema_keyword",
        ),
        (
            {
                "type": "object",
                "properties": {"email": {"type": "string", "format": "email"}},
                "additionalProperties": False,
            },
            "unsupported_json_schema_keyword",
        ),
        (
            {
                "type": "object",
                "properties": {
                    "invoice_number": {
                        "type": "string",
                        "x-parsehawk": {"semantic": "verbatim-string"},
                        "pattern": "^INV-",
                    }
                },
                "additionalProperties": False,
            },
            "unsupported_string_constraint",
        ),
        (
            {
                "type": "object",
                "properties": {"mixed": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
                "additionalProperties": False,
            },
            "unsupported_json_schema_union",
        ),
        (
            {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["missing"],
                "additionalProperties": False,
            },
            "invalid_json_schema_required",
        ),
        (
            {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "additionalProperties": True,
            },
            "unsupported_json_schema_keyword",
        ),
    ]

    for schema, expected_code in unsupported_cases:
        result = validate_extraction_schema(mode=MODE_JSON_SCHEMA, json_schema=schema)
        assert result.valid is False
        assert expected_code in {error.code for error in result.errors}


def test_authoring_json_schema_validator_reports_malformed_subset_nodes() -> None:
    cases: list[tuple[dict[str, Any], set[str]]] = [
        (
            {"type": "object", "properties": {"name": {"type": ["string", "integer"]}}},
            {"unsupported_json_schema_union"},
        ),
        (
            {"type": "object", "properties": {"status": {"type": "integer", "enum": ["open"]}}},
            {"unsupported_json_schema_keyword"},
        ),
        ({"type": "string"}, {"unsupported_json_schema_root"}),
        (
            {"type": "object", "properties": {"node": {"type": "null"}}},
            {"missing_json_schema_type"},
        ),
        (
            {"type": "object", "properties": {"node": {"type": "date"}}},
            {"unsupported_json_schema_type"},
        ),
        (
            {"type": "object", "properties": {"node": {}}},
            {"missing_json_schema_type"},
        ),
        (
            {"type": "object", "properties": {"node": {"type": "string", "$schema": "x"}}},
            {"unsupported_json_schema_keyword"},
        ),
        ({"type": "object", "properties": []}, {"invalid_json_schema_properties"}),
        (
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": "name"},
            {"invalid_json_schema_required"},
        ),
        ({"type": "object", "properties": {"name": []}}, {"invalid_json_schema_property"}),
        (
            {"type": "object", "properties": {"codes": {"type": "array"}}},
            {"invalid_json_schema_items"},
        ),
        (
            {"type": "object", "properties": {"codes": {"type": "array", "pattern": "^A"}}},
            {"unsupported_string_constraint", "invalid_json_schema_items"},
        ),
        (
            {
                "type": "object",
                "properties": {
                    "maybe": {
                        "anyOf": [{"type": "string"}],
                        "type": "string",
                    }
                },
            },
            {"unsupported_json_schema_union"},
        ),
        (
            {"type": "object", "properties": {"maybe": {"anyOf": []}}},
            {"invalid_json_schema_union"},
        ),
        (
            {"type": "object", "properties": {"maybe": {"anyOf": ["bad"]}}},
            {"invalid_json_schema_union"},
        ),
        (
            {"type": "object", "properties": {"maybe": {"anyOf": [{"type": "null"}]}}},
            {"unsupported_json_schema_union"},
        ),
        (
            {
                "type": "object",
                "properties": {
                    "maybe": {"anyOf": [{"type": "string"}, {"type": "null", "default": None}]}
                },
            },
            {"unsupported_json_schema_union"},
        ),
        (
            {
                "type": "object",
                "properties": {
                    "maybe": {"anyOf": [{"type": "string"}], "oneOf": [{"type": "null"}]}
                },
            },
            {"unsupported_json_schema_union"},
        ),
        (
            {
                "type": "object",
                "properties": {
                    "maybe": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
            },
            set(),
        ),
        (
            {"type": "object", "properties": {"code": {"type": "string", "pattern": 123}}},
            {"invalid_pattern"},
        ),
        (
            {"type": "object", "properties": {"code": {"type": "string", "minLength": -1}}},
            {"invalid_minLength"},
        ),
        (
            {
                "type": "object",
                "properties": {"code": {"type": "string", "minLength": 5, "maxLength": 3}},
            },
            {"invalid_string_length_bounds"},
        ),
        (
            {"type": "object", "properties": {"status": {"type": "string", "enum": []}}},
            {"invalid_json_schema_enum"},
        ),
        (
            {"type": "object", "properties": {"status": {"type": "string", "enum": [1]}}},
            {"invalid_json_schema_enum"},
        ),
        (
            {"type": "object", "properties": {"name": {"type": ["string", 1]}}},
            {"invalid_json_schema_type"},
        ),
        (
            {"type": "object", "properties": {"name": {"type": {"const": "string"}}}},
            {"invalid_json_schema_type"},
        ),
        (
            {"type": "object", "properties": {"name": {"type": "string", "x-parsehawk": []}}},
            {"invalid_parsehawk_extension"},
        ),
        (
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "x-parsehawk": {"semantic": "verbatim-string", "extra": True},
                    }
                },
            },
            {"invalid_parsehawk_extension"},
        ),
        (
            {"type": "object", "properties": {"name": {"type": "string", "x-parsehawk": {}}}},
            {"unsupported_semantic_type"},
        ),
        (
            {"type": "object", "properties": {"status": {"oneOf": [{"const": 1}]}}},
            {"unsupported_json_schema_union"},
        ),
        (
            {"type": "object", "properties": {"status": {"oneOf": [{"enum": [1]}]}}},
            {"unsupported_json_schema_union"},
        ),
        (
            {"type": "object", "properties": {"status": {"oneOf": [{"title": "missing"}]}}},
            {"unsupported_json_schema_union"},
        ),
    ]

    for schema, expected_codes in cases:
        errors = validate_authoring_json_schema(schema)
        assert {error.code for error in errors} == expected_codes

    assert validate_authoring_json_schema(cast(dict[str, Any], []))[0].code == (
        "invalid_authoring_schema"
    )


def test_validate_field_schema_reports_array_item_errors() -> None:
    errors = validate_field_schema(
        {
            "fields": [
                {"key": "object_items", "kind": "array", "items": {"kind": "object"}},
                {"key": "nested", "kind": "array", "items": {"kind": "array"}},
                {"key": "enum_items", "kind": "array", "items": {"kind": "enum", "enum": []}},
                {
                    "key": "bad_scalar_items",
                    "kind": "array",
                    "items": {"kind": "scalar", "json_type": "array"},
                },
            ]
        }
    )

    assert {error.code for error in errors} >= {
        "missing_child_fields",
        "unsupported_nested_array",
        "missing_enum_choices",
        "invalid_json_type",
    }


def test_field_schema_derives_objects_and_array_item_variants() -> None:
    field_schema = {
        "fields": [
            {
                "key": "customer",
                "kind": "object",
                "json_type": "object",
                "nuextract_type": "object",
                "required": False,
                "nullable": True,
                "fields": [
                    {
                        "key": "name",
                        "kind": "scalar",
                        "json_type": "string",
                        "required": True,
                        "nullable": False,
                    }
                ],
            },
            {
                "key": "tags",
                "kind": "array",
                "json_type": "array",
                "nuextract_type": "array",
                "required": False,
                "nullable": False,
                "items": {"kind": "enum", "enum": ["a", "b"]},
            },
            {
                "key": "notes",
                "kind": "array",
                "json_type": "array",
                "nuextract_type": "array",
                "required": False,
                "nullable": False,
                "items": {"kind": "scalar", "json_type": "string"},
            },
            {
                "key": "fallback",
                "kind": "scalar",
                "json_type": "string",
                "required": False,
                "nullable": True,
            },
        ]
    }

    assert json_schema_from_field_schema(field_schema)["properties"] == {
        "customer": {
            "type": ["object", "null"],
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        "tags": {"type": "array", "items": {"type": "string", "enum": ["a", "b"]}},
        "notes": {"type": "array", "items": {"type": "string"}},
        "fallback": {"type": ["string", "null"]},
    }
    assert nuextract_template_from_field_schema(field_schema) == {
        "customer": {"name": "string"},
        "tags": [["a", "b"]],
        "notes": ["string"],
        "fallback": "string",
    }


def test_json_schema_import_handles_warnings_and_complex_shapes() -> None:
    warnings = []
    assert field_schema_from_json_schema({}, warnings) == {"fields": []}
    assert warnings[0].code == "missing_properties"

    imported = field_schema_from_json_schema(
        {
            "type": "object",
            "properties": {
                "profile": {
                    "type": ["object", "null"],
                    "description": "Customer profile",
                    "properties": {
                        "name": {"type": "string", "description": "Full name"},
                    },
                    "required": ["name"],
                },
                "vendor_account": {
                    "type": "string",
                    "pattern": "^\\d{10}$",
                    "minLength": 10,
                    "maxLength": 10,
                },
                "items": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"sku": {"type": "string"}}},
                },
                "labels": {"type": "array", "items": {"type": "string", "enum": ["a"]}},
                "freeform": {"type": "array"},
                "choice": {"oneOf": [{"enum": ["x"]}, {"type": "null"}]},
                "fallback": {},
            },
        }
    )

    assert imported["fields"][0]["kind"] == "object"
    assert imported["fields"][0]["description"] == "Customer profile"
    assert imported["fields"][1]["pattern"] == "^\\d{10}$"
    assert imported["fields"][1]["minLength"] == 10
    assert imported["fields"][1]["maxLength"] == 10
    assert imported["fields"][2]["items"]["kind"] == "object"
    assert imported["fields"][3]["kind"] == "multi_enum"
    assert imported["fields"][4]["items"]["nuextract_type"] == "string"
    assert imported["fields"][5]["enum"] == ["x"]
    assert imported["fields"][6]["json_type"] == "string"


def test_nuextract_template_import_handles_objects_arrays_and_invalid_roots() -> None:
    warnings = []
    assert field_schema_from_nuextract_template(cast(dict[str, Any], []), warnings) == {
        "fields": []
    }
    assert warnings[0].code == "invalid_nuextract_template"

    imported = field_schema_from_nuextract_template(
        {
            "customer": {"name": "verbatim-string"},
            "codes": ["integer"],
            "items": [{"sku": "string"}],
            "missing": None,
            "status": ["open", "closed"],
        }
    )

    assert imported["fields"][0]["kind"] == "object"
    assert imported["fields"][1]["items"]["json_type"] == "integer"
    assert imported["fields"][2]["items"]["kind"] == "object"
    assert imported["fields"][3]["nuextract_type"] == "string"
    assert imported["fields"][4]["kind"] == "enum"


def test_nuextract_template_validation_reports_invalid_imported_fields() -> None:
    result = validate_extraction_schema(
        mode=MODE_NUEXTRACT_TEMPLATE,
        nuextract_template={"status": []},
    )

    assert result.valid is False
    assert result.errors[0].code == "missing_enum_choices"


def test_json_schema_mode_reports_defensive_invalid_derived_field_schema(monkeypatch) -> None:
    monkeypatch.setattr(
        schema_module,
        "field_schema_from_json_schema",
        lambda _schema, _warnings: {"fields": "bad"},
    )

    result = schema_module.validate_extraction_schema(
        mode=MODE_JSON_SCHEMA,
        json_schema={"type": "object"},
    )

    assert result.valid is False
    assert result.errors[0].code == "invalid_field_schema"


def test_validate_field_schema_accepts_nested_object_children() -> None:
    assert (
        validate_field_schema(
            {
                "fields": [
                    {
                        "key": "customer",
                        "kind": "object",
                        "fields": [{"key": "name", "kind": "scalar", "json_type": "string"}],
                    }
                ]
            }
        )
        == []
    )


def test_field_schema_derivation_handles_defensive_array_and_numeric_fallbacks() -> None:
    schema = json_schema_from_field_schema(
        {
            "fields": [
                {
                    "key": "loose_array",
                    "kind": "array",
                    "items": "bad",
                    "required": False,
                    "nullable": True,
                },
                {
                    "key": "numeric",
                    "kind": "scalar",
                    "nuextract_type": "number",
                    "required": False,
                    "nullable": True,
                },
                {
                    "key": "default_string",
                    "kind": "scalar",
                    "required": False,
                    "nullable": True,
                },
            ]
        }
    )

    assert schema["properties"]["loose_array"] == {"type": "array", "items": {"type": "string"}}
    assert schema["properties"]["numeric"] == {"type": ["number", "null"]}
    assert schema["properties"]["default_string"] == {"type": ["string", "null"]}


def test_json_schema_import_handles_nullable_enums_numeric_types_and_unions() -> None:
    imported = field_schema_from_json_schema(
        {
            "type": "object",
            "properties": {
                "nullable_enum": {"type": "string", "enum": ["a", None]},
                "amount": {"type": "number"},
                "multi_type": {"type": ["string", "integer"]},
                "branch_enum": {"anyOf": [{"enum": ["a", "b"]}, "ignored"]},
                "branch_scalar": {"anyOf": [{"type": "string"}, "ignored"]},
                "unsupported_union": {"anyOf": [{"type": "string", "minLength": 1}]},
            },
        }
    )

    assert imported["fields"][0]["nullable"] is True
    assert imported["fields"][0]["enum"] == ["a"]
    assert imported["fields"][1]["nuextract_type"] == "number"
    assert imported["fields"][2]["json_type"] == "string"
    assert imported["fields"][3]["enum"] == ["a", "b"]
    assert imported["fields"][4]["kind"] == "scalar"
    assert imported["fields"][5]["kind"] == "scalar"


def test_json_schema_import_handles_array_scalar_items() -> None:
    imported = field_schema_from_json_schema(
        {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "integer"}},
            },
        }
    )

    assert imported["fields"][0]["items"] == {
        "kind": "scalar",
        "json_type": "integer",
        "nuextract_type": "integer",
    }
