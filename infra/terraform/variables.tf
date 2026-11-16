variable "aws_region" {
  description = "Region to deploy into."
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "fleetpulse"
}

variable "instance_type" {
  description = "Graviton (arm64) instance type. Anything else breaks the point of the build."
  type        = string
  default     = "t4g.small"

  validation {
    condition     = can(regex("^[a-z]+[0-9]+[a-z]?g\\.", var.instance_type))
    error_message = "Use an arm64 Graviton type such as t4g.small, m7g.medium or c7g.large."
  }
}

variable "image" {
  description = "Full image reference to run, including the tag."
  type        = string
  default     = "ghcr.io/OWNER/fleetpulse:latest"

  validation {
    condition     = can(regex("^[a-z0-9./:_-]+$", var.image))
    error_message = "image must be a plain registry/repo:tag reference."
  }
}

variable "app_port" {
  description = "Port the API listens on, and the only inbound port opened."
  type        = number
  default     = 8000
}

variable "admin_cidr" {
  description = "Your public IP in CIDR form (e.g. 203.0.113.4/32). Never leave this as 0.0.0.0/0."
  type        = string

  validation {
    condition     = can(cidrhost(var.admin_cidr, 0))
    error_message = "admin_cidr must be valid CIDR, for example 203.0.113.4/32."
  }
}

variable "volume_size_gb" {
  description = "Encrypted gp3 root volume size."
  type        = number
  default     = 20
}

variable "github_org" {
  description = "GitHub user or organisation that owns the repo."
  type        = string
}

variable "github_repo" {
  description = "Repository name, without the owner."
  type        = string
  default     = "fleetpulse"
}

variable "github_branch" {
  description = "Branch allowed to assume the deploy role."
  type        = string
  default     = "main"
}

variable "github_environment" {
  description = "GitHub environment name the deploy job uses; it is part of the trust policy."
  type        = string
  default     = "production"
}

variable "create_github_oidc_provider" {
  description = "Set false if the account already has the token.actions.githubusercontent.com provider."
  type        = bool
  default     = true
}
