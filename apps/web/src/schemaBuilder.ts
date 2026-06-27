export const nuextractTypeOptions = [
  {
    value: "string",
    group: "Base",
    description: "General text that may be inferred or normalized.",
    examples: "Hello World"
  },
  {
    value: "verbatim-string",
    group: "Base",
    description: "Extractive text copied from the input, with whitespace normalized.",
    examples: "John Doe"
  },
  { value: "integer", group: "Base", description: "Whole number.", examples: "12" },
  { value: "number", group: "Base", description: "Integer or floating-point number.", examples: "3.14" },
  { value: "boolean", group: "Base", description: "Logical true or false value.", examples: "true" },
  { value: "date", group: "Date and time", description: "ISO 8601 date.", examples: "2024-01-15" },
  { value: "time", group: "Date and time", description: "ISO 8601 time.", examples: "14:30:57" },
  {
    value: "date-time",
    group: "Date and time",
    description: "ISO 8601 combined date and time.",
    examples: "2024-03-14T14:45:00"
  },
  {
    value: "duration",
    group: "Date and time",
    description: "ISO 8601 duration.",
    examples: "P2Y1M3D"
  },
  {
    value: "country",
    group: "Locale and codes",
    description: "Uppercase ISO 3166-1 alpha-2 country code.",
    examples: "FR"
  },
  {
    value: "currency",
    group: "Locale and codes",
    description: "Uppercase ISO 4217 currency code.",
    examples: "EUR"
  },
  {
    value: "language",
    group: "Locale and codes",
    description: "Lowercase ISO 639-3 language code.",
    examples: "eng"
  },
  {
    value: "language-tag",
    group: "Locale and codes",
    description: "IETF BCP 47 / RFC 5646 language tag.",
    examples: "en-US"
  },
  {
    value: "script",
    group: "Locale and codes",
    description: "Titlecase ISO 15924 script code.",
    examples: "Latn"
  },
  {
    value: "unit-code",
    group: "Locale and codes",
    description: "UCUM unit code.",
    examples: "kg"
  },
  { value: "url", group: "Contact and identifiers", description: "RFC 3987 IRI.", examples: "https://example.com/path" },
  {
    value: "email-address",
    group: "Contact and identifiers",
    description: "RFC 5322/6531 email address.",
    examples: "firstname.lastname@example.com"
  },
  {
    value: "phone-number",
    group: "Contact and identifiers",
    description: "E.164 number when region is known, otherwise raw digits.",
    examples: "+33612345678"
  },
  {
    value: "iban",
    group: "Contact and identifiers",
    description: "ISO 13616-1 International Bank Account Number.",
    examples: "DE89370400440532013000"
  },
  {
    value: "bic",
    group: "Contact and identifiers",
    description: "ISO 9362 Business Identifier Code.",
    examples: "BNPAFRPPXXX"
  },
  { value: "region:US", group: "Regions", description: "ISO 3166-2:US subdivision code.", examples: "NY" },
  { value: "region:FR", group: "Regions", description: "ISO 3166-2:FR subdivision code.", examples: "49" },
  { value: "region:IE", group: "Regions", description: "ISO 3166-2:IE subdivision code.", examples: "D" },
  { value: "region:GB", group: "Regions", description: "ISO 3166-2:GB subdivision code.", examples: "WSX" },
  { value: "region:IT", group: "Regions", description: "ISO 3166-2:IT subdivision code.", examples: "RM" },
  { value: "region:ES", group: "Regions", description: "ISO 3166-2:ES subdivision code.", examples: "GA" },
  { value: "region:DE", group: "Regions", description: "ISO 3166-2:DE subdivision code.", examples: "BY" },
  { value: "region:PT", group: "Regions", description: "ISO 3166-2:PT subdivision code.", examples: "11" },
  { value: "region:CA", group: "Regions", description: "ISO 3166-2:CA subdivision code.", examples: "QC" },
  { value: "region:MX", group: "Regions", description: "ISO 3166-2:MX subdivision code.", examples: "JAL" },
  { value: "region:BR", group: "Regions", description: "ISO 3166-2:BR subdivision code.", examples: "RJ" },
  { value: "region:AU", group: "Regions", description: "ISO 3166-2:AU subdivision code.", examples: "NSW" },
  { value: "region:JP", group: "Regions", description: "ISO 3166-2:JP subdivision code.", examples: "13" },
  { value: "region:KR", group: "Regions", description: "ISO 3166-2:KR subdivision code.", examples: "11" }
] as const;

