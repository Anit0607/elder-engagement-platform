ALTER TABLE content_items
  DROP CONSTRAINT content_items_language_check;

ALTER TABLE content_items
  ADD CONSTRAINT content_items_language_check
  CHECK (language IS NULL OR language IN ('bn', 'hi', 'en'));

ALTER TABLE content_items
  ADD COLUMN rights_statement_version varchar(32),
  ADD COLUMN rights_confirmed_at timestamptz;

ALTER TABLE content_items
  ADD CONSTRAINT content_items_rights_pair CHECK (
    (rights_statement_version IS NULL AND rights_confirmed_at IS NULL)
    OR (rights_statement_version IS NOT NULL AND rights_confirmed_at IS NOT NULL)
  );

CREATE TABLE content_uploads (
  id uuid PRIMARY KEY,
  content_item_id uuid NOT NULL UNIQUE REFERENCES content_items(id) ON DELETE CASCADE,
  contributor_id uuid NOT NULL REFERENCES app_users(id),
  quarantine_object_key text NOT NULL UNIQUE,
  content_type varchar(120) NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 262144000),
  sha256 char(64) NOT NULL,
  status varchar(24) NOT NULL DEFAULT 'authorised'
    CHECK (status IN ('authorised', 'completed', 'rejected')),
  storage_generation bigint,
  expires_at timestamptz NOT NULL,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT content_uploads_sha256_shape CHECK (sha256 ~ '^[a-f0-9]{64}$'),
  CONSTRAINT content_uploads_expiry_after_creation CHECK (expires_at > created_at),
  CONSTRAINT content_uploads_completion_shape CHECK (
    (status = 'authorised' AND completed_at IS NULL AND storage_generation IS NULL)
    OR (status = 'completed' AND completed_at IS NOT NULL AND storage_generation IS NOT NULL)
    OR (status = 'rejected' AND completed_at IS NOT NULL)
  )
);

CREATE INDEX content_uploads_contributor_pending_idx
  ON content_uploads (contributor_id, expires_at DESC)
  WHERE status = 'authorised';

COMMENT ON TABLE content_uploads IS
  'Short-lived Contributor upload authorisations for private content quarantine; completion validates the stored object before moderation.';

COMMENT ON COLUMN content_items.rights_statement_version IS
  'Version of the Contributor ownership/permission declaration accepted before upload.';
