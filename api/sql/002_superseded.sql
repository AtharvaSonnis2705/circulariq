-- A newer master circular on the same topic rescinds the older one. Keep old versions (useful for
-- "what changed?"), but search only documents still in force.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS superseded_by BIGINT REFERENCES documents (id) ON DELETE SET NULL;
