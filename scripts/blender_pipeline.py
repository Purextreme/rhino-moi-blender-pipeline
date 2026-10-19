"""Execute in Blender through MCP; provide ACTION and CONFIG globals.

Actions separate import/planning, rebuild with default cleanup/audit, and verification.
"""
import hashlib
import itertools
import json
import math
import pathlib
import re
import runpy

import bpy
import numpy as np
from mathutils import Matrix


def read_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8-sig'))


def write_new_json(path, data):
    with pathlib.Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)


def mesh_state(obj):
    mesh = obj.data
    vertices = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get('co', vertices)
    indices = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get('vertex_index', indices)
    starts = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get('loop_start', starts)
    materials = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get('material_index', materials)
    normals = np.empty(len(mesh.corner_normals) * 3, dtype=np.float32)
    mesh.corner_normals.foreach_get('vector', normals)
    return {'vertices': len(mesh.vertices), 'polygons': len(mesh.polygons), 'loops': len(mesh.loops),
            'geometry_hash': hashlib.sha256(vertices.tobytes() + indices.tobytes() + starts.tobytes()).hexdigest(),
            'normal_hash': hashlib.sha256(normals.tobytes()).hexdigest(),
            'has_custom_normals': bool(mesh.has_custom_normals),
            'materials': [m.name if m else None for m in mesh.materials],
            'material_indices_hash': hashlib.sha256(materials.tobytes()).hexdigest()}


def matrix_list(matrix):
    return [[float(value) for value in row] for row in matrix]


def object_state(obj):
    return {'type': obj.type, 'data': obj.data.name if obj.data else None,
            'parent': obj.parent.name if obj.parent else None,
            'matrix': matrix_list(obj.matrix_world),
            'collections': sorted(c.name for c in obj.users_collection),
            'mesh': mesh_state(obj) if obj.type == 'MESH' else None}


def exact_bbox(obj):
    values = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
    obj.data.vertices.foreach_get('co', values)
    points = values.reshape((-1, 3))
    assert len(points), 'Empty mesh: ' + obj.name
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    world = points @ matrix[:3, :3].T + matrix[:3, 3]
    assert np.isfinite(world).all(), 'Nonfinite mesh geometry'
    return [world.min(axis=0).tolist(), world.max(axis=0).tolist()]


def source_bbox(occurrence):
    return [[float(occurrence['bbox'][side][axis]) for axis in ('x','y','z')] for side in ('min','max')]


def mapped_bbox(box, matrix):
    corners = np.array(list(itertools.product(*zip(box[0], box[1]))))
    transformed = corners @ matrix[:3, :3].T + matrix[:3, 3]
    return [transformed.min(axis=0).tolist(), transformed.max(axis=0).tolist()]


def bbox_error(left, right):
    return float(np.max(np.abs(np.array(left) - np.array(right))))


def unit_scale(units):
    values = {'Millimeters': 0.001, 'Centimeters': 0.01, 'Meters': 1.0,
              'Inches': 0.0254, 'Feet': 0.3048, 'Microns': 1e-6, 'Kilometers': 1000.0}
    assert units in values, 'Unresolved Rhino document units: ' + units
    return values[units]


def get_scene(cfg):
    scene = bpy.data.scenes.get(cfg['scene_name'])
    assert scene and scene.get('rhino_run_id') == cfg['request_id'], 'Wrong pipeline scene or request ID'
    assert scene.unit_settings.system == 'METRIC' and scene.unit_settings.scale_length == 1.0, 'Pipeline requires one Blender unit = one meter; Scene unit scale changed'
    return scene


