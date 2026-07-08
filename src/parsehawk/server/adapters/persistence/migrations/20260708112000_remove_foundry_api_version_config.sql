-- Microsoft Foundry uses OpenAI-compatible /openai/v1 inference without an
-- api-version query parameter. Deployment discovery still needs an API version,
-- but that value is an internal implementation detail, not provider config.

UPDATE providers
SET configuration = json_remove(configuration, '$.api_version')
WHERE name = 'microsoft_foundry'
  AND json_type(configuration, '$.api_version') IS NOT NULL;
