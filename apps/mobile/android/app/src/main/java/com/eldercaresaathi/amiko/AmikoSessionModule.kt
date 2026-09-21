package com.eldercaresaathi.amiko

import android.app.Activity
import android.content.Intent
import com.facebook.react.bridge.BaseActivityEventListener
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import java.util.concurrent.Executors
import java.io.ByteArrayOutputStream
import org.json.JSONObject

/** Keeps tokens in Android Keystore storage; JavaScript only receives account state. */
class AmikoSessionModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
    private val executor = Executors.newSingleThreadExecutor()
    private val sessions = SessionController(SessionStore(context.applicationContext), MemberApi())
    private var photoPromise: Promise? = null
    private val photoPickerCode = 47031
    private val photoListener = object : BaseActivityEventListener() {
        override fun onActivityResult(activity: Activity, requestCode: Int, resultCode: Int, data: Intent?) {
            if (requestCode != photoPickerCode) return
            val pending = photoPromise ?: return
            photoPromise = null
            if (resultCode != Activity.RESULT_OK || data?.data == null) {
                pending.resolve(null)
                return
            }
            val uri = data.data ?: return
            executor.execute {
                try {
                    val resolver = reactApplicationContext.contentResolver
                    val contentType = resolver.getType(uri) ?: throw IllegalArgumentException()
                    require(contentType in listOf("image/jpeg", "image/png", "image/webp"))
                    val bytes = resolver.openInputStream(uri)?.use { input ->
                        val output = ByteArrayOutputStream()
                        val chunk = ByteArray(8192)
                        while (true) {
                            val read = input.read(chunk)
                            if (read < 0) break
                            if (read == 0) continue
                            if (output.size() + read > 5_242_880) throw IllegalArgumentException()
                            output.write(chunk, 0, read)
                        }
                        output.toByteArray()
                    } ?: throw IllegalArgumentException()
                    require(bytes.isNotEmpty())
                    val api = MemberApi()
                    val authorization = sessions.withSession {
                        api.startPhotoUpload(it.accessToken, contentType, bytes)
                    }
                    val uploadId = api.sendPhotoUpload(authorization, contentType, bytes)
                    pending.resolve(sessions.withSession { api.completePhotoUpload(it.accessToken, uploadId) })
                } catch (_: SessionEnded) {
                    pending.reject("SIGN_IN_REQUIRED", "Sign in again to upload a photo")
                } catch (_: IllegalArgumentException) {
                    pending.reject("PHOTO_INVALID", "Choose a JPEG, PNG or WebP photo under 5 MB")
                } catch (_: Exception) {
                    pending.reject("PHOTO_UNAVAILABLE", "Could not upload this photo")
                }
            }
        }
    }

    init { reactApplicationContext.addActivityEventListener(photoListener) }

    override fun getName() = "AmikoSession"

    @ReactMethod
    fun pickProfilePhoto(promise: Promise) {
        val activity = reactApplicationContext.currentActivity
        if (activity == null || photoPromise != null) {
            promise.reject("PHOTO_UNAVAILABLE", "Open Amiko before choosing a photo")
            return
        }
        photoPromise = promise
        try {
            activity.startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "image/*"
            }, photoPickerCode)
        } catch (_: Exception) {
            photoPromise = null
            promise.reject("PHOTO_UNAVAILABLE", "Could not open photos")
        }
    }

    @ReactMethod
    fun getUiLanguage(promise: Promise) {
        val language = reactApplicationContext.getSharedPreferences("amiko_ui", 0)
            .getString("language", "en")
        promise.resolve(if (language in listOf("en", "bn", "hi")) language else "en")
    }

    @ReactMethod
    fun setUiLanguage(language: String, promise: Promise) {
        if (language !in listOf("en", "bn", "hi")) {
            promise.reject("INVALID_LANGUAGE", "Select a supported language")
            return
        }
        reactApplicationContext.getSharedPreferences("amiko_ui", 0).edit()
            .putString("language", language).apply()
        promise.resolve(null)
    }

    @ReactMethod
    fun openPhoneSignIn(language: String, promise: Promise) {
        val activity = reactApplicationContext.currentActivity
        if (activity == null) {
            promise.reject("NO_ACTIVITY", "Open Amiko before signing in")
            return
        }
        try {
            if (language !in listOf("en", "bn", "hi")) {
                promise.reject("INVALID_LANGUAGE", "Select a supported language")
                return
            }
            reactApplicationContext.getSharedPreferences("amiko_ui", 0).edit()
                .putString("language", language).apply()
            activity.startActivity(Intent(activity, PhoneLoginActivity::class.java)
                .putExtra("amiko_return_to_app", true))
            promise.resolve(null)
        } catch (_: Exception) {
            promise.reject("SIGN_IN_UNAVAILABLE", "Phone sign-in is unavailable")
        }
    }

    @ReactMethod
    fun checkSignIn(promise: Promise) {
        executor.execute {
            try {
                val view = sessions.restore()
                val result = Arguments.createMap()
                result.putBoolean("signedIn", view != null)
                promise.resolve(result)
            } catch (_: SessionEnded) {
                val result = Arguments.createMap()
                result.putBoolean("signedIn", false)
                promise.resolve(result)
            } catch (_: Exception) {
                promise.reject("CONNECTION_UNAVAILABLE", "Could not check your sign-in")
            }
        }
    }

    @ReactMethod
    fun signOut(promise: Promise) {
        executor.execute {
            try {
                sessions.logout()
                promise.resolve(null)
            } catch (_: SessionEnded) {
                promise.resolve(null)
            } catch (_: Exception) {
                promise.reject("CONNECTION_UNAVAILABLE", "Could not sign out")
            }
        }
    }

    @ReactMethod
    fun getProfile(promise: Promise) {
        executor.execute {
            try {
                promise.resolve(sessions.withSession { MemberApi().profile(it.accessToken) })
            } catch (error: SessionHttpFailure) {
                if (error.status == 404) promise.resolve(null)
                else promise.reject("PROFILE_UNAVAILABLE", "Could not load your profile")
            } catch (_: SessionEnded) {
                promise.reject("SIGN_IN_REQUIRED", "Sign in again to view your profile")
            } catch (_: Exception) {
                promise.reject("PROFILE_UNAVAILABLE", "Could not load your profile")
            }
        }
    }

    @ReactMethod
    fun updateProfile(json: String, promise: Promise) {
        if (json.length > 32_768) {
            promise.reject("INVALID_PROFILE", "Profile is too large")
            return
        }
        val body = try { JSONObject(json) }
            catch (_: Exception) {
                promise.reject("INVALID_PROFILE", "Check your profile details")
                return
            }
        executor.execute {
            try {
                promise.resolve(sessions.withSession { MemberApi().updateProfile(it.accessToken, body) })
            } catch (_: SessionEnded) {
                promise.reject("SIGN_IN_REQUIRED", "Sign in again to save your profile")
            } catch (error: SessionHttpFailure) {
                promise.reject("PROFILE_REJECTED", "Check your profile details")
            } catch (_: Exception) {
                promise.reject("PROFILE_UNAVAILABLE", "Could not save your profile")
            }
        }
    }

    @ReactMethod
    fun listCircles(promise: Promise) {
        executor.execute {
            try {
                promise.resolve(sessions.withSession { MemberApi().circles(it.accessToken) })
            } catch (_: SessionEnded) {
                promise.reject("SIGN_IN_REQUIRED", "Sign in again to view circles")
            } catch (_: Exception) {
                promise.reject("CIRCLES_UNAVAILABLE", "Could not load circles")
            }
        }
    }

    @ReactMethod
    fun changeCircleMembership(id: String, join: Boolean, promise: Promise) {
        executor.execute {
            try {
                sessions.withSession {
                    if (join) MemberApi().joinCircle(it.accessToken, id)
                    else MemberApi().leaveCircle(it.accessToken, id)
                }
                promise.resolve(null)
            } catch (_: SessionEnded) {
                promise.reject("SIGN_IN_REQUIRED", "Sign in again to change circles")
            } catch (error: SessionHttpFailure) {
                promise.reject(if (error.status == 409) "CIRCLE_LIMIT" else "CIRCLE_UNAVAILABLE",
                    "Could not change this circle")
            } catch (_: Exception) {
                promise.reject("CIRCLE_UNAVAILABLE", "Could not change this circle")
            }
        }
    }

    @ReactMethod
    fun listDevices(promise: Promise) {
        executor.execute {
            try {
                val view = sessions.restore() ?: throw SessionEnded()
                val devices = Arguments.createArray()
                for (device in view.devices) {
                    val row = Arguments.createMap()
                    row.putString("id", device.id)
                    row.putString("platform", device.platform)
                    row.putBoolean("current", device.current)
                    row.putString("deviceName", device.name)
                    row.putString("lastSeenAt", device.lastSeenAt)
                    devices.pushMap(row)
                }
                promise.resolve(devices)
            } catch (_: SessionEnded) {
                promise.reject("SIGN_IN_REQUIRED", "Sign in again to view devices")
            } catch (_: Exception) {
                promise.reject("DEVICE_UNAVAILABLE", "Could not load devices")
            }
        }
    }

    @ReactMethod
    fun removeDevice(id: String, promise: Promise) {
        executor.execute {
            try {
                val remaining = sessions.removeDevice(id)
                promise.resolve(remaining != null)
            } catch (_: SessionEnded) {
                promise.reject("SIGN_IN_REQUIRED", "Sign in again to change devices")
            } catch (_: Exception) {
                promise.reject("DEVICE_UNAVAILABLE", "Could not change this device")
            }
        }
    }

    override fun invalidate() {
        reactApplicationContext.removeActivityEventListener(photoListener)
        photoPromise?.reject("PHOTO_UNAVAILABLE", "Photo choice was interrupted")
        photoPromise = null
        executor.shutdownNow()
        super.invalidate()
    }
}
