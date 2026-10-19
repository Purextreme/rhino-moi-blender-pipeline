# Blender operation contract

Use the running Blender MCP. Inspect the script before first use. The executable helper imports only Blender's bundled `numpy`, `bpy`, `mathutils` and standard-library modules; no Blender-side package installation is needed.

Provide `ACTION` and `CONFIG` in an isolated namespace and return its `result` through MCP:

```python
path = r'<skill-root>\scripts\blender_pipeline.py'
namespace = {'__name__': '__main__', 'ACTION': 'import', 'CONFIG': config}
exec(compile(open(path, encoding='utf-8').read(), path, 'exec'), namespace)
result = namespace['result']
```

`config` contains absolute task paths and per-run values:

| Key | Use |
|---|---|
| `request_id` | Current Rhino metadata `automation.request_id` |
| `scene_name` | Distinct new Blender Scene name |
| `fbx_path` | Verified nonzero MoI FBX |
| `occurrences_path` | Working-copy occurrence sidecar |
| `backup_path` | New protection `.blend` path; import only |
| `plan_path` | New reconstruction plan JSON; plan/rebuild/verify |
| `root_name` | Model root Collection/Empty; rebuild only |
| `bbox_tolerance_source_units` | Explicit CAD-to-mesh BBox tolerance in Rhino units; diagnose/plan |
| `mapping_gap_m` | Required separation from the next candidate mapping in summed meter errors; diagnose/plan |

Do not use a model-specific path, mapping, count or tolerance from this Skill. Obtain them from the current run. Diagnostic results are observations, not automatic permission to relax a failed gate.

## Actions

1. `import`: save a protection copy with `copy=True`, push Undo, create a new Scene, and import using the installed `bpy.ops.import_scene.fbx` with embedded axes/units, `global_scale=1`, custom normals on, animation/image search off. Verify these properties exist via RNA for the actual Blender version. If only another importer is available, inspect its API and write a guarded adapter instead of forwarding unsupported parameters.
2. `diagnose`: read-only scene analysis. Returns per-object BBox outliers, the best Rhino-to-Blender mapping and the next-candidate gap. Writes no plan and makes no scene changes.
3. `plan`: enforce identity, geometry, mapping, normal and count gates; exclusively create `plan_path`. Does not change the scene hierarchy. Inspect its successful result before rebuilding.
4. `rebuild`: assert that the validated inputs and imported mesh state have not changed; create one model Collection and nested Layer/Block Empty parents while preserving world matrices. Skip Layers with no imported descendants. Runs verification and returns `execution_ok`/`verification_ok`.
5. `verify`: independent read-only acceptance using the sidecar and plan, including old scene inventory, source assignments, geometry/material/normal fingerprints and world transforms.

`scene['rhino_stage']` records `importing`, `imported`, `rebuilding`, or `rebuilt`. If a call fails after mutation, a fresh read-only probe must inspect this value, scene contents and protection copy. The script intentionally refuses blind repeated import/rebuild. A state flag alone never proves success; successful independent verification is required.

The helper uses exact world BBoxes from all mesh vertices rather than transforming object bound-box corners. CAD BBoxes come from the transformed Rhino geometry. Local geometry and normal hashes remain invariant under hierarchy changes; a separate world-space matrix/BBox check catches misplaced parenting. Original material slots are preserved, but MoI FBX does not establish that Rhino procedural/PBR materials or external textures were faithfully translated. Report shader limitations separately when relevant.

Layer parents are identified by `(rhino_layer_scope, rhino_layer_path)`, with an empty scope for the model root and a Block occurrence key for a Block-local scope. A Block or mesh attaches to its full Layer path inside its enclosing Block scope. This keeps nested Blocks intact even when definition members use different Layers. Repeated Layer names across scopes are intentional; Blender suffixes are not identity. Layer Empty transforms start at their scope's origin with identity local transforms. Source effective visibility and locking are applied to every mesh/Block explicitly, since hiding an Empty does not automatically hide its children. Verification checks the exact parent graph, package Collection membership and absence of unused Layer nodes as well as geometry invariants.

For a changed active scene, stop before rebuilding and reselect the identified pipeline Scene only when appropriate. Never remove unrelated objects or recover by opening a `.blend` over the user's current work without approval.

## Boundary with optional materials

The five script actions verify the conversion, including the imported material slots and polygon material indices. Run `verify` after consolidation and before the optional appearance stage described in [preview-materials.md](preview-materials.md). These actions do not create preview materials.

After intentional shader/UV edits, the original `verify` may correctly reject the changed material signatures. Do not replace plan fingerprints with the new materials, disable assertions or claim that this unchanged verifier passed. Use a separate read-only appearance acceptance check: compare original geometry/custom-normal fingerprints, occurrence identity, world matrices/BBoxes, parent graph, collection membership and prior-scene state; independently check intended material assignments, image loading/packing, UV orientation/scale and a real screenshot or render. Preserve the original plan and recoverable pre-material assignments.
