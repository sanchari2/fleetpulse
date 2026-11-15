output "instance_id" {
  description = "Set this as the EC2_INSTANCE_ID repository variable."
  value       = aws_instance.app.id
}

output "deploy_role_arn" {
  description = "Set this as the AWS_DEPLOY_ROLE_ARN repository variable."
  value       = aws_iam_role.deploy.arn
}

output "aws_region" {
  description = "Set this as the AWS_REGION repository variable."
  value       = var.aws_region
}

output "public_ip" {
  description = "Public address of the instance."
  value       = aws_instance.app.public_ip
}

output "app_url" {
  description = "Where the API answers once the first container is up."
  value       = "http://${aws_instance.app.public_ip}:${var.app_port}"
}

output "image" {
  description = "Image the instance booted with."
  value       = var.image
}

output "architecture" {
  description = "Instance architecture, for the record."
  value       = "arm64 (Graviton)"
}
