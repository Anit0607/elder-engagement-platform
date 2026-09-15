CREATE TABLE event_reminder_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  minutes_before integer NOT NULL
    CHECK (minutes_before BETWEEN 5 AND 10080),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT event_reminder_rules_unique UNIQUE (event_id, minutes_before)
);

CREATE INDEX event_reminder_rules_due_idx
  ON event_reminder_rules (minutes_before, event_id);

COMMENT ON TABLE event_reminder_rules IS
  'Administrator-selected event reminder offsets; delivery is handled by the notification milestone.';
