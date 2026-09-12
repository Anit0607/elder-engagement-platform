-- Elder Engagement Platform database baseline
-- Migration: V0001 engagement baseline.
-- Status: Sprint 1 immutable candidate; verified in CI but not applied to the client database.
-- Target: PostgreSQL 16 on client-owned Google Cloud SQL.
-- Scope: approved engagement platform only. No booking, wallet, payment,
-- caregiver-operation, voice-health, translation, or custom-call tables.

CREATE TYPE user_role AS ENUM ('member', 'contributor', 'administrator');
CREATE TYPE user_status AS ENUM ('invited', 'active', 'suspended', 'deleted');
CREATE TYPE content_kind AS ENUM ('video', 'audio', 'pdf', 'youtube', 'broadcast_replay');
CREATE TYPE moderation_status AS ENUM ('draft', 'pending', 'approved', 'rejected', 'archived');
CREATE TYPE moderation_outcome AS ENUM ('approved', 'rejected', 'returned');
CREATE TYPE audience_kind AS ENUM ('all_members', 'circle');
CREATE TYPE event_join_kind AS ENUM ('google_meet', 'telephone', 'information_only');
CREATE TYPE broadcast_status AS ENUM ('scheduled', 'live', 'ended', 'failed', 'cancelled');
CREATE TYPE recording_status AS ENUM ('requested', 'processing', 'ready', 'failed', 'deleted');

CREATE TABLE app_users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  public_id varchar(32) NOT NULL UNIQUE,
  role user_role NOT NULL,
  status user_status NOT NULL DEFAULT 'invited',
  phone_e164 text UNIQUE,
  username text UNIQUE,
  identity_provider_subject text UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT app_users_identity_required CHECK (
    phone_e164 IS NOT NULL OR username IS NOT NULL OR identity_provider_subject IS NOT NULL
  ),
  CONSTRAINT app_users_phone_shape CHECK (
    phone_e164 IS NULL OR phone_e164 ~ '^[+][1-9][0-9]{7,14}$'
  ),
  CONSTRAINT app_users_deleted_state CHECK (
    (status = 'deleted' AND deleted_at IS NOT NULL) OR status <> 'deleted'
  )
);

CREATE TABLE staff_credentials (
  user_id uuid PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
  password_hash text NOT NULL,
  password_changed_at timestamptz NOT NULL DEFAULT now(),
  second_factor_enabled boolean NOT NULL DEFAULT false,
  failed_attempts integer NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
  locked_until timestamptz,
  CONSTRAINT staff_credentials_password_hash_shape CHECK (length(password_hash) >= 20)
);

CREATE FUNCTION enforce_staff_credentials_user_role()
RETURNS trigger
LANGUAGE plpgsql
SET search_path FROM CURRENT
AS $$
DECLARE
  target_role user_role;
BEGIN
  SELECT role
    INTO target_role
    FROM app_users
   WHERE id = NEW.user_id
     FOR UPDATE;

  IF target_role IS NULL OR target_role NOT IN ('contributor', 'administrator') THEN
    RAISE EXCEPTION 'staff credentials require a contributor or administrator account'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER staff_credentials_role_guard
BEFORE INSERT OR UPDATE OF user_id ON staff_credentials
FOR EACH ROW EXECUTE FUNCTION enforce_staff_credentials_user_role();

CREATE FUNCTION prevent_staff_role_demotion()
RETURNS trigger
LANGUAGE plpgsql
SET search_path FROM CURRENT
AS $$
BEGIN
  IF NEW.role = 'member'
     AND EXISTS (SELECT 1 FROM staff_credentials WHERE user_id = NEW.id) THEN
    RAISE EXCEPTION 'remove staff credentials before changing this account to member'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER app_users_staff_role_guard
BEFORE UPDATE OF role ON app_users
FOR EACH ROW EXECUTE FUNCTION prevent_staff_role_demotion();

CREATE TABLE user_profiles (
  user_id uuid PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
  display_name varchar(120) NOT NULL,
  preferred_language varchar(2) NOT NULL CHECK (preferred_language IN ('bn', 'hi')),
  age_group varchar(64),
  interests jsonb NOT NULL DEFAULT '[]'::jsonb,
  country_code char(2),
  state_name varchar(120),
  city_name varchar(120),
  photo_object_key text,
  profile_complete boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT user_profiles_interests_array CHECK (jsonb_typeof(interests) = 'array'),
  CONSTRAINT user_profiles_country_shape CHECK (
    country_code IS NULL OR country_code ~ '^[A-Z]{2}$'
  )
);

