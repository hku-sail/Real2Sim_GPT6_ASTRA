#!/usr/bin/env python3
"""Extract visual measurements; geometry is a fitted, uncalibrated approximation.
Run with a Python environment containing NumPy, SciPy and OpenCV.
"""
from pathlib import Path
import json
import cv2
import numpy as np
from scipy.optimize import least_squares
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'reconstruction';OUT.mkdir(exist_ok=True)
N=593

def led(im,cam):
 hsv=cv2.cvtColor(im,cv2.COLOR_BGR2HSV)
 mask=cv2.inRange(hsv,np.array([75,90,135]),np.array([100,255,255]))
 if cam=='head': mask[:100]=0;mask[:,:375]=0
 else: mask[260:]=0;mask[:,:220]=0
 cs,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
 cs=[c for c in cs if cv2.contourArea(c)>7]
 if not cs:return None
 c=max(cs,key=cv2.contourArea);m=cv2.moments(c)
 return [round(m['m10']/m['m00'],3),round(m['m01']/m['m00'],3)]

def cup(im,cam):
 hsv=cv2.cvtColor(im,cv2.COLOR_BGR2HSV)
 mask=cv2.inRange(hsv,np.array([35,65,28]),np.array([83,255,255]))
 if cam=='head':mask[:190]=0;mask[335:]=0;mask[:,:333]=0;mask[:,405:]=0
 if cam=='hand_left':mask[:200]=0;mask[330:]=0;mask[:,:99]=0;mask[:,209:]=0
 if cam=='hand_right':mask[:,605:]=0
 mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
 cs,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
 cs=[c for c in cs if cv2.contourArea(c)>75]
 if not cs:return None
 c=max(cs,key=cv2.contourArea);m=cv2.moments(c);x,y,w,h=cv2.boundingRect(c)
 return {'centroid':[round(m['m10']/m['m00'],2),round(m['m01']/m['m00'],2)],'bbox':[int(x),int(y),int(w),int(h)],'area_px':round(cv2.contourArea(c),1)}

C0=np.array([-.0631,-.4814,.7419]);fw=np.array([0,.625,-.7806]);fw/=np.linalg.norm(fw);up=np.array([0,.7806,.625]);up/=np.linalg.norm(up)
R0=np.array([[1,0,0],-up,fw]);K0=np.array([[600.,0,320],[0,600,240],[0,0,1]])
def head_ray(uv):return R0.T@np.array([(uv[0]-320)/600,(uv[1]-240)/600,1.])
def head_plane(uv,z):
 r=head_ray(uv);return C0+(z-C0[2])/r[2]*r

def look_rotation(C,T):
 f=np.array(T)-C;f/=np.linalg.norm(f);right=np.cross(f,[0,0,1]);right/=np.linalg.norm(right);u=np.cross(right,f)
 return np.array([right,-u,f])

def proj(P,C,R,f):
 q=(R@(np.asarray(P)-C).T).T
 return q[:,:2]/q[:,2:]*f+[320,240]

tracks={cam:[] for cam in ['head','hand_left','hand_right']}
for cam in tracks:
 for i in range(N):
  im=cv2.imread(str(ROOT/'real_rgb'/cam/f'{i:06}.png'))
  tracks[cam].append({'frame':i,'wrist_led_uv':led(im,cam) if cam!='hand_right' else None,'green_cup':cup(im,cam)})
 print('tracked',cam,flush=True)

pairs=[(i,tracks['head'][i]['wrist_led_uv'],tracks['hand_left'][i]['wrist_led_uv']) for i in range(315,541,5) if tracks['head'][i]['wrist_led_uv'] and tracks['hand_left'][i]['wrist_led_uv']]
H=np.array([p[1] for p in pairs]);L=np.array([p[2] for p in pairs]);rH=np.array([head_ray(p) for p in H]);rH/=np.linalg.norm(rH,axis=1)[:,None]
# Static correspondences. Cup top is a geometry assumption; marker lies on z=.009.
static_world=np.array([[0,0,.115],head_plane([474,204],.009),head_plane([527,269],.009),head_plane([318,220],.135)])
static_left=np.array([[151,236],[176,165],[246,174],[79,252]],dtype=float)
weights=np.array([1.,1.,1.,.45])

