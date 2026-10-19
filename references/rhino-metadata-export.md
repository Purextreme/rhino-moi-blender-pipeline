# Bundled Rhino metadata export

Use the internal component, not a separate `rhino-metadata-export` Skill:

```powershell
& '<skill-root>\scripts\rhino-metadata\invoke_export.ps1' -OutputPath '<absolute-task-path>\rhino_metadata.json'
```

The wrapper requires exactly one Rhino process, connects through `Rhino.Interface.7`, writes a fresh request to `%LOCALAPPDATA%\Codex\RhinoBlenderPipeline`, and invokes the bundled IronPython exporter. A nonzero exit code, `ok: false`, missing output, mismatched request ID or malformed response is failure. Do not close extra Rhino instances automatically.

Require response `request_id` to equal metadata `automation.request_id`, and verify the returned document path, runtime serial number and object counts before using the data. Existing files alone are not proof that the current request completed. Keep runtime metadata outside the Skill and out of version control unless an explicit fixture is requested.

The schema version 2 snapshot includes document units/tolerance/path/modified state, Layers and full paths, top-level objects, nested definitions/members, source IDs, instance transforms, BBoxes, colors/material provenance, visibility/locking, groups and user strings. The document's `modified` field is captured separately from path and counts.

The exporter reads the active in-memory document and never changes geometry, selection, source path or modified state. Before any working-copy write, the next script builds another snapshot and compares semantic document/object/Layer/definition records. Request-specific automation fields are excluded from final semantic equality checks.

For supplemental read-only IronPython probes, explicitly convert CLR scalars to JSON primitives, for example `int(doc.RuntimeSerialNumber)`. Serialize before opening the response file, publish through a temporary file, return the current request ID and a structured failure response, and avoid re-raising into a blocking Rhino error dialog after publishing the failure.

A COM timeout means unknown completion. Inspect the request, output and matching response before deciding whether retry is safe; do not accept an older file or overwrite a potentially completed artifact blindly.
