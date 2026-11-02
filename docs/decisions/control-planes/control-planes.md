---
type: Decision Area
title: "Control planes — one pattern, eight planes, and the traps are shared"
governs: [lambdas/**, infra/modules/shared-spaces/**, infra/modules/table-builder/**, infra/modules/table-share/**, infra/modules/data-quality/**, infra/modules/file-send/**, infra/modules/file-ops/**, infra/modules/results-conversion/**, infra/modules/archive/**, infra/modules/notifications/**, infra/modules/control-plane-dlq-drain/**, infra/modules/observability/**, apps/portal/src/features/shared-spaces/**, apps/portal/src/features/notifications/**, apps/portal/src/features/data-quality/**]
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
