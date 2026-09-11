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

variable "allow_unauthenticated" {
  description = "Whether the Cloud Run API can receive unauthenticated requests."
  type        = bool
  default     = false
}
