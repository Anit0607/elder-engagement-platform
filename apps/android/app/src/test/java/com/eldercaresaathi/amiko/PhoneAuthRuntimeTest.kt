package com.eldercaresaathi.amiko

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import androidx.core.content.ContextCompat
import java.lang.reflect.Modifier
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Check the actual resolved library, not just a declared dependency version. */
class PhoneAuthRuntimeTest {
    @Test
    fun phoneVerificationHasRequiredReceiverRegistrationMethod() {
        val method = ContextCompat::class.java.getMethod(
            "registerReceiver",
            Context::class.java,
            BroadcastReceiver::class.java,
            IntentFilter::class.java,
            Int::class.javaPrimitiveType,
        )
        assertTrue(Modifier.isStatic(method.modifiers))
        assertEquals(Intent::class.java, method.returnType)
    }
}