export const nuextractTypes = nuextractTypeOptions.map((option) => option.value);
export const nuextractTypeGroups = ["Base", "Date and time", "Locale and codes", "Contact and identifiers", "Regions"] as const;
export const nuextractTypeMetadata = Object.fromEntries(
  nuextractTypeOptions.map((option) => [option.value, option])
) as Record<NuExtractType, (typeof nuextractTypeOptions)[number]>;

export const schemaFieldShapes = ["scalar", "object", "array"] as const;
export const arrayItemShapes = ["scalar", "object"] as const;

export type NuExtractType = (typeof nuextractTypeOptions)[number]["value"];
export type SchemaFieldShape = (typeof schemaFieldShapes)[number];
export type SchemaArrayItemShape = (typeof arrayItemShapes)[number];
export type JsonType = "string" | "integer" | "number" | "boolean" | "object" | "array";
export type ValidationPreset = "none" | "digits" | "exact_digits" | "exact_alphanumeric" | "custom";

export type SchemaField = {
  id: string;
  name: string;
  shape: SchemaFieldShape;
  type: NuExtractType;
  required: boolean;
  nullable: boolean;
  itemShape: SchemaArrayItemShape;
  enumText: string;
  description: string;
  validationPreset: ValidationPreset;
  validationPattern: string;
  validationLength: string;
  fields: SchemaField[];
};

export type FieldSchema = {
  fields: FieldSchemaField[];
};

export type FieldSchemaField = {
  key?: string;
  kind: "scalar" | "object" | "array" | "enum" | "multi_enum";
  json_type?: JsonType;
  nuextract_type?: string;
  required?: boolean;
  nullable?: boolean;
  enum?: string[];
  description?: string;
  pattern?: string;
  minLength?: number;
  maxLength?: number;
  fields?: FieldSchemaField[];
  items?: FieldSchemaField;
};

type FieldOverrides = Partial<SchemaField> & {
  list?: boolean;
};

export const defaultSchemaFields: SchemaField[] = [
  field({ name: "merchant_name", type: "verbatim-string" }),
  field({ name: "receipt_id", type: "verbatim-string" }),
  field({ name: "date", type: "date" }),
  field({ name: "total", type: "number" }),
  field({ name: "currency", type: "currency", enumText: "EUR, USD, GBP" }),
  field({
    name: "line_items",
    shape: "array",
    itemShape: "object",
    required: false,
    nullable: false,
    fields: [
      field({ name: "description", type: "verbatim-string" }),
      field({ name: "quantity", type: "number", required: false }),
      field({ name: "line_total", type: "number", required: false })
    ]
  })
];

export function freshDefaultSchemaFields(): SchemaField[] {
  return cloneFields(defaultSchemaFields);
}

export function field(overrides: FieldOverrides = {}): SchemaField {
  const shape = overrides.shape ?? (overrides.list ? "array" : "scalar");
  const fields = cloneFields(overrides.fields ?? []);
  return {
    id: overrides.id ?? newFieldId(),
    name: overrides.name ?? "",
    shape,
    type: overrides.type ?? "string",
    required: overrides.required ?? true,
    nullable: shape === "array" ? false : (overrides.nullable ?? true),
    itemShape: overrides.itemShape ?? "scalar",
    enumText: overrides.enumText ?? "",
    description: overrides.description ?? "",
    validationPreset: overrides.validationPreset ?? "none",
    validationPattern: overrides.validationPattern ?? "",
    validationLength: overrides.validationLength ?? "10",
    fields
  };
}

export function schemaFromFields(fields: SchemaField[]): Record<string, unknown> {
  return objectSchemaFromFields(fields);
}

export function fieldsFromSchema(schema: Record<string, unknown>): SchemaField[] {
  const properties = asRecord(schema.properties);
  const required = _requiredKeys(schema);

  return Object.entries(properties)
    .filter(([, property]) => isRecord(property))
    .map(([name, property]) => fieldFromJsonProperty(name, property as Record<string, unknown>, required));
}

