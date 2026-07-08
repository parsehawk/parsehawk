-- Snapshot the resolved provider/model used by each job execution. These fields
-- are nullable so historical queued/completed jobs remain valid.

ALTER TABLE jobs ADD COLUMN provider_name_used TEXT;
ALTER TABLE jobs ADD COLUMN model_used TEXT;
