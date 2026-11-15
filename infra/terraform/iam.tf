# Two roles, both narrow.
#
# 1. The instance role can talk to SSM and nothing else. It has no ECR, S3 or
#    Secrets Manager permission because it needs none: the image is public.
# 2. The deploy role can be assumed only by this repository, only from the
#    `production` environment on the deploy job, and can send exactly one
#    document to exactly one instance.

resource "aws_iam_role" "instance" {
  name        = "${var.project}-instance"
  description = "FleetPulse EC2 instance: SSM managed, nothing else"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.project}-instance"
  role = aws_iam_role.instance.name
}

# -- GitHub OIDC ------------------------------------------------------------
data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # AWS validates this provider against its own trust store now; the thumbprint
  # is still required by the API.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

locals {
  github_oidc_arn = var.create_github_oidc_provider ? (
    aws_iam_openid_connect_provider.github[0].arn
  ) : data.aws_iam_openid_connect_provider.github[0].arn

  # Only this repo, only this environment: a fork or a branch cannot assume it.
  deploy_subject = "repo:${var.github_org}/${var.github_repo}:environment:${var.github_environment}"
}

resource "aws_iam_role" "deploy" {
  name        = "${var.project}-deploy"
  description = "Assumed by GitHub Actions to roll out a release over SSM"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.github_oidc_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = local.deploy_subject
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "deploy" {
  name = "${var.project}-deploy"
  role = aws_iam_role.deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "SendCommandToThisInstanceOnly"
        Effect   = "Allow"
        Action   = ["ssm:SendCommand"]
        Resource = [
          aws_instance.app.arn,
          "arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript",
        ]
      },
      {
        Sid    = "ReadTheResult"
        Effect = "Allow"
        # these APIs are account-scoped and cannot be narrowed to a resource
        Action   = ["ssm:GetCommandInvocation", "ssm:ListCommands", "ssm:ListCommandInvocations"]
        Resource = "*"
      },
    ]
  })
}
