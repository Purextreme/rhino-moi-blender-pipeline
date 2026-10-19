# Workflow

## Preflight and Rhino snapshot

Load `blender-playbook`. Confirm Blender MCP can read the intended running instance; capture Blender version, current file/Scene, dirty state, object inventory, units and FBX operator properties. Inspect current MoI contents before opening another file. Preserve existing work in every application.

Require one Rhino 7 process and export metadata using the bundled wrapper. Verify response `ok`, metadata `automation.request_id`, source path, document runtime serial number, units and modified state. Count top-level types and live InstanceReferences, and inspect definitions. Viewport appearance is not evidence that a model has been exploded.

Keep baseline metadata for semantic comparison at acceptance. Choose an ASCII-only writable transport directory if MoI cannot handle the source path. Runtime files never belong inside the Skill.

## Rhino 5 transport and occurrence sidecar

Run `invoke_working_copy.ps1` with the current metadata, distinct `.3dm` and sidecar paths. Its bundled script:

1. Builds fresh live metadata and requires semantic equality with the baseline before copying.
2. Creates a separate in-memory `File3dm` using the live document's units/tolerance.
3. Walks top-level geometry and nested Blocks. Multiplies outer-to-inner instance transforms, detects definition cycles along the current recursion path, and gives each occurrence a separate key.
4. Duplicates and transforms supported geometry without changing the source. Uses `ObjectAttributes.ObjectId` for new transport IDs and a unique `RB_...` token for each geometry occurrence.
5. Makes standalone transport attributes Normal and visible so definition-only or hidden flags cannot silently remove geometry in MoI. Source visibility/locking remain recorded for reconstruction. Source Layer identity remains in the sidecar; temporary MoI style names are not reconstruction identity.
6. Reopens the Rhino 5 file to validate geometry, count, tokens and standalone modes. Rechecks source identity and modified state before publishing the sidecar.

The version 2 sidecar is the authoritative occurrence schema. `occurrences` contains `key`, `parent`, `source_id`, `transport_name`, source `layer`/name/type/display metadata, and the BBox measured from transformed geometry. `blocks` contains occurrence keys, parent keys, definition IDs/names and accumulated world matrices. Both carry effective visibility and locking computed through object, Layer and Block ancestry. A visible definition member inside a hidden/locked Block must remain effectively hidden/locked in Blender. `omitted` lists each excluded non-mesh object.

The bundled script accepts Breps, Surface and Extrusion conversion. It does not claim Mesh/SubD or arbitrary annotation support. Stop for a dedicated adapter on unsupported meshable geometry. Curves/points require a separate explicitly requested conversion if they must appear in Blender.

Do not re-export over an existing file. A nonzero `.3dm` without its sidecar/response is a partial commit; inspect the file, request ID and source state before recovering. Do not silently overwrite it.

## MoI meshing

Open the validated transport copy, wait for loading and visually inspect the geometry. Use Save As/Export to a distinct ASCII `.fbx`. Do not save the Rhino source through MoI.

Use the originating pipeline's meshing preset unless the user specifies otherwise:

| Setting | Value |
|---|---|
| Output | N-gons |
| Display | Shaded + edges |
| Weld vertices along edges | Checked |
| Angle | 3 |
| Divide larger than | 20, All |
| Avoid smaller than | 0.5 |
| Aspect ratio limit | 0 |

These lengths use the MoI document's units; they are a meshing preset, not a geometric error bound. Verify the high-detail slider is consistent with Angle 3. Numeric fields may open a keypad: commit the field, wait for remeshing, and inspect the settled value before continuing. Prefer the separate dialog screenshot and its own screenshot ID when a scaled main-window screenshot produces ineffective input. Reobserve after failed input; do not assume an error or an immediate stale frame proves the action did not happen.

