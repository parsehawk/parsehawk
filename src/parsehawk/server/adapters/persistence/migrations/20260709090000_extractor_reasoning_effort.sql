-- Replace the boolean enable_thinking with a nullable reasoning effort
-- (none | minimal | low | medium | high | xhigh). NULL means "send no
-- reasoning parameter and use the model's own default", which is the only
-- setting that is safe for every model.
--
-- The backfill must preserve behavior per payload adapter:
--   * enable_thinking=0 sent nothing anywhere -> NULL everywhere.
--   * enable_thinking=1 only had a request effect for NuExtract3 models
--     (thinking on via chat_template_kwargs) -> 'medium' keeps thinking on.
--     A NULL model inherits the bundled NuExtract3 runtime, so it counts.
--   * enable_thinking=1 on any other model sent nothing (the engine never set
--     a reasoning mode) -> NULL, so e.g. gpt-4o extractors keep working
--     instead of newly sending reasoning_effort and failing with HTTP 400.
-- The NuExtract3 model list is snapshotted as of this migration on purpose.

ALTER TABLE extractors ADD COLUMN reasoning_effort TEXT;

UPDATE extractors
SET reasoning_effort = 'medium'
WHERE enable_thinking = 1
  AND (
    model IS NULL
    OR model IN (
      'numind/NuExtract3',
      'numind/NuExtract3-GGUF',
      'numind/NuExtract3-W8A8',
      'numind/NuExtract3-W4A16',
      'numind/NuExtract3-FP8',
      'numind/NuExtract3-mlx-4bits',
      'numind/NuExtract3-mlx-5bits',
      'numind/NuExtract3-mlx-6bits',
      'numind/NuExtract3-mlx-8bits',
      'numind/NuExtract3-mlx-nvfp4',
      'numind/NuExtract3-mlx-mxfp8'
    )
  );

ALTER TABLE extractors DROP COLUMN enable_thinking;
