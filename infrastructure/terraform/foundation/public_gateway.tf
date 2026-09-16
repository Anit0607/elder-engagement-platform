resource "google_compute_global_address" "public_api" {
  count = var.prepare_public_gateway ? 1 : 0

  project      = var.project_id
  name         = "${local.name_prefix}-public-api"
  description  = "Reserved address for the protected Amiko API gateway"
  address_type = "EXTERNAL"
  ip_version   = "IPV4"
  labels       = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_compute_region_network_endpoint_group" "public_api" {
  count = var.prepare_public_gateway ? 1 : 0

  project               = var.project_id
  name                  = "${local.name_prefix}-public-api"
  region                = var.region
  description           = "Serverless endpoint for the protected Amiko API"
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.api[0].name
  }
}

resource "google_compute_security_policy" "public_api" {
  count = var.prepare_public_gateway ? 1 : 0

  project     = var.project_id
  name        = "${local.name_prefix}-public-api"
  description = "Cloud Armor protections for the Amiko API"
  type        = "CLOUD_ARMOR"

  rule {
    priority    = 900
    action      = "rate_based_ban"
    description = "Temporarily block an address that floods the whole API"

    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }

    rate_limit_options {
      conform_action   = "allow"
      exceed_action    = "deny(429)"
      enforce_on_key   = "IP"
      ban_duration_sec = 600

      rate_limit_threshold {
        count        = 600
        interval_sec = 60
      }

      ban_threshold {
        count        = 1200
        interval_sec = 300
      }
    }
  }

  rule {
    priority    = 1000
    action      = "deny(403)"
    preview     = true
    description = "Observe likely database-injection attacks before enforcement"

    match {
      expr {
        expression = "evaluatePreconfiguredWaf('sqli-v33-stable')"
      }
    }
  }

  rule {
    priority    = 1010
    action      = "deny(403)"
    preview     = true
    description = "Observe likely browser-script attacks before enforcement"

    match {
      expr {
        expression = "evaluatePreconfiguredWaf('xss-v33-stable')"
      }
    }
  }

  rule {
    priority    = 2147483647
    action      = "allow"
    description = "Allow ordinary traffic after security checks"

    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
  }
}

resource "google_compute_backend_service" "public_api" {
  count = var.prepare_public_gateway ? 1 : 0

  project               = var.project_id
  name                  = "${local.name_prefix}-public-api"
  description           = "Protected external backend for the Amiko API"
  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec           = 300
  security_policy       = google_compute_security_policy.public_api[0].id

  backend {
    group = google_compute_region_network_endpoint_group.public_api[0].id
  }

  log_config {
    enable      = true
    sample_rate = 1.0
  }
}

resource "google_compute_url_map" "public_api" {
  count = var.prepare_public_gateway ? 1 : 0

  project         = var.project_id
  name            = "${local.name_prefix}-public-api"
  description     = "Route the approved API hostname to its protected backend"
  default_service = google_compute_backend_service.public_api[0].id
}

resource "google_compute_managed_ssl_certificate" "public_api" {
  count = var.prepare_public_gateway ? 1 : 0

  project     = var.project_id
  name        = "${local.name_prefix}-public-api"
  description = "Google-managed certificate for the approved Amiko API hostname"

  managed {
    domains = [lower(var.public_api_hostname)]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_target_https_proxy" "public_api" {
  count = var.prepare_public_gateway ? 1 : 0

  project          = var.project_id
  name             = "${local.name_prefix}-public-api"
  description      = "HTTPS entry point for the protected Amiko API"
  url_map          = google_compute_url_map.public_api[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.public_api[0].id]
}

resource "google_compute_global_forwarding_rule" "public_api" {
  count = var.prepare_public_gateway ? 1 : 0

  project               = var.project_id
  name                  = "${local.name_prefix}-public-api-https"
  description           = "Receive HTTPS traffic for the protected Amiko API"
  ip_address            = google_compute_global_address.public_api[0].id
  ip_protocol           = "TCP"
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  network_tier          = "PREMIUM"
  target                = google_compute_target_https_proxy.public_api[0].id
  labels                = local.common_labels
}
