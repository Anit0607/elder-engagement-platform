provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "storage" {
  project                    = var.project_id
  service                    = "storage.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

locals {
  common_labels = {
    application = "elder-engage"
    environment = var.environment
    managed_by  = "terraform"
    data_class  = "restricted"
  }
}

resource "google_storage_bucket" "terraform_state" {
  name                        = var.state_bucket_name
  project                     = var.project_id
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = 604800
    is_locked        = false
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 20
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.storage]
}

output "state_bucket_name" {
  description = "Bucket name to place in the local backend configuration."
  value       = google_storage_bucket.terraform_state.name
}
