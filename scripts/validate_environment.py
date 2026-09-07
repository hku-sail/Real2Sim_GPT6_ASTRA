"""Read-only evaluated-mesh collision audit for room, table, and robot animation.

Run Blender with --python scripts/validate_environment.py -- [--blend scene.blend]
    [--output outputs/environment_validation.json] [--frame-step 1]
AABB is only a broad phase. Positive reports require BVH triangle intersection or
interior containment against a closed mesh. Adjacent environment parts are not
tested against each other, since rails, uprights, trays and products are joined.
"""
import argparse
from collections import defaultdict, Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view


def arguments():
    p=argparse.ArgumentParser()
    p.add_argument('--blend')
    p.add_argument('--output',default='outputs/environment_validation.json')
    p.add_argument('--frame-step',type=int,default=1)
    p.add_argument('--contact-tolerance',type=float,default=.0002)
    p.add_argument('--fail-on-collision',action='store_true')
    return p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])


def category(o):
    n=o.name.lower()
    if n.startswith('cage |'): return 'cage'
    if n.startswith('shelf |'): return 'shelf'
    if n.startswith('room |') and ('wall' in n or 'partition' in n):return 'wall'
    if n.startswith('table |') or n.startswith('tablecloth |'):return 'table'
    if n.startswith('left_ag_gripper') or n.startswith('left_arm'):return 'left_robot'
    if n.startswith('right_ag_gripper') or n.startswith('right_arm'):return 'right_robot'
    return None


def geometry(obj,depsgraph):
    evaluated=obj.evaluated_get(depsgraph)
    mesh=evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        vertices=np.array([v.co[:] for v in mesh.vertices],dtype=float)
        triangles=[tuple(t.vertices)for t in mesh.loop_triangles]
        edges=Counter()
        for a,b,c in triangles:
            for p,q in ((a,b),(b,c),(c,a)):edges[tuple(sorted((p,q)))]+=1
        closed=bool(edges)and all(n==2 for n in edges.values())
        if not len(vertices):return None
        lo=vertices.min(axis=0);hi=vertices.max(axis=0)
        corners=np.array([[x,y,z]for x in(lo[0],hi[0])for y in(lo[1],hi[1])for z in(lo[2],hi[2])])
        return {'vertices':vertices,'triangles':triangles,'closed':closed,'corners':corners}
    finally:evaluated.to_mesh_clear()


def transformed(points,matrix):
    return points@matrix[:3,:3].T+matrix[:3,3]


def bounds(g,matrix):
    corners=transformed(g['corners'],matrix)
    return corners.min(axis=0),corners.max(axis=0)


def bvh(g,matrix):
    vertices=transformed(g['vertices'],matrix)
    return BVHTree.FromPolygons(vertices.tolist(),g['triangles'],all_triangles=True,epsilon=0),vertices


def inside(point,tree,tolerance):
    """Odd-ray parity, offset from faces, with two independent directions."""
    nearest=tree.find_nearest(Vector(point))
    if nearest[0]is None or nearest[3]<=tolerance:return False
    votes=[]
    for direction in ((.913,.371,.172),(.223,.831,.509)):
        d=Vector(direction).normalized();origin=Vector(point);count=0
        for _ in range(128):
            hit,normal,index,distance=tree.ray_cast(origin,d,100)
            if hit is None:break
            count+=1;origin=hit+d*max(tolerance*.25,1e-6)
        votes.append(count%2==1)
    return all(votes)


def exact_intersection(ga,gb,ta,tb,va,vb,tolerance):
    overlap=ta.overlap(tb)
    if overlap:return {'method':'BVH_triangle_intersection','triangle_pairs':len(overlap)}
    # A wholly embedded component can have no intersecting surface triangles.
    # Sample actual vertices, not only the AABB center of a hollow object.
    for name,container,points,isclosed in [('robot_or_table_inside_environment',ta,vb,ga['closed']),
                                          ('environment_inside_robot_or_table',tb,va,gb['closed'])]:
        if not isclosed:continue
        indices=np.linspace(0,len(points)-1,min(9,len(points)),dtype=int)
        for point in points[indices]:
            if inside(point,container,tolerance):return {'method':'closed_mesh_containment','containment':name,'interior_vertex':point.tolist()}
    return None


def ranges(values):
    values=sorted(set(values));out=[]
    for x in values:
        if not out or x>out[-1][1]+1:out.append([x,x])
        else:out[-1][1]=x
    return out