MoI's developer documents `geometryDatabase.fileExport(path, options)` with `Angle`, `Output`, `MaxLength`, `MaxLengthApplyTo`, `MinLength`, `AspectRatio`, `Weld`, and `Display` options. Consult the installed command sources and [developer's parameter explanation](https://moi3d.com/forum/lmessages.php?msg=11689.7&webtag=MOI) before using a version-specific script. A scripted call still requires file and downstream geometry verification; do not assume `NoUI=true` proves settings or completion.

Require a nonzero FBX. Preview point counts can include rendering/normal splits; compare actual imported mesh counts and topology rather than requiring MoI preview points to equal Blender vertices.

## Blender import and planning

Use `blender_pipeline.py` through MCP, following [blender-operations.md](blender-operations.md). A new Scene isolates the model; original scenes and objects remain present. Require all expected meshes and imported custom normals. The initial stage refuses an existing import Scene to avoid duplicates.

First use `diagnose` to inspect mapping and per-occurrence errors. Physical length comes from Rhino document units and Blender Scene unit scale, not the displayed length-unit label. The helper creates and verifies a METRIC Scene with `scale_length=1.0` (one Blender unit = one meter); changing that scale after import must fail planning/rebuilding/verification. Blender's importer may honor FBX units/axes itself; do not add another 0.001 scale or rotate the model without measured evidence.

The bundled planner groups only exact controlled transport tokens (with Blender numeric suffixes permitted for verified split parts), evaluates signed axis permutations at the known physical scale, and estimates translation from multiple token-paired object centers. Require a unique mapping, every group present, source-envelope containment and accepted BBox error for every occurrence. It never matches by the ordinal encoded in a token.

Set `bbox_tolerance_source_units` from units, intended use and actual meshing evidence. CAD analytic BBoxes and tessellated mesh BBoxes can differ. On a failed tolerance check inspect the worst objects: verify identity, orientation, scale, trimming and curved extrema. Do not merely increase tolerance until the check passes. If quality is inadequate, revise meshing and repeat from a fresh import Scene with a new checked FBX.

The bundled planner refuses lost/unknown tokens, even for equal counts. If accepting an external FBX without controlled names, create a separate global BBox assignment with an explicit ambiguity check; do not weaken this planner or force assignments by object order/material names. For excess meshes, accept only groups that retain unique controlled provenance and pass union-envelope and per-part containment checks. Otherwise stop for inspection.

## Hierarchy and verification

Reconstruction must use the checked plan and unchanged FBX/sidecar hashes. Validate active Scene, request ID, imported mesh set, matrices, geometry, custom normals and material signatures before the first hierarchy side effect.

Create one model packaging Collection and a root Empty. Represent full Layer paths and nested Block occurrences with Empty parent objects. A mesh or Block attaches to the appropriate Layer Empty within its enclosing Block scope; repeat Layer paths inside different Block scopes when necessary to preserve both hierarchies. Only create Layer nodes that lead to imported objects; retain populated sublayer ancestors and omit entirely empty branches. Do not delete hidden meshes, source geometry or unrelated data as cleanup. Block transforms are `source_to_blender @ source_world_matrix @ inverse(source_to_blender)`. Reparent meshes and Blocks with a saved `matrix_world`, then restore it and update the dependency graph. Keep imported mesh data and materials intact. Source visibility/locking should be represented on the new data only; retain original Layer/Block IDs and full paths as properties even when Blender adds name suffixes.

Inspect both MCP and script result fields. After a separate read-only `verify`, require:

- one imported group for every supported source occurrence and no unassigned meshes;
- expected Layer/Block Empty parent graph, one model Collection, and no unused Layer branches;
- correct physical scale and object-level BBoxes within the accepted CAD-to-mesh tolerance;
- unchanged mesh vertex/loop/polygon data, custom normal signatures, material slots and polygon material indices across hierarchy mutation;
- unchanged world matrices and near-zero world-BBox drift after parenting;
- original Blender objects/scenes and file identity preserved;
- fresh Rhino metadata semantically equal to the original document/object/Layer/definition snapshot, excluding request-specific automation fields, including unchanged modified state.

Frame the imported model in a 3D View and inspect a screenshot. Viewport shading can improve readability without replacing materials or changing geometry. A framing failure is not an import failure. Keep preview rigs separate from model contents when an appearance finish needs a render. Final `.blend` saving still requires the user's requested destination or approval.

## Final artifact consolidation

Use `<original source folder>\codex_export_fbx` by default; an unsaved source uses the task's writable outputs directory. Use distinct filenames for the Rhino 5 copy, MoI FBX, metadata, occurrence sidecar, reconstruction plan and any protection copy retained for recovery.

Resolve exact paths and compare SHA-256 before any collision cleanup. Reuse identical destination files and delete only verified transport duplicates. Refuse to overwrite differing files. Switch the pipeline Scene's manifest/plan paths to the consolidated files, and verify again with those paths. A sidecar's original `transport_path` is historical export provenance; use consolidated paths for future reimports.

Remove a temporary transport directory only after proving it empty, without recursive deletion. Keep scripts and model-specific results separate.

## Optional appearance and completion

After conversion, consolidation and the independent import `verify` have passed, follow [preview-materials.md](preview-materials.md) when the user supplied model appearance references, product-page links or texture assets. Complete the simple material/texture finish and its visual and structural checks before reporting completion. No supplied appearance reference means skip this stage, preserve imported shaders and optionally ask one short material follow-up at the end. Do not block the transfer waiting for optional resources or a follow-up answer.

Summarize conversion outcome, omitted geometry, artifact location and save state in chat. If appearance work ran, include the sources actually inspected, materials/textures applied, visual verification and remaining approximations. A separate case report is optional, not required.
