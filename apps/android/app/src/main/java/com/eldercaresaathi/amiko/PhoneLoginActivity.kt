package com.eldercaresaathi.amiko

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.res.Configuration
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.widget.*
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseException
import com.google.firebase.FirebaseNetworkException
import com.google.firebase.FirebaseOptions
import com.google.firebase.FirebaseTooManyRequestsException
import com.google.firebase.auth.*
import java.util.Locale
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Real Google phone verification; no fake success path or hardcoded verification code. */
class PhoneLoginActivity : Activity() {
    private val policy = PhoneLoginPolicy { SystemClock.elapsedRealtime() / 1000 }
    private val executor = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private lateinit var auth: FirebaseAuth
    private lateinit var phone: EditText
    private lateinit var code: EditText
    private lateinit var consent: CheckBox
    private lateinit var status: TextView
    private lateinit var send: Button
    private lateinit var verify: Button
    private lateinit var change: Button
    private lateinit var retry: Button
    private lateinit var sessionRetry: Button
    private lateinit var logout: Button
    private lateinit var deviceList: LinearLayout
    private lateinit var sessions: SessionController
    private var verificationId: String? = null
    private var resendToken: PhoneAuthProvider.ForceResendingToken? = null
    private var busy = false
    private var completed = false
    private var epoch = 0
    private var ready = false
    private var providerAccepted = false
    private val ticker = object : Runnable {
        override fun run() { render(); main.postDelayed(this, 1000) }
    }

