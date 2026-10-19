"""Guarded post-conversion scale/origin cleanup; execute in Blender via MCP.

ACTION = 'inspect', 'clean', or 'verify'; CONFIG identifies scene/root and paths.
The receipt is acceptance data, separate from the immutable import plan.
"""
import base64
import hashlib
import json
import math
import pathlib
import zlib

import bpy
import numpy as np
from mathutils import Matrix, Vector


def pack_array(array):
    a = np.asarray(array, dtype='<f8')
    return {'shape': list(a.shape), 'zlib_f64': base64.b64encode(zlib.compress(a.tobytes())).decode('ascii')}


def unpack_array(data):
    return np.frombuffer(zlib.decompress(base64.b64decode(data['zlib_f64'])), dtype='<f8').reshape(data['shape'])


def values(items, field, width, dtype=np.float32):
    a = np.empty(len(items) * width, dtype=dtype)
    items.foreach_get(field, a)
    return a.reshape((len(items), width))


def digest(a):
    return hashlib.sha256(a.tobytes()).hexdigest()


def mesh_stamp(mesh):
    fields = {'FLOAT': ('value',1,np.float32), 'INT': ('value',1,np.int32),
              'BOOLEAN': ('value',1,np.bool_), 'FLOAT_VECTOR': ('vector',3,np.float32),
              'FLOAT2': ('vector',2,np.float32), 'FLOAT_COLOR': ('color',4,np.float32),
              'BYTE_COLOR': ('color',4,np.float32), 'INT8': ('value',1,np.int8),
              'INT32_2D': ('value',2,np.int32), 'INT16_2D': ('value',2,np.int16)}
    attributes = {}
    for a in mesh.attributes:
        if a.name in ('position','custom_normal'):
            continue
        assert a.data_type in fields, 'Unsupported attribute: ' + a.name
        field, width, dtype = fields[a.data_type]
        attributes[a.name] = [a.data_type, a.domain, len(a.data), digest(values(a.data,field,width,dtype))]
    return {'vertices':len(mesh.vertices), 'loops':len(mesh.loops), 'polygons':len(mesh.polygons),
            'attributes':attributes, 'custom_normals':bool(mesh.has_custom_normals),
            'materials':[m.name if m else None for m in mesh.materials],
            'active_uv':mesh.uv_layers.active.name if mesh.uv_layers.active else None,
            'render_uv':[u.name for u in mesh.uv_layers if u.active_render]}


def world_mesh(obj, mesh):
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    co = values(mesh.vertices,'co',3).astype(np.float64)
    normal = values(mesh.corner_normals,'vector',3).astype(np.float64)
    normal = normal @ np.linalg.inv(matrix[:3,:3])
    if len(normal):
        normal /= np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-30)
    return {'vertices':pack_array(co @ matrix[:3,:3].T + matrix[:3,3]),
            'normals':pack_array(normal),
            'uv':{u.name:pack_array(values(u.data,'uv',2)) for u in mesh.uv_layers}}


def snapshot(obj, depsgraph):
    result = {'type':obj.type, 'parent':obj.parent.name if obj.parent else None,
              'collections':sorted(c.name for c in obj.users_collection),
              'matrix':[list(row) for row in obj.matrix_world],
              'scale':list(obj.scale), 'delta_scale':list(obj.delta_scale),
              'visibility':[obj.hide_get(),obj.hide_render,obj.hide_select],
              'identity':{k:obj[k] for k in obj.keys() if k.startswith('rhino_')},
              'modifiers':modifier_stamp(obj)}
    if obj.type == 'MESH':
        result['mesh'] = mesh_stamp(obj.data)
        result['world'] = world_mesh(obj,obj.data)
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True,depsgraph=depsgraph)
        try:
            result['evaluated'] = world_mesh(obj,mesh)
        finally:
            evaluated.to_mesh_clear()
    return result


def modifier_stamp(obj):
    result = []
    for mod in obj.modifiers:
        fields = {}
        for p in mod.bl_rna.properties:
            if p.is_readonly or p.type == 'COLLECTION':
                continue
            value = getattr(mod,p.identifier)
            if p.type == 'POINTER':
                value = value.name if value else None
            elif getattr(p,'is_array',False):
                value = list(value)
            fields[p.identifier] = value
        result.append([mod.type,fields])
    return result


