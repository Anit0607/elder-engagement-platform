CREATE TABLE profile_photo_uploads (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  quarantine_object_key text NOT NULL UNIQUE,
  approved_object_key text UNIQUE,
  content_type varchar(32) NOT NULL
    CHECK (content_type IN ('image/jpeg', 'image/png', 'image/webp')),
  size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 5242880),
  sha256 char(64) NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
  expires_at timestamptz NOT NULL,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT profile_photo_uploads_expiry_after_creation
    CHECK (expires_at > created_at),
  CONSTRAINT profile_photo_uploads_completion_shape CHECK (
    (completed_at IS NULL AND approved_object_key IS NULL)
    OR (completed_at IS NOT NULL AND approved_object_key IS NOT NULL)
  )
);

CREATE INDEX profile_photo_uploads_user_pending_idx
  ON profile_photo_uploads (user_id, expires_at DESC)
  WHERE completed_at IS NULL;

COMMENT ON TABLE profile_photo_uploads IS
  'Short-lived private upload intents; only content validated and copied to approved storage can be attached to a profile.';
