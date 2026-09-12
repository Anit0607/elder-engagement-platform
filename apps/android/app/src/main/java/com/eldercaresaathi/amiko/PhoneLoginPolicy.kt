package com.eldercaresaathi.amiko

/** UI guards complement, but do not replace, Google's/server-side abuse controls. */
class PhoneLoginPolicy(private val nowSeconds: () -> Long) {
    var resendAfter = 0L
        private set
    var wrongCodeAttempts = 0
        private set
    fun asciiDigits(input: String) = input.map { character ->
        val digit = Character.digit(character, 10)
        if (digit >= 0) ('0'.code + digit).toChar() else character
    }.joinToString("")
    fun indiaPhone(input: String): String? {
        val digits = asciiDigits(input).filterNot { it.isWhitespace() || it == '-' }
        val national = if (digits.startsWith("+91")) digits.substring(3) else digits
        return if (national.matches(Regex("[0-9]{10}"))) "+91$national" else null
    }
    fun validCode(code: String) = asciiDigits(code).matches(Regex("[0-9]{6}"))
    fun remainingSeconds() = (resendAfter - nowSeconds()).coerceAtLeast(0)
    fun canRequest() = remainingSeconds() == 0L
    fun requested() { resendAfter = nowSeconds() + 60; wrongCodeAttempts = 0 }
    fun failedCode() { wrongCodeAttempts++ }
    fun canVerify() = wrongCodeAttempts < 5
    fun reset() { wrongCodeAttempts = 0 /* Switching number must not bypass resend cooldown. */ }
}
