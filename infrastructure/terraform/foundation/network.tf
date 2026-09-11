resource "google_compute_network" "application" {
  project                 = var.project_id
  name                    = "${local.name_prefix}-network"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.required]
}

resource "google_compute_subnetwork" "serverless" {
  project                  = var.project_id
  name                     = "${local.name_prefix}-serverless"
  region                   = var.region
  network                  = google_compute_network.application.id
  ip_cidr_range            = var.serverless_subnet_cidr
  private_ip_google_access = true
}

resource "google_compute_global_address" "private_services" {
  project       = var.project_id
  name          = "${local.name_prefix}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.application.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.application.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}
