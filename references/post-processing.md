# Default model post-processing

Run after the original import/hierarchy checks and before optional materials. This stage is part of every normal handoff. Preserve current user edits when applying it later to an already edited scene; do not reimport or restore deleted objects to match an old plan.

## Scale and origins

`blender_pipeline.py` automatically calls `blender_cleanup.py` at the end of `rebuild`. Supply new absolute `cleanup_path` and `cleanup_backup_path` values before rebuilding. The helper refuses existing evidence files, takes a protection copy, records a prepared acceptance receipt before mutation, then independently checks the result before marking it verified.

- Limit cleanup to the identified model root and its descendants. Do not apply transforms to unrelated scenes, cameras, lights or preview floor geometry.
- Bake mesh Scale and delta Scale into mesh data and expose `(1,1,1)` channels. Process parents before children and restore child world transforms after each parent change. Make shared mesh data single-user before editing it, preserving unrelated users.
- Default `origin_mode='auto'`: only if **all** mesh origins are within 1 micrometre of world zero, move every mesh origin to its own local bounding-box center, equivalent to Origin to Geometry with Bounds center. A lone offset/intentional pivot disables automatic centering for the whole mesh set. The test excludes Empties because they have no geometry.
- Keep Empty group pivots. Bake group scale with child compensation. A parented Empty used as a UV Warp/texture reference retains its mapping matrix through its parent offset while its visible Scale channels become one; this avoids changing an editable UV rig. Do not treat such a controller as removable garbage.
- Applying this to an edited scene may use standalone `blender_cleanup.py` with `ACTION='inspect'`, `'clean'`, then a separate `'verify'`. Use `origin_mode='geometry'` only when the user explicitly requests centering or checked original import evidence proves common CAD origins; `'keep'` preserves intentionally placed pivots. Inspect current geometry, references and user edits first. Do not bypass the fresh pipeline's original import verification to accommodate edited content.
- The bundled helper handles static Mesh/Empty hierarchies and UV Warp. Geometry modifiers, animation, constraints, shape keys, linked libraries, singular transforms or unsupported attributes require a dedicated inspected adapter before mutation. Do not remove them to make a gate pass.

The transformation changes local coordinates and matrices intentionally. Acceptance compares every original and evaluated world-space vertex and corner-normal direction, topology/attributes, base and evaluated UVs, materials, occurrence IDs, hierarchy, visibility, unrelated objects and file identity. All Scale/delta Scale channels must be one; centered local bounds must contain zero at their midpoint.

Custom normals are re-encoded only after all vertex/origin edits. Blender's compressed custom-normal representation may introduce small direction differences even with unchanged topology. The helper bounds the **angular** difference to 0.05 degrees and reports the observed maximum; it never accepts a sign flip as rounding. Position tolerance is the recorded floating-point allowance (`max(1e-8 m, max world coordinate * 2e-6)`). Check an actual viewport/render, including UV controllers, rather than declaring bitwise-local hash equality after baking.

Keep the immutable import plan and the separate cleanup receipt. `verify`/`verify_cleanup` checks the receipt's original world geometry and current conversion-input hashes, not replacement fingerprints invented after failure. `rhino_cleanup_stage='cleaning'` or a prepared receipt means incomplete/unknown completion: inspect the live scene, receipt and backup before recovery; never blindly repeat cleanup. Do not open a protection file over unsaved user work without authorization.

## Outward-normal audit

`rebuild` runs this audit by default. Rerun the read-only `audit_normals` action for a detailed object/component list, or execute `scripts/blender_normals_audit.py` with the target `scene_name`.

1. Inspect polygon winding and custom normals separately. FBX UV/normal seams can duplicate vertices, so use virtual geometric adjacency for auditing; never weld the source mesh or destroy split normals.
2. For each connected component, count boundary/non-manifold edges and inconsistent shared-edge winding. A closed, consistently oriented, non-degenerate exterior shell supports the sign of its world-space signed volume. Interpret negative determinant transforms in world space. Treat zero volume, nested shells/cavities and custom normals opposing the face surface as ambiguous.
3. Signed-volume orientation assumes a non-self-intersecting shell; the helper does not prove absence of self-intersections. Visually inspect suspicious geometry and treat known/suspected self-intersections as uncertain even if the volume sign is positive.
4. Inspect Face Orientation from useful exterior views, restoring the user's shading/overlay settings afterward. Back faces seen through an opening or from inside a hollow part do not establish an error. Open labels/decals/single-sided panels need their intended visible side checked against the product/reference, not an invented solid-volume direction.
5. Report definite outward shells, suspected inward shells and uncertain objects separately. Include object names (and source Layer/occurrence identity where useful) and the reason for uncertainty. A successful script call is not proof every normal is outward. Do not block the completed transfer solely because a legitimate open sheet has no solid-volume orientation.

This audit never flips faces or runs blanket Recalculate Outside. When an inward result is unambiguous, identify the specific part and show the evidence; a correction must preserve that part's UVs, topology and intentional split/custom normals and be separately verified. If the intended side or cavity interpretation is uncertain, tell the user instead of guessing.

## Review Collections

After conversion, cleanup and artifact-consolidation verification, collect actionable orientation findings for user inspection. Use separate clearly named Collections for reversed/suspected normals and uncertain normals, such as `检查_法线反向` and `检查_法线待确认`. An open surface is uncertain, not automatically defective. Include visually discovered problems even when a volume-based audit cannot classify them.

Link each existing object to the appropriate review Collection in the model's working Scene. Preserve its original Collection memberships, parent, object/data identity, world transform, topology, normals, UVs, materials and visibility. Do not copy/instance meshes, reparent objects, move them out of their original package, or flip normals merely to organize findings. Reuse a pipeline-owned review Collection when appropriate; do not overwrite a same-named unrelated collection or keep obsolete findings after a fresh audit. Create no empty review Collections when there are no corresponding findings.

The model still has one packaging Collection; these are additional review memberships, not replacement Layer hierarchies. A strict cleanup verifier correctly rejects membership changes after its baseline. Keep its original receipt intact: finish strict verification first, then independently verify that the only change is the intended extra membership for the identified objects, with all other objects and properties unchanged. Subsequent appearance checks use this reviewed scene as their pre-material baseline. Do not weaken the import/cleanup assertions or rewrite old receipts to accept review organization.

Tell the user the review Collection names and counts, distinguishing uncertainty from confirmed problems. Objects remain present through their original Collections, so toggling the review Collection alone does not isolate them. If isolation is needed, select its members and use an appropriate temporary view, restoring view settings afterward.
