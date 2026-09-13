package com.eldercaresaathi.amiko

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.util.UUID

class MemberApi {
    fun exchange(providerToken: String, installation: String): String {
        val origin = URI(BuildConfig.API_ORIGIN)
        require(origin.userInfo == null && origin.query == null && origin.fragment == null)
        require(origin.path.isNullOrEmpty() || origin.path == "/")
        require(origin.scheme == "https" || (BuildConfig.DEBUG && origin.scheme == "http" &&
            origin.host == "127.0.0.1"))
        require(UUID.fromString(installation).toString() == installation)
        val connection = origin.resolve("/v1/auth/member/session").toURL().openConnection() as HttpURLConnection
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 15_000
            connection.readTimeout = 20_000
            connection.instanceFollowRedirects = false
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            val body = JSONObject().put("providerIdToken", providerToken)
                .put("installationId", installation).put("platform", "android").toString()
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            if (BuildConfig.DEBUG) android.util.Log.w("AmikoLoginCheck", "stage=backend_http status=$status")
            if (status == 429) throw LoginRateLimited()
            if (status != 200) throw LoginConnectionFailed()
            val response = connection.inputStream.bufferedReader().use { reader ->
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
            val payload = JSONObject(response)
            check(payload.getString("accessToken").isNotBlank() && payload.getString("refreshToken").isNotBlank())
            val user = payload.getJSONObject("user")
            check(user.getString("role") == "member" && user.getString("status") == "active")
            return response
        } finally { connection.disconnect() }
    }
}
class LoginRateLimited : RuntimeException()
class LoginConnectionFailed : RuntimeException()
