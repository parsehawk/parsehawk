from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_KIND_EXTRACTION = "extraction"
MODE_FIELD_SCHEMA = "field_schema"
MODE_JSON_SCHEMA = "json_schema"
MODE_NUEXTRACT_TEMPLATE = "nuextract_template"

FIELD_KINDS = {"scalar", "object", "array", "enum", "multi_enum"}
JSON_TYPES = {"string", "integer", "number", "boolean", "object", "array"}
SCALAR_JSON_TYPES = {"string", "integer", "number", "boolean"}
AUTHORING_JSON_SCHEMA_KEYS = {
    "$schema",
    "additionalProperties",
    "anyOf",
    "description",
    "enum",
    "items",
    "maxLength",
    "minLength",
    "oneOf",
    "pattern",
    "properties",
    "required",
    "title",
    "type",
    "x-parsehawk",
}
NUEXTRACT_NUMERIC_TYPES = {"integer": "integer", "number": "number", "boolean": "boolean"}
NUEXTRACT_TYPES = (
    "string",
    "verbatim-string",
    "integer",
    "number",
    "boolean",
    "date",
    "time",
    "date-time",
    "duration",
    "country",
    "currency",
    "language",
    "language-tag",
    "script",
    "url",
    "email-address",
    "phone-number",
    "iban",
    "bic",
    "unit-code",
    "region:US",
    "region:FR",
    "region:IE",
    "region:GB",
    "region:IT",
    "region:ES",
    "region:DE",
    "region:PT",
    "region:CA",
    "region:MX",
    "region:BR",
    "region:AU",
    "region:JP",
    "region:KR",
)
KNOWN_NUEXTRACT_SCALARS = set(NUEXTRACT_TYPES)


@dataclass(frozen=True)
class SchemaDiagnostic:
    message: str
    code: str
    path: str = "$"


@dataclass(frozen=True)
class SchemaValidationResult:
    valid: bool
    field_schema: dict[str, Any] | None = None
    json_schema: dict[str, Any] | None = None
    nuextract_template: dict[str, Any] | None = None
    warnings: list[SchemaDiagnostic] = dataclass_field(default_factory=list)
    errors: list[SchemaDiagnostic] = dataclass_field(default_factory=list)


def validate_extraction_schema(
    *,
    mode: str,
    field_schema: dict[str, Any] | None = None,
    json_schema: dict[str, Any] | None = None,
    nuextract_template: dict[str, Any] | None = None,
) -> SchemaValidationResult:
    errors: list[SchemaDiagnostic] = []
    warnings: list[SchemaDiagnostic] = []

    if mode == MODE_JSON_SCHEMA:
        if json_schema is None:
            return _invalid("json_schema is required", "missing_json_schema")
        errors.extend(validate_json_schema(json_schema))
        if not errors:
            errors.extend(validate_authoring_json_schema(json_schema))
        if errors:
            return SchemaValidationResult(valid=False, json_schema=json_schema, errors=errors)
        field_schema = field_schema_from_json_schema(json_schema, warnings)
    elif mode == MODE_FIELD_SCHEMA:
        if field_schema is None:
            return _invalid("field_schema is required", "missing_field_schema")
        errors.extend(validate_field_schema(field_schema))
        if errors:
            return SchemaValidationResult(valid=False, field_schema=field_schema, errors=errors)
    elif mode == MODE_NUEXTRACT_TEMPLATE:
        if nuextract_template is None:
            return _invalid(
                "nuextract_template is required",
                "missing_nuextract_template",
            )
        field_schema = field_schema_from_nuextract_template(nuextract_template, warnings)
        errors.extend(validate_field_schema(field_schema))
        if errors:
            return SchemaValidationResult(
                valid=False,
                field_schema=field_schema,
                nuextract_template=nuextract_template,
                warnings=warnings,
                errors=errors,
            )
    else:
        return _invalid("unsupported mode", "unsupported_mode")

    assert field_schema is not None
    errors.extend(validate_field_schema(field_schema))
    if errors:
        return SchemaValidationResult(
            valid=False,
            field_schema=field_schema,
            json_schema=json_schema,
            nuextract_template=nuextract_template,
            warnings=warnings,
            errors=errors,
        )

    derived_json_schema = json_schema_from_field_schema(field_schema)
    derived_nuextract_template = nuextract_template_from_field_schema(field_schema)
    errors.extend(validate_json_schema(derived_json_schema))

    return SchemaValidationResult(
        valid=not errors,
        field_schema=field_schema,
        json_schema=derived_json_schema,
        nuextract_template=derived_nuextract_template,
        warnings=warnings,
        errors=errors,
    )


def validate_json_schema(schema: dict[str, Any]) -> list[SchemaDiagnostic]:
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # jsonschema raises several detailed schema exceptions.
        return [SchemaDiagnostic(message=str(exc), code="invalid_json_schema")]
    return []