export function fieldSchemaFromFields(fields: SchemaField[]): FieldSchema {
  return {
    fields: fields
      .map((schemaField) => fieldSchemaField(schemaField))
      .filter((schemaField): schemaField is FieldSchemaField => schemaField !== null)
  };
}

export function fieldsFromFieldSchema(fieldSchema: Record<string, unknown> | null | undefined): SchemaField[] {
  const fields = Array.isArray(fieldSchema?.fields) ? fieldSchema.fields : [];
  return fields.filter(isRecord).map((schemaField) => fieldFromFieldSchema(schemaField));
}

export function nuextractTemplateFromFields(fields: SchemaField[]): Record<string, unknown> {
  const template: Record<string, unknown> = {};
  for (const schemaField of fields) {
    const name = schemaField.name.trim();
    if (!name) continue;
    template[name] = nuextractTemplateForField(schemaField);
  }
  return template;
}

export function fieldsFromNuextractTemplate(template: Record<string, unknown>): SchemaField[] {
  return Object.entries(template).map(([name, value]) => fieldFromTemplateValue(name, value));
}

export function cloneFields(fields: SchemaField[]): SchemaField[] {
  return fields.map((schemaField) =>
    field({
      ...schemaField,
      id: newFieldId(),
      fields: cloneFields(schemaField.fields)
    })
  );
}

function objectSchemaFromFields(fields: SchemaField[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];

  for (const schemaField of fields) {
    const name = schemaField.name.trim();
    if (!name) continue;
    properties[name] = propertySchema(schemaField);
    if (schemaField.required) required.push(name);
  }

  return {
    type: "object",
    additionalProperties: false,
    properties,
    required
  };
}

function fieldSchemaField(schemaField: SchemaField): FieldSchemaField | null {
  const key = schemaField.name.trim();
  if (!key) return null;
  const common: {
    key: string;
    required: boolean;
    nullable: boolean;
    description?: string;
  } = {
    key,
    required: schemaField.required,
    nullable: schemaField.shape === "array" ? false : schemaField.nullable
  };
  if (schemaField.description.trim()) {
    common.description = schemaField.description.trim();
  }
  const stringConstraints = stringConstraintsFromField(schemaField);

  if (schemaField.shape === "object") {
    return {
      ...common,
      kind: "object",
      json_type: "object",
      nuextract_type: "object",
      fields: fieldSchemaFromFields(schemaField.fields).fields
    };
  }

  if (schemaField.shape === "array" && schemaField.itemShape === "object") {
    return {
      ...common,
      kind: "array",
      json_type: "array",
      nuextract_type: "array",
      nullable: false,
      items: {
        kind: "object",
        json_type: "object",
        nuextract_type: "object",
        fields: fieldSchemaFromFields(schemaField.fields).fields
      }
    };
  }

  const enumValues = enumValuesFromField(schemaField);
  if (schemaField.shape === "array" && enumValues.length > 0) {
    return {
      ...common,
      kind: "multi_enum",
      json_type: "array",
      nuextract_type: "multi_enum",
      nullable: false,
      enum: enumValues
    };
  }

  if (schemaField.shape === "array") {
    return {
      ...common,
      kind: "array",
      json_type: "array",
      nuextract_type: "array",
      nullable: false,
      items: {
        ...scalarFieldSchema(schemaField),
        ...stringConstraints
      }
    };
  }

  if (enumValues.length > 0) {
    return {
      ...common,
      kind: "enum",
      json_type: "string",
      nuextract_type: "enum",
      enum: enumValues
    };
  }

  return {
    ...common,
    ...scalarFieldSchema(schemaField),
    ...stringConstraints
  };
}

function scalarFieldSchema(schemaField: SchemaField): FieldSchemaField {
  return {
    kind: "scalar",
    json_type: jsonTypeFromNuExtractType(schemaField.type),
    nuextract_type: schemaField.type
  };
}

function propertySchema(schemaField: SchemaField): Record<string, unknown> {
  if (schemaField.shape === "object") {
    return nullableSchema(objectSchemaFromFields(schemaField.fields), schemaField.nullable);
  }
  if (schemaField.shape === "array") {
    const itemSchema =
      schemaField.itemShape === "object" ? objectSchemaFromFields(schemaField.fields) : scalarSchema(schemaField);
    return { type: "array", items: itemSchema };
  }
  return nullableSchema(scalarSchema(schemaField), schemaField.nullable);
}

