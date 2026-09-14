-- Additive staff authentication update. The runner owns the transaction.
-- No plaintext password, authenticator seed or verification code is stored.
ALTER TABLE staff_credentials
  ADD COLUMN mfa_secret_ciphertext bytea,
  ADD COLUMN last_accepted_totp_step bigint,
  ADD COLUMN credential_version uuid NOT NULL DEFAULT gen_random_uuid(),
  ADD CONSTRAINT staff_mfa_ciphertext_size CHECK (
    mfa_secret_ciphertext IS NULL OR octet_length(mfa_secret_ciphertext) = 60
  ),
  ADD CONSTRAINT staff_mfa_configuration CHECK (
    (second_factor_enabled AND mfa_secret_ciphertext IS NOT NULL)
    OR (NOT second_factor_enabled AND mfa_secret_ciphertext IS NULL
        AND last_accepted_totp_step IS NULL)
  ),
  ADD CONSTRAINT staff_totp_counter_nonnegative CHECK (
    last_accepted_totp_step IS NULL OR last_accepted_totp_step >= 0
  );

ALTER TABLE auth_sessions
  ADD COLUMN staff_credential_version uuid;

-- A password/authenticator change invalidates old sessions. Accepted code
-- counters cannot move backwards unless the authenticator configuration changes.
CREATE FUNCTION guard_staff_credential_update()
RETURNS trigger LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
  IF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
    RAISE EXCEPTION 'Staff credentials cannot be transferred to another account';
  END IF;
  IF NEW.password_hash IS DISTINCT FROM OLD.password_hash
     OR NEW.second_factor_enabled IS DISTINCT FROM OLD.second_factor_enabled
     OR NEW.mfa_secret_ciphertext IS DISTINCT FROM OLD.mfa_secret_ciphertext THEN
    NEW.credential_version := gen_random_uuid();
    IF NEW.password_hash IS DISTINCT FROM OLD.password_hash THEN
      NEW.password_changed_at := clock_timestamp();
    END IF;
    IF NEW.second_factor_enabled IS DISTINCT FROM OLD.second_factor_enabled
       OR NEW.mfa_secret_ciphertext IS DISTINCT FROM OLD.mfa_secret_ciphertext THEN
      NEW.last_accepted_totp_step := NULL;
    END IF;
    UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, clock_timestamp())
      WHERE user_id = OLD.user_id;
  ELSE
    NEW.credential_version := OLD.credential_version;
    IF OLD.last_accepted_totp_step IS NOT NULL AND
       (NEW.last_accepted_totp_step IS NULL OR
        NEW.last_accepted_totp_step < OLD.last_accepted_totp_step) THEN
      RAISE EXCEPTION 'Accepted authenticator counter cannot move backwards';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER staff_credentials_update_guard
  BEFORE UPDATE ON staff_credentials
  FOR EACH ROW EXECUTE FUNCTION guard_staff_credential_update();