def validate_authoring_json_schema(schema: dict[str, Any]) -> list[SchemaDiagnostic]:
    errors: list[SchemaDiagnostic] = []
    if not isinstance(schema, dict):
        return [
            SchemaDiagnostic(
                message="JSON Schema must be an object",
                code="invalid_authoring_schema",
            )
        ]
    _validate_authoring_json_schema_node(schema, "$", errors, root=True)
    return errors


def validate_field_schema(schema: dict[str, Any]) -> list[SchemaDiagnostic]:
    errors: list[SchemaDiagnostic] = []
    fields = schema.get("fields")
    if not isinstance(fields, list):
        return [
            SchemaDiagnostic(
                message="field_schema.fields must be a list",
                code="invalid_field_schema",
                path="$.fields",
            )
        ]
    _validate_fields(fields, "$.fields", errors)
    return errors


def json_schema_from_field_schema(field_schema: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for schema_field in _fields(field_schema):
        key = str(schema_field["key"]).strip()
        properties[key] = _json_schema_for_field(schema_field)
        if schema_field.get("required", True):
            required.append(key)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def nuextract_template_from_field_schema(field_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        str(field["key"]).strip(): _nuextract_template_for_field(field)
        for field in _fields(field_schema)
    }


def field_schema_from_json_schema(
    schema: dict[str, Any], warnings: list[SchemaDiagnostic] | None = None
) -> dict[str, Any]:
    warnings = warnings if warnings is not None else []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        warnings.append(
            SchemaDiagnostic(
                message="JSON Schema has no object properties; generated an empty field schema",
                code="missing_properties",
            )
        )
        return {"fields": []}
    required = _string_set(schema.get("required"))
    return {
        "fields": [
            _field_from_json_property(name, property_schema, required)
            for name, property_schema in properties.items()
            if isinstance(property_schema, dict)
        ]
    }


def field_schema_from_nuextract_template(
    template: dict[str, Any], warnings: list[SchemaDiagnostic] | None = None
) -> dict[str, Any]:
    warnings = warnings if warnings is not None else []
    if not isinstance(template, dict):
        warnings.append(
            SchemaDiagnostic(
                message="NuExtract template root must be an object",
                code="invalid_nuextract_template",
            )
        )
        return {"fields": []}
    return {"fields": [_field_from_template_value(key, value) for key, value in template.items()]}


def _invalid(message: str, code: str, path: str = "$") -> SchemaValidationResult:
    return SchemaValidationResult(
        valid=False,
        errors=[SchemaDiagnostic(message=message, code=code, path=path)],
    )


def _fields(schema: dict[str, Any]) -> list[dict[str, Any]]:
    fields = schema.get("fields", [])
    return [field for field in fields if isinstance(field, dict)]


def _validate_fields(fields: list[Any], path: str, errors: list[SchemaDiagnostic]) -> None:
    seen_keys: set[str] = set()
    for index, value in enumerate(fields):
        field_path = f"{path}[{index}]"
        if not isinstance(value, dict):
            errors.append(
                SchemaDiagnostic(
                    message="field must be an object",
                    code="invalid_field",
                    path=field_path,
                )
            )
            continue
        key = value.get("key")
        if not isinstance(key, str) or not key.strip():
            errors.append(
                SchemaDiagnostic(
                    message="field.key is required",
                    code="missing_field_key",
                    path=f"{field_path}.key",
                )
            )
        elif key in seen_keys:
            errors.append(
                SchemaDiagnostic(
                    message=f"duplicate field key: {key}",
                    code="duplicate_field_key",
                    path=f"{field_path}.key",
                )
            )
        else:
            seen_keys.add(key)

        kind = value.get("kind", "scalar")
        if kind not in FIELD_KINDS:
            errors.append(
                SchemaDiagnostic(
                    message=f"unsupported field kind: {kind}",
                    code="unsupported_field_kind",
                    path=f"{field_path}.kind",
                )
            )
            continue

        if kind == "object":
            child_fields = value.get("fields")
            if not isinstance(child_fields, list):
                errors.append(
                    SchemaDiagnostic(
                        message="object fields require a fields list",
                        code="missing_child_fields",
                        path=f"{field_path}.fields",
                    )
                )
            else:
                _validate_fields(child_fields, f"{field_path}.fields", errors)
        elif kind == "array":
            items = value.get("items")
            if not isinstance(items, dict):
                errors.append(
                    SchemaDiagnostic(
                        message="array fields require an items object",
                        code="missing_array_items",
                        path=f"{field_path}.items",
                    )
                )
            else:
                _validate_array_item(items, f"{field_path}.items", errors)
        elif kind in {"enum", "multi_enum"}:
            enum = value.get("enum")
            if not isinstance(enum, list) or not enum:
                errors.append(
                    SchemaDiagnostic(
                        message="enum fields require at least one choice",
                        code="missing_enum_choices",
                        path=f"{field_path}.enum",
                    )
                )
            elif any(not isinstance(choice, str) or not choice for choice in enum):
                errors.append(
                    SchemaDiagnostic(
                        message="enum choices must be non-empty strings",
                        code="invalid_enum_choice",
                        path=f"{field_path}.enum",
                    )
                )
        else:
            json_type = value.get("json_type", "string")
            if json_type not in SCALAR_JSON_TYPES:
                errors.append(
                    SchemaDiagnostic(
                        message="scalar fields require a scalar json_type",
                        code="invalid_json_type",
                        path=f"{field_path}.json_type",
                    )
                )
        _validate_string_constraints(value, field_path, errors)


def _validate_array_item(item: dict[str, Any], path: str, errors: list[SchemaDiagnostic]) -> None:
    kind = item.get("kind", "scalar")
    if kind == "object":
        child_fields = item.get("fields")
        if not isinstance(child_fields, list):
            errors.append(
                SchemaDiagnostic(
                    message="array object items require a fields list",
                    code="missing_child_fields",
                    path=f"{path}.fields",
                )
            )
        else:
            _validate_fields(child_fields, f"{path}.fields", errors)
    elif kind == "array":
        errors.append(
            SchemaDiagnostic(
                message="nested array items are not supported yet",
                code="unsupported_nested_array",
                path=path,
            )
        )
    elif kind in {"enum", "multi_enum"}:
        enum = item.get("enum")
        if not isinstance(enum, list) or not enum:
            errors.append(
                SchemaDiagnostic(
                    message="array enum items require at least one choice",
                    code="missing_enum_choices",
                    path=f"{path}.enum",
                )
            )
    else:
        json_type = item.get("json_type", "string")
        if json_type not in SCALAR_JSON_TYPES:
            errors.append(
                SchemaDiagnostic(
                    message="array scalar items require a scalar json_type",
                    code="invalid_json_type",
                    path=f"{path}.json_type",
                )
            )
    _validate_string_constraints(item, path, errors)


def _validate_string_constraints(
    field: dict[str, Any], path: str, errors: list[SchemaDiagnostic]
) -> None:
    if field.get("format") is not None:
        errors.append(
            SchemaDiagnostic(
                message="format is not part of the ParseHawk authoring schema",
                code="unsupported_string_constraint",
                path=f"{path}.format",
            )
        )
    for key in ("pattern",):
        value = field.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(
                SchemaDiagnostic(
                    message=f"{key} must be a string",
                    code=f"invalid_{key}",
                    path=f"{path}.{key}",
                )
            )
    for key in ("minLength", "maxLength"):
        value = field.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            errors.append(
                SchemaDiagnostic(
                    message=f"{key} must be a non-negative integer",
                    code=f"invalid_{key}",
                    path=f"{path}.{key}",
                )
            )
    if any(
        field.get(key) is not None for key in ("pattern", "minLength", "maxLength")
    ) and not _field_supports_text_pattern(field):
        errors.append(
            SchemaDiagnostic(
                message="text patterns are only supported for plain string fields",
                code="unsupported_string_constraint",
                path=path,
            )
        )
    min_length = field.get("minLength")
    max_length = field.get("maxLength")
    if (
        isinstance(min_length, int)
        and not isinstance(min_length, bool)
        and isinstance(max_length, int)
        and not isinstance(max_length, bool)
        and min_length > max_length
    ):
        errors.append(
            SchemaDiagnostic(
                message="minLength must be less than or equal to maxLength",
                code="invalid_string_length_bounds",
                path=path,
            )
        )


def _json_schema_for_field(field: dict[str, Any]) -> dict[str, Any]:
    kind = field.get("kind", "scalar")
    schema: dict[str, Any]
    if kind == "object":
        schema = _json_schema_for_object(field)
    elif kind == "array":
        schema = _json_schema_for_array(field)
    elif kind == "enum":
        choices = [str(choice) for choice in field.get("enum", [])]
        schema = {"type": "string", "enum": choices}
    elif kind == "multi_enum":
        choices = [str(choice) for choice in field.get("enum", [])]
        schema = {"type": "array", "items": {"type": "string", "enum": choices}}
    else:
        schema = {"type": _scalar_json_type(field)}

    description = field.get("description")
    if isinstance(description, str) and description.strip():
        schema["description"] = description.strip()
    _apply_string_constraints(schema, field)
    semantic = _semantic_from_field(field)
    if semantic is not None and semantic != schema.get("type"):
        schema["x-parsehawk"] = {"semantic": semantic}

    return _nullable_schema(schema, bool(field.get("nullable", True)))


def _apply_string_constraints(schema: dict[str, Any], field: dict[str, Any]) -> None:
    if schema.get("type") != "string" or not _field_supports_text_pattern(field):
        return
    for key in ("pattern",):
        value = field.get(key)
        if isinstance(value, str) and value.strip():
            schema[key] = value.strip()
    for key in ("minLength", "maxLength"):
        value = field.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            schema[key] = value


def _json_schema_for_object(field: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for child in _fields(field):
        key = str(child["key"]).strip()
        properties[key] = _json_schema_for_field(child)
        if child.get("required", True):
            required.append(key)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _json_schema_for_array(field: dict[str, Any]) -> dict[str, Any]:
    item = field.get("items")
    if not isinstance(item, dict):
        item_schema: dict[str, Any] = {"type": "string"}
    elif item.get("kind") == "object":
        item_schema = _json_schema_for_object(item)
    elif item.get("kind") == "enum":
        choices = [str(choice) for choice in item.get("enum", [])]
        item_schema = {"type": "string", "enum": choices}
    else:
        item_schema = _json_schema_for_field({**item, "nullable": False})
    return {"type": "array", "items": item_schema}


def _scalar_json_type(field: dict[str, Any]) -> str:
    json_type = field.get("json_type")
    if json_type in SCALAR_JSON_TYPES:
        return str(json_type)
    nuextract_type = field.get("nuextract_type")
    if isinstance(nuextract_type, str) and nuextract_type in NUEXTRACT_NUMERIC_TYPES:
        return NUEXTRACT_NUMERIC_TYPES[nuextract_type]
    return "string"


def _nullable_schema(schema: dict[str, Any], nullable: bool) -> dict[str, Any]:
    if not nullable:
        return schema
    if ArrayAware.is_array(schema):
        return schema
    if isinstance(schema.get("enum"), list):
        enum = schema["enum"]
        return {**schema, "enum": [*enum, None] if None not in enum else enum}
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return {**schema, "type": [schema_type, "null"]}
    return schema  # pragma: no cover - defensive fallback for malformed derived schemas.


class ArrayAware:
    @staticmethod
    def is_array(schema: dict[str, Any]) -> bool:
        return schema.get("type") == "array"


def _nuextract_template_for_field(field: dict[str, Any]) -> Any:
    kind = field.get("kind", "scalar")
    if kind == "object":
        return {
            str(child["key"]).strip(): _nuextract_template_for_field(child)
            for child in _fields(field)
        }
    if kind == "array":
        item = field.get("items")
        return [_nuextract_template_for_field(item) if isinstance(item, dict) else "string"]
    if kind == "enum":
        return [str(choice) for choice in field.get("enum", [])]
    if kind == "multi_enum":
        return [[str(choice) for choice in field.get("enum", [])]]
    nuextract_type = field.get("nuextract_type")
    if isinstance(nuextract_type, str) and nuextract_type:
        return nuextract_type
    return _scalar_json_type(field)


def _field_from_json_property(
    key: str, schema: dict[str, Any], required: set[str]
) -> dict[str, Any]:
    nullable = _schema_allows_null(schema)
    effective_schema = _without_null(schema)
    schema_type = _schema_type(effective_schema)
    description = effective_schema.get("description")
    base: dict[str, Any] = {
        "key": key,
        "required": key in required,
        "nullable": nullable,
    }
    if isinstance(description, str) and description:
        base["description"] = description

    enum_values = _enum_values(effective_schema)
    if enum_values:
        return {
            **base,
            "kind": "enum",
            "json_type": "string",
            "nuextract_type": "enum",
            "enum": enum_values,
        }

    if schema_type == "object" or isinstance(effective_schema.get("properties"), dict):
        return {
            **base,
            "kind": "object",
            "json_type": "object",
            "nuextract_type": "object",
            "fields": field_schema_from_json_schema(effective_schema)["fields"],
        }

    if schema_type == "array":
        item_schema = effective_schema.get("items")
        if isinstance(item_schema, dict):
            item_enum = _enum_values(_without_null(item_schema))
            if item_enum:
                return {
                    **base,
                    "kind": "multi_enum",
                    "json_type": "array",
                    "nuextract_type": "multi_enum",
                    "enum": item_enum,
                    "nullable": False,
                }
            item_field = _array_item_from_json_schema(item_schema)
        else:
            item_field = {"kind": "scalar", "json_type": "string", "nuextract_type": "string"}
        return {
            **base,
            "kind": "array",
            "json_type": "array",
            "nuextract_type": "array",
            "items": item_field,
            "nullable": False,
        }

    json_type = schema_type if schema_type in SCALAR_JSON_TYPES else "string"
    return {
        **base,
        "kind": "scalar",
        "json_type": json_type,
        "nuextract_type": _nuextract_type_from_json_schema(effective_schema, json_type),
        **_string_constraints_from_json_schema(effective_schema),
    }


def _array_item_from_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    effective_schema = _without_null(schema)
    schema_type = _schema_type(effective_schema)
    if schema_type == "object" or isinstance(effective_schema.get("properties"), dict):
        return {
            "kind": "object",
            "json_type": "object",
            "nuextract_type": "object",
            "fields": field_schema_from_json_schema(effective_schema)["fields"],
        }
    return {
        "kind": "scalar",
        "json_type": schema_type if schema_type in SCALAR_JSON_TYPES else "string",
        "nuextract_type": _nuextract_type_from_json_schema(
            effective_schema,
            schema_type if schema_type in SCALAR_JSON_TYPES else "string",
        ),
        **_string_constraints_from_json_schema(effective_schema),
    }


def _string_constraints_from_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    for key in ("pattern",):
        value = schema.get(key)
        if isinstance(value, str) and value.strip():
            constraints[key] = value.strip()
    for key in ("minLength", "maxLength"):
        value = schema.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            constraints[key] = value
    return constraints


def _field_from_template_value(key: str, value: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": key,
        "required": True,
        "nullable": True,
    }
    if isinstance(value, dict):
        return {
            **base,
            "kind": "object",
            "json_type": "object",
            "nuextract_type": "object",
            "fields": [
                _field_from_template_value(child_key, child_value)
                for child_key, child_value in value.items()
            ],
        }
    if isinstance(value, list):
        if len(value) == 1 and isinstance(value[0], list):
            return {
                **base,
                "kind": "multi_enum",
                "json_type": "array",
                "nuextract_type": "multi_enum",
                "enum": [str(choice) for choice in value[0]],
                "nullable": False,
            }
        if len(value) == 1:
            return {
                **base,
                "kind": "array",
                "json_type": "array",
                "nuextract_type": "array",
                "items": _array_item_from_template_value(value[0]),
                "nullable": False,
            }
        return {
            **base,
            "kind": "enum",
            "json_type": "string",
            "nuextract_type": "enum",
            "enum": [str(choice) for choice in value],
        }
    nuextract_type = str(value) if value is not None else "string"
    return {
        **base,
        "kind": "scalar",
        "json_type": _json_type_from_nuextract_type(nuextract_type),
        "nuextract_type": nuextract_type,
    }


def _array_item_from_template_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "kind": "object",
            "json_type": "object",
            "nuextract_type": "object",
            "fields": [
                _field_from_template_value(child_key, child_value)
                for child_key, child_value in value.items()
            ],
        }
    nuextract_type = str(value) if value is not None else "string"
    return {
        "kind": "scalar",
        "json_type": _json_type_from_nuextract_type(nuextract_type),
        "nuextract_type": nuextract_type,
    }


def _json_type_from_nuextract_type(nuextract_type: str) -> str:
    if nuextract_type in NUEXTRACT_NUMERIC_TYPES:
        return NUEXTRACT_NUMERIC_TYPES[nuextract_type]
    return "string"


def _nuextract_type_from_json_schema(schema: dict[str, Any], json_type: str) -> str:
    parsehawk_extension = schema.get("x-parsehawk")
    if isinstance(parsehawk_extension, dict):
        semantic = parsehawk_extension.get("semantic")
        if isinstance(semantic, str) and semantic:
            return semantic
    if json_type in NUEXTRACT_NUMERIC_TYPES:
        return json_type
    return "string"


def _semantic_from_field(field: dict[str, Any]) -> str | None:
    if field.get("kind", "scalar") != "scalar":
        return None
    nuextract_type = field.get("nuextract_type")
    if not isinstance(nuextract_type, str) or not nuextract_type:
        return None
    return nuextract_type


def _field_supports_text_pattern(field: dict[str, Any]) -> bool:
    if field.get("kind", "scalar") != "scalar":
        return False
    if _scalar_json_type(field) != "string":
        return False
    semantic = _semantic_from_field(field)
    return semantic in (None, "string")


def _validate_authoring_json_schema_node(
    schema: dict[str, Any],
    path: str,
    errors: list[SchemaDiagnostic],
    *,
    root: bool = False,
) -> None:
    _validate_authoring_supported_keywords(schema, path, errors, root=root)
    union_key = _authoring_union_key(schema)
    if union_key is not None:
        _validate_authoring_union_schema(schema, path, errors, union_key=union_key, root=root)
        return

    error_count = len(errors)
    schema_types = _authoring_schema_types(schema, path, errors)
    if len(errors) > error_count:
        return
    non_null_types = [schema_type for schema_type in schema_types if schema_type != "null"]
    schema_type = non_null_types[0] if non_null_types else None
    if len(non_null_types) > 1:
        errors.append(
            SchemaDiagnostic(
                message="JSON Schema type arrays may only add nullability",
                code="unsupported_json_schema_union",
                path=f"{path}.type",
            )
        )
        return

    enum_values = schema.get("enum")
    if enum_values is not None:
        _validate_authoring_enum(enum_values, path, errors)
        if schema_type not in (None, "string"):
            errors.append(
                SchemaDiagnostic(
                    message="enum fields must use string values",
                    code="unsupported_json_schema_keyword",
                    path=path,
                )
            )
        schema_type = "string"

    if root and schema_type != "object":
        errors.append(
            SchemaDiagnostic(
                message="root JSON Schema must be an object schema",
                code="unsupported_json_schema_root",
                path=path,
            )
        )
        return

    if schema_type == "object" or isinstance(schema.get("properties"), dict):
        _validate_authoring_object_schema(schema, path, errors)
    elif schema_type == "array":
        _validate_authoring_array_schema(schema, path, errors)
    elif schema_type in SCALAR_JSON_TYPES:
        _validate_authoring_scalar_schema(schema, path, errors, schema_type)
    elif schema_type is None:
        errors.append(
            SchemaDiagnostic(
                message="JSON Schema nodes must declare a supported type",
                code="missing_json_schema_type",
                path=f"{path}.type",
            )
        )
    else:
        errors.append(
            SchemaDiagnostic(
                message=f"unsupported JSON Schema type: {schema_type}",
                code="unsupported_json_schema_type",
                path=f"{path}.type",
            )
        )


def _validate_authoring_supported_keywords(
    schema: dict[str, Any],
    path: str,
    errors: list[SchemaDiagnostic],
    *,
    root: bool,
) -> None:
    for key in schema:
        if key == "$schema" and not root:
            errors.append(
                SchemaDiagnostic(
                    message="$schema is only supported at the root",
                    code="unsupported_json_schema_keyword",
                    path=f"{path}.{key}",
                )
            )
        elif key not in AUTHORING_JSON_SCHEMA_KEYS:
            errors.append(
                SchemaDiagnostic(
                    message=f"{key} is not part of the ParseHawk authoring schema",
                    code="unsupported_json_schema_keyword",
                    path=f"{path}.{key}",
                )
            )


def _validate_authoring_object_schema(
    schema: dict[str, Any], path: str, errors: list[SchemaDiagnostic]
) -> None:
    _reject_authoring_string_constraints(schema, path, errors)
    properties = schema.get("properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        errors.append(
            SchemaDiagnostic(
                message="object schemas require a properties object",
                code="invalid_json_schema_properties",
                path=f"{path}.properties",
            )
        )
        return
    additional_properties = schema.get("additionalProperties")
    if additional_properties is not None and additional_properties is not False:
        errors.append(
            SchemaDiagnostic(
                message="ParseHawk schemas must set additionalProperties to false",
                code="unsupported_json_schema_keyword",
                path=f"{path}.additionalProperties",
            )
        )
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(key, str) for key in required):
        errors.append(
            SchemaDiagnostic(
                message="required must be a list of field names",
                code="invalid_json_schema_required",
                path=f"{path}.required",
            )
        )
    else:
        unknown_required = sorted(set(required) - set(properties))
        if unknown_required:
            errors.append(
                SchemaDiagnostic(
                    message=f"required references unknown properties: {', '.join(unknown_required)}",
                    code="invalid_json_schema_required",
                    path=f"{path}.required",
                )
            )
    for key, value in properties.items():
        property_path = f"{path}.properties.{key}"
        if not isinstance(value, dict):
            errors.append(
                SchemaDiagnostic(
                    message="property schemas must be objects",
                    code="invalid_json_schema_property",
                    path=property_path,
                )
            )
            continue
        _validate_authoring_json_schema_node(value, property_path, errors)


