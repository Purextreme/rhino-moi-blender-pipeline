"""Read-only orientation audit; open sheets/cavities are not auto-flipped."""
import collections
import itertools
import bpy
import numpy as np


def geometric_vertices(world, tolerance):
    # FBX can duplicate vertices at UV/normal seams. Weld only this virtual
    # adjacency map; never merge the source mesh or discard its split normals.
    cells=collections.defaultdict(list);unique=[];indices=[]
    offsets=list(itertools.product((-1,0,1),repeat=3))
    for p in world:
        key=tuple(np.floor(p/tolerance).astype(np.int64))
        found=None
        for offset in offsets:
            for index in cells[tuple(key[i]+offset[i] for i in range(3))]:
                if np.linalg.norm(p-unique[index])<=tolerance:
                    found=index;break
            if found is not None:break
        if found is None:
            found=len(unique);unique.append(p);cells[key].append(found)
        indices.append(found)
    return indices


def audit_object(obj):
    mesh=obj.data
    mesh.calc_loop_triangles()
    matrix=np.array(obj.matrix_world,dtype=np.float64)
    co=np.array([v.co[:] for v in mesh.vertices],dtype=np.float64)
    world=co @ matrix[:3,:3].T + matrix[:3,3]
    weld_tolerance=max(float(np.linalg.norm(world.max(axis=0)-world.min(axis=0)))*1e-7,1e-10)
    geometric=geometric_vertices(world,weld_tolerance)
    corners=np.array([n.vector[:] for n in mesh.corner_normals],dtype=np.float64)
    corners=corners @ np.linalg.inv(matrix[:3,:3])
    edges=collections.defaultdict(list)
    for face in mesh.polygons:
        vertices=[geometric[v] for v in face.vertices]
        for a,b in zip(vertices,vertices[1:]+vertices[:1]):
            edges[tuple(sorted((a,b)))].append((face.index,1 if a<b else -1))
    adjacency=collections.defaultdict(set)
    for users in edges.values():
        for f,_ in users:
            adjacency[f].update(g for g,_ in users if g!=f)
    components=[];unseen=set(range(len(mesh.polygons)))
    while unseen:
        pending=[unseen.pop()];faces=set(pending)
        while pending:
            for n in adjacency[pending.pop()] & unseen:
                unseen.remove(n);faces.add(n);pending.append(n)
        indices={v for f in faces for v in mesh.polygons[f].vertices}
        pts=world[sorted(indices)]
        lo,hi=pts.min(axis=0),pts.max(axis=0)
        relevant=[users for users in edges.values() if any(f in faces for f,_ in users)]
        boundary=sum(len(u)==1 for u in relevant)
        nonmanifold=sum(len(u)>2 for u in relevant)
        inconsistent=sum(len(u)==2 and u[0][1]==u[1][1] for u in relevant)
        center=(lo+hi)*.5
        volume=area=opposed_area=0.
        triangles=[]
        for tri in mesh.loop_triangles:
            if tri.polygon_index not in faces:continue
            p=world[list(tri.vertices)]-center
            n=np.cross(p[1]-p[0],p[2]-p[0]);size=np.linalg.norm(n)
            volume+=float(np.dot(p[0],np.cross(p[1],p[2])))/6
            area+=size
            shader_normal=corners[list(tri.loops)].sum(axis=0)
            if size and np.linalg.norm(shader_normal) and np.dot(n,shader_normal)<-.25*size*np.linalg.norm(shader_normal):
                opposed_area+=size
            triangles.append(tuple(tri.vertices))
        components.append({'faces':len(faces),'bounds':[lo.tolist(),hi.tolist()],
                           'boundary_edges':boundary,'nonmanifold_edges':nonmanifold,'inconsistent_edges':inconsistent,
                           'signed_volume_m3':volume,'opposed_custom_normal_area_fraction':opposed_area/area if area else 0.,
                           'status':'uncertain','reason':'open_or_nonmanifold', '_triangles':triangles})
    for i,c in enumerate(components):
        lo,hi=np.array(c['bounds'])
        nested=any(np.all(lo>=np.array(o['bounds'][0])-1e-9) and np.all(hi<=np.array(o['bounds'][1])+1e-9)
                   for j,o in enumerate(components) if i!=j)
        volume_tol=max(float(np.linalg.norm(hi-lo))**3*1e-10,1e-30)
        if not(c['boundary_edges'] or c['nonmanifold_edges'] or c['inconsistent_edges']):
            if nested:c['reason']='nested_shell_or_cavity'
            elif abs(c['signed_volume_m3'])<=volume_tol:c['reason']='near_zero_volume'
            else:
                c['status']='outward' if c['signed_volume_m3']>0 else 'inward_candidate'
                c['reason']='closed_consistent_signed_volume'
        if c['inconsistent_edges']:c['reason']='inconsistent_winding'
        if c['opposed_custom_normal_area_fraction']>.01:
            c['status']='uncertain';c['reason']='custom_normals_oppose_surface'
        del c['_triangles']
    statuses={c['status'] for c in components}
    status='outward' if statuses=={'outward'} else 'inward_candidate' if 'inward_candidate' in statuses else 'uncertain'
    return {'name':obj.name,'status':status,'virtual_weld_tolerance_m':weld_tolerance,'components':components}


def audit(scene,objects=None):
    objects=list(scene.objects) if objects is None else objects
    rows=[audit_object(o) for o in objects if o.type=='MESH']
    counts=dict(collections.Counter(row['status'] for row in rows))
    return {'execution_ok':True,'read_only':True,'counts':counts,'objects':rows,
            'needs_user_notice':[r['name'] for r in rows if r['status']!='outward'],
            'limitation':'Closed-volume classification assumes no self-intersection. Open sheets, nested cavities, ambiguous winding and custom-normal conflicts require visual inspection; no automatic flip or recalculation.'}


if __name__=='__main__':
    result=audit(bpy.data.scenes[CONFIG['scene_name']])