def targets(cfg):
    scene = bpy.data.scenes[cfg['scene_name']]
    assert scene.get('rhino_run_id') == cfg['request_id'], 'Wrong run ID'
    assert bpy.context.scene == scene and bpy.context.mode == 'OBJECT'
    root = scene.objects[cfg['root_name']]
    assert root.type == 'EMPTY' and root.get('rhino_run_id') == cfg['request_id']
    objects = [root] + list(root.children_recursive)
    assert all(o.name in scene.objects for o in objects)
    return scene, objects


def mapping_references(objects):
    refs = set()
    for owner in bpy.data.objects:
        for mod in owner.modifiers:
            if mod.type == 'UV_WARP':
                for ref in (mod.object_from,mod.object_to):
                    if ref in objects:
                        assert owner in objects, 'External UV modifier depends on model'
                        assert ref.type == 'EMPTY' and ref.parent, 'UV mapping reference needs a parented Empty'
                        refs.add(ref)
    for mat in bpy.data.materials:
        if mat.use_nodes:
            for node in mat.node_tree.nodes:
                ref = getattr(node,'object',None)
                if ref in objects:
                    assert ref.type == 'EMPTY' and ref.parent, 'Object texture reference needs an adapter'
                    refs.add(ref)
    return refs


def inspect(cfg):
    scene, objects = targets(cfg)
    for obj in objects:
        assert obj.type in ('MESH','EMPTY'), 'Unsupported object: ' + obj.name
        assert not obj.animation_data and not obj.constraints, 'Animated/constrained object: ' + obj.name
        assert obj.library is None and obj.instance_type == 'NONE', 'Linked/instanced object: ' + obj.name
        assert all(abs(v)<1e-12 for v in obj.delta_location) and all(abs(v)<1e-12 for v in obj.delta_rotation_euler)
        assert all(abs(v)>1e-12 for v in (*obj.scale,*obj.delta_scale)), 'Singular scale: ' + obj.name
        assert abs(obj.matrix_world.determinant())>1e-30
        if obj.type == 'MESH':
            assert len(obj.data.vertices) and not obj.data.shape_keys
            assert all(m.type == 'UV_WARP' for m in obj.modifiers), 'Evaluate geometry modifiers separately: ' + obj.name
    refs = mapping_references(objects)
    meshes = [o for o in objects if o.type == 'MESH']
    assert meshes
    all_zero = all(o.matrix_world.translation.length <= 1e-6 for o in meshes)
    return {'execution_ok':True, 'scene':scene.name, 'object_count':len(objects), 'mesh_count':len(meshes),
            'nonunit_scale_count':sum(max(abs(v-1) for v in (*o.scale,*o.delta_scale))>1e-6 for o in objects),
            'all_mesh_origins_at_world_zero':all_zero,
            'mapping_reference_empties':sorted(o.name for o in refs)}


def compare(before, after, position_tolerance):
    for key in ('type','parent','collections','visibility','identity','modifiers'):
        assert before[key] == after[key], key
    if before['type'] != 'MESH':
        return 0.,0.,0.
    assert before['mesh'] == after['mesh'], 'Topology, attributes, UVs, custom-normal presence or materials changed'
    max_position = max_normal = max_uv = 0.
    for domain in ('world','evaluated'):
        for field, tolerance in (('vertices',position_tolerance),('normals',2*math.sin(math.radians(.05)/2))):
            a,b = unpack_array(before[domain][field]),unpack_array(after[domain][field])
            assert a.shape == b.shape and np.isfinite(b).all()
            error = float(np.max(np.linalg.norm(a-b,axis=1),initial=0)) if field=='normals' else float(np.max(np.abs(a-b),initial=0))
            assert error<=tolerance, (domain,field,error,tolerance)
            if field == 'vertices': max_position=max(max_position,error)
            else: max_normal=max(max_normal,error)
        assert set(before[domain]['uv']) == set(after[domain]['uv'])
        for name, packed in before[domain]['uv'].items():
            a,b=unpack_array(packed),unpack_array(after[domain]['uv'][name])
            assert a.shape == b.shape and np.isfinite(b).all()
            error=float(np.max(np.abs(a-b),initial=0))
            assert error <= 2e-5, ('UV',name,error)
            max_uv=max(max_uv,error)
    return max_position,max_normal,max_uv