def _validate_authoring_array_schema(
    schema: dict[str, Any], path: str, errors: list[SchemaDiagnostic]
) -> None:
    _reject_authoring_string_constraints(schema, path, errors)
    items = schema.get("items")
    if not isinstance(items, dict):
        errors.append(
            SchemaDiagnostic(
                message="array schemas require a single items schema object",
                code="invalid_json_schema_items",
                path=f"{path}.items",
            )
        )
        return
    _validate_authoring_json_schema_node(items, f"{path}.items", errors)


def _validate_authoring_scalar_schema(
    schema: dict[str, Any],
    path: str,
    errors: list[SchemaDiagnostic],
    schema_type: str,
) -> None:
    semantic = _authoring_semantic(schema, path, errors)
    if schema_type != "string":
        _reject_authoring_string_constraints(schema, path, errors)
        return
    _validate_authoring_string_constraints(
        schema,
        path,
        errors,
        supports_patterns=schema.get("enum") is None and semantic in (None, "string"),
    )


def _validate_authoring_union_schema(
    schema: dict[str, Any],
    path: str,
    errors: list[SchemaDiagnostic],
    *,
    union_key: str,
    root: bool,
) -> None:
    if "anyOf" in schema and "oneOf" in schema:
        errors.append(
            SchemaDiagnostic(
                message="schemas may use anyOf or oneOf, not both",
                code="unsupported_json_schema_union",
                path=path,
            )
        )
        return
    if any(key in schema for key in ("type", "enum", "properties", "items")):
        errors.append(
            SchemaDiagnostic(
                message="union schemas cannot be mixed with type, enum, properties, or items",
                code="unsupported_json_schema_union",
                path=path,
            )
        )
        return
    branches = schema.get(union_key)
    if not isinstance(branches, list) or not branches:
        errors.append(
            SchemaDiagnostic(
                message=f"{union_key} must be a non-empty list",
                code="invalid_json_schema_union",
                path=f"{path}.{union_key}",
            )
        )
        return
    if any(not isinstance(branch, dict) for branch in branches):
        errors.append(
            SchemaDiagnostic(
                message=f"{union_key} branches must be schema objects",
                code="invalid_json_schema_union",
                path=f"{path}.{union_key}",
            )
        )
        return
    dict_branches = [branch for branch in branches if isinstance(branch, dict)]
    for branch in dict_branches:
        if _authoring_is_null_schema(branch) and set(branch) - {"description", "title", "type"}:
            errors.append(
                SchemaDiagnostic(
                    message="null union branches may only include metadata",
                    code="unsupported_json_schema_union",
                    path=f"{path}.{union_key}",
                )
            )
            return
    non_null_branches = [
        branch for branch in dict_branches if not _authoring_is_null_schema(branch)
    ]
    if _authoring_const_enum_branches(non_null_branches):
        return
    if len(non_null_branches) == 1 and len(non_null_branches) < len(dict_branches):
        _validate_authoring_json_schema_node(
            non_null_branches[0],
            f"{path}.{union_key}[0]",
            errors,
            root=root,
        )
        return
    errors.append(
        SchemaDiagnostic(
            message="JSON Schema unions may only express nullability or enum choices",
            code="unsupported_json_schema_union",
            path=f"{path}.{union_key}",
        )
    )


