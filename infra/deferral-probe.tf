# TEMPORARY, reverted before merge. The positive control: a read behind the same edge, which the
# plan must show as read during apply, or the probe above did not defer anything.
data "aws_partition" "deferral_control" {
  depends_on = [module.base]
}

resource "terraform_data" "deferral_control" {
  input = data.aws_partition.deferral_control.partition
}
