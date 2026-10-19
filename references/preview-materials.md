# Optional preview materials and textures

## Activation and scope

Apply this stage when the user supplies appearance reference images, product links or texture assets for the transferred model, unless they explicitly ask to skip it. Their supplied appearance context is sufficient authorization for a simple in-Blender preview finish; do not ask another routine “要不要上材质” question. Merely finding unrelated images beside a CAD file or receiving a technical documentation link is not an appearance request.

Without supplied appearance context, skip material creation and texture searches. Finish the transfer with imported materials intact and optionally ask one short follow-up at completion. If the user later requests materials without references, follow that explicit request and establish only the appearance details that materially affect the result.

Keep the result lightweight: recognizable surface color, metal/plastic/rubber/glass distinctions, supplied labels/screens and obvious texture scale. Do not expand this into detailed look development, extra modeling, animation, a paid asset search or a new reusable shader system.

## Reference and asset inspection

- Inspect supplied local folders and view the actual candidate images before assigning them. Distinguish product photos, interface artwork, color maps, normal maps and other data maps; a product photo is a visual reference, not a texture to project over the entire model.
- Open product links in an available browser, using the user's existing signed-in session when needed. Verify product/SKU and relevant images from the visible page. If access is blocked, use supplied local references when sufficient and state the limitation. Never claim to have checked inaccessible images; ask for the missing reference only when the unresolved appearance prevents useful work.
- Map each material to actual scene geometry using source IDs, full Layer paths, Block ancestry and local bounds/shape evidence. Do not classify parts by import order, numeric suffixes or a previous model's object names.
- Reuse supplied textures and already available resources. Do not wait indefinitely for an optional library download; existing studio lighting and simple shaders usually suffice. Use a newly available resource only when it improves the requested preview. Do not install a resource library just to finish basic materials.

## Blender implementation

1. Require successful conversion and default [post-processing](post-processing.md) verification first. Use the cleaned conversion baseline; inspect current material slots, object/data links, UV layers and sharing, normals, visibility and active file identity. Keep original shader assignments recoverable through the existing protection copy plus Undo/assignment capture; make a fresh protection copy when the current appearance state needs one. Do not overwrite user shaders or shared materials in unrelated scenes.
2. Build only the small set of materials the reference needs. Prefer Principled BSDF with restrained roughness/metallicity and emission only for luminous artwork. Query actual socket names/API in the connected Blender version before assigning uncertain properties.
3. Assign materials by verified part identity. Keep normals and topology intact; do not merge parts, apply transforms or recalculate normals for texturing. Add a dedicated UV layer or mapping nodes when necessary instead of overwriting existing UVs. Avoid new mesh duplicates or per-object unique materials without a concrete need.
4. Treat color artwork as color-managed input and normal/roughness/mask maps as non-color data. Use a suitable projection: a flat label/display usually needs planar mapping, while a cable or tube may need cylindrical mapping. Check orientation, mirroring, aspect ratio, seam continuity and physical repeat size against the reference. Do not connect a normal map as color or invent arbitrary displacement for a simple preview.
5. Preserve original image files and make dependencies portable by packing used images or retaining verified stable paths. Keep source image resolution; use shader mapping rather than destructively rewriting the user's artwork. Record any intentional reference-only visibility changes so they can be restored, and do not mistake a product-reference plane for product geometry.
6. Configure material preview with available studio lighting. If a render helps verify appearance, use a small separate preview scene/rig; keep cameras, lights and floor geometry out of the model's working hierarchy. Do not interrupt a user's ongoing asset download or switch away from their active task just to frame a viewport. Saving the final `.blend` still follows the user's requested destination or approval.

## Acceptance and completion

Inspect a real material-preview screenshot or render. Correct visible issues such as mirrored text, stretched artwork, missing images, white/pink materials, severe exposure errors and texture repeats that look unlike the supplied reference. A successful node-creation call does not prove correct appearance.

Perform a separate read-only structural check against the cleaned pre-material conversion baseline: source occurrences and mesh count, geometry/topology and custom-normal fingerprints, world matrices/BBoxes, Layer/Block parent graph, package membership, original scene objects and file identity must remain intact. Check intended material assignments and UV/image links separately; original material/UV signatures are intentionally allowed to differ. Do not alter the conversion plan or cleanup receipt to make strict imported-material checks pass.

Report what was actually applied and visually checked, which reference/texture sources were usable, any remaining approximation and the `.blend` save state. Keep model-specific settings, paths, screenshots and texture assets outside this Skill.
