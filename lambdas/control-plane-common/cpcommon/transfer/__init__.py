"""The shared bulk-transfer engine: manifest out, batched copy, results back in.

A control plane that copies many objects between S3 prefixes writes a JSON Lines manifest of
``(destination, source)`` items, hands it to a Step Functions Distributed Map, and reads the
Map Run's exported results back to attribute per-item failures. Three modules, one each for
those steps, plus the sizing constants both the verbs and the rendered ASL read.

Table-share is the first caller; the send-files plane is the second and the archive
plane the third, which is why the engine lives here rather than in a domain layer — cpcommon
owns the algorithm, a domain layer owns its wording.

Import-free like the parent package, and for the parent's reason: it attaches to every
control-plane verb, so an import here is cold-start cost paid by functions that never transfer
anything.
"""
