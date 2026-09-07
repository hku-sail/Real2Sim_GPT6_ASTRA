"""Create the editable Blender scene and bake one state per input RGB frame.
Run: blender -b --python scripts/build_replay.py -- --preview
"""
import bpy,sys,math,json,argparse
from pathlib import Path
from mathutils import Vector,Matrix,Quaternion
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from robot_geometry import build_gripper,set_gripper_opening,build_arm
from environment_geometry import build_environment
from render_sequence import configure_engine
from scene_math import head_ray,head_project

def material(name,color,metal=0,rough=.4,emission=0):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
 bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(*color,1);bs.inputs['Metallic'].default_value=metal;bs.inputs['Roughness'].default_value=rough
 if emission:bs.inputs['Emission Color'].default_value=(*color,1);bs.inputs['Emission Strength'].default_value=emission
 return m

def camera(name,p,right,up,forward,f):
 d=bpy.data.cameras.new(name);o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o)
 o.location=p;o.rotation_mode='QUATERNION';o.rotation_quaternion=Matrix((Vector(right),Vector(up),-Vector(forward))).transposed().to_quaternion()
 d.type='PERSP';d.sensor_width=36;d.sensor_fit='HORIZONTAL';d.lens=f*36/640;d.clip_start=.005;d.clip_end=50
 return o

def pose(forward,up=Vector((0,0,1))):
 y=Vector(forward).normalized();x=y.cross(up).normalized();z=x.cross(y).normalized()
 return Matrix((x,y,z)).transposed().to_quaternion()

def key(obj,f):
 obj.keyframe_insert('location',frame=f);obj.keyframe_insert('rotation_quaternion',frame=f)

def interp(keys,frame):
 if frame<=keys[0][0]:return keys[0][1:]
 if frame>=keys[-1][0]:return keys[-1][1:]
 for a,b in zip(keys,keys[1:]):
  if a[0]<=frame<=b[0]:
   t=(frame-a[0])/(b[0]-a[0]);t=t*t*(3-2*t)
   return [aa+(bb-aa)*t for aa,bb in zip(a[1:],b[1:])]

def support_arm(name,side,mats):
 # The visible wrists are supplemented with fixed bases and two rigid links.
 # This is analytic geometric IK, not an estimate of the hidden robot's joints.
 shoulder=Vector((side*.70,-.39,.18))
 objects=[]
 for label in ['upper','lower']:
  bpy.ops.mesh.primitive_cylinder_add(vertices=40,radius=.038,depth=1)
  ob=bpy.context.object;ob.name=name+'_'+label;ob.rotation_mode='QUATERNION'
  ob.data.materials.append(mats['white']);mod=ob.modifiers.new('Soft link edges','BEVEL');mod.width=.015;mod.segments=4
  for poly in ob.data.polygons:poly.use_smooth=True
  objects.append(ob)
 for label in ['shoulder','elbow','wrist_joint']:
  bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,radius=.046)
  ob=bpy.context.object;ob.name=name+'_'+label;ob.data.materials.append(mats['white'])
  for poly in ob.data.polygons:poly.use_smooth=True
  objects.append(ob)
 bpy.ops.mesh.primitive_cylinder_add(vertices=40,radius=.075,depth=.19,location=(side*.70,-.39,.015))
 bpy.context.object.name=name+'_fixed_base';bpy.context.object.data.materials.append(mats['white'])
 bpy.ops.mesh.primitive_cube_add(size=1,location=(side*.70,-.39,-.095))
 bpy.context.object.name=name+'_mounting_plate';bpy.context.object.dimensions=(.20,.22,.025);bpy.context.object.data.materials.append(mats['metal'])
 return shoulder,objects

def update_support(support,gripper,frame):
 shoulder,objects=support
 endpoint=gripper.location+gripper.rotation_quaternion@Vector((0,-.427*.72,.022*.72))
 dvec=endpoint-shoulder;d=dvec.length;direction=dvec.normalized()
 length=.29;distance=min(d,length*2-.0001)
 bend=Vector((0,0,1));bend=(bend-direction*direction.dot(bend)).normalized()
 elbow=shoulder+direction*(distance*.5)+bend*math.sqrt(max(0,length*length-distance*distance*.25))
 for ob,a,b in [(objects[0],shoulder,elbow),(objects[1],elbow,endpoint)]:
  ob.location=(a+b)*.5;ob.rotation_quaternion=(b-a).to_track_quat('Z','Y');ob.scale.z=(b-a).length
  key(ob,frame);ob.keyframe_insert('scale',frame=frame)
 for ob,p in zip(objects[2:],[shoulder,elbow,endpoint]):ob.location=p;ob.keyframe_insert('location',frame=frame)

