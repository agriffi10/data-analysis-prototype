---
type: Decision Area
title: "Control planes — one pattern, eight planes, and the traps are shared"
governs: [lambdas/**, infra/modules/control-plane/**, infra/modules/scheduled-function/**, infra/modules/shared-space-storage/**, infra/control-planes.tf, infra/planes/shared-spaces/**, infra/plane-shared-spaces.tf, infra/planes/table-builder/**, infra/plane-table-builder.tf, infra/planes/table-share/**, infra/plane-table-share.tf, infra/planes/data-quality/**, infra/plane-data-quality.tf, infra/planes/file-send/**, infra/plane-file-send.tf, infra/planes/file-ops/**, infra/plane-file-ops.tf, infra/planes/results-conversion/**, infra/plane-results-conversion.tf, infra/planes/archive/**, infra/plane-archive.tf, infra/modules/queue-consumer/**, infra/function-notifications.tf, infra/functions/notifications/**, infra/function-feedback.tf, infra/functions/feedback/**, infra/function-control-plane-dlq-drain.tf, infra/functions/control-plane-dlq-drain/**, infra/modules/observability/**, infra/function-log-sweep.tf, infra/functions/log-sweep/**, apps/portal/src/features/shared-spaces/**, apps/portal/src/features/notifications/**, apps/portal/src/features/data-quality/**]
---

The register's decisions on the shape every privileged pipeline follows, the ASL and notification fences, the layer split, structured logging.

Shared spaces, table builder, table share, data quality, file send, **archive**, file
operations and results conversion each get:
a **FIFO SQS** queue → EventBridge Pipe → Step Functions → single-task verb Lambdas, **one execution
role per plane** and its own DLQ; `cpcommon` and a domain module are a CODE split, not a packaging
one, since the cutover. The DLQ is the plane's own because the drain names the feature by the DLQ
a request lands on; a malformed body is not what sends a request there, since the plane refuses it
inside the execution the Pipe starts.

**The traps, every one of which ships green:**
