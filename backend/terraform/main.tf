terraform {
  required_version = ">= 1.6.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
}
}

# ============================================
# AWS Provider - Uses Environment Variables
# ============================================
provider "aws" {
  region = "us-east-1"
  # Automatically uses AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY from environment
}

# ============================================
# Fetch ALL AWS GPU Instances
# ============================================
data "aws_instances" "existing_gpu_instances" {
  filter {
    name   = "instance-type"
    values = ["p3.*", "p4d.*", "g5.*", "g4dn.*"]
  }
  
  filter {
    name   = "instance-state-name"
    values = ["running", "stopped", "stopping", "pending"]
  }
}

# Fetch details for each AWS instance
data "aws_instance" "gpu_details" {
  for_each    = toset(data.aws_instances.existing_gpu_instances.ids)
  instance_id = each.value
}