def _validate_authoring_string_constraints(
    schema: dict[str, Any],
    path: str,
    errors: list[SchemaDiagnostic],
    *,
    supports_patterns: bool,
) -> None:
    for key in ("pattern",):
        value = schema.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(
                SchemaDiagnostic(
                    message=f"{key} must be a string",
                    code=f"invalid_{key}",
                    path=f"{path}.{key}",
                )
            )
    for key in ("minLength", "maxLength"):
        value = schema.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            errors.append(
                SchemaDiagnostic(
                    message=f"{key} must be a non-negative integer",
                    code=f"invalid_{key}",
                    path=f"{path}.{key}",
                )
            )
    if any(schema.get(key) is not None for key in ("pattern", "minLength", "maxLength")):
        if not supports_patterns:
            errors.append(
                SchemaDiagnostic(
                    message="text patterns are only supported for plain string fields",
                    code="unsupported_string_constraint",
                    path=path,
                )
            )
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if (
            isinstance(min_length, int)
            and not isinstance(min_length, bool)
            and isinstance(max_length, int)
            and not isinstance(max_length, bool)
            and min_length > max_length
        ):
            errors.append(
                SchemaDiagnostic(
                    message="minLength must be less than or equal to maxLength",
                    code="invalid_string_length_bounds",
                    path=path,
                )
            )


