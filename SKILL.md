---
name: rhino-moi-blender-pipeline
description: Transfer the active Rhino 7 model through a Rhino 5 working copy and MoI FBX into Blender, preserving source documents, CAD occurrence identity, Empty parent hierarchies, scale and custom normals. Optionally finish simple preview materials and textures when the user supplies appearance references or assets. Use for Rhino to MoI to Blender handoffs, not ordinary Blender imports or Cinema 4D work.
---

# Rhino MoI Blender Pipeline

Complete and verify the model handoff in the open Blender instance. Read [references/workflow.md](references/workflow.md) before operating the applications. Use the external `blender-playbook` Skill for Blender inspection and verification; use Blender MCP for the running application. Cinema 4D and `c4d-remote-executor` are not dependencies.

## Components

- `scripts/rhino-metadata/invoke_export.ps1` exports the active Rhino snapshot through COM; it needs no Rhino plug-in or manual ScriptEditor step. Read [references/rhino-metadata-export.md](references/rhino-metadata-export.md) before use.
- `scripts/rhino-metadata/invoke_working_copy.ps1` and `prepare_working_copy.py` duplicate the loaded geometry, expand nested Block occurrences and write a separate Rhino 5 transport file plus occurrence sidecar. Read [references/rhino-working-copy.md](references/rhino-working-copy.md) first.
- `scripts/blender_pipeline.py` runs through Blender MCP in separate `import`, `diagnose`, `plan`, `rebuild`, and `verify` actions. Read [references/blender-operations.md](references/blender-operations.md) for its contract and invocation.
- MoI meshing uses the actual application. Use an available Computer Use skill for dialogs; inspect the resulting settings before confirming. Application scripting is preferred when the installed version exposes a verified API.

## Optional appearance finish

When the user supplies appearance reference images, product-page links or textures for this model, include simple Blender preview materials and texture placement in the handoff without asking again. Read [references/preview-materials.md](references/preview-materials.md) after the conversion has passed verification. Respect an explicit request to skip materials or retain existing shaders.

When no appearance references or assets are supplied, complete and verify the model transfer with imported materials intact. Do not invent a material scheme or delay the transfer to ask for references. At completion, optionally ask one short question, such as “需要我根据参考图或商品链接，再补一版简单预览材质吗？” Technical documentation links alone do not activate this optional stage.

## Invariants

- Require exactly one Rhino process. Identify the active document, units, runtime serial number, path and modified state; export metadata before expanding Blocks.
- Preserve Rhino source geometry, selection, identity and modified state. Work on duplicated geometry in a separate `File3dm`; never run `ExplodeBlock` on the source.
- Every run has a fresh metadata request ID. Validate this ID throughout the working copy, occurrence sidecar and Blender plan.
- Match occurrences, not unique definition objects. Accumulate nested transforms and measure the transformed geometry itself. Preserve source IDs, full Layer paths and Block occurrence keys.
- The bundled transport supports Breps and surfaces/extrusions converted to Breps. Curves and points are explicitly listed as omitted, not counted as imported meshes. Stop on unsupported meshable geometry instead of silently dropping it.
- Use controlled, unique export tokens together with object-level world BBox validation. Never infer identity from MoI `obj*` names, Blender suffixes alone, import order or overall bounds. If tokens are lost, stop; a separately validated global spatial assignment is needed.
- Determine axes and physical scale per model. Never copy a previous model's mapping or BBox tolerance. A successful import is not proof of correct units.
- Preserve the existing Blender scenes and data. Import into a new Scene; save a protection copy without changing the current `.blend` identity. Do not clear the existing scene.
- Reconstruct Rhino Layers and Block occurrences as parented Empty objects. Use one Collection to package the imported model, not one Collection per Layer. Preserve Block ancestry by creating Layer parents within each Block scope; retain full Layer paths and occurrence IDs as properties. Preserve every mesh and Block `matrix_world` while parenting.
- Omit Layer nodes with no imported descendants, recursively retaining ancestors of populated sublayers. An empty-looking parent with populated children is required structure. Only clean pipeline-owned empty Layer containers; do not remove meshes, hidden geometry, Blocks, materials or unrelated scene data as generic garbage.
- Preserve imported custom normals, geometry and material assignments during conversion and hierarchy reconstruction. Do not apply transforms, merge meshes, recalculate normals or replace shaders as routine cleanup. Intentional material/UV edits belong only to the optional appearance stage after conversion verification; retain recoverable original assignments.
- A timeout or exception after the first side effect means unknown completion. Inspect stage properties, live data and existing files before any retry. Never repeat import or rebuilding to repair viewport framing.
- Require MCP `status: ok` plus task `execution_ok` and `verification_ok` where returned. Perform a separate read-only `verify` call after reconstruction and viewport framing, before optional material edits. After an appearance finish, separately verify geometry, custom normals, transforms, hierarchy and texture appearance; do not weaken the original import checks to accept intentional shader changes.
- Consolidate conversion artifacts into the source-side `codex_export_fbx` folder, compare collisions by SHA-256, and remove temporary transport files only after verification. Keep model-specific files and measurements outside the Skill.

Leave the imported Blender Scene open for review. Save the final `.blend` only when the user requests a destination or approves saving; protection copies are separate from the final deliverable.
