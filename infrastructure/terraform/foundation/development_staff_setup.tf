# Separate preparation and deployment let the operator add secret versions
# securely before creating a job that requires them. No plaintext enters Terraform.
resource "google_secret_manager_secret" "fictional_staff_setup" {
  count     = var.prepare_development_staff_secrets ? 1 : 0
  project   = var.project_id
  secret_id = "${local.name_prefix}-fictional-staff-setup-input"
  labels    = merge(local.common_labels, { component = "fictional-staff-setup" })

  replication {
    user_managed {
      replicas { location = var.region }
    }
  }

  lifecycle {
    precondition {
      condition     = var.environment == "development"
      error_message = "Fictional staff secret preparation is development-only."
    }
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "fictional_staff_setup" {
  count     = var.prepare_development_staff_secrets ? 1 : 0
  project   = var.project_id
  secret_id = google_secret_manager_secret.fictional_staff_setup[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_job" "fictional_staff_setup" {
  count               = var.deploy_development_staff_setup_job ? 1 : 0
  project             = var.project_id
  name                = "${local.name_prefix}-fictional-staff-setup"
  location            = var.region
  deletion_protection = false
  labels              = merge(local.common_labels, { component = "fictional-staff-setup" })

  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account       = google_service_account.runtime.email
      max_retries           = 0
      timeout               = "300s"
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = google_compute_network.application.name
          subnetwork = google_compute_subnetwork.serverless.name
        }
      }

      containers {
        image   = coalesce(var.development_staff_setup_image, "invalid.invalid/requires-approved-image@sha256:0000000000000000000000000000000000000000000000000000000000000000")
        command = ["python"]
        args    = ["-m", "app.development_staff_setup"]
        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }

        dynamic "env" {
          for_each = merge(local.cloud_run_environment, {
            EE_STAFF_SESSION_ENABLED = "true"
            # This already-completed, one-time job must never inherit later
            # application account-control activation.
            EE_ACCOUNT_CONTROLS_ENABLED           = "false"
            EE_STAFF_AUTHENTICATOR_KEY_SECRET_REF = "projects/${var.project_id}/secrets/${local.name_prefix}-staff-authenticator-key/versions/${coalesce(var.staff_authenticator_secret_version, "invalid")}"
            STAFF_SETUP_MODE                      = "fictional-development"
            STAFF_SETUP_PROJECT                   = var.project_id
            SOURCE_REVISION                       = coalesce(var.development_staff_setup_source_revision, "invalid")
          })
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = merge(var.member_session_secret_versions, {
            "staff-authenticator-key" = coalesce(var.staff_authenticator_secret_version, "invalid")
          })
          content {
            name = {
              "session-signing-key"     = "AMIKO_SESSION_SIGNING_KEY_BASE64"
              "refresh-token-pepper"    = "AMIKO_REFRESH_PEPPER_BASE64"
              "staff-authenticator-key" = "AMIKO_STAFF_AUTHENTICATOR_KEY_BASE64"
            }[env.key]
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.application[env.key].secret_id
                version = env.value
              }
            }
          }
        }
        env {
          name = "AMIKO_FICTIONAL_STAFF_SETUP_INPUT"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.fictional_staff_setup[0].secret_id
              version = coalesce(var.development_staff_setup_input_version, "invalid")
            }
          }
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition = var.environment == "development" && var.prepare_development_staff_secrets && var.enable_member_session && var.enable_profiles && (
        var.database_application_schema == "engagement_app" &&
        var.staff_authenticator_secret_version != null && var.development_staff_setup_input_version != null
      )
      error_message = "Fictional setup requires the private development runtime, reviewed schema/profiles and prepared numeric secret versions."
    }
    precondition {
      condition = var.development_staff_setup_image == null ? false : (
        startswith(var.development_staff_setup_image, local.approved_image_prefix) &&
        can(regex("@sha256:[0-9a-f]{64}$", var.development_staff_setup_image)) &&
        var.development_staff_setup_source_revision != null
      )
      error_message = "Fictional setup requires a reviewed immutable engagement-api image and exact source revision."
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.runtime, google_secret_manager_secret_iam_member.fictional_staff_setup]
}