def _reject_authoring_string_constraints(
    schema: dict[str, Any], path: str, errors: list[SchemaDiagnostic]
) -> None:
    if any(schema.get(key) is not None for key in ("pattern", "minLength", "maxLength")):
        errors.append(
            SchemaDiagnostic(
                message="text patterns are only supported for plain string fields",
                code="unsupported_string_constraint",
                path=path,
            )
        )


def _validate_authoring_enum(enum_values: Any, path: str, errors: list[SchemaDiagnostic]) -> None:
    if not isinstance(enum_values, list) or not enum_values:
        errors.append(
            SchemaDiagnostic(
                message="enum must contain at least one choice",
                code="invalid_json_schema_enum",
                path=f"{path}.enum",
            )
        )
        return
    if any(value is not None and not isinstance(value, str) for value in enum_values):
        errors.append(
            SchemaDiagnostic(
                message="ParseHawk enum choices must be strings",
                code="invalid_json_schema_enum",
                path=f"{path}.enum",
            )
        )


def _authoring_schema_types(
    schema: dict[str, Any], path: str, errors: list[SchemaDiagnostic]
) -> list[str]:
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return [schema_type]
    if isinstance(schema_type, list):
        if any(not isinstance(value, str) for value in schema_type):
            errors.append(
                SchemaDiagnostic(
                    message="type arrays must contain strings",
                    code="invalid_json_schema_type",
                    path=f"{path}.type",
                )
            )
            return []
        return schema_type
    if schema_type is None:
        return []
    errors.append(
        SchemaDiagnostic(
            message="type must be a string or nullable type array",
            code="invalid_json_schema_type",
            path=f"{path}.type",
        )
    )
    return []


