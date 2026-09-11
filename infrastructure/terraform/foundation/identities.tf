resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "${local.name_prefix}-runtime"
  display_name = "Elder Engage ${var.environment} runtime"
}

resource "google_service_account" "migration" {
  project      = var.project_id
  account_id   = "${local.name_prefix}-migration"
  display_name = "Elder Engage ${var.environment} database migration"
}

resource "google_service_account" "github_deployer" {
  project      = var.project_id
  account_id   = "${local.name_prefix}-github"
  display_name = "Elder Engage ${var.environment} GitHub deployer"
}

resource "google_service_account" "upload_signer" {
  project      = var.project_id
  account_id   = "${local.name_prefix}-upload"
  display_name = "Elder Engage ${var.environment} upload signer"
}

resource "google_project_iam_member" "runtime" {
  for_each = local.runtime_project_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "migration_cloudsql" {
  for_each = toset(["roles/cloudsql.client", "roles/cloudsql.instanceUser"])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.migration.email}"
}

resource "google_project_iam_member" "github_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_service_account_iam_member" "github_uses_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_service_account_iam_member" "runtime_uses_upload_signer" {
  service_account_id = google_service_account.upload_signer.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_artifact_registry_repository_iam_member" "github_pushes_images" {
  project    = var.project_id
  location   = google_artifact_registry_repository.containers.location
  repository = google_artifact_registry_repository.containers.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.github_deployer.email}"
}
