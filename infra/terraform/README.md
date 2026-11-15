# infra/terraform

One Graviton instance running the container, plus the two IAM roles that let
GitHub deploy to it without storing an AWS key.

```bash
cp terraform.tfvars.example terraform.tfvars   # fill in admin_cidr, github_org, image
terraform init
terraform apply
```

Then set these repository variables (Settings → Secrets and variables →
Actions → Variables):

| Variable | Where it comes from |
| --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | `terraform output -raw deploy_role_arn` |
| `EC2_INSTANCE_ID` | `terraform output -raw instance_id` |
| `AWS_REGION` | `terraform output -raw aws_region` |

And create an environment named `production` (Settings → Environments) with
required reviewers if you want a human in the loop. The OIDC trust policy
includes the environment name, so a job without it cannot assume the role.

## What each choice buys

| Choice | Why |
| --- | --- |
| `t4g.small` (Graviton) | The image is built for arm64; this is the cloud half of the same cloud-to-edge split as a Jetson |
| `http_tokens = "required"` | IMDSv2 only. A request-forgery bug in the app cannot mint instance credentials |
| `encrypted = true` on the root volume | Nothing on the box is readable if the volume leaks |
| No port 22 rule | No SSH key exists, so there is nothing to leak or rotate |
| `AmazonSSMManagedInstanceCore` only | The instance can be managed, not read your account |
| OIDC role with `environment:production` subject | Short-lived credentials, one repo, one environment, one instance |
| `user_data_replace_on_change` | Changing the boot image or port recreates the box instead of leaving it half-configured |

## Deploy contract

`user_data` installs `/usr/local/bin/fleetpulse-deploy`. CI calls it through SSM:

```bash
aws ssm send-command \
  --instance-ids "$EC2_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters "commands=/usr/local/bin/fleetpulse-deploy ghcr.io/sanchari2/fleetpulse:v0.1.0"
```

The script pulls, replaces the container, and polls `/healthz` for up to a
minute. It exits non-zero if the new container never becomes healthy, so the
workflow fails with the container logs in the SSM output.

## Getting a shell without SSH

```bash
aws ssm start-session --target "$(terraform output -raw instance_id)"
```

Every session and every command is recorded in AWS, which is the point.

## Cost

`t4g.small` plus a 20 GB gp3 volume: roughly a few dollars a month while it
runs. `terraform destroy` when you are done — the demo has no reason to idle.
