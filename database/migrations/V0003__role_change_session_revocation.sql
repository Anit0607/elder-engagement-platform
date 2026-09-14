-- Preserve existing schema/data; the migration runner owns the transaction.
-- Opaque refresh tokens must not acquire a new privilege after role promotion.
CREATE FUNCTION revoke_sessions_on_role_change()
RETURNS trigger LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
  IF NEW.role IS DISTINCT FROM OLD.role THEN
    UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, clock_timestamp())
      WHERE user_id = OLD.id;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER app_users_session_role_guard
  BEFORE UPDATE OF role ON app_users
  FOR EACH ROW EXECUTE FUNCTION revoke_sessions_on_role_change();