function scalarSchema(schemaField: SchemaField): Record<string, unknown> {
  const enumValues = enumValuesFromField(schemaField);
  const schema: Record<string, unknown> = {};

  if (enumValues.length > 0) {
    schema.type = "string";
    schema.enum = enumValues;
  } else if (schemaField.type === "number" || schemaField.type === "integer" || schemaField.type === "boolean") {
    schema.type = schemaField.type;
  } else {
    schema.type = "string";
  }

  if (schemaField.type !== "string" && schemaField.type !== "number" && schemaField.type !== "integer" && schemaField.type !== "boolean") {
    schema["x-parsehawk"] = { semantic: schemaField.type };
  }
  if (schemaField.description.trim()) {
    schema.description = schemaField.description.trim();
  }
  Object.assign(schema, stringConstraintsFromField(schemaField));
  return schema;
}

function fieldFromJsonProperty(name: string, property: Record<string, unknown>, required: Set<string>): SchemaField {
  const nullable = schemaAllowsNull(property);
  const effectiveSchema = withoutNull(property);
  const schemaTypeValue = schemaType(effectiveSchema);
  const description = isString(effectiveSchema.description) ? effectiveSchema.description : "";
  const validation = validationFromSchema(effectiveSchema);
  const common = {
    name,
    required: required.has(name),
    nullable,
    description,
    ...validation
  };
  const enumValues = enumValuesFromSchema(effectiveSchema);

  if (enumValues.length > 0) {
    return field({
      ...common,
      shape: "scalar",
      type: nuextractTypeFromSchema(effectiveSchema),
      enumText: enumValues.join(", ")
    });
  }

  if (schemaTypeValue === "object" || isRecord(effectiveSchema.properties)) {
    return field({
      ...common,
      shape: "object",
      type: "string",
      fields: fieldsFromSchema(effectiveSchema)
    });
  }

  if (schemaTypeValue === "array") {
    const items = asRecord(effectiveSchema.items);
    const itemSchema = withoutNull(items);
    const itemEnumValues = enumValuesFromSchema(itemSchema);
    if (schemaType(itemSchema) === "object" || isRecord(itemSchema.properties)) {
      return field({
        ...common,
        shape: "array",
        itemShape: "object",
        nullable: false,
        fields: fieldsFromSchema(itemSchema)
      });
    }
    return field({
      ...common,
      shape: "array",
      itemShape: "scalar",
      nullable: false,
      type: nuextractTypeFromSchema(itemSchema),
      enumText: itemEnumValues.join(", "),
      ...validationFromSchema(itemSchema)
    });
  }

  return field({
    ...common,
    shape: "scalar",
    type: nuextractTypeFromSchema(effectiveSchema)
  });
}

function fieldFromFieldSchema(schemaField: Record<string, unknown>): SchemaField {
  const kind = isString(schemaField.kind) ? schemaField.kind : "scalar";
  const common = {
    name: isString(schemaField.key) ? schemaField.key : "",
    required: schemaField.required !== false,
    nullable: schemaField.nullable !== false,
    description: isString(schemaField.description) ? schemaField.description : ""
  };
  const validation = validationFromFieldSchema(schemaField);

  if (kind === "object") {
    return field({
      ...common,
      shape: "object",
      type: "string",
      fields: fieldsFromFieldSchema({ fields: Array.isArray(schemaField.fields) ? schemaField.fields : [] })
    });
  }

  if (kind === "array") {
    const items = isRecord(schemaField.items) ? schemaField.items : {};
    if (items.kind === "object") {
      return field({
        ...common,
        shape: "array",
        itemShape: "object",
        nullable: false,
        fields: fieldsFromFieldSchema({ fields: Array.isArray(items.fields) ? items.fields : [] })
      });
    }
    const enumValues = Array.isArray(items.enum) ? items.enum.filter(isString) : [];
    return field({
      ...common,
      shape: "array",
      itemShape: "scalar",
      nullable: false,
      type: nuextractTypeFromValue(items.nuextract_type ?? items.json_type),
      enumText: enumValues.join(", "),
      ...validationFromFieldSchema(items)
    });
  }

  const enumValues = Array.isArray(schemaField.enum) ? schemaField.enum.filter(isString) : [];
  return field({
    ...common,
    shape: kind === "multi_enum" ? "array" : "scalar",
    itemShape: "scalar",
    nullable: kind === "multi_enum" ? false : common.nullable,
    type: nuextractTypeFromValue(schemaField.nuextract_type ?? schemaField.json_type),
    enumText: enumValues.join(", "),
    ...validation
  });
}

