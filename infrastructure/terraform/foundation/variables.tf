variable "project_id" {
  description = "Google Cloud project dedicated to this environment."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid Google Cloud project identifier."
  }
}

variable "region" {
  description = "Approved region for all regional resources."
  type        = string

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+$", var.region))
    error_message = "region must be a specific Google Cloud region, not a multi-region."
  }
}

variable "environment" {
  description = "Isolated deployment environment."
  type        = string

  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "environment must be development, staging or production."
  }
}

variable "billing_account_id" {
  description = "Billing account used only to scope the mandatory project budget."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$", var.billing_account_id))
    error_message = "billing_account_id must use the Google Cloud billing-account format."
  }
}

variable "state_bucket_name" {
  description = "Remote-state bucket created by state-bootstrap."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "state_bucket_name must be a valid Cloud Storage bucket name."
  }
}

variable "github_owner" {
  description = "GitHub repository owner allowed to federate."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9-]{0,38}$", var.github_owner))
    error_message = "github_owner must be a GitHub account or organisation name."
  }
}

variable "github_repository" {
  description = "Single GitHub repository allowed to federate."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository contains unsupported characters."
  }
}

variable "github_owner_id" {
  description = "Immutable numeric GitHub owner identifier allowed to federate."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "github_owner_id must contain only digits."
  }
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository identifier allowed to federate."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must contain only digits."
  }
}

variable "github_release_ref" {
  description = "Only this Git reference may deploy."
  type        = string
  default     = "refs/heads/main"

  validation {
    condition     = can(regex("^refs/heads/[A-Za-z0-9._/-]+$", var.github_release_ref))
    error_message = "github_release_ref must identify a branch under refs/heads/."
  }
}

variable "monthly_budget_units" {
  description = "Whole-currency monthly project budget."
  type        = number

  validation {
    condition     = var.monthly_budget_units > 0
    error_message = "monthly_budget_units must be greater than zero."
  }
}

variable "budget_currency" {
  description = "ISO 4217 currency matching the billing account."
  type        = string

  validation {
    condition     = can(regex("^[A-Z]{3}$", var.budget_currency))
    error_message = "budget_currency must be a three-letter ISO 4217 currency code."
  }
}

variable "database_tier" {
  description = "Approved Cloud SQL PostgreSQL machine tier."
  type        = string
}

variable "database_disk_gb" {
  description = "Initial Cloud SQL storage in gibibytes."
  type        = number

  validation {
    condition     = var.database_disk_gb >= 10
    error_message = "database_disk_gb must be at least 10."
  }
}

variable "serverless_subnet_cidr" {
  description = "Private subnet used by Cloud Run Direct Virtual Private Cloud egress."
  type        = string
  default     = "10.20.0.0/24"

  validation {
    condition     = can(cidrnetmask(var.serverless_subnet_cidr))
    error_message = "serverless_subnet_cidr must be a valid IPv4 CIDR range."
  }
}

variable "environment_isolation_acknowledged" {
  description = "Explicit acknowledgement that this state and project are dedicated to the selected environment."
  type        = bool

  validation {
    condition     = var.environment_isolation_acknowledged
    error_message = "A dedicated environment project and state must be acknowledged before planning."
  }
}

variable "deploy_application" {
  description = "Create Cloud Run only after an immutable image digest is approved."
  type        = bool
  default     = false
}

variable "container_image" {
  description = "Immutable Artifact Registry image reference ending in a sha256 digest."
  type        = string
  default     = null
  nullable    = true
}

variable "deploy_database_migration_job" {
  description = "Create the dormant Cloud Run migration job only after bootstrap inputs and an immutable image are approved. Terraform never executes it."
  type        = bool
  default     = false
}

variable "database_migration_image" {
  description = "Approved immutable engagement-migration image ending in a sha256 digest."
  type        = string
  default     = null
  nullable    = true
}

variable "database_migration_source_revision" {
  description = "Exact 40-character Git revision embedded in the approved migration image."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.database_migration_source_revision == null ? true : can(regex("^[0-9a-f]{40}$", var.database_migration_source_revision))
    error_message = "database_migration_source_revision must be an exact lowercase 40-character Git revision."
  }
}

variable "database_application_schema" {
  description = "Client-approved PostgreSQL application schema name."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.database_application_schema == null ? true : (
      can(regex("^[a-z][a-z0-9_]{0,62}$", var.database_application_schema)) &&
      !startswith(var.database_application_schema, "pg_") &&
      !contains(["information_schema", "public"], var.database_application_schema)
    )
    error_message = "database_application_schema must be an approved lowercase non-system PostgreSQL identifier."
  }
}

variable "database_migration_schema" {
  description = "Client-approved PostgreSQL migration-control schema name."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.database_migration_schema == null ? true : (
      can(regex("^[a-z][a-z0-9_]{0,62}$", var.database_migration_schema)) &&
      !startswith(var.database_migration_schema, "pg_") &&
      !contains(["information_schema", "public"], var.database_migration_schema)
    )
    error_message = "database_migration_schema must be an approved lowercase non-system PostgreSQL identifier."
  }
}

