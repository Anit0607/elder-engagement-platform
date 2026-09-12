resource "google_sql_database_instance" "postgres" {
  project             = var.project_id
  name                = "${local.name_prefix}-postgres"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = var.environment == "production"

  settings {
    tier              = var.database_tier
    edition           = "ENTERPRISE"
    availability_type = var.environment == "production" ? "REGIONAL" : "ZONAL"
    data_api_access   = "DISALLOW_DATA_API"
    disk_type         = "PD_SSD"
    disk_size         = var.database_disk_gb
    disk_autoresize   = true
    user_labels       = local.common_labels

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "18:00"
      transaction_log_retention_days = var.environment == "production" ? 7 : 3

      backup_retention_settings {
        retained_backups = var.environment == "production" ? 14 : 7
        retention_unit   = "COUNT"
      }
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.application.id
      enable_private_path_for_google_cloud_services = true
      ssl_mode                                      = "ENCRYPTED_ONLY"
    }

    maintenance_window {
      day          = 7
      hour         = 20
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = true
      record_client_address   = false
    }
  }

  depends_on = [google_project_service.required, google_service_networking_connection.private_services]
}

resource "google_sql_database" "application" {
  project  = var.project_id
  name     = "engagement"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "runtime_iam" {
  project  = var.project_id
  name     = trimsuffix(google_service_account.runtime.email, ".gserviceaccount.com")
  instance = google_sql_database_instance.postgres.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_sql_user" "migration_iam" {
  project  = var.project_id
  name     = trimsuffix(google_service_account.migration.email, ".gserviceaccount.com")
  instance = google_sql_database_instance.postgres.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}
