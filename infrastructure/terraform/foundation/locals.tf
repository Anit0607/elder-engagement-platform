locals {
  name_prefix                     = "ee-${var.environment}"
  cloud_run_service_name          = "ee-${var.environment}-api"
  bootstrap_api_origin            = "https://${local.cloud_run_service_name}.bootstrap.invalid"
  cloud_run_origin                = coalesce(var.public_api_origin, local.bootstrap_api_origin)
  cloud_run_hostname              = trimprefix(local.cloud_run_origin, "https://")
  approved_image_prefix           = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.containers.repository_id}/engagement-api@sha256:"
  approved_migration_image_prefix = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.containers.repository_id}/engagement-migration@sha256:"

  common_labels = {
    application = "elder-engage"
    environment = var.environment
    managed_by  = "terraform"
    cost_center = "elder-engage"
    data_class  = "restricted"
  }

  required_services = toset([
    "artifactregistry.googleapis.com",
    "cloudbilling.googleapis.com",
    "cloudasset.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "identitytoolkit.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "serviceusage.googleapis.com",
    "sqladmin.googleapis.com",
    "sts.googleapis.com"
  ])

  secret_names = toset([
    "database-url",
    "field-encryption-key",
    "refresh-token-pepper",
    "session-signing-key"
  ])

  runtime_project_roles = toset([
    "roles/cloudsql.client",
    "roles/cloudsql.instanceUser",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter"
  ])

  cloud_run_environment = {
    EE_ENVIRONMENT                      = var.environment
    EE_APP_NAME                         = "Elder Engage API"
    EE_API_PREFIX                       = "/v1"
    EE_LOG_LEVEL                        = "INFO"
    EE_GCP_PROJECT_ID                   = var.project_id
    EE_GCP_REGION                       = var.region
    EE_PUBLIC_API_ORIGIN                = local.cloud_run_origin
    EE_TRUSTED_HOSTS                    = local.cloud_run_hostname
    EE_CORS_ORIGINS                     = local.cloud_run_origin
    EE_CLOUD_SQL_INSTANCE               = google_sql_database_instance.postgres.connection_name
    EE_DATABASE_URL_SECRET_REF          = "projects/${var.project_id}/secrets/${local.name_prefix}-database-url/versions/latest"
    EE_RATE_LIMIT_STORE                 = "memory"
    EE_REDIS_URL_SECRET_REF             = ""
    EE_SESSION_SIGNING_KEY_SECRET_REF   = "projects/${var.project_id}/secrets/${local.name_prefix}-session-signing-key/versions/latest"
    EE_REFRESH_TOKEN_PEPPER_SECRET_REF  = "projects/${var.project_id}/secrets/${local.name_prefix}-refresh-token-pepper/versions/latest"
    EE_FIELD_ENCRYPTION_KEY_SECRET_REF  = "projects/${var.project_id}/secrets/${local.name_prefix}-field-encryption-key/versions/latest"
    EE_MEMBER_IDENTITY_PROVIDER         = "mock"
    EE_FIREBASE_PROJECT_ID              = ""
    EE_MEMBER_TOKEN_AUDIENCE            = ""
    EE_UPLOADS_BUCKET                   = google_storage_bucket.uploads.name
    EE_APPROVED_MEDIA_BUCKET            = google_storage_bucket.approved_media.name
    EE_UPLOAD_SIGNER_SERVICE_ACCOUNT    = google_service_account.upload_signer.email
    EE_UPLOAD_MAX_BYTES                 = "10485760"
    EE_UPLOAD_ALLOWED_MIME_TYPES        = "video/mp4,audio/mpeg,application/pdf"
    EE_UPLOAD_AUTHORIZATION_SECONDS     = "300"
    EE_FCM_ENABLED                      = "false"
    EE_FCM_PROJECT_ID                   = ""
    EE_YOUTUBE_ENABLED                  = "false"
    EE_YOUTUBE_API_KEY_SECRET_REF       = ""
    EE_MEET_MODE                        = "disabled"
    EE_MEET_OAUTH_CLIENT_SECRET_REF     = ""
    EE_BROADCAST_PROVIDER               = "disabled"
    EE_AGORA_APP_ID                     = ""
    EE_AGORA_APP_CERTIFICATE_SECRET_REF = ""
    EE_ACCESS_TOKEN_MINUTES             = "10"
    EE_REFRESH_TOKEN_DAYS               = "30"
  }
}
