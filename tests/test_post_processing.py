import pathlib
import runpy
import tempfile
import json
import shutil
import bpy
from mathutils import Matrix

SKILL=pathlib.Path(__file__).resolve().parents[1]
WORK=pathlib.Path(tempfile.mkdtemp(prefix='rhino_cleanup_test_'))
ns=runpy.run_path(str(SKILL/'scripts'/'blender_cleanup.py'),run_name='cleanup_test')

def fixture(label, offset=False):
    s=bpy.data.scenes.new('Fixture '+label)
    bpy.context.window.scene=s
    s['rhino_run_id']=label
    root=bpy.data.objects.new('Root '+label,None);s.collection.objects.link(root);root['rhino_run_id']=label
    group=bpy.data.objects.new('Group '+label,None);s.collection.objects.link(group);group.parent=root
    group.scale=(2,.5,3)
    bpy.context.view_layer.update()
    mesh=bpy.data.meshes.new('Data '+label)
    mesh.from_pydata([(10,20,30),(11,20,30),(11,22,30),(10,22,30),(10,20,33),(11,20,33),(11,22,33),(10,22,33)],[],[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])
    mesh.update();mesh.normals_split_custom_set([tuple(n.vector) for n in mesh.corner_normals])
    uv=mesh.uv_layers.new(name='SourceUV')
    for i,v in enumerate(uv.data):v.uv=(i/30,(i%4)/4)
    mat=bpy.data.materials.new('Material '+label);mesh.materials.append(mat)
    a=bpy.data.objects.new('Mesh A '+label,mesh);s.collection.objects.link(a);a.parent=group
    a.matrix_world=Matrix.Diagonal((.002,.001,-.003,1))
    b=bpy.data.objects.new('Mesh B '+label,mesh);s.collection.objects.link(b);b.parent=group
    b.matrix_world=Matrix.Diagonal((.001,.001,.001,1))
    if offset:b.location.x+=.2
    b.hide_set(True);b.hide_select=True
    ref=bpy.data.objects.new('UV Reference '+label,None);s.collection.objects.link(ref);ref.parent=a;ref.scale=(12,8,.01)
    control=bpy.data.objects.new('UV Control '+label,None);s.collection.objects.link(control);control.parent=ref;control.location=(.01,.02,0)
    mod=a.modifiers.new('Keep editable UV','UV_WARP');mod.object_from=ref;mod.object_to=control;mod.uv_layer='SourceUV'
    outside_scene=bpy.data.scenes.new('Outside '+label)
    outside=bpy.data.objects.new('Unrelated '+label,mesh);outside_scene.collection.objects.link(outside)
    bpy.context.view_layer.update()
    cfg={'scene_name':s.name,'request_id':label,'root_name':root.name,
         'cleanup_path':str(WORK/(label+'.json')),'cleanup_backup_path':str(WORK/(label+'.blend'))}
    return cfg,a,b,group,ref,control,outside

cfg,a,b,g,r,c,out=fixture('common_origin')
assert ns['inspect'](cfg)['all_mesh_origins_at_world_zero']
result=ns['clean'](cfg)
assert result['all_scales_one'] and result['origins_centered']
assert a.data!=out.data and b.data!=out.data and a.data!=b.data
assert ns['main']('verify',cfg)['verification_ok']
try:ns['clean'](cfg);raise RuntimeError('Repeated cleanup accepted')
except AssertionError:pass
old=a.data.vertices[0].co.copy();a.data.vertices[0].co.x+=.01
try:ns['main']('verify',cfg);raise RuntimeError('Bad geometry accepted')
except AssertionError:pass
a.data.vertices[0].co=old;a.data.update()
old_uv=a.data.uv_layers[0].data[0].uv.copy();a.data.uv_layers[0].data[0].uv.x+=.1
try:ns['main']('verify',cfg);raise RuntimeError('Bad UV accepted')
except AssertionError:pass
a.data.uv_layers[0].data[0].uv=old_uv
cfg2,a2,*rest=fixture('intentional_origin',offset=True)
assert not ns['inspect'](cfg2)['all_mesh_origins_at_world_zero']
result2=ns['clean'](cfg2)
assert result2['all_scales_one'] and not result2['origins_centered']
assert ns['main']('verify',cfg2)['verification_ok']
cfg3,a3,*rest=fixture('guard_modifier')
a3.modifiers.new('User bevel','BEVEL')
try:ns['clean'](cfg3);raise RuntimeError('Geometry modifier accepted')
except AssertionError:pass
assert not pathlib.Path(cfg3['cleanup_backup_path']).exists()
assert not bpy.context.scene.get('rhino_cleanup_stage')
audit=runpy.run_path(str(SKILL/'scripts'/'blender_normals_audit.py'),run_name='audit_test')
bpy.context.window.scene=bpy.data.scenes[cfg2['scene_name']]
assert audit['audit_object'](bpy.data.objects['Unrelated intentional_origin'])['status']=='outward'
reversed_mesh=bpy.data.objects['Unrelated intentional_origin'].data.copy()
reversed_mesh.flip_normals()
reversed_mesh.normals_split_custom_set([tuple(n.vector) for n in reversed_mesh.corner_normals])
reversed_obj=bpy.data.objects.new('Reversed cube',reversed_mesh)
bpy.context.scene.collection.objects.link(reversed_obj)
assert audit['audit_object'](reversed_obj)['status']=='inward_candidate'
plane=bpy.data.meshes.new('Open label');plane.from_pydata([(0,0,0),(1,0,0),(1,1,0),(0,1,0)],[],[(0,1,2,3)]);plane.update()
plane_obj=bpy.data.objects.new('Open label',plane);bpy.context.scene.collection.objects.link(plane_obj)
assert audit['audit_object'](plane_obj)['status']=='uncertain'

