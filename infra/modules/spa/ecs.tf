# ── The container runtime ─────────────────────────────────────────────────────
# What the container IS belongs to the image; everything about how it runs is here. README.md.

resource "aws_ecs_cluster" "spa" {
  name = local.spa_name

  # The only view of task-level CPU and memory a design with no host access has.
  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { Name = local.spa_name }
}

# DECLARED, not created by awslogs-create-group. With no group at all every task dies at
# start with ResourceInitializationError, INDISTINGUISHABLE during verification from the
# CannotPullContainerError the no-NAT design is tested by. README.md.
resource "aws_cloudwatch_log_group" "spa" {
  name              = local.log_group_name
  retention_in_days = 14
}

# ── The task definition ───────────────────────────────────────────────────────
# The environment block is DERIVED — one CONFIG_<documentKey> entry per key in root's runtime
# config map, NEVER a hand-written list. A hand-written list is how a container ships serving
# seven of twenty-one values, with every optional key missing. README.md.
locals {
  config_environment = [
    for key in sort(keys(var.runtime_config)) : {
      name  = "CONFIG_${key}"
      value = var.runtime_config[key]
    }
  ]

  # tmpfs, NOT a task volume — MEASURED. A Fargate task volume arrives EMPTY and root-owned
  # and does not initialise from the image, so a non-root container cannot write to it and
  # nginx dies on a permission error that reads as a container bug. README.md.
  writable_paths = ["/tmp", "/var/cache/nginx"]

  # ONE uid feeding both `user` and every mount option. Split between the two, a mount is
  # silently unwritable by the process that needs it.
  container_uid = "101"
}

resource "aws_ecs_task_definition" "spa" {
  family                   = local.spa_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  # DECLARED, not defaulted. An image built by hand on Apple Silicon is arm64, and the task
  # fails with a manifest error that reads nothing like the architecture mismatch it is.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "spa"
      image     = "${var.repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]

      # uid 101 is nginx-unprivileged's own user.
      user                   = local.container_uid
      readonlyRootFilesystem = true

      # EACH MOUNT IS CREATED OWNED BY THE CONTAINER'S USER — the entire reason this is a
      # tmpfs rather than a volume.
      linuxParameters = {
        tmpfs = [
          for path in local.writable_paths : {
            containerPath = path
            size          = 64
            mountOptions  = ["uid=${local.container_uid}", "gid=${local.container_uid}", "mode=1777"]
          }
        ]
      }

      environment = concat(local.config_environment, [
        {
          name  = "PORTAL_CSP_CONNECT_SRC"
          value = var.csp_connect_src
        }
      ])

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.spa.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "spa"
        }
      }
    }
  ])

  tags = { Name = local.spa_name }
}

# ── The service ───────────────────────────────────────────────────────────────
# PLATFORM VERSION 1.4.0 IS PINNED AND LOAD-BEARING: on 1.3.0 the image pull travelled a
# separate Amazon-owned ENI that VPC endpoints did not apply to, so the whole
# endpoints-instead-of-a-NAT design silently does not hold.
#
# Circuit breaker ENABLED WITH ROLLBACK DISABLED — with rollback on and no previous good task
# set, a missing image reads as a rollback rather than CannotPullContainerError. README.md.
resource "aws_ecs_service" "spa" {
  name             = local.spa_name
  cluster          = aws_ecs_cluster.spa.id
  task_definition  = aws_ecs_task_definition.spa.arn
  desired_count    = var.desired_count
  launch_type      = "FARGATE"
  platform_version = "1.4.0"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.task_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.spa.arn
    container_name   = "spa"
    container_port   = var.container_port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = false
  }

  health_check_grace_period_seconds = 60

  lifecycle {
    # ⚠ CI MUST POINT THE SERVICE, not merely register a revision — a pipeline that only
    # registers leaves a CannotPullContainerError indistinguishable from the endpoint failure
    # the platform is tested for.
    #
    # `desired_count` is deliberately NOT here: its raise from 0 to 1 is a verification STEP,
    # and ignoring it makes that step a silent no-op reading as a broken service. README.md.
    ignore_changes = [task_definition]
  }

  # Two edges Terraform does not infer: the listener (it infers the target group but not
  # that), and the execution role's POLICY, reachable only through the role — a task could
  # otherwise start before the pull grant exists.
  depends_on = [
    aws_lb_listener.https,
    aws_iam_role_policy.task_execution,
  ]

  tags = { Name = local.spa_name }
}
