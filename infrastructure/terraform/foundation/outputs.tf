output "artifact_repository" {
  description = "Artifact Registry repository used by the reviewed delivery workflow."
  value       = google_artifact_registry_repository.containers.name
}

output "cloud_run_service" {
  description = "Cloud Run service name when application deployment is enabled."
  value       = try(google_cloud_run_v2_service.api[0].name, null)
}

output "database_connection_name" {
  description = "Cloud SQL connector name; this is not a credential."
  value       = google_sql_database_instance.postgres.connection_name
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