    override fun attachBaseContext(base: Context) {
        val language = base.getSharedPreferences("amiko_ui", MODE_PRIVATE).getString("language", "bn")!!
        super.attachBaseContext(base.createConfigurationContext(Configuration(base.resources.configuration).apply {
            setLocale(Locale.forLanguageTag(language))
        }))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(32), dp(24), dp(32))
        }
        val scroll = ScrollView(this).apply { isFillViewport = true; addView(root) }
        setContentView(scroll)
        scroll.setOnApplyWindowInsetsListener { _, insets ->
            root.setPadding(dp(24), dp(24) + insets.systemWindowInsetTop,
                dp(24), dp(24) + insets.systemWindowInsetBottom)
            insets
        }
        root.addView(TextView(this).apply { text = "Amiko"; textSize = 32f })
        root.addView(TextView(this).apply { setText(R.string.sign_in); textSize = 24f })
        val languages = LinearLayout(this)
        for ((label, language) in listOf("বাংলা" to "bn", "हिन्दी" to "hi")) {
            languages.addView(Button(this).apply {
                text = label; minHeight = dp(56)
                setOnClickListener {
                    if (!busy && verificationId == null && policy.canRequest()) {
                        getSharedPreferences("amiko_ui", MODE_PRIVATE).edit().putString("language", language).apply()
                        recreate()
                    }
                }
            })
        }
        root.addView(languages)
        phone = EditText(this).apply {
            hint = getString(R.string.phone_hint); inputType = InputType.TYPE_CLASS_PHONE
            textSize = 22f; importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
            contentDescription = getString(R.string.phone_hint)
        }
        root.addView(phone)
        consent = CheckBox(this).apply { setText(R.string.consent); textSize = 18f }
        root.addView(consent)
        send = button(root, R.string.send_code) { requestCode() }
        code = EditText(this).apply {
            hint = getString(R.string.code_hint); inputType = InputType.TYPE_CLASS_NUMBER
            textSize = 24f; importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
            contentDescription = getString(R.string.code_hint)
        }
        root.addView(code)
        verify = button(root, R.string.verify) {
            val entered = code.text.toString()
            if (!policy.validCode(entered)) message(R.string.invalid_code)
            else if (policy.canVerify()) verificationId?.let {
                signIn(PhoneAuthProvider.getCredential(it, policy.asciiDigits(entered)), epoch)
            }
        }
        change = button(root, R.string.change_phone) {
            epoch++; verificationId = null; resendToken = null; code.text.clear(); policy.reset()
            providerAccepted = false; auth.signOut()
            retry.visibility = View.GONE; message(R.string.enter_phone); render()
        }
        retry = button(root, R.string.retry_connection) { exchange(epoch) }.apply { visibility = View.GONE }
        status = TextView(this).apply { textSize = 20f; accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
        root.addView(status)
        sessions = SessionController(SessionStore(applicationContext), MemberApi())
        sessionRetry = button(root, R.string.check_session) { sessionAction { sessions.restore() } }
            .apply { visibility = View.GONE }
        logout = button(root, R.string.sign_out) {
            AlertDialog.Builder(this).setMessage(R.string.sign_out_confirm)
                .setPositiveButton(R.string.sign_out) { _, _ -> sessionAction { sessions.logout(); null } }
                .setNegativeButton(android.R.string.cancel, null).show()
        }.apply { visibility = View.GONE }
        deviceList = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(deviceList)
        try {
            check(listOf(BuildConfig.FIREBASE_API_KEY, BuildConfig.FIREBASE_APP_ID,
                BuildConfig.FIREBASE_PROJECT).all { it.isNotBlank() })
            if (FirebaseApp.getApps(this).isEmpty()) FirebaseApp.initializeApp(this,
                FirebaseOptions.Builder().setApiKey(BuildConfig.FIREBASE_API_KEY)
                    .setApplicationId(BuildConfig.FIREBASE_APP_ID).setProjectId(BuildConfig.FIREBASE_PROJECT).build())
            auth = FirebaseAuth.getInstance()
            auth.signOut() // Amiko sessions, not the provider's cached sign-in, own persistence.
            ready = true
            message(R.string.enter_phone)
            sessionAction { sessions.restore() }
        } catch (_: Exception) { message(R.string.configuration_missing) }
        main.post(ticker)
    }

    private fun requestCode() {
        if (!ready || busy || !policy.canRequest()) return
        val number = policy.indiaPhone(phone.text.toString())
        if (number == null) { message(R.string.invalid_phone); return }
        if (!consent.isChecked) { message(R.string.consent_required); return }
        busy = true; policy.requested(); epoch++
        providerAccepted = false; retry.visibility = View.GONE; auth.signOut()
        val requestEpoch = epoch
        message(R.string.sending); render()
        val callbacks = object : PhoneAuthProvider.OnVerificationStateChangedCallbacks() {
            override fun onVerificationCompleted(credential: PhoneAuthCredential) {
                if (validEpoch(requestEpoch) && !providerAccepted) {
                    busy = false; signIn(credential, requestEpoch)
                }
            }
            override fun onVerificationFailed(error: FirebaseException) {
                if (validEpoch(requestEpoch) && !providerAccepted) {
                    busy = false
                    message(if (error is FirebaseTooManyRequestsException) R.string.rate_limited
                        else if (error is FirebaseNetworkException) R.string.connection_failed else R.string.verification_failed)
                    render()
                }
            }
            override fun onCodeSent(id: String, token: PhoneAuthProvider.ForceResendingToken) {
                if (validEpoch(requestEpoch) && !providerAccepted) {
                    verificationId = id; resendToken = token; busy = false
                    code.text.clear(); message(R.string.code_sent); render()
                }
            }
        }
        val options = PhoneAuthOptions.newBuilder(auth).setPhoneNumber(number)
            .setTimeout(60, TimeUnit.SECONDS).setActivity(this).setCallbacks(callbacks)
        resendToken?.let { options.setForceResendingToken(it) }
        try { PhoneAuthProvider.verifyPhoneNumber(options.build()) }
        catch (_: Exception) { busy = false; message(R.string.verification_failed); render() }
    }

    private fun signIn(credential: PhoneAuthCredential, requestEpoch: Int) {
        if (busy || !validEpoch(requestEpoch)) return
        providerAccepted = true
        busy = true; message(R.string.verifying); render()
        auth.signInWithCredential(credential).addOnCompleteListener(this) { result ->
            if (!validEpoch(requestEpoch)) return@addOnCompleteListener
            busy = false
            if (result.isSuccessful) { code.text.clear(); exchange(requestEpoch) }
            else {
                providerAccepted = false
                if (result.exception is FirebaseAuthInvalidCredentialsException) policy.failedCode()
                message(if (!policy.canVerify()) R.string.request_new_code
                    else if (result.exception is FirebaseTooManyRequestsException) R.string.rate_limited
                    else if (result.exception is FirebaseNetworkException) R.string.connection_failed
                    else R.string.invalid_code)
                render()
            }
        }
    }

    private fun exchange(requestEpoch: Int) {
        if (busy || !validEpoch(requestEpoch) || auth.currentUser == null) return
        busy = true; retry.visibility = View.GONE; message(R.string.connecting); render()
        auth.currentUser!!.getIdToken(true).addOnCompleteListener(this) { result ->
            if (!validEpoch(requestEpoch)) return@addOnCompleteListener
            val proof = if (result.isSuccessful) result.result?.token else null
            if (!result.isSuccessful || proof.isNullOrBlank()) {
                if (BuildConfig.DEBUG) android.util.Log.w("AmikoLoginCheck", "stage=google_proof_failed")
                busy = false; retry.visibility = View.VISIBLE; message(R.string.connection_failed); render()
                return@addOnCompleteListener
            }
            val preferences = getSharedPreferences("amiko_installation", MODE_PRIVATE)
            val installation = preferences.getString("id", null) ?: UUID.randomUUID().toString().also {
                preferences.edit().putString("id", it).apply()
            }
            executor.execute {
                var errorMessage = 0
                val stage = "backend"
                try {
                    sessions.signIn(proof, installation)
                }
                catch (_: LoginRateLimited) { errorMessage = R.string.rate_limited }
                catch (error: Exception) {
                    // Never log exception messages, stack traces, request/response data or tokens.
                    if (BuildConfig.DEBUG) android.util.Log.w("AmikoLoginCheck",
                        "stage=${stage}_failed type=${error.javaClass.simpleName}")
                    errorMessage = R.string.connection_failed
                }
                main.post {
                    if (validEpoch(requestEpoch)) {
                        busy = false
                        if (errorMessage == 0) {
                            auth.signOut()
                            completed = true; phone.text.clear(); code.text.clear(); verificationId = null
                            resendToken = null; message(R.string.signed_in)
                            sessionRetry.visibility = View.VISIBLE
                            logout.visibility = View.VISIBLE
                            sessionAction { sessions.restore() }
                        } else { retry.visibility = View.VISIBLE; message(errorMessage) }
                        render()
                    }
                }
            }
        }
    }

    private fun validEpoch(value: Int) = value == epoch && !isFinishing && !isDestroyed && !completed
    private fun sessionAction(action: () -> SessionView?) {
        if (busy || isFinishing || isDestroyed) return
        busy = true; val actionEpoch = ++epoch
        deviceList.removeAllViews(); message(R.string.checking_session); render()
        executor.execute {
            var view: SessionView? = null
            var error = 0
            try { view = action() }
            catch (_: SessionEnded) { error = R.string.session_ended }
            catch (_: Exception) { error = R.string.session_connection_failed }
            main.post {
                if (actionEpoch != epoch || isFinishing || isDestroyed) return@post
                busy = false
                if (error == R.string.session_connection_failed) {
                    // No offline success claim; preserve credentials if renewal never began.
                    completed = true; sessionRetry.visibility = View.VISIBLE; logout.visibility = View.VISIBLE
                    message(error)
                } else if (view != null && error == 0) {
                    completed = true; phone.text.clear(); code.text.clear(); verificationId = null; resendToken = null
                    sessionRetry.visibility = View.VISIBLE; logout.visibility = View.VISIBLE
                    message(R.string.signed_in)
                    for (device in view!!.devices) {
                        val label = getString(if (device.current) R.string.current_device else R.string.other_device,
                            device.platform)
                        device.lastSeenAt?.let {
                            val seen = java.time.OffsetDateTime.parse(it).atZoneSameInstant(java.time.ZoneId.systemDefault())
                                .format(java.time.format.DateTimeFormatter.ofLocalizedDateTime(
                                    java.time.format.FormatStyle.SHORT).withLocale(resources.configuration.locales[0]))
                            deviceList.addView(TextView(this).apply {
                                text = label + "\n" + getString(R.string.device_last_seen, seen); textSize = 18f
                            })
                        }
                        button(deviceList, R.string.remove_device) {
                            AlertDialog.Builder(this).setMessage(R.string.remove_device_confirm)
                                .setPositiveButton(R.string.remove_device) { _, _ ->
                                    sessionAction { sessions.removeDevice(device.id) }
                                }.setNegativeButton(android.R.string.cancel, null).show()
                        }.text = label + " — " + getString(R.string.remove_device)
                    }
                } else {
                    completed = false; providerAccepted = false
                    verificationId = null; resendToken = null; phone.text.clear(); code.text.clear()
                    consent.isChecked = false; retry.visibility = View.GONE
                    sessionRetry.visibility = View.GONE; logout.visibility = View.GONE
                    if (::auth.isInitialized) auth.signOut()
                    message(if (error == 0) R.string.enter_phone else error)
                }
                render()
            }
        }
    }
    private fun render() {
        if (!::send.isInitialized) return
        phone.visibility = if (completed) View.GONE else View.VISIBLE
        consent.visibility = phone.visibility
        send.visibility = phone.visibility
        change.visibility = phone.visibility
        if (completed) retry.visibility = View.GONE
        phone.isEnabled = ready && !busy && verificationId == null && !completed
        consent.isEnabled = phone.isEnabled
        send.isEnabled = ready && !busy && policy.canRequest() && !completed
        send.text = if (!policy.canRequest()) getString(R.string.wait_seconds, policy.remainingSeconds())
            else getString(if (verificationId == null) R.string.send_code else R.string.resend_code)
        code.visibility = if (verificationId != null && !completed) View.VISIBLE else View.GONE
        code.isEnabled = !busy && policy.canVerify()
        verify.isEnabled = ready && !busy && verificationId != null && policy.canVerify() && !completed
        change.isEnabled = ready && !busy && !completed
        retry.isEnabled = !busy && !completed
        sessionRetry.isEnabled = !busy
        logout.isEnabled = !busy
        for (i in 0 until deviceList.childCount) deviceList.getChildAt(i).isEnabled = !busy
    }
    private fun message(resource: Int) { status.setText(resource) }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun button(root: LinearLayout, label: Int, action: () -> Unit): Button = Button(this).apply {
        setText(label); textSize = 20f; minHeight = dp(56); isAllCaps = false
        setOnClickListener { action() }; root.addView(this)
    }
    override fun onDestroy() {
        epoch++; main.removeCallbacks(ticker); executor.shutdownNow(); super.onDestroy()
    }
    override fun onResume() {
        super.onResume()
        if (ready && completed && !busy) sessionAction { sessions.restore() }
    }
}