def import_model(cfg):
    manifest = read_json(cfg['occurrences_path'])
    assert manifest['schema_version'] == 2, 'Require current occurrence schema with effective visibility/locking'
    assert manifest['metadata_request_id'] == cfg['request_id']
    assert bpy.context.mode == 'OBJECT', 'Leave Edit/Sculpt mode before import'
    assert cfg['scene_name'] not in bpy.data.scenes, 'Import scene already exists; inspect instead of repeating'
    path = pathlib.Path(cfg['fbx_path'])
    assert path.is_file() and path.stat().st_size > 0
    backup = pathlib.Path(cfg['backup_path'])
    assert not backup.exists(), 'Do not overwrite protection backup'
    baseline = {o.name: object_state(o) for o in bpy.data.objects}
    original_scene = bpy.context.scene.name
    original_filepath = bpy.data.filepath
    bpy.ops.wm.save_as_mainfile(filepath=str(backup), copy=True, check_existing=False)
    assert backup.is_file() and backup.stat().st_size > 0
    assert bpy.data.filepath == original_filepath
    bpy.ops.ed.undo_push(message='Before Rhino MoI import')
    scene = bpy.data.scenes.new(cfg['scene_name'])
    scene['rhino_run_id'] = cfg['request_id']
    scene['rhino_stage'] = 'importing'
    scene['rhino_prior_objects'] = json.dumps(baseline)
    scene['rhino_original_scene'] = original_scene
    scene['rhino_original_filepath'] = original_filepath
    scene['rhino_manifest_path'] = cfg['occurrences_path']
    bpy.context.window.scene = scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = 'MILLIMETERS'
    status = bpy.ops.import_scene.fbx(filepath=str(path), global_scale=1.0,
        use_manual_orientation=False, bake_space_transform=False,
        use_custom_normals=True, use_anim=False, use_image_search=False)
    assert 'FINISHED' in status, 'FBX import did not finish'
    bpy.context.view_layer.update()
    meshes = [o for o in scene.objects if o.type == 'MESH']
    assert meshes, 'FBX contains no meshes; retain scene for diagnosis'
    assert all(o.type == 'MESH' for o in scene.objects), 'Unexpected FBX object types; inspect before reconstruction'
    scene['rhino_stage'] = 'imported'
    return {'execution_ok': True, 'scene': scene.name, 'mesh_count': len(meshes),
            'custom_normals_count': sum(o.data.has_custom_normals for o in meshes),
            'polygons': sum(len(o.data.polygons) for o in meshes),
            'vertices': sum(len(o.data.vertices) for o in meshes),
            'name_samples': [o.name for o in meshes[:8]],
            'bbox_samples': [{'name':o.name,'bbox':exact_bbox(o)} for o in meshes[:3]],
            'backup_path': str(backup), 'original_scene_preserved': original_scene in bpy.data.scenes}


