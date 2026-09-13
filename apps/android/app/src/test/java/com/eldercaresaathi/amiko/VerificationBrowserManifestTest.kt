package com.eldercaresaathi.amiko

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.w3c.dom.Element

class VerificationBrowserManifestTest {
    @Test
    fun verificationCanDiscoverBrowserWithoutBroadPackageAccess() {
        val factory = DocumentBuilderFactory.newInstance().apply {
            isNamespaceAware = true
            setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
        }
        val document = factory.newDocumentBuilder().parse(File("src/main/AndroidManifest.xml"))
        val namespace = "http://schemas.android.com/apk/res/android"
        val queries = document.getElementsByTagName("queries")
        assertTrue("Browser discovery queries required", queries.length > 0)
        val intents = (queries.item(0) as Element).getElementsByTagName("intent")
        var httpsBrowser = false
        var customTabs = false
        for (index in 0 until intents.length) {
            val intent = intents.item(index) as Element
            val actions = intent.getElementsByTagName("action")
            val names = (0 until actions.length).map {
                (actions.item(it) as Element).getAttributeNS(namespace, "name")
            }
            customTabs = customTabs || "android.support.customtabs.action.CustomTabsService" in names
            if ("android.intent.action.VIEW" in names) {
                val categories = intent.getElementsByTagName("category")
                val browsable = (0 until categories.length).any {
                    (categories.item(it) as Element).getAttributeNS(namespace, "name") ==
                        "android.intent.category.BROWSABLE"
                }
                val data = intent.getElementsByTagName("data")
                httpsBrowser = httpsBrowser || (browsable && (0 until data.length).any {
                    (data.item(it) as Element).getAttributeNS(namespace, "scheme") == "https"
                })
            }
        }
        assertTrue("HTTPS browser discovery required", httpsBrowser)
        assertTrue("Custom Tab provider discovery required", customTabs)
        val permissions = document.getElementsByTagName("uses-permission")
        assertFalse((0 until permissions.length).any {
            (permissions.item(it) as Element).getAttributeNS(namespace, "name") ==
                "android.permission.QUERY_ALL_PACKAGES"
        })
    }
}
