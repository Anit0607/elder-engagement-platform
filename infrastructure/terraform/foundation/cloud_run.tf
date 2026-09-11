resource "google_cloud_run_v2_service" "api" {
  count = var.deploy_application ? 1 : 0

  project             = var.project_id
  name                = "${local.name_prefix}-api"
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

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      env {
        name  = "EE_ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "EE_GCP_PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "EE_GCP_REGION"
        value = var.region
      }

      env {
        name  = "EE_CLOUD_SQL_INSTANCE"
        value = google_sql_database_instance.postgres.connection_name
      }

      env {
        name  = "EE_UPLOADS_BUCKET"
        value = google_storage_bucket.uploads.name
      }

      env {
        name  = "EE_APPROVED_MEDIA_BUCKET"
        value = google_storage_bucket.approved_media.name
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
      condition     = !var.deploy_application || (var.container_image != null && can(regex("@sha256:[0-9a-f]{64}$", var.container_image)))
      error_message = "Cloud Run deployment requires an immutable image reference ending in @sha256:<64 lowercase hexadecimal characters>."
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service_iam_member" "public_api" {
  count = var.deploy_application && var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
