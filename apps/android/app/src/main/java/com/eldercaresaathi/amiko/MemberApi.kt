package com.eldercaresaathi.amiko

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.util.UUID

object SessionCodec {
    fun parse(response: String): MemberSession {
        check(response.length <= 32_768)
        val payload = JSONObject(response)
        val access = payload.get("accessToken").also { check(it is String) } as String
        val refresh = payload.get("refreshToken").also { check(it is String) } as String
        check(access.length in 32..8192 && access.split('.').size == 3)
        check(Regex("amr1_[A-Za-z0-9_-]{64}").matches(refresh))
        check(payload.getString("tokenType") == "Bearer")
        val lifetime = payload.get("expiresInSeconds")
        check(lifetime is Int && lifetime in 60..3600)
        val user = payload.getJSONObject("user")
        check(user.getString("role") == "member" && user.getString("status") == "active")
        val id = user.getString("id")
        check(UUID.fromString(id).toString() == id)
        return MemberSession(response, access, refresh, id)
    }
}

class MemberApi : SessionTransport {
    fun profile(accessToken: String): String = request("GET", "/v1/me/profile", access=accessToken)
    fun updateProfile(accessToken: String, body: JSONObject): String =
        request("PATCH", "/v1/me/profile", access=accessToken, body=body)
    fun circles(accessToken: String): String = request("GET", "/v1/me/circles", access=accessToken)
    fun joinCircle(accessToken: String, circleId: String) {
        require(UUID.fromString(circleId).toString() == circleId)
        request("POST", "/v1/me/circles/$circleId/membership", access=accessToken, expected=204)
    }
    fun leaveCircle(accessToken: String, circleId: String) {
        require(UUID.fromString(circleId).toString() == circleId)
        request("DELETE", "/v1/me/circles/$circleId/membership", access=accessToken, expected=204)
    }
    override fun exchange(providerToken: String, installation: String): MemberSession {
        require(UUID.fromString(installation).toString() == installation)
        return SessionCodec.parse(request("POST", "/v1/auth/member/session", body=JSONObject()
            .put("providerIdToken", providerToken).put("installationId", installation).put("platform", "android")))
    }
    override fun refresh(refreshToken: String) = SessionCodec.parse(request("POST", "/v1/auth/refresh",
        body=JSONObject().put("refreshToken", refreshToken)))
    override fun devices(accessToken: String): List<MemberDevice> {
        val rows = JSONArray(request("GET", "/v1/me/sessions", access=accessToken))
        return (0 until rows.length()).map { index ->
            val row = rows.getJSONObject(index)
            val id = row.getString("id")
            check(UUID.fromString(id).toString() == id)
            val platform = row.getString("platform")
            check(platform in listOf("android", "ios", "web"))
            check(row.get("current") is Boolean)
            MemberDevice(id, platform, if (row.isNull("deviceName")) null else row.getString("deviceName"),
                row.getBoolean("current"), row.getString("lastSeenAt").also {
                    java.time.OffsetDateTime.parse(it)
                })
        }
    }
    override fun logout(accessToken: String) { request("POST", "/v1/auth/logout", access=accessToken, expected=204) }
    override fun revoke(accessToken: String, deviceId: String) {
        require(UUID.fromString(deviceId).toString() == deviceId)
        request("DELETE", "/v1/me/sessions/$deviceId", access=accessToken, expected=204)
    }
    private fun request(method: String, path: String, access: String?=null, body: JSONObject?=null,
                        expected: Int=200): String {
        val origin = URI(BuildConfig.API_ORIGIN)
        require(origin.userInfo == null && origin.query == null && origin.fragment == null)
        require(origin.path.isNullOrEmpty() || origin.path == "/")
        require(origin.scheme == "https" || (BuildConfig.DEBUG && origin.scheme == "http" &&
            origin.host == "127.0.0.1"))
        val connection = origin.resolve(path).toURL().openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 15_000
            connection.readTimeout = 20_000
            connection.instanceFollowRedirects = false
            if (access != null) connection.setRequestProperty("Authorization", "Bearer $access")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            if (BuildConfig.DEBUG) android.util.Log.w("AmikoLoginCheck", "stage=backend_http status=$status")
            if (status == 429) throw LoginRateLimited()
            if (status != expected) throw SessionHttpFailure(status)
            if (status == 204) return ""
            return connection.inputStream.bufferedReader().use { reader ->
                val buffer = CharArray(32_769)
                var count = 0
                while (count < buffer.size) {
                    val read = reader.read(buffer, count, buffer.size - count)
                    if (read < 0) break
                    count += read
                }
                check(count < buffer.size)
                String(buffer, 0, count)
            }
        } finally { connection.disconnect() }
    }
}
