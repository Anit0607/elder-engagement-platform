output "artifact_repository" {
  description = "Artifact Registry repository used by the reviewed delivery workflow."
  value       = google_artifact_registry_repository.containers.name
}

output "cloud_run_service" {
  description = "Cloud Run service name when application deployment is enabled."
  value       = try(google_cloud_run_v2_service.api[0].name, null)
}

output "cloud_run_uri" {
  description = "Cloud Run URI when application deployment is enabled."
  value       = try(google_cloud_run_v2_service.api[0].uri, null)
}

output "database_connection_name" {
  description = "Cloud SQL connector name; this is not a credential."
  value       = google_sql_database_instance.postgres.connection_name
}

output "deployment_environment" {
  description = "Environment recorded in the protected Terraform state."
  value       = var.environment
}

output "deployment_project_id" {
  description = "Google Cloud project recorded in the protected Terraform state."
  value       = var.project_id
}

output "deployment_region" {
  description = "Google Cloud region recorded in the protected Terraform state."
  value       = var.region
}

output "database_instance_name" {
  description = "Cloud SQL instance recorded in the protected Terraform state."
  value       = google_sql_database_instance.postgres.name
}

output "database_name" {
  description = "PostgreSQL database recorded in the protected Terraform state."
  value       = google_sql_database.application.name
}

output "github_repository_slug" {
  description = "GitHub owner and repository recorded in the protected Terraform state."
  value       = "${var.github_owner}/${var.github_repository}"
}

output "database_migration_job" {
  description = "Dormant migration job name when explicitly enabled; Terraform does not execute it."
  value       = try(google_cloud_run_v2_job.database_migration[0].name, null)
}

output "database_runtime_iam_user" {
  description = "PostgreSQL IAM username used by the application runtime."
  value       = google_sql_user.runtime_iam.name
}

output "database_migration_iam_user" {
  description = "PostgreSQL IAM username used only by the controlled migration runner."
  value       = google_sql_user.migration_iam.name
}

output "github_deployer_service_account" {
  description = "Service account identifier to configure as a GitHub environment variable."
  value       = google_service_account.github_deployer.email
}

output "github_workload_identity_provider" {
  description = "Provider identifier to configure as a GitHub environment variable."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "upload_signer_service_account" {
  description = "Dedicated create-only identity used to sign direct-upload requests."
  value       = google_service_account.upload_signer.email
}

output "secret_containers" {
  description = "Created secret containers. Values must be inserted out of band."
  value       = { for name, secret in google_secret_manager_secret.application : name => secret.id }
}