# Actual FBX import -> plan -> rebuild(default cleanup/audit) -> independent verify.
pipeline=runpy.run_path(str(SKILL/'scripts'/'blender_pipeline.py'),run_name='pipeline_test')
source=bpy.data.scenes.new('Transport source');bpy.context.window.scene=source
source.unit_settings.system='METRIC';source.unit_settings.scale_length=1
source_objects=[];occurrences=[]
for i,(lo,hi) in enumerate([((2,3,5),(13,20,28)),((31,47,71),(48,76,102)),((91,118,177),(120,155,220))]):
    token='RB_%05d_%08x'%(i,i+1)
    verts=[(lo[0],lo[1],lo[2]),(hi[0],lo[1],lo[2]),(hi[0],hi[1],lo[2]),(lo[0],hi[1],lo[2]),
           (lo[0],lo[1],hi[2]),(hi[0],lo[1],hi[2]),(hi[0],hi[1],hi[2]),(lo[0],hi[1],hi[2])]
    mesh=bpy.data.meshes.new(token);mesh.from_pydata(verts,[],[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]);mesh.update()
    mesh.normals_split_custom_set([tuple(n.vector) for n in mesh.corner_normals])
    obj=bpy.data.objects.new(token,mesh);source.collection.objects.link(obj);obj.scale=(.001,)*3;obj.select_set(True);source_objects.append(obj)
    occurrences.append({'key':'o'+str(i),'parent':'b0' if i==0 else None,'source_id':str(i),'transport_name':token,'name':'Part '+str(i),'layer':'A::B',
                        'bbox':{'min':dict(zip(('x','y','z'),lo)),'max':dict(zip(('x','y','z'),hi))},
                        'source_metadata':{'visible':True,'locked':False,'effective_visible':True,'effective_locked':False}})
bpy.context.view_layer.objects.active=source_objects[0]
fbx=WORK/'fixture.fbx'
assert 'FINISHED' in bpy.ops.export_scene.fbx(filepath=str(fbx),use_selection=True,use_mesh_modifiers=False,add_leaf_bones=False,bake_anim=False)
manifest={'schema_version':2,'metadata_request_id':'full-test','document':{'model_units':'Millimeters'},
          'layers':[{'full_path':'A','name':'A','id':'a','visible':True,'locked':False},{'full_path':'A::B','name':'B','id':'b','visible':True,'locked':False},
                    {'full_path':'Unused','name':'Unused','id':'unused','visible':True,'locked':False}],
          'blocks':[{'key':'b0','parent':None,'name':'Scaled Block','source_id':'b0','definition_id':'def','definition_name':'Definition',
                     'world_matrix':[[2,0,0,10],[0,.5,0,20],[0,0,3,30],[0,0,0,1]],'layer':'A',
                     'source_metadata':{'visible':True,'locked':False,'effective_visible':True,'effective_locked':False}}],
          'occurrences':occurrences,'omitted':[]}
manifest_path=WORK/'manifest.json';manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
cfg_full={'request_id':'full-test','scene_name':'Full Pipeline Test','root_name':'Model root','fbx_path':str(fbx),'occurrences_path':str(manifest_path),
          'backup_path':str(WORK/'before_import.blend'),'plan_path':str(WORK/'plan.json'),
          'cleanup_path':str(WORK/'cleanup.json'),'cleanup_backup_path':str(WORK/'before_cleanup.blend'),
          'bbox_tolerance_source_units':.001,'mapping_gap_m':1e-6}
assert pipeline['main']('import',cfg_full)['execution_ok']
assert pipeline['main']('plan',cfg_full)['verification_ok']
rebuilt=pipeline['main']('rebuild',cfg_full)
assert rebuilt['verification_ok'] and rebuilt['all_scales_one'] and rebuilt['conversion_verified_before_cleanup']
assert pipeline['main']('verify',cfg_full)['verification_ok']
assert pipeline['main']('audit_normals',cfg_full)['counts']=={'outward':3}
# Relocation is accepted only for byte-identical conversion inputs.
consolidated=WORK/'consolidated';consolidated.mkdir()
for key in ('fbx_path','occurrences_path','plan_path'):
    old=pathlib.Path(cfg_full[key]);new=consolidated/old.name;shutil.copy2(old,new);cfg_full[key]=str(new)
assert pipeline['main']('verify',cfg_full)['verification_ok']
with pathlib.Path(cfg_full['fbx_path']).open('ab') as stream:stream.write(b'bad change')
try:pipeline['main']('verify',cfg_full);raise RuntimeError('Changed FBX accepted')
except AssertionError:pass
print({'cleanup_common':result,'cleanup_intentional':result2,'pipeline_default_cleanup':rebuilt,
       'checks':'sharing, parent compensation, UV controls, hidden objects, reentry/geometry/UV/modifier guards, outward/reversed/open normals, real FBX import, relocation and input tamper passed'})
