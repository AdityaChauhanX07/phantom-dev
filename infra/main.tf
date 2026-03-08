terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # TODO: configure remote state backend (GCS bucket)
  # backend "gcs" {
  #   bucket = "your-tfstate-bucket"
  #   prefix = "phantom-dev/state"
  # }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Run"
  type        = string
  default     = "us-central1"
}

variable "gemini_api_key" {
  description = "Gemini API key (stored in Secret Manager in production)"
  type        = string
  sensitive   = true
}

# ---------------------------------------------------------------------------
# Cloud Run — Agent service
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "agent" {
  name     = "phantom-dev-agent"
  location = var.region

  template {
    containers {
      image = "gcr.io/${var.gcp_project_id}/phantom-dev-agent:latest"

      env {
        name  = "GEMINI_API_KEY"
        value = var.gemini_api_key
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.gcp_project_id
      }

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  # TODO: restrict to VPC / authenticated callers in production
}

# Allow unauthenticated invocations (development only — restrict in prod)
resource "google_cloud_run_service_iam_member" "agent_public" {
  location = google_cloud_run_v2_service.agent.location
  service  = google_cloud_run_v2_service.agent.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------------------------------------------------------------------------
# Firestore database
# ---------------------------------------------------------------------------

resource "google_firestore_database" "default" {
  project     = var.gcp_project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "agent_url" {
  description = "Public URL of the Cloud Run agent service"
  value       = google_cloud_run_v2_service.agent.uri
}