function nuextractTemplateForField(schemaField: SchemaField): unknown {
  const enumValues = enumValuesFromField(schemaField);

  if (schemaField.shape === "object") {
    return nuextractTemplateFromFields(schemaField.fields);
  }
  if (schemaField.shape === "array" && schemaField.itemShape === "object") {
    return [nuextractTemplateFromFields(schemaField.fields)];
  }
  if (schemaField.shape === "array" && enumValues.length > 0) {
    return [enumValues];
  }
  if (schemaField.shape === "array") {
    return [schemaField.type];
  }
  if (enumValues.length > 0) {
    return enumValues;
  }
  return schemaField.type;
}

function fieldFromTemplateValue(name: string, value: unknown): SchemaField {
  if (isRecord(value)) {
    return field({
      name,
      shape: "object",
      type: "string",
      fields: fieldsFromNuextractTemplate(value)
    });
  }
  if (Array.isArray(value)) {
    if (value.length === 1 && isRecord(value[0])) {
      return field({
        name,
        shape: "array",
        itemShape: "object",
        nullable: false,
        fields: fieldsFromNuextractTemplate(value[0])
      });
    }
    if (value.length === 1 && Array.isArray(value[0])) {
      return field({
        name,
        shape: "array",
        itemShape: "scalar",
        type: "string",
        nullable: false,
        enumText: value[0].filter(isString).join(", ")
      });
    }
    if (value.length === 1) {
      return field({
        name,
        shape: "array",
        itemShape: "scalar",
        type: nuextractTypeFromValue(value[0]),
        nullable: false
      });
    }
    return field({
      name,
      shape: "scalar",
      type: "string",
      enumText: value.filter(isString).join(", ")
    });
  }
  return field({ name, type: nuextractTypeFromValue(value) });
}

function nullableSchema(schema: Record<string, unknown>, nullable: boolean): Record<string, unknown> {
  if (!nullable) return schema;
  let next = schema;
  if (isString(next.type)) {
    next = { ...next, type: [next.type, "null"] };
  }
  if (Array.isArray(schema.enum)) {
    return { ...next, enum: schema.enum.includes(null) ? schema.enum : [...schema.enum, null] };
  }
  return next;
}

function withoutNull(schema: Record<string, unknown>): Record<string, unknown> {
  const next: Record<string, unknown> = { ...schema };
  if (Array.isArray(next.type)) {
    const types = next.type.filter((value) => value !== "null");
    next.type = types.length === 1 ? types[0] : types;
  }
  if (Array.isArray(next.enum)) {
    next.enum = next.enum.filter((value) => value !== null);
  }
  return next;
}

function nuextractTypeFromSchema(schema: Record<string, unknown>): NuExtractType {
  const parsehawkExtension = asRecord(schema["x-parsehawk"]);
  if (isNuExtractType(parsehawkExtension.semantic)) {
    return parsehawkExtension.semantic;
  }
  const type = schemaType(schema);
  if (type === "number" || type === "integer" || type === "boolean") return type;
  return "string";
}

function schemaAllowsNull(schema: Record<string, unknown>): boolean {
  if (Array.isArray(schema.type)) return schema.type.includes("null");
  if (Array.isArray(schema.enum)) return schema.enum.includes(null);
  if (Array.isArray(schema.anyOf)) return schema.anyOf.some(isNullSchema);
  if (Array.isArray(schema.oneOf)) return schema.oneOf.some(isNullSchema);
  return false;
}

function schemaType(schema: Record<string, unknown>): string | null {
  if (Array.isArray(schema.type)) {
    return schema.type.find((value) => value !== "null" && isString(value)) ?? null;
  }
  return isString(schema.type) ? schema.type : null;
}

function enumValuesFromSchema(schema: Record<string, unknown>): string[] {
  if (Array.isArray(schema.enum)) {
    return schema.enum.filter((value) => value !== null).map(String);
  }
  const union = Array.isArray(schema.anyOf) ? schema.anyOf : Array.isArray(schema.oneOf) ? schema.oneOf : [];
  return union.flatMap((branch) => {
    if (!isRecord(branch) || isNullSchema(branch)) return [];
    if (Array.isArray(branch.enum)) return branch.enum.filter((value) => value !== null).map(String);
    if ("const" in branch && branch.const !== null && branch.const !== undefined) return [String(branch.const)];
    return [];
  });
}