variable "public_api_origin" {
  description = "Exact externally assigned HTTPS origin for this Cloud Run service or approved custom domain."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.public_api_origin == null ? true : can(regex(
      "^https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$",
      var.public_api_origin
    ))
    error_message = "public_api_origin must be an HTTPS origin containing only a hostname, without a port, path, credentials, query or fragment."
  }
}

variable "allow_unauthenticated" {
  description = "Whether the Cloud Run API can receive unauthenticated requests."
  type        = bool
  default     = false
}

variable "alert_notification_email" {
  description = "Client-approved operational alert recipient. Keep the real address only in an ignored environment values file."
  type        = string
  default     = null
  nullable    = true
  sensitive   = true

  validation {
    condition = var.alert_notification_email == null ? true : can(regex(
      "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$",
      var.alert_notification_email
    ))
    error_message = "alert_notification_email must be null or a valid email address."
  }
}

variable "enable_identity_platform" {
  description = "Enable client-owned phone identity for Member sign-in in this environment."
  type        = bool
  default     = false
}

variable "enable_member_session" {
  description = "Connect reviewed Member sign-in to private Cloud SQL and injected Secret Manager session keys."
  type        = bool
  default     = false
}

variable "enable_staff_session" {
  description = "Enable reviewed staff login only after the staff database migration and enrollment release gates."
  type        = bool
  default     = false
}

variable "prepare_development_staff_secrets" {
  description = "Prepare private secrets for the approved fictional development staff trial without enabling app staff login."
  type        = bool
  default     = false
}

variable "deploy_development_staff_setup_job" {
  description = "Create the dormant fictional-only staff setup job. Terraform never executes it."
  type        = bool
  default     = false
}

variable "development_staff_setup_image" {
  description = "Reviewed immutable engagement-api image for the separate fictional staff setup job."
  type        = string
  default     = null
}

variable "development_staff_setup_source_revision" {
  description = "Exact reviewed source revision embedded in the fictional setup image."
  type        = string
  default     = null

  validation {
    condition     = var.development_staff_setup_source_revision == null ? true : can(regex("^[0-9a-f]{40}$", var.development_staff_setup_source_revision))
    error_message = "The setup source must be an exact lowercase 40-character revision."
  }
}

variable "development_staff_setup_input_version" {
  description = "Pinned numeric Secret Manager version for private fictional setup input. No secret values."
  type        = string
  default     = null

  validation {
    condition     = var.development_staff_setup_input_version == null ? true : can(regex("^[1-9][0-9]*$", var.development_staff_setup_input_version))
    error_message = "The setup input version must be a positive numeric version."
  }
}

variable "staff_authenticator_secret_version" {
  description = "Pinned numeric version of the separate staff authenticator encryption secret; never a secret value."
  type        = string
  default     = null

  validation {
    condition     = var.staff_authenticator_secret_version == null ? true : can(regex("^[1-9][0-9]*$", var.staff_authenticator_secret_version))
    error_message = "The staff authenticator secret version must be a positive numeric version."
  }
}

variable "enable_profiles" {
  description = "Enable reviewed own-profile endpoints after the English preference migration is verified."
  type        = bool
  default     = false
}

variable "enable_profile_photos" {
  description = "Enable private profile-photo upload and viewing after its migration and storage checks pass."
  type        = bool
  default     = false
}

variable "enable_account_controls" {
  description = "Enable reviewed Administrator-only account controls after connected staff sign-in is ready."
  type        = bool
  default     = false
}

variable "member_session_secret_versions" {
  description = "Numeric Secret Manager versions for session-signing-key and refresh-token-pepper. No secret values."
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for key, version in var.member_session_secret_versions :
      contains(["session-signing-key", "refresh-token-pepper"], key) && can(regex("^[1-9][0-9]*$", version))
    ])
    error_message = "Only the two approved session secret names with numeric versions are allowed."
  }
}

variable "identity_test_phone_numbers" {
  description = "Fictional E.164 phone numbers mapped to six-digit test codes. Keep values only in an ignored environment file and rotate them regularly."
  type        = map(string)
  default     = {}
  sensitive   = true

  validation {
    condition = length(var.identity_test_phone_numbers) <= 10 && alltrue([
      for phone, code in var.identity_test_phone_numbers :
      can(regex("^[+][1-9][0-9]{7,14}$", phone)) && can(regex("^[0-9]{6}$", code))
    ])
    error_message = "Use at most ten fictional E.164 phone numbers, each with a six-digit test code."
  }
}

variable "identity_sms_allowed_regions" {
  description = "ISO 3166-1 alpha-2 regions allowed to receive real phone sign-in messages."
  type        = set(string)
  default     = ["IN"]

  validation {
    condition = length(var.identity_sms_allowed_regions) > 0 && alltrue([
      for region in var.identity_sms_allowed_regions : can(regex("^[A-Z]{2}$", region))
    ])
    error_message = "At least one two-letter uppercase region must be allowed for phone sign-in messages."
  }
}