def verify_receipt(cfg, receipt):
    scene, objects = targets(cfg)
    for existing in bpy.data.scenes:
        for view_layer in existing.view_layers:
            view_layer.update()
    assert receipt['schema_version']==1 and receipt['request_id']==cfg['request_id']
    assert receipt['scene_name']==scene.name and receipt['root_name']==cfg['root_name']
    assert set(receipt['before'])=={o.name for o in objects}, 'Cleanup object set changed'
    assert bpy.data.filepath==receipt['filepath'], 'File identity changed'
    assert set(bpy.data.objects.keys())==set(receipt['inventory']), 'Global inventory changed'
    assert sorted(bpy.data.scenes.keys())==receipt['scenes']
    for key,data in receipt['input_hashes'].items():
        path=pathlib.Path(cfg.get(key,data['path']))
        assert hashlib.sha256(path.read_bytes()).hexdigest()==data['sha256'], 'Conversion input changed: '+str(path)
    dg=bpy.context.evaluated_depsgraph_get()
    errors=[]
    for obj in objects:
        assert max(abs(v-1) for v in (*obj.scale,*obj.delta_scale))<1e-6, 'Scale not one: '+obj.name
        after=snapshot(obj,dg)
        errors.append(compare(receipt['before'][obj.name],after,receipt['position_tolerance_m']))
        if receipt['center_origins'] and obj.type=='MESH':
            co=values(obj.data.vertices,'co',3)
            center=(co.min(axis=0)+co.max(axis=0))*.5
            assert np.max(np.abs(center))<=receipt['position_tolerance_m'], 'Origin not at bounds center: '+obj.name
        if obj.name in receipt['mapping_reference_empties']:
            assert np.allclose(after['matrix'],receipt['before'][obj.name]['matrix'],rtol=0,atol=receipt['position_tolerance_m'])
    for name,before in receipt['outside'].items():
        assert snapshot(bpy.data.objects[name],dg)==before, 'Unrelated object changed: '+name
    return {'execution_ok':True,'verification_ok':True,'objects':len(objects),
            'meshes':sum(o.type=='MESH' for o in objects),'all_scales_one':True,
            'origins_centered':receipt['center_origins'],'origin_mode':receipt['origin_mode'],
            'max_world_vertex_error_m':max((x[0] for x in errors),default=0),
            'max_world_normal_error':max((x[1] for x in errors),default=0),
            'max_world_normal_angle_deg':math.degrees(2*math.asin(min(1,max((x[1] for x in errors),default=0)/2))),
            'max_uv_error':max((x[2] for x in errors),default=0),
            'filepath':bpy.data.filepath,'saved_current_changes':False}


def capture_receipt(cfg, info):
    scene,objects=targets(cfg)
    for existing in bpy.data.scenes:
        for view_layer in existing.view_layers:
            view_layer.update()
    mode=cfg.get('origin_mode','auto')
    assert mode in ('auto','geometry','keep')
    center=info['all_mesh_origins_at_world_zero'] if mode=='auto' else mode=='geometry'
    dg=bpy.context.evaluated_depsgraph_get()
    snapshots={o.name:snapshot(o,dg) for o in objects}
    max_coordinate=max(float(np.max(np.abs(unpack_array(v['world']['vertices'])),initial=0)) for v in snapshots.values() if v['type']=='MESH')
    return {'schema_version':1,'status':'prepared','request_id':cfg['request_id'],'scene_name':scene.name,'root_name':cfg['root_name'],
             'filepath':bpy.data.filepath,'inventory':sorted(bpy.data.objects.keys()),'scenes':sorted(bpy.data.scenes.keys()),
             'origin_mode':mode,'center_origins':center,'position_tolerance_m':max(1e-8,max_coordinate*2e-6),
             'before':snapshots,'outside':{o.name:snapshot(o,dg) for o in bpy.data.objects if o not in objects},
             'mapping_reference_empties':info['mapping_reference_empties'],
             'input_hashes':{k:{'path':str(pathlib.Path(cfg[k])),'sha256':hashlib.sha256(pathlib.Path(cfg[k]).read_bytes()).hexdigest()}
                             for k in ('plan_path','occurrences_path','fbx_path') if k in cfg}}
