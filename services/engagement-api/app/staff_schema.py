"""Runtime metadata checks without granting application access to the ledger."""

from app.config import ConfigurationError


async def verify_staff_schema(pool):
    async with pool.acquire() as connection:
        ready = await connection.fetchval(
            """SELECT
                (SELECT count(*)=3 FROM information_schema.columns
                 WHERE table_schema='engagement_app' AND table_name='staff_credentials'
                   AND (column_name,udt_name) IN (
                     ('mfa_secret_ciphertext','bytea'),('last_accepted_totp_step','int8'),
                     ('credential_version','uuid')))
                AND EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema='engagement_app' AND table_name='auth_sessions'
                      AND column_name='staff_credential_version' AND udt_name='uuid')
                AND (SELECT count(*)=3 FROM pg_constraint
                     WHERE conrelid='engagement_app.staff_credentials'::regclass AND convalidated
                       AND conname IN ('staff_mfa_ciphertext_size','staff_mfa_configuration',
                                       'staff_totp_counter_nonnegative'))
                AND (SELECT count(*)=2 FROM pg_trigger t
                     JOIN pg_proc p ON p.oid=t.tgfoid
                     WHERE NOT t.tgisinternal AND t.tgenabled='O' AND t.tgtype=19
                       AND p.pronamespace='engagement_app'::regnamespace AND NOT p.prosecdef
                       AND ((t.tgrelid='engagement_app.staff_credentials'::regclass
                             AND t.tgname='staff_credentials_update_guard'
                             AND p.proname='guard_staff_credential_update')
                         OR (t.tgrelid='engagement_app.app_users'::regclass
                             AND t.tgname='app_users_session_role_guard'
                             AND p.proname='revoke_sessions_on_role_change')))
            """
        )
    if ready is not True:
        raise ConfigurationError("Staff authentication database updates are missing or disabled")
