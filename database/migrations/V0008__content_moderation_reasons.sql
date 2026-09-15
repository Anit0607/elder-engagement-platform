ALTER TABLE moderation_decisions
  ADD COLUMN reason_code varchar(40),
  ADD COLUMN note varchar(900);

UPDATE moderation_decisions
SET reason_code = CASE WHEN outcome = 'approved' THEN 'approved' ELSE 'other' END,
    note = CASE WHEN outcome = 'approved' THEN NULL ELSE left(reason, 900) END;

ALTER TABLE moderation_decisions
  ALTER COLUMN reason_code SET NOT NULL;

ALTER TABLE moderation_decisions
  ADD CONSTRAINT moderation_decisions_reason_shape CHECK (
    (outcome = 'approved' AND reason_code = 'approved')
    OR (
      outcome IN ('rejected', 'returned')
      AND reason_code IN (
        'copyright_permission',
        'unsafe_inappropriate',
        'misleading',
        'poor_quality',
        'duplicate',
        'other'
      )
      AND (reason_code <> 'other' OR length(btrim(note)) > 0)
    )
  );

CREATE INDEX moderation_decisions_content_history_idx
  ON moderation_decisions (content_item_id, decided_at DESC);

COMMENT ON COLUMN moderation_decisions.reason_code IS
  'Controlled Administrator decision reason used by Android, iOS and audit reporting.';

COMMENT ON COLUMN moderation_decisions.note IS
  'Optional Administrator explanation; mandatory when reason_code is other.';