def restore_world_normals(objects, receipt):
    # Encode custom normals only after the final vertex coordinates/origins
    # exist: changing the origin can otherwise perturb the loop-space basis.
    for obj in objects:
        before=receipt['before'][obj.name]
        if obj.type=='MESH' and before['mesh']['custom_normals']:
            local=unpack_array(before['world']['normals']) @ np.array(obj.matrix_world.to_3x3(),dtype=np.float64)
            local/=np.maximum(np.linalg.norm(local,axis=1,keepdims=True),1e-30)
            obj.data.normals_split_custom_set(local.tolist())
            obj.data.update()
    bpy.context.view_layer.update()


def clean(cfg):
    info=inspect(cfg)
    scene,objects=targets(cfg)
    assert not scene.get('rhino_cleanup_stage'), 'Cleanup already started; inspect and verify before retry'
    receipt_path=pathlib.Path(cfg['cleanup_path'])
    backup=pathlib.Path(cfg['cleanup_backup_path'])
    assert receipt_path.is_absolute() and backup.is_absolute()
    assert not receipt_path.exists() and not backup.exists(), 'Never overwrite cleanup evidence'
    assert receipt_path.parent.is_dir() and backup.parent.is_dir()
    receipt=capture_receipt(cfg,info)
    center=receipt['center_origins']
    status=bpy.ops.wm.save_as_mainfile(filepath=str(backup),copy=True,check_existing=False)
    assert 'FINISHED' in status and backup.is_file() and bpy.data.filepath==receipt['filepath']
    bpy.ops.ed.undo_push(message='Before Rhino scale and origin cleanup')
    with receipt_path.open('x',encoding='utf-8') as stream:
        json.dump(receipt,stream,ensure_ascii=False,separators=(',',':'))
    scene['rhino_cleanup_stage']='cleaning'
    refs=mapping_references(objects)
    def depth(obj):
        n=0
        while obj.parent:
            n+=1;obj=obj.parent
        return n
    for obj in sorted(objects,key=depth):
        children={c:c.matrix_world.copy() for c in obj.children}
        old_world=obj.matrix_world.copy()
        if obj.type=='MESH' and obj.data.users>1:
            obj.data=obj.data.copy()
        mesh=obj.data if obj.type=='MESH' else None
        obj.scale=(1,1,1)
        obj.delta_scale=(1,1,1)
        bpy.context.view_layer.update()
        if obj in refs:
            # Mapping controls have no geometry to bake. Keep their mapping
            # matrix in the existing parent offset while exposing unit scales.
            obj.matrix_parent_inverse=obj.parent.matrix_world.inverted() @ old_world @ obj.matrix_basis.inverted()
        elif mesh:
            bake=obj.matrix_world.inverted() @ old_world
            mesh.transform(bake)
            mesh.update()
        if mesh and center:
            co=values(mesh.vertices,'co',3)
            midpoint=Vector(((co.min(axis=0)+co.max(axis=0))*.5).tolist())
            obj.location+=obj.matrix_basis.to_3x3() @ midpoint
            mesh.transform(Matrix.Translation(-midpoint))
            mesh.update()
        bpy.context.view_layer.update()
        for child,world in children.items():
            child.matrix_world=world
        bpy.context.view_layer.update()
    restore_world_normals(objects,receipt)
    outcome=verify_receipt(cfg,receipt)
    receipt['status']='verified'
    with receipt_path.open('w',encoding='utf-8') as stream:
        json.dump(receipt,stream,ensure_ascii=False,separators=(',',':'))
    scene['rhino_cleanup_path']=str(receipt_path)
    scene['rhino_cleanup_stage']='cleaned'
    bpy.ops.ed.undo_push(message='Rhino scale and origin cleanup verified')
    return outcome


def main(action,cfg):
    if action=='inspect': return inspect(cfg)
    if action=='clean': return clean(cfg)
    if action=='verify':
        scene,_=targets(cfg)
        assert scene.get('rhino_cleanup_stage')=='cleaned', 'Cleanup incomplete'
        path=pathlib.Path(cfg['cleanup_path'])
        assert str(path)==scene.get('rhino_cleanup_path')
        receipt=json.loads(path.read_text(encoding='utf-8'))
        assert receipt['status']=='verified', 'Cleanup receipt incomplete'
        return verify_receipt(cfg,receipt)
    raise ValueError('Unsupported cleanup action: '+action)


if __name__=='__main__':
    result=main(ACTION,CONFIG)