def main():
    args=arguments();started=time.perf_counter()
    if args.blend:bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend).resolve()))
    scene=bpy.context.scene;scene.frame_set(scene.frame_start);depsgraph=bpy.context.evaluated_depsgraph_get()
    source=Path(bpy.data.filepath).resolve()
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    objects={o.name:o for o in scene.objects if o.type in {'MESH','CURVE'}and category(o)}
    groups={n:category(o)for n,o in objects.items()}
    geoms={n:geometry(o,depsgraph)for n,o in objects.items()}
    geoms={n:g for n,g in geoms.items()if g is not None}
    env=[n for n in geoms if groups[n]in{'wall','cage','shelf'}]
    tables=[n for n in geoms if groups[n]=='table']
    robots=[n for n in geoms if groups[n]in{'left_robot','right_robot'}]
    static_matrices={n:np.array(objects[n].matrix_world)for n in env+tables}
    static_bounds={n:bounds(geoms[n],static_matrices[n])for n in env+tables}
    static_trees={}
    events={};broadphase=0;precise=0;false_aabb=0
    robot_envelope={k:[np.full(3,np.inf),np.full(3,-np.inf)]for k in ['left_robot','right_robot']}
    def record(a,b,frame,ma,mb,ba,bb,cache):
        nonlocal broadphase,precise,false_aabb
        penetration=np.minimum(ba[1],bb[1])-np.maximum(ba[0],bb[0])
        if np.any(penetration<=args.contact_tolerance):return
        broadphase+=1
        if a not in static_trees:static_trees[a]=bvh(geoms[a],ma)
        if b not in cache:cache[b]=bvh(geoms[b],mb)
        ta,va=static_trees[a];tb,vb=cache[b];precise+=1
        hit=exact_intersection(geoms[a],geoms[b],ta,tb,va,vb,args.contact_tolerance)
        if hit is None:false_aabb+=1;return
        key=(a,b)
        if key not in events:events[key]={'environment_object':a,'environment_category':groups[a],
            'other_object':b,'other_category':groups[b],'frames':[],
            'maximum_aabb_overlap_extent_m':[0,0,0],'first_geometric_evidence':hit}
        rec=events[key];rec['frames'].append(frame)
        rec['maximum_aabb_overlap_extent_m']=np.maximum(rec['maximum_aabb_overlap_extent_m'],penetration).tolist()
    for a in env:
        for b in tables:record(a,b,0,static_matrices[a],static_matrices[b],static_bounds[a],static_bounds[b],static_trees)
    static_event_count=len(events)
    checked=[]
    for frame in range(scene.frame_start,scene.frame_end+1,max(1,args.frame_step)):
        scene.frame_set(frame);depsgraph.update();checked.append(frame)
        dynamic_cache={}
        for b in robots:
            mb=np.array(objects[b].matrix_world);bb=bounds(geoms[b],mb)
            envelope=robot_envelope[groups[b]];envelope[0]=np.minimum(envelope[0],bb[0]);envelope[1]=np.maximum(envelope[1],bb[1])
            for a in env:record(a,b,frame-scene.frame_start,static_matrices[a],mb,static_bounds[a],bb,dynamic_cache)
        if len(checked)%100==0:print('VALIDATE_PROGRESS',len(checked),'frames',len(events),'colliding pairs',flush=True)
    collision_records=[]
    for rec in events.values():
        frames=rec.pop('frames');rec['source_frame_ranges']=ranges(frames)
        rec['intersecting_frame_count']=len(frames);rec['static']=rec['other_category']=='table'
        if rec['static']:rec['source_frame_ranges']=[[0,scene.frame_end-scene.frame_start]];rec['intersecting_frame_count']=scene.frame_end-scene.frame_start+1
        collision_records.append(rec)
    # Visibility diagnostic: frustum projection plus occlusion rays to sampled
    # shelf surface vertices. No conclusion is based only on object existence.
    shelf_names=[n for n in env if groups[n]=='shelf'];visibility=[]
    for frame in sorted(set([scene.frame_start,min(scene.frame_end,236),min(scene.frame_end,401),scene.frame_end])):
        scene.frame_set(frame);depsgraph.update()
        for camera_name in ['head','hand_left','hand_right']:
            camera=scene.objects.get(camera_name)
            if camera is None:continue
            seen=0;in_frame=0;occluders=Counter();uvs=[]
            for n in shelf_names:
                g=geoms[n];indices=np.linspace(0,len(g['vertices'])-1,min(12,len(g['vertices'])),dtype=int)
                points=transformed(g['vertices'][indices],static_matrices[n])
                for point in points:
                    ndc=world_to_camera_view(scene,camera,Vector(point))
                    if ndc.z<=camera.data.clip_start or not(0<=ndc.x<=1 and 0<=ndc.y<=1):continue
                    in_frame+=1;uvs.append([ndc.x*scene.render.resolution_x,(1-ndc.y)*scene.render.resolution_y])
                    direction=Vector(point)-camera.matrix_world.translation;distance=direction.length
                    hit,loc,normal,idx,obj,matrix=scene.ray_cast(depsgraph,camera.matrix_world.translation,direction.normalized(),distance=distance+.001)
                    if not hit or obj.name.startswith('Shelf |')or (loc-Vector(point)).length<.002:seen+=1
                    else:occluders[obj.name]+=1
            visibility.append({'source_frame':frame-scene.frame_start,'camera':camera_name,'in_frustum_surface_samples':in_frame,'visible_surface_samples':seen,
                'projected_sample_bbox_uv':[np.min(uvs,axis=0).tolist(),np.max(uvs,axis=0).tolist()]if uvs else None,
                'occluders':dict(occluders.most_common(8))})
    env_envelopes={k:None for k in ['wall','cage','shelf','table']}
    for k in env_envelopes:
        names=[n for n in env+tables if groups[n]==k]
        if names:env_envelopes[k]={'minimum':np.min([static_bounds[n][0]for n in names],axis=0).tolist(),'maximum':np.max([static_bounds[n][1]for n in names],axis=0).tolist()}
    room_limits={}
    for side,key in [('right','right_robot'),('left','left_robot')]:
        box=robot_envelope[key]
        wallx=max(box[1][0],env_envelopes['table']['maximum'][0])+.025 if side=='right'else min(box[0][0],env_envelopes['table']['minimum'][0])-.025
        room_limits[side]={'suggested_minimum_wall_inner_face_x_m'if side=='right'else'suggested_maximum_wall_inner_face_x_m':float(wallx),'meaning':'Conservative x-only safe halfspace including full animated robot/cables and table plus 25 mm clearance; more compact y/z-dependent layouts can pass the exact collision test.'}
    output={'status':'passed'if not collision_records else'failed_geometric_intersections','checked_utc':datetime.now(timezone.utc).isoformat(),
        'blend_path':str(source),'blend_sha256':sha,'frame_start':scene.frame_start,'frame_end':scene.frame_end,'source_frame_count':len(checked),
        'frame_step':args.frame_step,'contact_tolerance_m':args.contact_tolerance,'method':'Evaluated modifier meshes; world-space AABB broad phase, BVH triangle overlap, and closed-mesh ray-parity containment. AABB-only overlaps are discarded.','geometry_counts':dict(Counter(groups[n]for n in geoms)),
        'broadphase_candidate_pairs_over_frames':broadphase,'precise_tests':precise,'aabb_false_positives_rejected':false_aabb,
        'colliding_object_pair_count':len(collision_records),'static_table_collision_pair_count':static_event_count,'collisions':collision_records,
        'robot_motion_envelopes':{k:{'minimum':v[0].tolist(),'maximum':v[1].tolist()}for k,v in robot_envelope.items()},
        'environment_envelopes':env_envelopes,'wall_placement_suggestions':room_limits,
        'shelf_visibility':{'shelf_mesh_count':len(shelf_names),'surface_sample_tests':visibility,
            'assessment':'Surface samples with first-hit shelf visibility distinguish modeled-but-occluded shelving from absent shelving. Use rendered previews to verify recognizable products and shelf tiers.','recommendation':'Keep right shelving on the wrist-camera-facing side of any opaque wall; moving an opaque side panel behind or above the shelf is preferable to leaving the shelf completely hidden.'},
        'limitations':['No robot/environment contact is intentionally allowed here; support bases/table mounts are excluded from robot-table checks.','This checks every sampled pose, not continuous swept volume between frames. Default frame-step 1 covers all 593 recorded states.','Boundary overlaps shallower than contact tolerance in any AABB axis are treated as touching.','Containment samples supplement BVH surfaces and assume closed manifold meshes; non-manifold imported assets are reported by surface crossings only.','Shelf visibility uses sparse deterministic surface samples, not a final pixel segmentation or photorealism score.'],
        'elapsed_seconds':time.perf_counter()-started}
    baseline_path=Path('outputs/environment_validation_baseline.json')
    if baseline_path.exists():
        baseline=json.loads(baseline_path.read_text())
        output['baseline_comparison']={'baseline_report':str(baseline_path),
            'baseline_blend_sha256':baseline.get('blend_sha256'),
            'baseline_colliding_object_pairs':baseline.get('colliding_object_pair_count'),
            'current_colliding_object_pairs':len(collision_records),
            'old_intersections_detected':baseline.get('colliding_object_pair_count',0)>0,
            'all_old_intersections_resolved':baseline.get('colliding_object_pair_count',0)>0 and not collision_records}
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(output,indent=2)+'\n')
    print('ENVIRONMENT_VALIDATION',json.dumps({k:output[k]for k in ['status','colliding_object_pair_count','static_table_collision_pair_count','source_frame_count','elapsed_seconds']}),flush=True)
    if args.fail_on_collision and collision_records:raise SystemExit(2)


if __name__=='__main__':main()