CREATE TABLE auth_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  token_family_id uuid NOT NULL,
  refresh_token_hash text NOT NULL UNIQUE,
  installation_id uuid NOT NULL,
  platform varchar(16) NOT NULL CHECK (platform IN ('android', 'ios', 'web')),
  device_name varchar(120),
  created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  replaced_by_session_id uuid REFERENCES auth_sessions(id),
  CONSTRAINT auth_sessions_expiry CHECK (expires_at > created_at)
);

CREATE TABLE circles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name varchar(120) NOT NULL,
  description varchar(1000),
  active boolean NOT NULL DEFAULT true,
  suggestion_rules jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by uuid NOT NULL REFERENCES app_users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT circles_name_unique UNIQUE (name),
  CONSTRAINT circles_rules_object CHECK (jsonb_typeof(suggestion_rules) = 'object')
);

CREATE TABLE circle_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  circle_id uuid NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  selected_by_user boolean NOT NULL DEFAULT true,
  joined_at timestamptz NOT NULL DEFAULT now(),
  left_at timestamptz,
  CONSTRAINT circle_memberships_time_order CHECK (left_at IS NULL OR left_at >= joined_at)
);

CREATE TABLE content_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  contributor_id uuid NOT NULL REFERENCES app_users(id),
  kind content_kind NOT NULL,
  title varchar(200) NOT NULL,
  description varchar(4000),
  language varchar(2) CHECK (language IS NULL OR language IN ('bn', 'hi')),
  status moderation_status NOT NULL DEFAULT 'draft',
  youtube_video_id varchar(32),
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz,
  CONSTRAINT content_items_youtube_reference CHECK (
    (kind = 'youtube' AND youtube_video_id IS NOT NULL)
    OR (kind <> 'youtube' AND youtube_video_id IS NULL)
  ),
  CONSTRAINT content_items_publish_state CHECK (
    published_at IS NULL OR status IN ('approved', 'archived')
  )
);

CREATE TABLE content_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  object_key text NOT NULL UNIQUE,
  detected_media_type varchar(120),
  declared_media_type varchar(120) NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes > 0),
  sha256 char(64) NOT NULL,
  quarantined boolean NOT NULL DEFAULT true,
  scan_status varchar(24) NOT NULL DEFAULT 'pending'
    CHECK (scan_status IN ('pending', 'clean', 'rejected', 'failed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT content_assets_sha256_shape CHECK (sha256 ~ '^[a-f0-9]{64}$')
);

CREATE TABLE content_audiences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  audience audience_kind NOT NULL,
  circle_id uuid REFERENCES circles(id) ON DELETE CASCADE,
  CONSTRAINT content_audiences_circle_shape CHECK (
    (audience = 'circle' AND circle_id IS NOT NULL)
    OR (audience = 'all_members' AND circle_id IS NULL)
  ),
  CONSTRAINT content_audiences_unique UNIQUE NULLS NOT DISTINCT (content_item_id, audience, circle_id)
);

CREATE TABLE moderation_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_item_id uuid NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
  administrator_id uuid NOT NULL REFERENCES app_users(id),
  outcome moderation_outcome NOT NULL,
  reason varchar(1000) NOT NULL,
  decided_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_by uuid NOT NULL REFERENCES app_users(id),
  title varchar(200) NOT NULL,
  description varchar(4000),
  starts_at timestamptz NOT NULL,
  ends_at timestamptz,
  join_kind event_join_kind NOT NULL,
  join_reference_encrypted text,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT events_time_order CHECK (ends_at IS NULL OR ends_at > starts_at),
  CONSTRAINT events_join_reference CHECK (
    join_kind = 'information_only' OR join_reference_encrypted IS NOT NULL
  )
);

CREATE TABLE event_audiences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  audience audience_kind NOT NULL,
  circle_id uuid REFERENCES circles(id) ON DELETE CASCADE,
  CONSTRAINT event_audiences_circle_shape CHECK (
    (audience = 'circle' AND circle_id IS NOT NULL)
    OR (audience = 'all_members' AND circle_id IS NULL)
  ),
  CONSTRAINT event_audiences_unique UNIQUE NULLS NOT DISTINCT (event_id, audience, circle_id)
);

CREATE TABLE notification_preferences (
  user_id uuid PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
  enabled boolean NOT NULL DEFAULT true,
  window_start time,
  window_end time,
  time_zone varchar(64) NOT NULL DEFAULT 'Asia/Kolkata',
  push_events boolean NOT NULL DEFAULT true,
  push_content boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT notification_preferences_window_pair CHECK (
    (window_start IS NULL AND window_end IS NULL)
    OR (window_start IS NOT NULL AND window_end IS NOT NULL)
  )
);

