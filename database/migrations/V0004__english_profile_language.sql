-- English is an approved profile preference, not an automatic translation mode.
ALTER TABLE user_profiles
  DROP CONSTRAINT user_profiles_preferred_language_check;
ALTER TABLE user_profiles
  ADD CONSTRAINT user_profiles_preferred_language_check
    CHECK (preferred_language IN ('bn', 'hi', 'en'));
