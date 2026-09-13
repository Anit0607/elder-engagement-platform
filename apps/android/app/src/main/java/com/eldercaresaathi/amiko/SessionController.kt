package com.eldercaresaathi.amiko

import java.util.UUID

// Do not implement toString(): these objects contain credentials.
class MemberSession(val response: String, val accessToken: String, val refreshToken: String, val userId: String)
data class MemberDevice(val id: String, val platform: String, val name: String?, val current: Boolean,
                        val lastSeenAt: String? = null)
class SessionView(val session: MemberSession, val devices: List<MemberDevice>)

interface SessionRepository {
    fun load(): MemberSession?
    fun save(session: MemberSession)
    fun clear()
}
interface SessionTransport {
    fun exchange(providerToken: String, installation: String): MemberSession
    fun refresh(refreshToken: String): MemberSession
    fun devices(accessToken: String): List<MemberDevice>
    fun logout(accessToken: String)
    fun revoke(accessToken: String, deviceId: String)
}
class SessionEnded : RuntimeException()
class SessionHttpFailure(val status: Int) : RuntimeException()
class LoginRateLimited : RuntimeException()
class LoginConnectionFailed : RuntimeException()

/** One process-wide lock: activity recreation must not send the same refresh twice. */
class SessionController(private val store: SessionRepository, private val transport: SessionTransport) {
    companion object { private val lock = Any() }
    fun signIn(proof: String, installation: String): MemberSession = synchronized(lock) {
        transport.exchange(proof, installation).also { store.save(it) }
    }
    fun restore(): SessionView? = synchronized(lock) {
        if (store.load() == null) return@synchronized null
        authenticated { SessionView(it, transport.devices(it.accessToken)) }
    }
    fun logout() = synchronized(lock) {
        if (store.load() == null) return@synchronized
        authenticated { transport.logout(it.accessToken) }
        store.clear()
    }
    fun removeDevice(id: String): SessionView? = synchronized(lock) {
        require(UUID.fromString(id).toString() == id)
        val view = authenticated { SessionView(it, transport.devices(it.accessToken)) }
        val target = view.devices.singleOrNull { it.id == id } ?: throw SessionHttpFailure(404)
        if (target.current) {
            // Renewal changes the current row ID, but logout still revokes its same family.
            authenticated { transport.logout(it.accessToken) }
            store.clear(); null
        } else {
            authenticated { transport.revoke(it.accessToken, id) }
            authenticated { SessionView(it, transport.devices(it.accessToken)) }
        }
    }
    private fun <T> authenticated(action: (MemberSession) -> T): T {
        val original = store.load() ?: throw SessionEnded()
        try { return action(original) }
        catch (error: SessionHttpFailure) {
            if (error.status == 403) { store.clear(); throw SessionEnded() }
            if (error.status != 401) throw error
        }
        // Clear BEFORE sending: process death cannot replay an in-flight refresh token.
        store.clear()
        val renewed = try {
            transport.refresh(original.refreshToken).also {
                check(it.userId == original.userId)
                check(it.refreshToken != original.refreshToken && it.accessToken != original.accessToken)
                store.save(it)
            }
        } catch (_: Exception) {
            store.clear()
            throw SessionEnded()
        }
        try { return action(renewed) }
        catch (error: SessionHttpFailure) {
            if (error.status in listOf(401, 403)) { store.clear(); throw SessionEnded() }
            throw error
        }
    }
}