def residual(p):
 C=p[:3];R=cv2.Rodrigues(p[3:6])[0];f=p[6]
 rayL=(R.T@np.column_stack([(L[:,0]-320)/f,(L[:,1]-240)/f,np.ones(len(L))]).T).T
 rayL/=np.linalg.norm(rayL,axis=1)[:,None]
 normals=np.cross(rH,C-C0);normal_norm=np.maximum(np.linalg.norm(normals,axis=1),1e-9)
 epi=np.sum(rayL*normals,axis=1)/normal_norm*f
 stat=((proj(static_world,C,R,f)-static_left)*weights[:,None]).ravel()
 # Weak priors prevent implausible solutions when the mostly planar motion is degenerate.
 priors=np.array([(C[0]+.35)*3,(C[1]+.12)*3,(C[2]-.35)*3,(f-530)/180])
 cam_in_head=proj([C],C0,R0,600)[0]
 return np.r_[epi*.16,stat,(cam_in_head-[45,272])*.20,priors]
solutions=[]
for c in [[-.35,-.12,.35],[-.4,-.2,.4],[-.3,-.2,.45],[-.5,0,.4]]:
 r=cv2.Rodrigues(look_rotation(np.array(c),[.06,.03,.07]))[0].ravel()
 init=np.r_[c,r,500.]
 res=least_squares(residual,init,bounds=([-1,-1,.12,-6,-6,-6,300],[.1,.5,1.,6,6,6,1000]),loss='soft_l1',f_scale=2,max_nfev=2000)
 solutions.append(res)
res=min(solutions,key=lambda r:np.sum(residual(r.x)**2));C=res.x[:3];R=cv2.Rodrigues(res.x[3:6])[0];f=res.x[6]
print('left camera',C,R,'f',f,'rms',np.sqrt(np.mean(residual(res.x)**2)),flush=True)
K=np.array([[f,0,320],[0,f,240],[0,0,1.]])
P0=K0@np.c_[R0,-R0@C0];PL=K@np.c_[R,-R@C]
world=[]
for i in range(N):
 h=tracks['head'][i]['wrist_led_uv'];l=tracks['hand_left'][i]['wrist_led_uv']
 if h is not None and l is not None:
  p=cv2.triangulatePoints(P0,PL,np.array(h,dtype=float).reshape(2,1),np.array(l,dtype=float).reshape(2,1));p=(p[:3]/p[3]).ravel()
  reproject=np.linalg.norm(proj([p],C,R,f)[0]-l)
  world.append({'frame':i,'xyz':np.round(p,6).tolist(),'left_reprojection_error_px':round(float(reproject),3)})

# Key phases were inspected independently in all three cameras; boundaries are approximate.
phases=[{'start':0,'end':55,'action':'stationary, jaws open'},{'start':56,'end':193,'action':'approach marker on table'},{'start':194,'end':212,'action':'finish approach'},{'start':213,'end':235,'action':'close jaws around marker'},{'start':236,'end':279,'action':'lift marker off cloth'},{'start':280,'end':363,'action':'transport marker above cup and rotate wrist'},{'start':364,'end':456,'action':'lower marker into cup'},{'start':457,'end':485,'action':'open jaws; marker drops into cup beginning 457-459'},{'start':486,'end':592,'action':'retreat toward starting pose'}]
result={'frame_count':N,'source_indexing':'000000.png through 000592.png inclusive; RGB images have no timestamp/fps metadata','pixel_coordinates':'u right, v down, original resolution 640x480','limitations':'No measured camera intrinsics/extrinsics, robot joint states, or dimensions supplied. World coordinates are a visual fit to assumed geometry, not metrically calibrated ground truth. Cyan wrist LED is directly measured when visible.','camera_roles':{'head':'approximately fixed overview','hand_left':'approximately fixed wrist camera on stationary left gripper','hand_right':'moving camera rigidly mounted above active right gripper'},'head_camera':{'position':C0.tolist(),'world_to_camera_rotation':R0.tolist(),'intrinsics':K0.tolist()},'hand_left_camera_fit':{'position':C.tolist(),'world_to_camera_rotation':R.tolist(),'intrinsics':K.tolist(),'blender_forward_world':R[2].tolist(),'blender_up_world':(-R[1]).tolist(),'fit_residual_rms':float(np.sqrt(np.mean(residual(res.x)**2))),'static_reprojections':proj(static_world,C,R,f).tolist(),'static_measured_uv':static_left.tolist()},'static_landmarks':{'head_initial_marker_endpoints':[[474,204],[527,269]],'marker_world_endpoints':static_world[1:3].tolist(),'head_cup_mouth_center':[363,247],'left_cup_mouth_center':[151,236],'head_final_marker_endpoints':[[341,215],[360,269]],'left_final_marker_endpoints':[[79,204],[144,274]]},'action_phases':phases,'tracks':tracks,'triangulated_wrist_led':world}
# Motion events are frame indexed, independent of the chosen playback fps.
result['marker_attachment']={'grip_closed_frame':235,'release_frame':457,'release_observation':'At 456 the marker is still held; at 459 it has visibly dropped.'}
result['gripper_open_fraction']=[{'frame':i,'open_fraction':round(float(np.interp(i,[0,212,235,456,485,592],[1,1,0,0,1,1])),5)} for i in range(N)]
for cam,roi in [('head',(100,0,420,190)),('hand_left',(35,255,185,420))]:
 x1,y1,x2,y2=roi
 im0=cv2.imread(str(ROOT/'real_rgb'/cam/'000000.png'),0)[y1:y2,x1:x2].astype('float32');jitter=[]
 for i in range(0,N,25):
  im=cv2.imread(str(ROOT/'real_rgb'/cam/f'{i:06}.png'),0)[y1:y2,x1:x2].astype('float32')
  shift,conf=cv2.phaseCorrelate(im0,im)
  jitter.append({'frame':i,'shift_px':[round(t,3) for t in shift],'confidence':round(conf,3)})
 result['camera_jitter_'+cam]=jitter