def _authoring_semantic(
    schema: dict[str, Any], path: str, errors: list[SchemaDiagnostic]
) -> str | None:
    parsehawk_extension = schema.get("x-parsehawk")
    if parsehawk_extension is None:
        return None
    if not isinstance(parsehawk_extension, dict):
        errors.append(
            SchemaDiagnostic(
                message="x-parsehawk must be an object",
                code="invalid_parsehawk_extension",
                path=f"{path}.x-parsehawk",
            )
        )
        return None
    unsupported_keys = set(parsehawk_extension) - {"semantic"}
    if unsupported_keys:
        errors.append(
            SchemaDiagnostic(
                message=f"unsupported x-parsehawk keys: {', '.join(sorted(unsupported_keys))}",
                code="invalid_parsehawk_extension",
                path=f"{path}.x-parsehawk",
            )
        )
    semantic = parsehawk_extension.get("semantic")
    if not isinstance(semantic, str) or semantic not in KNOWN_NUEXTRACT_SCALARS:
        errors.append(
            SchemaDiagnostic(
                message="x-parsehawk.semantic must be a supported semantic type",
                code="unsupported_semantic_type",
                path=f"{path}.x-parsehawk.semantic",
            )
        )
        return None
    return semantic


def _authoring_union_key(schema: dict[str, Any]) -> str | None:
    if "anyOf" in schema and "oneOf" in schema:
        return "anyOf"
    if "anyOf" in schema:
        return "anyOf"
    if "oneOf" in schema:
        return "oneOf"
    return None


