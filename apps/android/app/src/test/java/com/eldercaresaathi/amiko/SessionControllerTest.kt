package com.eldercaresaathi.amiko

import org.junit.Assert.*
import org.junit.Test
import java.util.UUID
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class SessionControllerTest {
    private val old = MemberSession("fixture-old", "old-access", "old-refresh", "same-member")
    private val new = MemberSession("fixture-new", "new-access", "new-refresh", "same-member")
    private val current = MemberDevice(UUID.randomUUID().toString(), "android", null, true)
    private val other = MemberDevice(UUID.randomUUID().toString(), "ios", null, false)
    private class Store(var value: MemberSession?) : SessionRepository {
        var saves = 0
        var clears = 0
        var failSave = false
        override fun load() = value
        override fun save(session: MemberSession) {
            if (failSave) throw IllegalStateException()
            saves++; value = session
        }
        override fun clear() { clears++; value = null }
    }
    private inner class Transport(private val store: Store) : SessionTransport {
        var refreshes = 0
        var logouts = 0
        var revoked: String? = null
        var accessFailure: Int? = 401
        var renewedAccessFailure: Int? = null
        var logoutNeedsRenewal = false
        var offline = false
        var renewalError: Exception? = null
        var replacement = new
        var calls = 0
        override fun exchange(providerToken: String, installation: String) = old
        override fun refresh(refreshToken: String): MemberSession {
            assertNull(store.value) // In-flight token invalidated persistently first.
            assertEquals("old-refresh", refreshToken)
            refreshes++
            renewalError?.let { throw it }
            return replacement
        }
        override fun devices(accessToken: String): List<MemberDevice> {
            calls++
            if (offline) throw LoginConnectionFailed()
            if (accessToken == old.accessToken) accessFailure?.let { throw SessionHttpFailure(it) }
            if (accessToken == new.accessToken) renewedAccessFailure?.let { throw SessionHttpFailure(it) }
            return listOf(current, other)
        }
        override fun logout(accessToken: String) {
            if (offline) throw LoginConnectionFailed()
            if (accessToken == old.accessToken && logoutNeedsRenewal) throw SessionHttpFailure(401)
            if (accessToken == old.accessToken) accessFailure?.let { throw SessionHttpFailure(it) }
            logouts++
        }
        override fun revoke(accessToken: String, deviceId: String) { revoked = deviceId }
    }
    @Test fun restoreRenewsOnceKeepsIdentityAndSavesBothCredentials() {
        val store = Store(old); val api = Transport(store)
        val view = SessionController(store, api).restore()!!
        assertSame(new, view.session); assertSame(new, store.value)
        assertEquals(1, api.refreshes); assertEquals(1, store.saves); assertEquals(1, store.clears)
        assertEquals(2, api.calls)
        assertEquals(2, view.devices.size)
    }
    @Test fun profileRequestUsesTheSameSafeRenewalPath() {
        val store = Store(old); val api = Transport(store)
        val result = SessionController(store, api).withSession { session ->
            if (session.accessToken == old.accessToken) throw SessionHttpFailure(401)
            assertSame(new, session)
            "profile-loaded"
        }
        assertEquals("profile-loaded", result)
        assertSame(new, store.value)
        assertEquals(1, api.refreshes)
    }
    @Test fun profileRequestWithoutSignInDoesNotRun() {
        val store = Store(null); val api = Transport(store)
        assertThrows(SessionEnded::class.java) {
            SessionController(store, api).withSession { "unexpected" }
        }
        assertEquals(0, api.refreshes)
    }
    @Test fun reopeningUsesSavedReplacementWithoutAnotherRenewal() {
        val store = Store(old); val api = Transport(store)
        SessionController(store, api).restore()
        assertSame(new, SessionController(store, api).restore()!!.session)
        assertEquals(1, api.refreshes)
    }
    @Test fun rejectedReplacementCannotTriggerAnotherRefreshLoop() {
        val store = Store(old); val api = Transport(store).apply { renewedAccessFailure = 401 }
        assertThrows(SessionEnded::class.java) { SessionController(store, api).restore() }
        assertEquals(1, api.refreshes); assertNull(store.value)
    }
    @Test fun signInPersistsServerIssuedCredentialsWithoutRefresh() {
        val store = Store(null); val api = Transport(store)
        assertSame(old, SessionController(store, api).signIn("fixture-proof", UUID.randomUUID().toString()))
        assertSame(old, store.value); assertEquals(0, api.refreshes)
    }
    @Test fun missingSessionDoesNotCallServer() {
        val store = Store(null); val api = Transport(store)
        assertNull(SessionController(store, api).restore()); assertEquals(0, api.calls)
    }
    @Test fun ordinaryConnectionFailureKeepsSavedSession() {
        val store = Store(old); val api = Transport(store).apply { offline = true }
        assertThrows(LoginConnectionFailed::class.java) { SessionController(store, api).restore() }
        assertSame(old, store.value); assertEquals(0, api.refreshes)
    }
    @Test fun uncertainRenewalClearsCredentialsAndNeverRetriesOldToken() {
        for (failure in listOf(LoginConnectionFailed(), SessionHttpFailure(409), SessionHttpFailure(503))) {
            val store = Store(old); val api = Transport(store).apply { renewalError = failure }
            assertThrows(SessionEnded::class.java) { SessionController(store, api).restore() }
            assertNull(store.value); assertEquals(1, api.refreshes)
            assertNull(SessionController(store, api).restore()); assertEquals(1, api.refreshes)
        }
    }
    @Test fun suspensionClearsWithoutTryingRefresh() {
        val store = Store(old); val api = Transport(store).apply { accessFailure = 403 }
        assertThrows(SessionEnded::class.java) { SessionController(store, api).restore() }
        assertNull(store.value); assertEquals(0, api.refreshes)
    }
    @Test fun outageDoesNotTriggerRefresh() {
        val store = Store(old); val api = Transport(store).apply { accessFailure = 503 }
        assertThrows(SessionHttpFailure::class.java) { SessionController(store, api).restore() }
        assertSame(old, store.value); assertEquals(0, api.refreshes)
    }
    @Test fun wrongAccountUnchangedTokensOrStorageFailureEndSession() {
        for (replacement in listOf(old, MemberSession("fixture", "new-access", "new-refresh", "different"))) {
            val store = Store(old); val api = Transport(store).apply { this.replacement = replacement }
            assertThrows(SessionEnded::class.java) { SessionController(store, api).restore() }
            assertNull(store.value)
        }
        val store = Store(old).apply { failSave = true }; val api = Transport(store)
        assertThrows(SessionEnded::class.java) { SessionController(store, api).restore() }
        assertNull(store.value)
    }
    @Test fun logoutConfirmsRemoteRevocationBeforeClearing() {
        val store = Store(old); val api = Transport(store)
        SessionController(store, api).logout()
        assertEquals(1, api.logouts); assertNull(store.value)
    }
    @Test fun offlineLogoutDoesNotPretendToSucceed() {
        val store = Store(old); val api = Transport(store).apply { offline = true }
        assertThrows(LoginConnectionFailed::class.java) { SessionController(store, api).logout() }
        assertSame(old, store.value); assertEquals(0, api.logouts)
    }
    @Test fun removingCurrentDeviceWorksEvenIfCredentialNeedsRenewal() {
        val store = Store(old); val api = Transport(store)
        assertNull(SessionController(store, api).removeDevice(current.id))
        assertNull(store.value); assertEquals(1, api.logouts); assertNull(api.revoked)
    }
    @Test fun expiryBetweenDeviceListingAndCurrentRemovalDoesNotUseAReplacedRowId() {
        val store = Store(old); val api = Transport(store).apply {
            accessFailure = null; logoutNeedsRenewal = true
        }
        assertNull(SessionController(store, api).removeDevice(current.id))
        assertNull(store.value); assertEquals(1, api.refreshes); assertEquals(1, api.logouts)
        assertNull(api.revoked)
    }
    @Test fun removingAnotherDeviceDoesNotSignOutCurrentDevice() {
        val store = Store(old); val api = Transport(store)
        assertNotNull(SessionController(store, api).removeDevice(other.id))
        assertSame(new, store.value); assertEquals(other.id, api.revoked); assertEquals(0, api.logouts)
    }
    @Test fun unavailableOrInvalidDeviceCannotBeRemoved() {
        val store = Store(old); val api = Transport(store).apply { accessFailure = null }
        val manager = SessionController(store, api)
        assertThrows(SessionHttpFailure::class.java) { manager.removeDevice(UUID.randomUUID().toString()) }
        assertThrows(IllegalArgumentException::class.java) { manager.removeDevice("../foreign") }
        assertNull(api.revoked)
    }
    @Test fun twoActivityControllersCannotReuseTheSameRefresh() {
        val store = Store(old); val api = Transport(store)
        val executor = Executors.newFixedThreadPool(2)
        try {
            val futures = executor.invokeAll(listOf(
                Callable { SessionController(store, api).restore() },
                Callable { SessionController(store, api).restore() }))
            for (future in futures) assertSame(new, future.get(5, TimeUnit.SECONDS)!!.session)
            assertEquals(1, api.refreshes)
        } finally { executor.shutdownNow() }
    }
    @Test fun credentialsAreNotExposedByDefaultObjectStrings() {
        assertFalse(old.toString().contains(old.accessToken))
        assertFalse(old.toString().contains(old.refreshToken))
    }
}