def build():
 bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
 sc=bpy.context.scene;sc.render.engine='CYCLES' if False else 'BLENDER_EEVEE_NEXT'
 sc.render.resolution_x=640;sc.render.resolution_y=480;sc.render.resolution_percentage=100
 sc.render.image_settings.file_format='PNG';sc.render.image_settings.color_mode='RGB';sc.render.image_settings.color_depth='8';sc.render.image_settings.compression=30
 sc.render.fps=30;sc.frame_start=1;sc.frame_end=593
 sc.render.film_transparent=False;sc.render.use_file_extension=True
 sc.eevee.taa_render_samples=24
 sc.world.color=(.16,.16,.16);sc.world.use_nodes=True;sc.world.node_tree.nodes['Background'].inputs[0].default_value=(.20,.225,.23,1);sc.world.node_tree.nodes['Background'].inputs[1].default_value=.45
 sc.view_settings.view_transform='AgX';sc.view_settings.look='AgX - Medium High Contrast';sc.view_settings.exposure=-1.0
 env=build_environment()
 # Visual fit keeps the measured mouth fixed while tapering/leaning the base.
 for vertex in env['cup_body'].data.vertices:
  vertex.co.y += .035 * max(0,1-vertex.co.z/.115)
  vertex.co.x -= .006
 for obj in env['cup'].children:
  if obj.type=='CURVE':
   for sp in obj.data.splines:
    for pt in sp.bezier_points:
     pt.co.y += .035*max(0,1-pt.co.z/.115);pt.co.x-=.006
 env['panda'].scale=(1.08,1.12,1.21)
 floor_bs=env['materials']['floor'].node_tree.nodes.get('Principled BSDF')
 floor_bs.inputs['Base Color'].default_value=(.05,.055,.047,1)
 # A capped bottle visible near the table edge in the fixed wrist view.
 bottle_mat=material('Dark translucent bottle',(.018,.023,.02),.05,.32)
 for rad,dep,z in [(.023,.065,.034),(.014,.020,.076),(.010,.072,.116)]:
  bpy.ops.mesh.primitive_cylinder_add(vertices=40,radius=rad,depth=dep,location=(.412,.067,z))
  ob=bpy.context.object;ob.name='Small capped bottle';ob.data.materials.append(bottle_mat)
  mod=ob.modifiers.new('Soft bottle edges','BEVEL');mod.width=.005;mod.segments=3
 mats={k:material('Robot_'+k,*args) for k,args in {'black':((.009,.012,.010),.18,.29),'rubber':((.005,.008,.007),0,.8),'metal':((.47,.50,.5),.72,.30),'white':((.78,.80,.77),.05,.23),'green_led':((0,.80,.47),.2,.18,2)}.items()}
 for loc,power,size in [((-.2,-.6,2.5),140,3.0),((1.4,.2,1.7),65,2.0),((-.9,.8,2.1),70,2.5)]:
  d=bpy.data.lights.new('Ceiling softbox','AREA');o=bpy.data.objects.new(d.name,d);bpy.context.collection.objects.link(o);o.location=loc;d.energy=power;d.shape='DISK';d.size=size;o.rotation_euler=(-Vector(loc)).to_track_quat('-Z','Y').to_euler()
 V=json.loads((ROOT/'reconstruction/vision_tracks.json').read_text());hc=V['head_camera'];lc=V['hand_left_camera_fit']
 R=hc['world_to_camera_rotation'];cams={'head':camera('head',hc['position'],R[0],[-v for v in R[1]],R[2],hc['intrinsics'][0][0])}
 R=lc['world_to_camera_rotation'];cams['hand_left']=camera('hand_left',lc['position'],R[0],[-v for v in R[1]],R[2],lc['intrinsics'][0][0])
 left=build_gripper('Left_AG_gripper',mats);right=build_gripper('Right_AG_gripper',mats)
 for g in (left,right):g.rotation_mode='QUATERNION';g.scale=(.72,)*3;build_arm(g.name+'_white_arm',g)
 supports=[support_arm('Left_arm',-1,mats),support_arm('Right_arm',1,mats)]
 # Initial approximate pose; image-derived trajectory below can override it.
 left.rotation_quaternion=pose((.94,.20,-.27));left.location=Vector(head_ray((105,365),.32))-left.rotation_quaternion@Vector((0,-.05*.72,0))
 left_pose_path=ROOT/'reconstruction/left_gripper_pose.json'
 if left_pose_path.exists() and json.loads(left_pose_path.read_text()).get('approved_for_render',False):
  lp=json.loads(left_pose_path.read_text());left.location=lp['location'];left.rotation_quaternion=lp['quaternion_wxyz']
 # Fit the visible fixed camera enclosure to the head-image silhouette.
 target_camera=Vector(head_ray((27,270),.40))
 camera_local=left.rotation_quaternion.inverted()@(target_camera-left.location)/.72
 camera_delta=camera_local-Vector((0,-.09,.10))
 for obj in left.children:
  if '_camera_' in obj.name and obj.type=='MESH':obj.location+=camera_delta
 right.rotation_quaternion=pose((-.94,.20,-.27));right.location=Vector(head_ray((549,360),.32))-right.rotation_quaternion@Vector((0,-.05*.72,0))
 # Wrist camera is rigidly attached to the moving right end effector.
 cr=camera('hand_right',(0,-.035,.09),(1,0,0),(0,.25,.968),(0,.968,-.25),420);cr.parent=right;cams['hand_right']=cr
 # Marker is independent after release; its trajectory is baked into editable keys.
 ink=material('Marker glossy black',(.006,.008,.007),.15,.22)
 bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=.0065,depth=.145)
 pen=bpy.context.object;pen.name='Black_marker';pen.data.materials.append(ink);pen.rotation_mode='QUATERNION'
 bevel=pen.modifiers.new('Rounded marker ends','BEVEL');bevel.width=.002;bevel.segments=3
 for p in pen.data.polygons:p.use_smooth=True
 bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=.007,depth=.04)
 cap=bpy.context.object;cap.name='Marker_cap';cap.parent=pen;cap.location=(0,0,.053);cap.data.materials.append(ink)
 # Fine silver seams and cap clip create visible marker details without baked photos.
 bpy.ops.mesh.primitive_torus_add(major_radius=.00665,minor_radius=.0003,major_segments=24,minor_segments=8)
 seam=bpy.context.object;seam.name='Marker_cap_seam';seam.parent=pen;seam.location=(0,0,.033);seam.data.materials.append(mats['metal'])
 bpy.ops.mesh.primitive_cube_add(size=1)
 clip=bpy.context.object;clip.name='Marker_clip';clip.parent=pen;clip.location=(.007,0,.052);clip.dimensions=(.002,.003,.035);clip.data.materials.append(ink)
 e0,e1=[Vector(x) for x in V['static_landmarks']['marker_world_endpoints']];pen_start=(e0+e1)/2;pen_axis=(e0-e1).normalized();pen_start_rot=pen_axis.to_track_quat('Z','Y')
 # Temporary visual keyframes, replaced by constrained motion.json when available.
 states=[(0,549,360,.32,-.94,.20,-.27,.14),(55,549,360,.32,-.94,.20,-.27,.14),(100,593,210,.22,-.92,.32,-.2,.14),(160,594,231,.11,-.92,.32,-.22,.14),(210,566,236,.07,-.91,.38,-.12,.08),(240,563,234,.07,-.91,.38,-.12,.013),(270,579,218,.12,-.88,.42,-.05,.013),(320,514,221,.26,-.75,.49,.42,.013),(360,434,231,.27,-.63,.66,.4,.013),(400,425,252,.22,-.60,.70,.39,.013),(460,418,263,.21,-.59,.7,.41,.013),(480,430,254,.24,-.60,.70,.35,.10),(510,467,238,.28,-.75,.5,.15,.14),(550,539,276,.33,-.93,.21,-.29,.14),(592,549,360,.32,-.94,.20,-.27,.14)]
 motionpath=ROOT/'reconstruction/motion.json';motion=json.loads(motionpath.read_text()) if motionpath.exists() else None
 records=[]
 for i in range(593):
  if motion:
   m=motion['frames'][i];right.location=m['right_root_position'];right.rotation_quaternion=m['right_root_quaternion'];width=m['opening_m']
   if 'right_camera_local_position' in motion:cr.location=motion['right_camera_local_position'];cr.rotation_quaternion=motion['right_camera_local_quaternion'];cr.data.lens=motion.get('right_camera_focal_px',420)*36/640
  else:
   u,v,z,dx,dy,dz,width=interp(states,i);right.rotation_quaternion=pose((dx,dy,dz));right.location=Vector(head_ray((u,v),z))-right.rotation_quaternion@Vector((0,-.05*.72,0))
  set_gripper_opening(right,width);key(right,i+1)
  update_support(supports[0],left,i+1);update_support(supports[1],right,i+1)
  for ch in right.children:
   if ch.get('role'):
    ch.keyframe_insert('location',frame=i+1);ch.keyframe_insert('rotation_euler',frame=i+1);ch.keyframe_insert('scale',frame=i+1)
  if motion and 'marker_position' in motion['frames'][i]:
   pen.location=m['marker_position'];pen.rotation_quaternion=m['marker_quaternion']
  elif i<242:
   pen.location=pen_start;pen.rotation_quaternion=pen_start_rot
  elif i<480:
   pen.location=right.location+right.rotation_quaternion@Vector((0,.09*.72,-.018));pen.rotation_quaternion=(right.rotation_quaternion@Vector((0,1,0))).to_track_quat('Z','Y')
  else:
   pen.location=(-.013,.013,.106);pen.rotation_quaternion=Vector((-.22,-.05,.974)).to_track_quat('Z','Y')
  key(pen,i+1)
  records.append({'source_frame':i,'blender_frame':i+1,'right_root_position':list(right.location),'right_root_quaternion_wxyz':list(right.rotation_quaternion),'opening_m_unscaled':width,'marker_position':list(pen.location)})
 # Use linear interpolation between measured frames: exactly one state per input frame.
 for a in bpy.data.actions:
  try:
   for fc in a.fcurves:
    for k in fc.keyframe_points:k.interpolation='LINEAR'
  except AttributeError:pass
 sc['reconstruction_note']='RGB-only visual reconstruction. Approximate metric scale, camera parameters and hidden arm shape. No measured joints or dynamics.'
 sc['frame_mapping']='source PNG n (0..592) = Blender frame n+1 = video frame n, playback 30fps assumed.'
 for view,c in cams.items():
  c.data.show_background_images=True
  reference=c.data.background_images.new()
  reference.image=bpy.data.images.load(str(ROOT/'real_rgb'/view/'000000.png'),check_existing=False)
  reference.image.source='SEQUENCE';reference.image.filepath='//../real_rgb/'+view+'/000000.png'
  reference.image_user.frame_duration=593;reference.image_user.frame_start=1;reference.image_user.use_auto_refresh=True
  reference.alpha=.30;reference.display_depth='BACK'
 configure_engine(sc,'cycles',64)
 sc.frame_set(1);sc.camera=cams['head']
 bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'reconstruction/replay.blend'))
 (ROOT/'reconstruction/baked_frame_states.json').write_text(json.dumps(records,indent=2))
 return sc,cams

if __name__=='__main__':
 args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
 ap=argparse.ArgumentParser();ap.add_argument('--preview',action='store_true');ap.add_argument('--frames',default='0,220,400,592');ns=ap.parse_args(args)
 sc,cams=build()
 if ns.preview:
  out=ROOT/'outputs/preview';out.mkdir(parents=True,exist_ok=True)
  for f in map(int,ns.frames.split(',')):
   sc.frame_set(f+1)
   for v,c in cams.items():
    sc.camera=c;sc.render.filepath=str(out/f'sim_{v}_{f:06}.png');bpy.ops.render.render(write_still=True)