def file_hash(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def make_plan(cfg, diagnostic=False):
    scene = get_scene(cfg)
    assert bpy.context.scene == scene and scene['rhino_stage'] == 'imported'
    manifest = read_json(cfg['occurrences_path'])
    assert manifest['schema_version'] == 2
    assert manifest['metadata_request_id'] == cfg['request_id']
    occurrences = manifest['occurrences']
    by_token = {o['transport_name']: o for o in occurrences}
    assert len(by_token) == len(occurrences)
    groups = {token: [] for token in by_token}
    meshes = [o for o in scene.objects if o.type == 'MESH']
    for mesh in meshes:
        match = re.fullmatch(r'(RB_\d{5}_[0-9a-f]{8})(?:\.\d+)?', mesh.name)
        assert match and match[1] in groups, 'Lost or unknown export token: ' + mesh.name
        groups[match[1]].append(mesh)
    assert all(groups.values()), 'Missing source occurrence meshes'
    boxes = {}
    for token, objects in groups.items():
        values = np.array([exact_bbox(o) for o in objects])
        boxes[token] = [values[:,0,:].min(axis=0).tolist(), values[:,1,:].max(axis=0).tolist()]
    scale = unit_scale(manifest['document']['model_units'])
    tolerance = float(cfg['bbox_tolerance_source_units']) * scale
    assert tolerance > 0
    candidates = []
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1,1), repeat=3):
            transform = np.eye(4)
            transform[:3,:3] = 0
            for axis, source in enumerate(permutation):
                transform[axis,source] = signs[axis] * scale
            mapped = {token:mapped_bbox(source_bbox(o),transform) for token,o in by_token.items()}
            offsets = [np.mean(boxes[t],axis=0)-np.mean(mapped[t],axis=0) for t in by_token]
            translation = np.median(offsets,axis=0)
            transform[:3,3] = translation
            errors = {t:bbox_error(np.array(mapped[t])+translation,boxes[t]) for t in by_token}
            candidates.append({'matrix':transform.tolist(),'sum_error':sum(errors.values()),
                               'max_error':max(errors.values()),'errors':errors})
    candidates.sort(key=lambda c:(c['sum_error'],c['max_error']))
    best = candidates[0]
    if diagnostic:
        worst = sorted(best['errors'],key=best['errors'].get,reverse=True)[:12]
        return {'source_to_blender':best['matrix'],'max_error_m':best['max_error'],
                'worst':[{'token':t,'layer':by_token[t]['layer'],'error_m':best['errors'][t],
                          'expected':mapped_bbox(source_bbox(by_token[t]),np.array(best['matrix'])),
                          'actual':boxes[t]} for t in worst],
                'mapping_gap_m':candidates[1]['sum_error']-best['sum_error']}
    assert best['max_error'] <= tolerance, 'BBox tolerance exceeded: ' + str(best['max_error'])
    gap = float(cfg['mapping_gap_m'])
    assert candidates[1]['sum_error'] - best['sum_error'] > gap, 'Ambiguous axis mapping'
    transform = np.array(best['matrix'])
    # Brep material splits must remain inside their exact transformed source envelope.
    for token, objects in groups.items():
        envelope = np.array(mapped_bbox(source_bbox(by_token[token]),transform))
        for obj in objects:
            box = np.array(exact_bbox(obj))
            assert (box[0] >= envelope[0]-tolerance).all() and (box[1] <= envelope[1]+tolerance).all(), 'Invalid split containment'
    assert all(o.data.has_custom_normals for o in meshes), 'Missing imported custom normals'
    # Layer identity must be complete before constructing object parents.
    layer_paths = [l['full_path'] for l in manifest['layers']]
    assert len(set(layer_paths)) == len(layer_paths)
    assert all(o['layer'] in layer_paths for o in occurrences)
    block_keys = set()
    for block in manifest['blocks']:
        assert block['key'] not in block_keys
        assert block['parent'] is None or block['parent'] in block_keys, 'Block parent order/cycle invalid'
        assert len(block['world_matrix']) == 4
        assert all(isinstance(block['source_metadata'][k], bool) for k in ('effective_visible', 'effective_locked'))
        block_keys.add(block['key'])
    assert all(o['parent'] is None or o['parent'] in block_keys for o in occurrences)
    assert all(isinstance(o['source_metadata'][k], bool) for o in occurrences for k in ('effective_visible','effective_locked'))
    hierarchy_spec(manifest)
    plan = {'request_id':cfg['request_id'],'scene_name':scene.name,
            'manifest_hash':file_hash(cfg['occurrences_path']), 'fbx_hash':file_hash(cfg['fbx_path']),
            'mapping':best,'bbox_tolerance_m':tolerance,
            'groups':{t:[o.name for o in objects] for t,objects in groups.items()},
            'before':{o.name:{'mesh':mesh_state(o),'matrix':matrix_list(o.matrix_world),'bbox':exact_bbox(o)} for o in meshes}}
    write_new_json(cfg['plan_path'],plan)
    return {'execution_ok':True,'verification_ok':True,'plan_path':cfg['plan_path'],
            'source_occurrences':len(occurrences),'mesh_count':len(meshes),
            'split_mesh_count':len(meshes)-len(occurrences),'source_to_blender':best['matrix'],
            'max_bbox_error_m':best['max_error'],'bbox_tolerance_m':tolerance,
            'next_mapping_sum_gap_m':candidates[1]['sum_error']-best['sum_error']}


def hierarchy_spec(manifest):
    """Each Block is its own Layer scope; unused Layers are never instantiated."""
    layers = {item['full_path']: item for item in manifest['layers']}
    assert len(layers) == len(manifest['layers']), 'Duplicate Layer paths'
    blocks = {item['key']: item for item in manifest['blocks']}
    required = set()
    for item in manifest['blocks'] + manifest['occurrences']:
        scope = item['parent'] or ''
        assert not scope or scope in blocks, 'Missing Block scope'
        parts = item['layer'].split('::')
        for length in range(1, len(parts) + 1):
            path = '::'.join(parts[:length])
            assert path in layers, 'Missing Layer ancestor: ' + path
            required.add((scope, path))
    return layers, blocks, required