function _requiredKeys(schema: Record<string, unknown>): Set<string> {
  return new Set(Array.isArray(schema.required) ? schema.required.filter(isString) : []);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNullSchema(value: unknown): boolean {
  return isRecord(value) && value.type === "null";
}

function isNuExtractType(value: unknown): value is NuExtractType {
  return isString(value) && nuextractTypes.includes(value as NuExtractType);
}

function nuextractTypeFromValue(value: unknown): NuExtractType {
  return isNuExtractType(value) ? value : "string";
}

function jsonTypeFromNuExtractType(type: NuExtractType): "string" | "integer" | "number" | "boolean" {
  if (type === "integer" || type === "number" || type === "boolean") return type;
  return "string";
}

function enumValuesFromField(schemaField: SchemaField): string[] {
  return schemaField.enumText
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function stringConstraintsFromField(schemaField: SchemaField): Record<string, unknown> {
  if (!isStringLikeField(schemaField) || enumValuesFromField(schemaField).length > 0) return {};
  const constraints = validationConstraints(schemaField.validationPreset, schemaField.validationPattern, schemaField.validationLength);
  return constraints ?? {};
}

function validationConstraints(
  preset: ValidationPreset,
  pattern: string,
  lengthValue: string
): Record<string, unknown> | null {
  if (preset === "digits") return { pattern: "^\\d+$" };
  if (preset === "exact_digits") {
    const length = parsePositiveInteger(lengthValue) ?? 10;
    return { pattern: `^\\d{${length}}$`, minLength: length, maxLength: length };
  }
  if (preset === "exact_alphanumeric") {
    const length = parsePositiveInteger(lengthValue) ?? 10;
    return { pattern: `^[A-Za-z0-9]{${length}}$`, minLength: length, maxLength: length };
  }
  if (preset === "custom" && pattern.trim()) return { pattern: pattern.trim() };
  return null;
}

function validationFromSchema(schema: Record<string, unknown>): Pick<
  SchemaField,
  "validationPreset" | "validationPattern" | "validationLength"
> {
  const pattern = isString(schema.pattern) ? schema.pattern : "";
  const minLength = typeof schema.minLength === "number" ? schema.minLength : null;
  const maxLength = typeof schema.maxLength === "number" ? schema.maxLength : null;
  const exactDigits = exactDigitsPatternLength(pattern);
  if (exactDigits && minLength === exactDigits && maxLength === exactDigits) {
    return { validationPreset: "exact_digits", validationPattern: "", validationLength: String(exactDigits) };
  }
  const exactAlphanumeric = exactAlphanumericPatternLength(pattern);
  if (exactAlphanumeric && minLength === exactAlphanumeric && maxLength === exactAlphanumeric) {
    return {
      validationPreset: "exact_alphanumeric",
      validationPattern: "",
      validationLength: String(exactAlphanumeric)
    };
  }
  if (pattern === "^\\d+$") {
    return { validationPreset: "digits", validationPattern: "", validationLength: "10" };
  }
  if (pattern) {
    return { validationPreset: "custom", validationPattern: pattern, validationLength: "10" };
  }
  return { validationPreset: "none", validationPattern: "", validationLength: "10" };
}

function validationFromFieldSchema(schemaField: Record<string, unknown>): Pick<
  SchemaField,
  "validationPreset" | "validationPattern" | "validationLength"
> {
  return validationFromSchema(schemaField);
}

function isStringLikeField(schemaField: SchemaField): boolean {
  return schemaField.type === "string";
}

function exactDigitsPatternLength(pattern: string): number | null {
  const match = /^\^\\d\{(\d+)\}\$$/.exec(pattern);
  return match ? parsePositiveInteger(match[1]) : null;
}

function exactAlphanumericPatternLength(pattern: string): number | null {
  const match = /^\^\[A-Za-z0-9\]\{(\d+)\}\$$/.exec(pattern);
  return match ? parsePositiveInteger(match[1]) : null;
}

function parsePositiveInteger(value: string): number | null {
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function newFieldId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `field_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}
