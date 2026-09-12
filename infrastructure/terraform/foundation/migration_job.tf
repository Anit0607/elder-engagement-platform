resource "google_cloud_run_v2_job" "database_migration" {
  count = var.deploy_database_migration_job ? 1 : 0

  project             = var.project_id
  name                = "${local.name_prefix}-database-migration"
  location            = var.region
  deletion_protection = var.environment == "production"
  labels              = merge(local.common_labels, { component = "database-migration" })

  template {
    parallelism = 1
    task_count  = 1

    template {
      service_account       = google_service_account.migration.email
      max_retries           = 0
      timeout               = "900s"
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = google_compute_network.application.name
          subnetwork = google_compute_subnetwork.serverless.name
        }
      }

      containers {
        image = coalesce(var.database_migration_image, "invalid.invalid/requires-approved-migration-image@sha256:0000000000000000000000000000000000000000000000000000000000000000")

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        env {
          name  = "MIGRATION_MODE"
          value = "production"
        }
        env {
          name  = "INSTANCE_CONNECTION_NAME"
          value = google_sql_database_instance.postgres.connection_name
        }
        env {
          name  = "DB_NAME"
          value = google_sql_database.application.name
        }
        env {
          name  = "DB_MIGRATION_IAM_USER"
          value = google_sql_user.migration_iam.name
        }
        env {
          name  = "DB_RUNTIME_IAM_USER"
          value = google_sql_user.runtime_iam.name
        }
        env {
          name  = "APP_SCHEMA"
          value = coalesce(var.database_application_schema, "requires_approved_application_schema")
        }
        env {
          name  = "MIGRATION_SCHEMA"
          value = coalesce(var.database_migration_schema, "requires_approved_migration_schema")
        }
        env {
          name  = "SOURCE_REVISION"
          value = coalesce(var.database_migration_source_revision, "requires-approved-source-revision")
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition = !var.deploy_database_migration_job || (
        var.database_migration_image != null &&
        startswith(var.database_migration_image, local.approved_migration_image_prefix) &&
        can(regex("@sha256:[0-9a-f]{64}$", var.database_migration_image))
      )
      error_message = "The migration job requires an immutable engagement-migration digest from this environment's approved Artifact Registry repository."
    }
    precondition {
      condition = !var.deploy_database_migration_job || (
        var.database_migration_source_revision != null &&
        can(regex("^[0-9a-f]{40}$", var.database_migration_source_revision))
      )
      error_message = "The migration job requires the exact Git revision represented by the approved image."
    }
    precondition {
      condition = !var.deploy_database_migration_job || (
        var.database_application_schema != null &&
        var.database_migration_schema != null &&
        var.database_application_schema != var.database_migration_schema
      )
      error_message = "Distinct client-approved application and migration-control schema names are required before creating the job."
    }
  }

  depends_on = [
    google_project_service.required,
    google_sql_user.migration_iam,
    google_sql_user.runtime_iam,
  ]
}