def layer_flags(scope, path, layers, blocks):
    parts = path.split('::')
    ancestors = [layers['::'.join(parts[:n])] for n in range(1, len(parts)+1)]
    inherited = blocks[scope]['source_metadata'] if scope else {}
    return (bool(inherited.get('effective_visible', True) and all(x['visible'] for x in ancestors)),
            bool(inherited.get('effective_locked', False) or any(x['locked'] for x in ancestors)))


def build_object_hierarchy(scene, manifest, root, root_collection):
    layers, block_info, required = hierarchy_spec(manifest)
    assert not any(o.get('rhino_layer_node') for o in scene.objects), 'Layer parents already exist'
    blocks = {o['rhino_block_key']: o for o in scene.objects if o.get('rhino_block_key')}
    meshes = {o['rhino_import_name']: o for o in scene.objects if o.type == 'MESH'}
    worlds = {o: o.matrix_world.copy() for o in list(blocks.values()) + list(meshes.values())}
    nodes = {}

    def layer_parent(scope, path):
        key = (scope, path)
        if key in nodes:
            return nodes[key]
        assert key in required
        parent_path = '::'.join(path.split('::')[:-1])
        parent = layer_parent(scope, parent_path) if parent_path else (blocks[scope] if scope else root)
        node = bpy.data.objects.new(layers[path]['name'], None)
        root_collection.objects.link(node)
        node.parent = parent
        node.matrix_parent_inverse = Matrix.Identity(4)
        node.matrix_basis = Matrix.Identity(4)
        node.empty_display_type = 'PLAIN_AXES'
        node.empty_display_size = 0.002
        node['rhino_layer_node'] = True
        node['rhino_layer_scope'] = scope
        node['rhino_layer_path'] = path
        node['rhino_layer_id'] = layers[path]['id']
        visible, locked = layer_flags(scope, path, layers, block_info)
        node['rhino_source_visible'] = layers[path]['visible']
        node['rhino_source_locked'] = layers[path]['locked']
        node.hide_set(not visible)
        node.hide_render = not visible
        node.hide_select = locked
        nodes[key] = node
        bpy.context.view_layer.update()
        return node

    # Reserve unqualified names for the model's top-level Layer tree first.
    for scope, path in sorted(required):
        if not scope:
            layer_parent(scope, path)
    # Block records are topologically ordered. Restore every world transform
    # after its parent has reached its final position, including nested scopes.
    for item in manifest['blocks']:
        obj = blocks[item['key']]
        obj.parent = layer_parent(item['parent'] or '', item['layer'])
        obj.matrix_world = worlds[obj]
        bpy.context.view_layer.update()
    by_occurrence = {}
    for obj in meshes.values():
        by_occurrence.setdefault(obj['rhino_occurrence_key'], []).append(obj)
    for item in manifest['occurrences']:
        parent = layer_parent(item['parent'] or '', item['layer'])
        for obj in by_occurrence[item['key']]:
            obj.parent = parent
            obj.matrix_world = worlds[obj]
            if root_collection not in obj.users_collection:
                root_collection.objects.link(obj)
            for collection in list(obj.users_collection):
                if collection != root_collection:
                    collection.objects.unlink(obj)
            bpy.context.view_layer.update()
    assert set(nodes) == required
    for obj, world in worlds.items():
        assert np.allclose(np.array(obj.matrix_world), np.array(world), rtol=0, atol=1e-7)
    scene['rhino_hierarchy'] = 'layer_empty_v1'
    return nodes


