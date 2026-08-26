# ── The container runtime ─────────────────────────────────────────────────────
# A Fargate cluster, one task definition and one service. What the container IS — the
# Dockerfile, the nginx configuration, what /healthz serves — belongs to the spec that
# builds the image; everything about how it runs is here.

resource "aws_ecs_cluster" "spa" {
  name = local.spa_name

  # ENABLED because the scanner gate's own criterion says to fix this class rather than
  # disposition it while the resource is new. It bills per metric on a cluster running one small
  # task, and it is the only view of task-level CPU and memory a design with no host access has.
  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { Name = local.spa_name }
}

# DECLARED, not created by the awslogs driver's `awslogs-create-group`. A group the driver
# creates is unmanaged and retained forever, and `retention_in_days` is an enforced scanner
# gate. The stronger reason is diagnostic: with no group at all every task dies at start with
# ResourceInitializationError, which during verification is indistinguishable from the
# CannotPullContainerError the whole no-NAT design is tested by.
resource "aws_cloudwatch_log_group" "spa" {
  name              = "/ecs/${local.spa_name}"
  retention_in_days = 14
}

# ── The task definition ───────────────────────────────────────────────────────
# The environment block is this module's, and it is DERIVED: one CONFIG_ entry per key in the
# runtime-configuration map root builds, never a hand-written list. A hand-written list is how
# a container ships serving seven of twenty-one values — every required key present, every
# optional one missing, and a portal with no shared spaces, no notifications and no queues.
#
# THE NAMING CONVENTION IS CONFIG_<documentKey>, and the container's entrypoint reads exactly that:
# the same prefix and the same camelCase key deploy-app.yml's render step already uses, so the
# two producers of /config.json name their inputs identically.
locals {
  config_environment = [
    for key in sort(keys(var.runtime_config)) : {
      name  = "CONFIG_${key}"
      value = var.runtime_config[key]
    }
  ]

  # The writable pair. `readonlyRootFilesystem` is what makes them necessary, and the mechanism is
  # `linuxParameters.tmpfs` — MEASURED, after task-level volumes were tried and could not work.
  #
  # A Fargate task volume arrives as a fresh, EMPTY, root-owned directory. It does not initialise
  # from the image, so a container running as a non-root user cannot write to it: the container
  # printed `uid=101(nginx)` beside `drwxr-xr-x root root /tmp` and `drwxr-xr-x root root
  # /var/cache/nginx` — the second of which the base image ships owned by 101, which is how we
  # know nothing is copied. nginx then died on `mkdir() "/tmp/proxy_temp" failed (13: Permission
  # denied)`, a message that reads as a container bug and is not one.
  #
  # tmpfs takes uid, gid and mode as mount options, which is the whole difference: the mount is
  # created owned by the user that has to write to it.
  writable_paths = ["/tmp", "/var/cache/nginx"]

  # The container's user, named once: the task definition sets it and every tmpfs mount is created
  # owned by it. Split between the two, a mount is silently unwritable by the process that needs it.
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

  # DECLARED, not defaulted. The default is X86_64 either way, but a placeholder image built by
  # hand on an Apple Silicon laptop is arm64, and the task then fails with an image-manifest
  # error that reads nothing like the architecture mismatch it is. Stating it here means the
  # build command has something to agree with.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "spa"
      image     = "${aws_ecr_repository.spa.repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]

      # uid 101 is nginx-unprivileged's own user. Named here rather than left to the image so
      # the task definition states the claim the acceptance criterion makes.
      user                   = local.container_uid
      readonlyRootFilesystem = true

      # EACH MOUNT IS CREATED OWNED BY THE CONTAINER'S USER. That is what task-level volumes
      # could not do, and it is the entire reason this is a tmpfs rather than a volume.
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
# Platform version 1.4.0 is pinned rather than left at LATEST, and it is load-bearing: on
# 1.3.0 the image pull travelled a separate Amazon-owned ENI to which VPC endpoints did not
# apply, so the whole endpoints-instead-of-a-NAT design silently does not hold.
#
# The circuit breaker is ENABLED WITH ROLLBACK DISABLED. With rollback on and no previous good
# task set, a missing image reads as a rollback rather than as CannotPullContainerError — which
# is the one diagnosis this arc's central claim is tested by. The spec that pushes a real image
# may enable rollback once a good task set exists.
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
    # THE IMAGE IS CI's, from the spec that builds it: its deploy registers a new revision and
    # points the service at it, and without this every later infra apply would point the
    # service straight back at whatever tag Terraform last rendered.
    #
    # `desired_count` is deliberately NOT in this list, and the plan review that asked for it
    # was measured against the wrong document: the spec makes the count a Terraform variable
    # whose raise from 0 to 1 is a verification STEP, and an ignored attribute makes that step
    # a silent no-op that reads as a broken service. If a later spec introduces autoscaling or
    # a CI-side scale, the count joins this list then — with the variable retired in the same
    # change, so one owner is losing it rather than two quietly disagreeing.
    ignore_changes = [task_definition]
  }

  # Two edges Terraform does not infer. The target group must be attached to a listener before
  # ECS will register a target against it — it infers the group but not the listener. And the
  # execution role's POLICY is reachable only through the role, so at any desired count above
  # zero a task could start before the pull grant exists; with rollback disabled that failed
  # deployment then needs a manual force-new-deployment to clear.
  depends_on = [
    aws_lb_listener.https,
    aws_iam_role_policy.task_execution,
  ]

  tags = { Name = local.spa_name }
}
