-- OpenAI-compatible extractors can inherit the active bundled runtime model.
-- Earlier unreleased provider/model work materialized the then-default
-- NuExtract3 model on new extractors, which would make those extractors stale
-- when ParseHawk is started with a different bundled runtime model.

UPDATE extractors
SET model = NULL
WHERE provider_name = 'openai_compatible_api'
  AND model = 'numind/NuExtract3-W4A16';