def rebuild(cfg):
    scene = get_scene(cfg)
    assert bpy.context.scene == scene and scene['rhino_stage'] == 'imported'
    for key in ('cleanup_path','cleanup_backup_path'):
        path = pathlib.Path(cfg[key])
        assert path.is_absolute() and path.parent.is_dir() and not path.exists(), 'Require a new cleanup path: ' + key
    plan = read_json(cfg['plan_path'])
    manifest = read_json(cfg['occurrences_path'])
    assert plan['request_id'] == cfg['request_id'] == manifest['metadata_request_id']
    assert plan['manifest_hash'] == file_hash(cfg['occurrences_path'])
    assert plan['fbx_hash'] == file_hash(cfg['fbx_path'])
    assert set(plan['before']) == {o.name for o in scene.objects if o.type == 'MESH'}
    for name, before in plan['before'].items():
        obj = scene.objects[name]
        assert mesh_state(obj) == before['mesh'], 'Imported geometry changed since planning'
        assert np.allclose(np.array(obj.matrix_world),before['matrix'],rtol=0,atol=1e-9)
    assert not any(o.get('rhino_occurrence_key') for o in scene.objects), 'Scene already reconstructed'
    bpy.ops.ed.undo_push(message='Before Rhino hierarchy reconstruction')
    scene['rhino_stage'] = 'rebuilding'
    root_collection = bpy.data.collections.new(cfg['root_name'])
    scene.collection.children.link(root_collection)
    root_collection['rhino_run_id'] = cfg['request_id']
    root = bpy.data.objects.new(cfg['root_name'],None)
    root_collection.objects.link(root)
    root['rhino_run_id'] = cfg['request_id']
    root.empty_display_size = 0.003
    mapping = Matrix(plan['mapping']['matrix'])
    inverse = mapping.inverted()
    blocks = {}
    for item in manifest['blocks']:
        empty = bpy.data.objects.new(item['name'] or item['definition_name'],None)
        root_collection.objects.link(empty)
        empty.parent = blocks[item['parent']] if item['parent'] else root
        empty.matrix_world = mapping @ Matrix(item['world_matrix']) @ inverse
        empty.empty_display_size = 0.002
        empty['rhino_block_key'] = item['key']
        empty['rhino_source_id'] = item['source_id']
        empty['rhino_definition_id'] = item['definition_id']
        empty['rhino_definition_name'] = item['definition_name']
        empty['rhino_effective_visible'] = item['source_metadata']['effective_visible']
        empty['rhino_effective_locked'] = item['source_metadata']['effective_locked']
        empty.hide_set(not item['source_metadata']['effective_visible'])
        empty.hide_render = not item['source_metadata']['effective_visible']
        empty.hide_select = item['source_metadata']['effective_locked']
        blocks[item['key']] = empty
        bpy.context.view_layer.update()
    for occurrence in manifest['occurrences']:
        for part, old_name in enumerate(plan['groups'][occurrence['transport_name']]):
            obj = scene.objects[old_name]
            world = obj.matrix_world.copy()
            target = root_collection
            target.objects.link(obj)
            for collection in list(obj.users_collection):
                if collection != target:
                    collection.objects.unlink(obj)
            obj.parent = blocks[occurrence['parent']] if occurrence['parent'] else root
            obj.matrix_world = world
            obj['rhino_occurrence_key'] = occurrence['key']
            obj['rhino_source_id'] = occurrence['source_id']
            obj['rhino_transport_name'] = occurrence['transport_name']
            obj['rhino_layer_path'] = occurrence['layer']
            obj['rhino_import_name'] = old_name
            obj['rhino_source_name'] = occurrence['name']
            obj['rhino_source_visible'] = occurrence['source_metadata']['visible']
            obj['rhino_source_locked'] = occurrence['source_metadata']['locked']
            obj['rhino_effective_visible'] = occurrence['source_metadata']['effective_visible']
            obj['rhino_effective_locked'] = occurrence['source_metadata']['effective_locked']
            obj.hide_set(not occurrence['source_metadata']['effective_visible'])
            obj.hide_render = not occurrence['source_metadata']['effective_visible']
            obj.hide_select = occurrence['source_metadata']['effective_locked']
            obj.name = occurrence['name'] or (occurrence['layer'].split('::')[-1] + '_' + occurrence['transport_name'][3:8])
            if part:
                obj.name += '_part' + str(part+1)
            bpy.context.view_layer.update()
            assert np.allclose(np.array(obj.matrix_world),np.array(world),rtol=0,atol=1e-7), 'World matrix changed during parenting'
    build_object_hierarchy(scene, manifest, root, root_collection)
    scene['rhino_stage'] = 'rebuilt'
    scene['rhino_plan_path'] = cfg['plan_path']
    bpy.context.view_layer.update()
    bpy.ops.ed.undo_push(message='Rhino hierarchy reconstructed')
    conversion = verify(cfg)
    cleanup = cleanup_entry('clean', cfg)
    normals = audit_normals(cfg)
    return {**conversion, **cleanup, 'conversion_verified_before_cleanup': True,
            'normal_orientation_counts': normals['counts'],
            'normal_orientation_attention': normals['needs_user_notice']}


