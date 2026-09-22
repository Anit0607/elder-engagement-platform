resource "google_cloud_run_v2_service" "api" {
  count = var.deploy_application ? 1 : 0

  project             = var.project_id
  name                = local.cloud_run_service_name
  location            = var.region
  deletion_protection = var.environment == "production"
  ingress             = var.activate_public_gateway ? "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" : "INGRESS_TRAFFIC_ALL"
  # Domain-restricted sharing can reject an allUsers IAM binding. Only the
  # activated gateway may use Google's public-invoker alternative; ingress
  # then prevents bypassing Cloud Armor through the direct run.app address.
  invoker_iam_disabled = var.activate_public_gateway && var.allow_unauthenticated
  labels               = local.common_labels

  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = var.enable_content_uploads ? "300s" : "60s"
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = var.environment == "production" ? 1 : 0
      max_instance_count = var.environment == "production" ? 10 : 2
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = google_compute_network.application.name
        subnetwork = google_compute_subnetwork.serverless.name
      }
    }

    containers {
      image = coalesce(var.container_image, "invalid.invalid/requires-approved-image@sha256:0000000000000000000000000000000000000000000000000000000000000000")

      ports {
        name           = "http1"
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      dynamic "env" {
        for_each = merge(
          local.cloud_run_environment,
          { EE_PROFILE_PHOTO_ENABLED = tostring(var.enable_profile_photos) },
          var.enable_content_uploads ? { EE_CONTENT_UPLOAD_ENABLED = "true" } : {},
          var.enable_content_moderation ? {
            EE_CONTENT_MODERATION_ENABLED        = "true"
            EE_MODERATION_SIGNER_SERVICE_ACCOUNT = google_service_account.moderation_viewer.email
          } : {},
          var.enable_content_feed ? {
            EE_CONTENT_FEED_ENABLED                    = "true"
            EE_CONTENT_DELIVERY_SIGNER_SERVICE_ACCOUNT = google_service_account.content_delivery.email
          } : {},
          var.enable_event_service ? { EE_EVENT_SERVICE_ENABLED = "true" } : {}
        )
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.enable_member_session ? var.member_session_secret_versions : {}
        content {
          name = env.key == "session-signing-key" ? "AMIKO_SESSION_SIGNING_KEY_BASE64" : "AMIKO_REFRESH_PEPPER_BASE64"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.application[env.key].secret_id
              version = env.value
            }
          }
        }
      }

      dynamic "env" {
        for_each = var.enable_staff_session ? [1] : []
        content {
          name = "AMIKO_STAFF_AUTHENTICATOR_KEY_BASE64"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.application["staff-authenticator-key"].secret_id
              version = var.staff_authenticator_secret_version
            }
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12

        tcp_socket {
          port = 8080
        }
      }

      liveness_probe {
        initial_delay_seconds = 10
        timeout_seconds       = 3
        period_seconds        = 30
        failure_threshold     = 3

        http_get {
          path = "/health"
          port = 8080

          http_headers {
            name  = "Host"
            value = local.cloud_run_hostname
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }
  }

  lifecycle {
    precondition {
      condition     = !var.enable_content_moderation || var.enable_content_uploads
      error_message = "Content moderation requires private Contributor uploads."
    }
    precondition {
      condition     = !var.enable_content_feed || var.enable_content_moderation
      error_message = "Content feed requires the reviewed moderation workflow."
    }
    precondition {
      condition     = !var.enable_event_service || var.enable_profiles
      error_message = "Events require the connected profile and circle runtime."
    }
    precondition {
      condition     = !var.enable_account_controls || var.enable_staff_session
      error_message = "Account controls require connected staff authentication and its database readiness gates."
    }
    precondition {
      condition     = !var.enable_profiles || var.enable_member_session
      error_message = "Profiles require the connected identity runtime; the profile database migration is checked at startup."
    }
    precondition {
      condition     = !var.enable_staff_session || (var.enable_member_session && var.staff_authenticator_secret_version != null)
      error_message = "Staff login requires the connected Member runtime and a separate pinned authenticator secret. Database readiness is also checked at application startup."
    }
    precondition {
      condition = !var.enable_member_session || (
        var.enable_identity_platform &&
        var.database_application_schema == "engagement_app" &&
        contains(keys(var.member_session_secret_versions), "session-signing-key") &&
        contains(keys(var.member_session_secret_versions), "refresh-token-pepper")
      )
      error_message = "Member login requires enabled Google identity, the approved application schema and both numeric session-secret versions."
    }
    precondition {
      condition = !var.deploy_application || (
        var.container_image != null &&
        startswith(var.container_image, local.approved_image_prefix) &&
        can(regex("@sha256:[0-9a-f]{64}$", var.container_image))
      )
      error_message = "Cloud Run requires an immutable engagement-api digest from this environment's approved Artifact Registry repository."
    }
    precondition {
      condition     = !var.deploy_application || var.environment == "development"
      error_message = "The current health-service deployment candidate is development-only."
    }
    precondition {
      condition = !var.deploy_application || var.public_api_origin != null || (
        var.environment == "development" && !var.allow_unauthenticated
      )
      error_message = "A public API origin is required before any non-development or unauthenticated deployment."
    }
    precondition {
      condition = !var.prepare_public_gateway || (
        var.deploy_application &&
        var.public_api_hostname != null
      )
      error_message = "Public gateway preparation requires a deployed application and a client-controlled API hostname."
    }
    precondition {
      condition = !var.activate_public_gateway || (
        var.prepare_public_gateway &&
        var.allow_unauthenticated &&
        var.public_api_origin == local.public_gateway_origin
      )
      error_message = "Public activation requires the prepared gateway, explicit unauthenticated API access and an origin that exactly matches the protected hostname."
    }
    precondition {
      condition     = !var.allow_unauthenticated || var.activate_public_gateway
      error_message = "Unauthenticated access is allowed only through the activated protected public gateway."
    }
  }

  depends_on = [google_project_service.required, google_secret_manager_secret_iam_member.runtime]
}

resource "google_cloud_run_v2_service_iam_member" "github_verifier" {
  count = var.deploy_application ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.github_deployer.email}"
}