CREATE TABLE broadcasts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  contributor_id uuid NOT NULL REFERENCES app_users(id),
  title varchar(200) NOT NULL,
  scheduled_at timestamptz,
  started_at timestamptz,
  ended_at timestamptz,
  status broadcast_status NOT NULL DEFAULT 'scheduled',
  provider_reference text UNIQUE,
  viewer_cap integer NOT NULL DEFAULT 100 CHECK (viewer_cap BETWEEN 1 AND 10000),
  recording_requested boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT broadcasts_time_order CHECK (
    ended_at IS NULL OR (started_at IS NOT NULL AND ended_at >= started_at)
  )
);

CREATE TABLE broadcast_audiences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  broadcast_id uuid NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
  audience audience_kind NOT NULL,
  circle_id uuid REFERENCES circles(id) ON DELETE CASCADE,
  CONSTRAINT broadcast_audiences_circle_shape CHECK (
    (audience = 'circle' AND circle_id IS NOT NULL)
    OR (audience = 'all_members' AND circle_id IS NULL)
  ),
  CONSTRAINT broadcast_audiences_unique UNIQUE NULLS NOT DISTINCT (broadcast_id, audience, circle_id)
);

CREATE TABLE recordings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  broadcast_id uuid NOT NULL UNIQUE REFERENCES broadcasts(id) ON DELETE CASCADE,
  provider_recording_reference text UNIQUE,
  object_key text UNIQUE,
  status recording_status NOT NULL DEFAULT 'requested',
  duration_seconds integer CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
  replay_content_item_id uuid UNIQUE REFERENCES content_items(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  ready_at timestamptz,
  retention_until timestamptz
);

CREATE TABLE notification_deliveries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  event_id uuid REFERENCES events(id) ON DELETE CASCADE,
  content_item_id uuid REFERENCES content_items(id) ON DELETE CASCADE,
  provider_message_id text,
  status varchar(24) NOT NULL CHECK (status IN ('queued', 'sent', 'failed', 'skipped')),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  next_attempt_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz,
  CONSTRAINT notification_deliveries_one_source CHECK (
    ((event_id IS NOT NULL)::integer + (content_item_id IS NOT NULL)::integer) = 1
  )
);

CREATE TABLE audit_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  actor_user_id uuid REFERENCES app_users(id),
  action varchar(120) NOT NULL,
  entity_type varchar(80) NOT NULL,
  entity_id text,
  trace_id varchar(128) NOT NULL,
  reason varchar(1000),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT audit_events_metadata_object CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX auth_sessions_user_active_idx
  ON auth_sessions (user_id, expires_at DESC) WHERE revoked_at IS NULL;
CREATE UNIQUE INDEX circle_memberships_one_active_idx
  ON circle_memberships (circle_id, user_id) WHERE left_at IS NULL;
CREATE INDEX circle_memberships_user_active_idx
  ON circle_memberships (user_id, joined_at DESC) WHERE left_at IS NULL;
CREATE INDEX content_items_feed_idx
  ON content_items (published_at DESC, id) WHERE status = 'approved';
CREATE INDEX content_items_moderation_idx
  ON content_items (status, created_at) WHERE status = 'pending';
CREATE INDEX content_audiences_circle_idx ON content_audiences (circle_id, content_item_id);
CREATE INDEX events_upcoming_idx ON events (starts_at, id) WHERE active = true;
CREATE INDEX broadcasts_schedule_idx ON broadcasts (status, scheduled_at);
CREATE INDEX notification_deliveries_queue_idx
  ON notification_deliveries (status, next_attempt_at) WHERE status IN ('queued', 'failed');
CREATE INDEX audit_events_entity_idx ON audit_events (entity_type, entity_id, occurred_at DESC);

COMMENT ON TABLE staff_credentials IS
  'Database triggers allow credentials only for contributor/administrator accounts and prevent demotion while credentials exist.';
COMMENT ON COLUMN content_items.youtube_video_id IS
  'Official YouTube identifier only. YouTube media is never copied into platform storage.';
COMMENT ON COLUMN broadcasts.viewer_cap IS
  'Initial production default is 100; any increase requires capacity evidence and client approval.';
COMMENT ON COLUMN recordings.retention_until IS
  'Final replay retention duration is a pending client privacy and operating-cost decision.';
