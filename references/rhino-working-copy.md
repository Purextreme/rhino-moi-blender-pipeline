# Rhino working copy

Use `scripts/rhino-metadata/invoke_working_copy.ps1` after the current metadata snapshot:

```powershell
& '<skill-root>\scripts\rhino-metadata\invoke_working_copy.ps1' -MetadataPath '<metadata.json>' -OutputPath '<new-rhino5.3dm>' -OccurrencesPath '<new-occurrences.json>'
```

Require absolute writable output paths outside the Skill. The output directories must exist and neither output file may exist. This wrapper uses exactly one running Rhino 7 instance, COM `Rhino.Interface.7` and a request/response under `%LOCALAPPDATA%\Codex\RhinoBlenderPipeline`; no manual ScriptEditor operation or Rhino plug-in is needed.

The script compares fresh live metadata against the supplied snapshot, including document path/runtime serial number/modified flag, objects, Layers and definitions. It duplicates the loaded source geometry directly rather than reading an older saved file. This handles unsaved or modified sources without calling Save or altering the source identity.

For each nested occurrence, multiply outer-to-inner transforms, duplicate geometry, transform the copy, and measure its actual tight world BBox. A transformed definition BBox's corners can overestimate rotated geometry and must not replace that measurement. Track cycles on the current recursion path, not a global visited set; repeated definition instances are valid occurrences.

Transport objects receive new `ObjectAttributes.ObjectId` values and unique controlled names, with standalone Normal/visible attributes. The sidecar preserves source IDs, original Layers, names and Block ancestry. Do not use these flattened transport attributes as evidence that the source was already exploded.

Verified Rhino 7 API details:

- Use `Rhino.DocObjects.Material(existing_material)` to copy a material; `Material.Duplicate()` is unavailable.
- Use `ObjectAttributes.ObjectId`, not `Id`, for the copied geometry's identifier.
- `File3dm.Objects.AddBrep(geometry, attributes)` is the typed insertion API; do not assume generic `Objects.Add` accepts the same pair.
- Create destination Layers explicitly; `Layer.Duplicate()` is unavailable, and a Layer table `Add` result must not be assumed to be an index. Inspect the inserted Layer to build the index map.
- A definition member may retain `ObjectMode.InstanceDefinitionObject`; normalize only the copied object's mode. Otherwise MoI can display an empty valid file.

After writing Rhino 5, reopen it as a `File3dm` and verify count, unique tokens, supported valid geometry and standalone modes. Compare the source identity/modified state again. Success requires the current matching response plus both the validated file and occurrence sidecar.

The `.3dm`, sidecar and response are separate commit points. If a write finishes but its sidecar/response fails, treat completion as unknown; inspect existing bytes and source state before recovery. Do not rerun over existing outputs. Use ASCII-safe response serialization and serialize before opening a response file to prevent partial JSON and modal IronPython errors.