# Background optical flow measures the wrist-camera image motion. These are image
# homographies, NOT calibrated SE(3) camera poses. Areas occupied by gripper/pen
# are excluded to avoid fitting the static-in-camera gripper instead of the room.
prev=None;flow=[]
for i in range(N):
 gray=cv2.imread(str(ROOT/'real_rgb'/'hand_right'/f'{i:06}.png'),0)
 entry={'frame':i,'from_frame':i-1,'homography_from_previous':None,'inliers':0}
 if prev is not None:
  mask=np.zeros(gray.shape,np.uint8);mask[:225,:]=255;mask[190:225,270:420]=0
  p=cv2.goodFeaturesToTrack(prev,300,.009,6,mask=mask,blockSize=5)
  if p is not None and len(p)>=8:
   q,status,err=cv2.calcOpticalFlowPyrLK(prev,gray,p,None,winSize=(25,25),maxLevel=3)
   valid=(status.ravel()==1)&(err.ravel()<22)
   a=p[valid].reshape(-1,2);b=q[valid].reshape(-1,2)
   if len(a)>=8:
    Hm,inlier=cv2.findHomography(a,b,cv2.RANSAC,2.5)
    if Hm is not None and inlier.sum()>=8:
     entry.update(homography_from_previous=np.round(Hm,8).tolist(),inliers=int(inlier.sum()),median_flow_px=np.round(np.median(b-a,axis=0),4).tolist())
 flow.append(entry);prev=gray
result['hand_right_background_flow']=flow
(OUT/'vision_tracks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
# Overview of the image-space measurements.
can=[]
for cam in ['head','hand_left']:
 im=cv2.imread(str(ROOT/'real_rgb'/cam/'000000.png'))
 for t in tracks[cam]:
  if t['wrist_led_uv']:
   u,v=t['wrist_led_uv'];color=tuple(int(x) for x in cv2.applyColorMap(np.uint8([[int(t['frame']/592*255)]]),cv2.COLORMAP_TURBO)[0,0]);cv2.circle(im,(round(u),round(v)),2,color,-1)
 for t in tracks[cam][::25]:
  if t['wrist_led_uv']:
   u,v=t['wrist_led_uv'];cv2.putText(im,str(t['frame']),(round(u)+4,round(v)),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,0,240),1)
 cv2.putText(im,cam+' wrist LED trajectory',(12,465),cv2.FONT_HERSHEY_SIMPLEX,.6,(20,40,220),2)
 can.append(im)
cv2.imwrite(str(OUT/'wrist_tracks.jpg'),np.hstack(can))
print('saved',OUT/'vision_tracks.json','triangulated points',len(world),flush=True)
