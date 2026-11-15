terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # Local state on purpose: this is a demo that costs money while it exists.
  # For anything shared, move this to an S3 backend with locking.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project      = var.project
      ManagedBy    = "terraform"
      Environment  = "demo"
      Architecture = "arm64"
    }
  }
}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

# Amazon Linux 2023, arm64: resolves through SSM so the AMI stays current
# without hard-coding an id per region.
data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "app" {
  name        = "${var.project}-app"
  description = "FleetPulse API: inbound on the app port only, no SSH"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "API from the operator's address"
    from_port   = var.app_port
    to_port     = var.app_port
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  # No port 22 rule, deliberately: access is SSM Session Manager only.
  egress {
    description = "Outbound for image pulls, package installs and SSM"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-app"
  }
}

resource "aws_instance" "app" {
  ami                         = data.aws_ssm_parameter.al2023_arm64.value
  instance_type               = var.instance_type
  subnet_id                   = sort(data.aws_subnets.default.ids)[0]
  vpc_security_group_ids      = [aws_security_group.app.id]
  iam_instance_profile        = aws_iam_instance_profile.app.name
  associate_public_ip_address = true
  monitoring                  = true

  # IMDSv2 only: a request-forgery bug in the app cannot reach instance
  # credentials, because credentials need a token that needs a PUT.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "disabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.volume_size_gb
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/user_data.sh.tftpl", {
    image = var.image
    port  = var.app_port
  })

  user_data_replace_on_change = true

  tags = {
    Name = "${var.project}-app"
  }

  lifecycle {
    # The AMI moves as Amazon publishes new images; replacing a demo box on
    # every apply is not what you want. Patch deliberately instead.
    ignore_changes = [ami]
  }
}
