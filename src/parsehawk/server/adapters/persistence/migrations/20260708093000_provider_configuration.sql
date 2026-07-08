-- Move provider-specific settings into JSON configuration and rename the
-- unreleased Azure OpenAI provider to Microsoft Foundry.

ALTER TABLE providers ADD COLUMN configuration TEXT NOT NULL DEFAULT '{}';

UPDATE providers
SET configuration = json_object('api_version', api_version)
WHERE api_version IS NOT NULL AND TRIM(api_version) <> '';

INSERT INTO providers (name, base_url, configuration, created_at, updated_at)
SELECT 'microsoft_foundry', base_url, configuration, created_at, updated_at
FROM providers
WHERE name = 'azure_openai'
ON CONFLICT(name) DO UPDATE SET
    base_url = excluded.base_url,
    configuration = excluded.configuration,
    updated_at = excluded.updated_at;

UPDATE provider_secrets
SET provider_name = 'microsoft_foundry'
WHERE provider_name = 'azure_openai';

UPDATE extractors
SET provider_name = 'microsoft_foundry'
WHERE provider_name = 'azure_openai';

DELETE FROM providers WHERE name = 'azure_openai';

ALTER TABLE providers DROP COLUMN api_version;
