resource "google_storage_bucket" "uploads" {
  name                        = "${var.project_id}-${local.name_prefix}-uploads"
  project                     = var.project_id
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = var.environment == "production" ? 30 : 7
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "approved_media" {
  name                        = "${var.project_id}-${local.name_prefix}-approved"
  project                     = var.project_id
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 10
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  lifecycle_rule {
    condition {
      days_since_noncurrent_time = var.environment == "production" ? 30 : 7
      matches_prefix             = ["profile-photos/"]
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket_iam_member" "upload_signer_creates_uploads" {
  bucket = google_storage_bucket.uploads.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.upload_signer.email}"
}

resource "google_storage_bucket_iam_member" "runtime_manages_profile_photo_quarantine" {
  bucket = google_storage_bucket.uploads.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.runtime.email}"
  condition {
    title      = "profile-photo-quarantine-only"
    expression = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.uploads.name}/objects/profile-photo-quarantine/')"
  }
}

resource "google_storage_bucket_iam_member" "runtime_manages_content_quarantine" {
  bucket = google_storage_bucket.uploads.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.runtime.email}"
  condition {
    title      = "content-quarantine-only"
    expression = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.uploads.name}/objects/content-quarantine/')"
  }
}

resource "google_storage_bucket_iam_member" "runtime_manages_approved_profile_photos" {
  bucket = google_storage_bucket.approved_media.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.runtime.email}"
  condition {
    title      = "approved-profile-photos-only"
    expression = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.approved_media.name}/objects/profile-photos/')"
  }
}

resource "google_storage_bucket_iam_member" "upload_signer_reads_approved_profile_photos" {
  bucket = google_storage_bucket.approved_media.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.upload_signer.email}"
  condition {
    title      = "approved-profile-photos-only"
    expression = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.approved_media.name}/objects/profile-photos/')"
  }
}

resource "google_storage_bucket_iam_member" "moderation_viewer_reads_content_quarantine" {
  bucket = google_storage_bucket.uploads.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.moderation_viewer.email}"
  condition {
    title      = "content-quarantine-preview-only"
    expression = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.uploads.name}/objects/content-quarantine/')"
  }
}
