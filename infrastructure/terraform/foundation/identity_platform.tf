resource "google_identity_platform_config" "member_phone" {
  count = var.enable_identity_platform ? 1 : 0

  project = var.project_id

  sign_in {
    phone_number {
      enabled            = true
      test_phone_numbers = var.identity_test_phone_numbers
    }
  }

  sms_region_config {
    allowlist_only {
      allowed_regions = var.identity_sms_allowed_regions
    }
  }

  depends_on = [google_project_service.required]
}