def _authoring_is_null_schema(schema: dict[str, Any]) -> bool:
    return schema.get("type") == "null"


def _authoring_const_enum_branches(branches: list[dict[str, Any]]) -> bool:
    if not branches:
        return False
    for branch in branches:
        allowed_keys = {"const", "description", "enum", "title"}
        if set(branch) - allowed_keys:
            return False
        if "const" in branch:
            if not isinstance(branch["const"], str):
                return False
        elif "enum" in branch:
            enum = branch["enum"]
            if not isinstance(enum, list) or any(
                value is not None and not isinstance(value, str) for value in enum
            ):
                return False
        else:
            return False
    return True


def _schema_allows_null(schema: dict[str, Any]) -> bool:
    schema_type = schema.get("type")
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    if isinstance(schema.get("enum"), list) and None in schema["enum"]:
        return True
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if isinstance(branches, list) and any(
            isinstance(branch, dict) and branch.get("type") == "null" for branch in branches
        ):
            return True
    return False


def _without_null(schema: dict[str, Any]) -> dict[str, Any]:
    next_schema = dict(schema)
    schema_type = next_schema.get("type")
    if isinstance(schema_type, list):
        non_null_types = [value for value in schema_type if value != "null"]
        next_schema["type"] = non_null_types[0] if len(non_null_types) == 1 else non_null_types
    if isinstance(next_schema.get("enum"), list):
        next_schema["enum"] = [value for value in next_schema["enum"] if value is not None]
    for key in ("anyOf", "oneOf"):
        branches = next_schema.get(key)
        if isinstance(branches, list):
            meaningful = [
                branch
                for branch in branches
                if not (isinstance(branch, dict) and branch.get("type") == "null")
            ]
            if len(meaningful) == 1 and isinstance(meaningful[0], dict):
                merged = dict(meaningful[0])
                merged.update({k: v for k, v in next_schema.items() if k not in {key}})
                return merged
            next_schema[key] = meaningful
    return next_schema


def _schema_type(schema: dict[str, Any]) -> str | None:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return next((value for value in schema_type if isinstance(value, str)), None)
    if isinstance(schema_type, str):
        return schema_type
    return None


def _enum_values(schema: dict[str, Any]) -> list[str]:
    enum = schema.get("enum")
    if isinstance(enum, list):
        return [str(value) for value in enum if value is not None]
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if not isinstance(branches, list):
            continue
        values: list[str] = []
        for branch in branches:
            if not isinstance(branch, dict) or branch.get("type") == "null":
                continue
            if "const" in branch and branch["const"] is not None:
                values.append(str(branch["const"]))
            elif isinstance(branch.get("enum"), list):
                values.extend(str(value) for value in branch["enum"] if value is not None)
            else:
                return []
        if values:
            return values
    return []


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}
