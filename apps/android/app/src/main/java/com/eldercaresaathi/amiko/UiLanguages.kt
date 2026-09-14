package com.eldercaresaathi.amiko

/** App-interface languages only; uploaded content is not automatically translated. */
object UiLanguages {
    val options = listOf("বাংলা" to "bn", "हिन्दी" to "hi", "English" to "en")

    fun selected(saved: String?): String =
        options.firstOrNull { it.second == saved }?.second ?: "bn"
}