def verify(cfg):
    scene = get_scene(cfg)
    assert scene['rhino_stage'] == 'rebuilt', 'Reconstruction incomplete; inspect before retry'
    manifest = read_json(cfg['occurrences_path'])
    assert manifest['schema_version'] == 2
    plan = read_json(cfg['plan_path'])
    assert manifest['metadata_request_id'] == plan['request_id'] == cfg['request_id']
    assert plan['manifest_hash'] == file_hash(cfg['occurrences_path'])
    assert plan['fbx_hash'] == file_hash(cfg['fbx_path'])
    bpy.context.view_layer.update()
    meshes = [o for o in scene.objects if o.type == 'MESH']
    by_old_name = {o.get('rhino_import_name'):o for o in meshes}
    assert set(by_old_name) == set(plan['before']) and len(meshes) == len(plan['before'])
    world_errors = []
    for name, before in plan['before'].items():
        obj = by_old_name[name]
        assert mesh_state(obj) == before['mesh'], 'Geometry, normals or materials changed: ' + obj.name
        assert np.allclose(np.array(obj.matrix_world),before['matrix'],rtol=0,atol=1e-7)
        world_errors.append(bbox_error(exact_bbox(obj),before['bbox']))
    assert max(world_errors,default=0) <= 1e-7
    assert scene.get('rhino_hierarchy') == 'layer_empty_v1', 'Expected Layer Empty hierarchy'
    layers, block_info, required = hierarchy_spec(manifest)
    nodes_list = [o for o in scene.objects if o.get('rhino_layer_node')]
    nodes = {(o.get('rhino_layer_scope'), o.get('rhino_layer_path')):o for o in nodes_list}
    assert len(nodes) == len(nodes_list) and set(nodes) == required, 'Missing, duplicate or empty Layer parents'
    blocks = {o.get('rhino_block_key'):o for o in scene.objects if o.get('rhino_block_key')}
    assert len(blocks) == len(manifest['blocks'])
    root = next(o for o in scene.objects if o.type == 'EMPTY' and o.get('rhino_run_id') == cfg['request_id'])
    assert len(root.users_collection) == 1
    root_collection = root.users_collection[0]
    assert root_collection.get('rhino_run_id') == cfg['request_id']
    assert list(scene.collection.children_recursive) == [root_collection], 'Unexpected collection structure'
    for (scope, path), node in nodes.items():
        assert node.type == 'EMPTY' and node.get('rhino_layer_id') == layers[path]['id']
        parent_path = '::'.join(path.split('::')[:-1])
        expected_parent = nodes[(scope,parent_path)] if parent_path else (blocks[scope] if scope else root)
        assert node.parent == expected_parent and len(node.children) > 0
        visible, locked = layer_flags(scope, path, layers, block_info)
        assert node.hide_get() == (not visible) and node.hide_render == (not visible)
        assert node.hide_select == locked
    assert set(scene.objects) == {root} | set(nodes.values()) | set(blocks.values()) | set(meshes)
    assert all(set(o.users_collection) == {root_collection} for o in scene.objects)
    mapping = np.array(plan['mapping']['matrix'])
    max_source_error = 0.0
    for occurrence in manifest['occurrences']:
        objects = [by_old_name[n] for n in plan['groups'][occurrence['transport_name']]]
        expected_parent = nodes[(occurrence['parent'] or '', occurrence['layer'])]
        for obj in objects:
            assert obj.parent == expected_parent
            assert obj.get('rhino_occurrence_key') == occurrence['key']
            assert obj.get('rhino_layer_path') == occurrence['layer']
            assert obj.hide_get() == (not occurrence['source_metadata']['effective_visible'])
            assert obj.hide_render == (not occurrence['source_metadata']['effective_visible'])
            assert obj.hide_select == occurrence['source_metadata']['effective_locked']
        boxes = np.array([exact_bbox(o) for o in objects])
        union = [boxes[:,0,:].min(axis=0).tolist(),boxes[:,1,:].max(axis=0).tolist()]
        error = bbox_error(union,mapped_bbox(source_bbox(occurrence),mapping))
        max_source_error = max(error,max_source_error)
        assert error <= plan['bbox_tolerance_m']
    for block in manifest['blocks']:
        obj = blocks[block['key']]
        assert obj.parent == nodes[(block['parent'] or '', block['layer'])]
        assert obj.hide_get() == (not block['source_metadata']['effective_visible'])
        assert obj.hide_render == (not block['source_metadata']['effective_visible'])
        assert obj.hide_select == block['source_metadata']['effective_locked']
        # Match Blender's float32 matrix representation used during creation;
        # float64 inversion can differ by one ULP for scaled Block occurrences.
        blender_mapping = Matrix(plan['mapping']['matrix'])
        expected = np.array(blender_mapping @ Matrix(block['world_matrix']) @ blender_mapping.inverted())
        assert np.allclose(np.array(obj.matrix_world),expected,rtol=0,atol=1e-7)
    prior = json.loads(scene['rhino_prior_objects'])
    for name,before in prior.items():
        assert name in bpy.data.objects and object_state(bpy.data.objects[name]) == before, 'Prior scene changed'
    assert scene['rhino_original_scene'] in bpy.data.scenes
    assert bpy.data.filepath == scene['rhino_original_filepath']
    return {'execution_ok':True,'verification_ok':True,'scene':scene.name,
            'mesh_count':len(meshes),'source_occurrences':len(manifest['occurrences']),
            'block_occurrences':len(blocks),'layer_empties':len(nodes),'model_collections':1,
            'omitted_empty_layers': sorted(set(layers) - {path for scope,path in required}),
            'polygons':sum(len(o.data.polygons) for o in meshes),
            'vertices':sum(len(o.data.vertices) for o in meshes),
            'custom_normals_count':sum(o.data.has_custom_normals for o in meshes),
            'max_source_bbox_error_m':max_source_error,'max_parenting_bbox_error_m':max(world_errors,default=0),
            'prior_objects_preserved':len(prior),'omitted_count':len(manifest['omitted']),
            'source_to_blender':plan['mapping']['matrix'],'blend_saved':bool(bpy.data.filepath)}


