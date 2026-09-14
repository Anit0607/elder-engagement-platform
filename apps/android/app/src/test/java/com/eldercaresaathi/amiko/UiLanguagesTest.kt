package com.eldercaresaathi.amiko

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.w3c.dom.Element

class UiLanguagesTest {
    @Test
    fun allThreeLanguagesAreSelectableAndSavedChoicesArePreserved() {
        assertEquals(listOf("bn", "hi", "en"), UiLanguages.options.map { it.second })
        assertEquals("English", UiLanguages.options.single { it.second == "en" }.first)
        for ((_, tag) in UiLanguages.options) assertEquals(tag, UiLanguages.selected(tag))
    }

    @Test
    fun missingOrUnsupportedChoiceKeepsTheExistingBengaliDefault() {
        assertEquals("bn", UiLanguages.selected(null))
        assertEquals("bn", UiLanguages.selected(""))
        assertEquals("bn", UiLanguages.selected("unsupported"))
    }

    @Test
    fun everyInterfaceMessageHasEnglishBengaliAndHindiText() {
        val english = messages("values")
        assertTrue(english.isNotEmpty())
        assertEquals(english.keys, messages("values-bn").keys)
        assertEquals(english.keys, messages("values-hi").keys)
        for (directory in listOf("values", "values-bn", "values-hi")) {
            assertTrue(messages(directory).values.all { it.isNotBlank() })
        }
    }

    private fun messages(directory: String): Map<String, String> {
        val factory = DocumentBuilderFactory.newInstance().apply {
            setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
        }
        val strings = factory.newDocumentBuilder()
            .parse(File("src/main/res/$directory/strings.xml")).getElementsByTagName("string")
        return (0 until strings.length).associate {
            val element = strings.item(it) as Element
            element.getAttribute("name") to element.textContent
        }
    }
}
