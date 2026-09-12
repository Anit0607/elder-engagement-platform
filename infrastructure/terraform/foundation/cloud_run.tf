resource "google_cloud_run_v2_service" "api" {
  count = var.deploy_application ? 1 : 0

  project             = var.project_id
  name                = local.cloud_run_service_name
  location            = var.region
  deletion_protection = var.environment == "production"
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = local.common_labels

  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "60s"
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
        for_each = local.cloud_run_environment
        content {
          name  = env.key
          value = env.value
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
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service_iam_member" "github_verifier" {
  count = var.deploy_application ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_cloud_run_v2_service_iam_member" "public_api" {
  count = var.deploy_application && var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
