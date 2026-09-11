locals {
  name_prefix = "ee-${var.environment}"

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
    "billingbudgets.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
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
}