def cleanup_entry(action, cfg):
    path = pathlib.Path(main.__code__.co_filename).with_name('blender_cleanup.py')
    return runpy.run_path(str(path), run_name='pipeline_cleanup')['main'](action, cfg)


def audit_normals(cfg):
    scene = get_scene(cfg)
    root = scene.objects[cfg['root_name']]
    path = pathlib.Path(main.__code__.co_filename).with_name('blender_normals_audit.py')
    return runpy.run_path(str(path), run_name='pipeline_normals')['audit'](scene,[root]+list(root.children_recursive))


def main(action, cfg):
    if action == 'import':
        return import_model(cfg)
    if action == 'plan':
        return make_plan(cfg)
    if action == 'diagnose':
        return make_plan(cfg, diagnostic=True)
    if action == 'rebuild':
        return rebuild(cfg)
    if action == 'verify':
        stage = get_scene(cfg).get('rhino_cleanup_stage')
        assert stage != 'cleaning', 'Cleanup incomplete; inspect before retry'
        if stage == 'cleaned':
            return cleanup_entry('verify', cfg)
        return verify(cfg)
    if action == 'verify_cleanup':
        return cleanup_entry('verify', cfg)
    if action == 'audit_normals':
        return audit_normals(cfg)
    raise ValueError('Unsupported action: ' + action)


if __name__ == '__main__':
    result = main(ACTION, CONFIG)
