-- Make extraction jobs explicit before parse jobs introduce a second queue.
-- The v0.3 `/v1/jobs` API remains a compatibility alias, but persistence no
-- longer models extraction as the only generic kind of job.

DROP INDEX idx_jobs_extractor_id;
DROP INDEX idx_jobs_status_created_at;

ALTER TABLE jobs RENAME TO extraction_jobs;

CREATE INDEX idx_extraction_jobs_extractor_id
ON extraction_jobs(extractor_id);

CREATE INDEX idx_extraction_jobs_status_created_at
ON extraction_jobs(status, created_at);
