# ============================================
# AWS Outputs - Existing Instances
# ============================================

output "aws_existing_instance_ids" {
  description = "All existing AWS GPU instance IDs"
  value       = data.aws_instances.existing_gpu_instances.ids
}

output "aws_existing_instances_details" {
  description = "Details of all existing AWS GPU instances"
  value = {
    for id, instance in data.aws_instance.gpu_details : id => {
      id                = instance.id
      instance_type     = instance.instance_type
      public_ip         = instance.public_ip
      private_ip        = instance.private_ip
      state             = instance.instance_state
      availability_zone = instance.availability_zone
      tags              = instance.tags
    }
  }
}

output "summary" {
  description = "Summary of all GPU instances"
  value = {
    aws_count = length(data.aws_instances.existing_gpu_instances.ids)
    total     = length(data.aws_instances.existing_gpu_instances.ids)
  }
}