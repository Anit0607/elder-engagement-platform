resource "google_monitoring_notification_channel" "operations_email" {
  count = var.alert_notification_email == null ? 0 : 1

  project      = var.project_id
  display_name = "${local.name_prefix}-operations-email"
  type         = "email"
  labels = {
    email_address = var.alert_notification_email
  }
  user_labels = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_monitoring_uptime_check_config" "api_health" {
  count = var.deploy_application ? 1 : 0

  project            = var.project_id
  display_name       = "${local.name_prefix}-api-health"
  period             = "60s"
  timeout            = "10s"
  selected_regions   = ["ASIA_PACIFIC", "EUROPE", "USA"]
  log_check_failures = true
  user_labels        = local.common_labels

  http_check {
    path           = "/health"
    port           = 443
    use_ssl        = true
    validate_ssl   = true
    request_method = "GET"

    service_agent_authentication {
      type = "OIDC_TOKEN"
    }

    accepted_response_status_codes {
      status_value = 200
    }
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      host       = local.cloud_run_hostname
      project_id = var.project_id
    }
  }

  content_matchers {
    content = "\"status\":\"ok\""
    matcher = "CONTAINS_STRING"
  }

  depends_on = [google_cloud_run_v2_service.api]
}

resource "google_cloud_run_v2_service_iam_member" "monitoring_uptime" {
  count = var.deploy_application ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-monitoring-notification.iam.gserviceaccount.com"

  depends_on = [google_monitoring_uptime_check_config.api_health]
}

resource "google_monitoring_alert_policy" "api_unavailable" {
  count = var.deploy_application ? 1 : 0

  project      = var.project_id
  display_name = "${local.name_prefix}-api-unavailable"
  combiner     = "OR"
  enabled      = true
  notification_channels = var.alert_notification_email == null ? [] : [
    google_monitoring_notification_channel.operations_email[0].name
  ]
  user_labels = local.common_labels

  conditions {
    display_name = "Health check fails from multiple regions"

    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.label.check_id=\"${google_monitoring_uptime_check_config.api_health[0].uptime_check_id}\" AND resource.type=\"uptime_url\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "120s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.host"]
      }

      trigger {
        count = 1
      }
    }
  }

  documentation {
    mime_type = "text/markdown"
    content   = "Amiko's backend health check has failed from more than one monitoring region for at least two minutes. Check Cloud Run, recent deployments and database availability before changing traffic."
  }

  alert_strategy {
    auto_close = "1800s"
  }

  depends_on = [google_cloud_run_v2_service_iam_member.monitoring_uptime]
}

resource "google_monitoring_alert_policy" "api_error_log" {
  count = var.deploy_application ? 1 : 0

  project      = var.project_id
  display_name = "${local.name_prefix}-api-error-log"
  combiner     = "OR"
  enabled      = true
  notification_channels = var.alert_notification_email == null ? [] : [
    google_monitoring_notification_channel.operations_email[0].name
  ]
  user_labels = local.common_labels

  conditions {
    display_name = "Cloud Run records an error"

    condition_matched_log {
      filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${local.cloud_run_service_name}\" AND severity>=ERROR"
    }
  }

  documentation {
    mime_type = "text/markdown"
    content   = "Amiko's backend recorded an error. Review the matching Cloud Run log, request trace and current revision. Never place credentials or personal data in an incident note."
  }

  alert_strategy {
    auto_close = "1800s"

    notification_rate_limit {
      period = "300s"
    }
  }

  depends_on = [google_cloud_run_v2_service.api]
}
