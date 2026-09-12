package com.eldercaresaathi.amiko

import org.junit.Assert.*
import org.junit.Test

class PhoneLoginPolicyTest {
    @Test fun indiaPhoneAndCodeValidation() {
        val policy = PhoneLoginPolicy { 0 }
        assertEquals("+911234567890", policy.indiaPhone("+91 12345-67890"))
        assertNull(policy.indiaPhone("+1 1234567890"))
        assertNull(policy.indiaPhone("1234"))
        assertNull(policy.indiaPhone("abcdefghij"))
        assertTrue(policy.validCode("123456"))
        assertFalse(policy.validCode("12345"))
        assertFalse(policy.validCode("12345a"))
        assertEquals("+911234567890", policy.indiaPhone("১২৩৪৫৬৭৮৯০"))
        assertEquals("+911234567890", policy.indiaPhone("१२३४५६७८९०"))
        assertTrue(policy.validCode("১২৩৪৫৬"))
        assertEquals("123456", policy.asciiDigits("१२३४५६"))
    }
    @Test fun resendCooldownCannotBeBypassedByChangingNumber() {
        var now = 100L
        val policy = PhoneLoginPolicy { now }
        assertTrue(policy.canRequest())
        policy.requested()
        assertFalse(policy.canRequest())
        now += 59
        assertEquals(1, policy.remainingSeconds())
        policy.reset()
        assertFalse(policy.canRequest())
        now++
        assertTrue(policy.canRequest())
    }
    @Test fun repeatedWrongCodeRequiresNewCode() {
        val policy = PhoneLoginPolicy { 100 }
        repeat(5) { policy.failedCode() }
        assertFalse(policy.canVerify())
        policy.requested()
        assertTrue(policy.canVerify())
    }
}
