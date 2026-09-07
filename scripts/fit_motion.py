#!/usr/bin/env python3
"""Fit a visual gripper trajectory and continuous grasp/release from RGB landmarks.
Uses RGB-estimated cameras, so poses are approximate, not measured robot telemetry.
"""
from pathlib import Path
import json,cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.interpolate import PchipInterpolator
from scipy.spatial.transform import Rotation,Slerp,RotationSpline
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reconstruction'
V=json.loads((OUT/'vision_tracks.json').read_text());A=json.loads((OUT/'right_gripper_keypoints.json').read_text())['frames']
SCALE=.72;TIP=.103
cams={}
for name,data in [('head',V['head_camera']),('hand_left',V['hand_left_camera_fit'])]:
 K=np.array(data['intrinsics']);C=np.array(data['position']);R=np.array(data['world_to_camera_rotation']);cams[name]=(K,C,R,K@np.c_[R,-R@C])
def project(points,cam):
 K,C,R,_=cams[cam];q=(R@(np.atleast_2d(points)-C).T).T
 return q[:,:2]/np.maximum(q[:,2:],.01)*K[0,0]+K[:2,2]
def plane(uv,z):
 K,C,R,_=cams['head'];r=R.T@np.r_[(np.array(uv)-K[:2,2])/K[0,0],1];return C+(z-C[2])/r[2]*r

def basis(f):
 y=np.array(f,dtype=float);y/=np.linalg.norm(y);x=np.cross(y,[0,0,1]);x/=np.linalg.norm(x);z=np.cross(x,y)
 return np.column_stack([x,y,z])

times=np.array([a['frame'] for a in A]);keytimes=np.array(sorted(set(times.tolist()+[212,235,245,456,457,485])))
headfields=['black_shell_cap_center_uv','gap_midpoint_uv','finger_pad_centers_uv']
interp={key:PchipInterpolator(times,np.array([a['head'][key] for a in A]),axis=0) for key in headfields}
lookup={a['frame']:a for a in A}
startends=np.array(V['static_landmarks']['marker_world_endpoints']);startcenter=startends.mean(axis=0);startaxis=startends[0]-startends[1];penlength=np.linalg.norm(startaxis);startaxis/=penlength
contact=startends[0]*.77+startends[1]*.23;contact[2]=.011
open_keys=np.array([[0,.14],[212,.14],[235,.0181],[456,.0181],[485,.14],[592,.14]])
def opening(i):return float(np.interp(i,open_keys[:,0],open_keys[:,1]))
def points(t,R,width):
 gap=t+R@np.array([0,TIP,0])*SCALE
 cap=t+R@np.array([0,-.05,.05])*SCALE
 led=t+R@np.array([0,-.153,0])*SCALE
 pads=np.array([gap+R[:,0]*s*(width*.5+.0095)*SCALE for s in [-1,1]])
 return cap,gap,led,pads

def orient_prior(i):
 ks=np.array([[0,-.97,.1,-.22],[100,-.75,.25,-.61],[200,-.35,.79,-.50],[250,-.35,.79,-.50],[300,-.67,.66,.34],[350,-.61,.61,.51],[456,-.57,.63,.53],[500,-.66,.66,.3],[592,-.97,.1,-.22]])
 f=np.array([np.interp(i,ks[:,0],ks[:,k]) for k in [1,2,3]]);return f/np.linalg.norm(f)

keyposes=[];stats=[]
for n,i in enumerate(keytimes):
 cap_uv=interp['black_shell_cap_center_uv'](i);gap_uv=interp['gap_midpoint_uv'](i);pads_uv=interp['finger_pad_centers_uv'](i)
 width=opening(i);ann=lookup.get(int(i));hl=V['tracks']['head'][i]['wrist_led_uv'];ll=V['tracks']['hand_left'][i]['wrist_led_uv']
 leftgap=ann['hand_left']['gap_midpoint_uv'] if ann and ann.get('hand_left') else None
 prior=orient_prior(i);Rg=basis(prior)
 relmarker=None
 if i>235:
  ai=list(keytimes).index(235);gp=keyposes[ai];gR=Rotation.from_rotvec(gp[3:]).as_matrix()
  relmarker=(gR.T@(startcenter-gp[:3]),gR.T@startaxis)
 marker_uv=ann['head'].get('pen_visible_segment_endpoints_uv') if ann else None
 z=float(np.interp(i,[0,100,200,250,350,456,500,592],[.37,.26,.13,.14,.3,.25,.32,.37]))
 guess=plane(cap_uv,z)-Rg@np.array([0,-.05,.05])*SCALE
 if keyposes:
  prev=keyposes[-1];prevR=Rotation.from_rotvec(prev[3:]).as_matrix()
  guess=prev[:3]+plane(cap_uv,z)-plane(interp['black_shell_cap_center_uv'](keytimes[n-1]),z)
  Rg=prevR
 init=np.r_[guess,Rotation.from_matrix(Rg).as_rotvec()]
 def fun(p):
  t=p[:3];R=Rotation.from_rotvec(p[3:]).as_matrix();cap,gap,led,pads=points(t,R,width)
  out=[]
  out.extend((project(cap,'head')[0]-cap_uv)/4.)
  out.extend((project(gap,'head')[0]-gap_uv)/4.)
  puv=project(pads,'head');e1=(puv-pads_uv).ravel();e2=(puv-pads_uv[::-1]).ravel();pe=e1 if np.sum(e1**2)<np.sum(e2**2) else e2
  out.extend(pe/(8. if 220<=i<=456 else 6.))
  if hl:out.extend((project(led,'head')[0]-hl)/14.)
  if ll:out.extend((project(led,'hand_left')[0]-ll)/18.)
  if leftgap:out.extend((project(gap,'hand_left')[0]-leftgap)/15.)
  # Pose ambiguity is resolved by an upright wrist and a weak phase-dependent axis prior.
  out.extend((R[:,1]-prior)*(35. if 200<=i<=250 else (10. if 275<=i<=485 else 4.)))
  zkeys=np.array([[0,.27],[55,.28],[75,.26],[100,.22],[125,.16],[150,.09],[175,.04],[200,.02],[212,.018],[225,.015],[235,.012],[245,.014],[250,.018],[275,.12],[300,.23],[325,.295],[350,.32],[375,.30],[400,.27],[425,.25],[450,.245],[457,.245],[475,.27],[500,.30],[535,.32],[560,.30],[592,.27]])
  ztarget=float(np.interp(i,zkeys[:,0],zkeys[:,1]))
  out.append((gap[2]-ztarget)/(.015 if i<=250 or i>=560 else .020))
  out.append(max(0,.6-R[2,2])*15)
  headup=-cams['head'][2][1]
  out.append(max(0,.08-np.dot(R[:,2],headup))*45)
  housing_keys={0:[626,265],275:[615,175],300:[583,152],325:[536,146],350:[485,150],375:[464,171],400:[454,185],425:[450,191],450:[450,192],592:[626,265]}
  if i in housing_keys:
   hp=t+R@np.array([0,-.09,.10])*SCALE
   out.extend((project(hp,'head')[0]-housing_keys[i])/5.)
  if i in [235,245]:out.extend((gap-contact)/np.array([.028,.028,.012]))
  if 200<=i<=250:out.append(np.dot(R[:,0],startaxis)*35.)
  if i==212:out.append((gap[2]-.025)/.04)
  if relmarker is not None and i<=456 and marker_uv is not None:
   mc=t+R@relmarker[0];ma=R@relmarker[1]
   mp=project(np.array([mc+ma*penlength*.5,mc-ma*penlength*.5]),'head')
   out.extend((mp[0]-marker_uv[0])/3.)
   if ann['head'].get('pen_full_length_visible'):out.extend((mp[1]-marker_uv[1])/4.)
   elif i>=400:out.extend((mp[1]-marker_uv[1])/12.)
  if relmarker is not None and 300<=i<=456:
   ma=R@relmarker[1]
   target=np.array([-.34,.18,.923]);target/=np.linalg.norm(target)
   out.extend((ma-target)*32.)
  if n:
   out.extend((p[:3]-keyposes[-1][:3])*.35)
  out.append(max(0,.015-gap[2])*30)
  return np.array(out)
 candidates=[]
 for rv in [init[3:],Rotation.from_matrix(basis(prior)).as_rotvec()]:
  q=least_squares(fun,np.r_[init[:3],rv],max_nfev=250,loss='soft_l1',f_scale=2)
  candidates.append(q)
 fit=min(candidates,key=lambda r:np.sum(fun(r.x)**2));keyposes.append(fit.x)
 R=Rotation.from_rotvec(fit.x[3:]).as_matrix();cap,gap,led,pads=points(fit.x[:3],R,width)
 stats.append({'frame':int(i),'residual_rms':float(np.sqrt(np.mean(fun(fit.x)**2))),'gap_world':gap.tolist(),'forward_world':R[:,1].tolist(),'cap_head_fit':project(cap,'head')[0].tolist(),'gap_head_fit':project(gap,'head')[0].tolist()})
 print(i,'rms',round(stats[-1]['residual_rms'],2),'gap',np.round(gap,3),'forward',np.round(R[:,1],2),flush=True)

keyposes=np.array(keyposes)
for lock_frame in [456,457]:keyposes[list(keytimes).index(lock_frame)]=keyposes[list(keytimes).index(450)]
keytimes=np.insert(keytimes,1,50);keyposes=np.insert(keyposes,1,keyposes[0],axis=0)
pos=PchipInterpolator(keytimes,keyposes[:,:3],axis=0)(np.arange(593));rots=RotationSpline(keytimes,Rotation.from_rotvec(keyposes[:,3:]))(np.arange(593))
# Initial source images are stationary through frame 50.
pos[:51]=pos[0];rr=rots.as_quat();rr[:51]=rr[0];rots=Rotation.from_quat(rr)
# Preserve the full measured initial marker pose exactly at attachment.
Rg=rots[235].as_matrix();Tg=pos[235];markerlocal=Rg.T@(startcenter-Tg);axislocal=Rg.T@startaxis
markerpos=[];markeraxis=[]
for i in range(593):
 R=rots[i].as_matrix()
 if i<=235:m=startcenter.copy();axis=startaxis.copy()
 else:m=pos[i]+R@markerlocal;axis=R@axislocal
 markerpos.append(m);markeraxis.append(axis)
# Drop smoothly from the held transform. Final marker has its lower tip inside cup.
finalbottom=np.array([0.,0.,.012]);finalaxis=np.array([-.028,.005,.148]);finalaxis/=np.linalg.norm(finalaxis);finalcenter=finalbottom+finalaxis*penlength*.5
releasepos=markerpos[457].copy();releaseaxis=markeraxis[457].copy()
for i in range(457,593):
 t=np.clip((i-457)/17.,0,1);t=t*t*(3-2*t)
 markerpos[i]=releasepos*(1-t)+finalcenter*t
 axis=releaseaxis*(1-t)+finalaxis*t;markeraxis[i]=axis/np.linalg.norm(axis)
# Camera rig fit: camera remains attached to right gripper. Sparse manually
# checked cup rim observations supplement camera-relative foreground pad points.
camuv={0:[594,392],75:[335,271],100:[211,186],275:[57,198],300:[165,341],592:[598,395]}
# The source wrist-camera tips remain near symmetric positions in the image.
# They provide a scale/orientation reference stronger than incomplete cup outlines.
padcam_open=np.array([[210,310],[500,320]],float);padcam_closed=np.array([[327,290],[365,290]],float)
# Blender camera local axes are right, up, backward; fitter uses OpenCV down/forward.
initC=np.array([0,-.063,.18]);initFw=np.array([0,.93,-.368]);initR=basis(initFw) # basis columns gripper x, forward, up
initCV=np.array([initR[:,0],-initR[:,2],initR[:,1]])
def camfun(p):
 C=p[:3];R=Rotation.from_rotvec(p[3:6]).as_matrix();f=p[6];out=[]
 for i,uv in camuv.items():
  local=rots[i].inv().apply(np.array([0,0,.115])-pos[i])/SCALE
  q=R@(local-C)
  if q[2]<=.01:out.extend([200.,200.])
  else:out.extend(((q[:2]/q[2]*f+[320,240])-uv)/18)
 for w,target in [(.14,padcam_open),(.0181,padcam_closed)]:
  pads=np.array([[s*(w*.5+.0095),TIP,0] for s in [-1,1]])
  q=(R@(pads-C).T).T;uv=q[:,:2]/np.maximum(q[:,2:],.01)*f+[320,240]
  out.extend(((uv-target)/6).ravel())
 out.extend((C-np.array([0,-.065,.18]))/np.array([.02,.03,.05]));out.append((f-380)/150)
 return np.array(out)
cfit=least_squares(camfun,np.r_[initC,Rotation.from_matrix(initCV).as_rotvec(),400],bounds=([-.04,-.20,.10,-6,-6,-6,300],[.04,-.04,.24,6,6,6,650]),max_nfev=600,loss='soft_l1',f_scale=2)
camC=cfit.x[:3];camR=Rotation.from_rotvec(cfit.x[3:6]).as_matrix();camBlender=np.column_stack([camR[0],-camR[1],-camR[2]]);camquat=Rotation.from_matrix(camBlender).as_quat();camquat=np.r_[camquat[3],camquat[:3]]
print('camera local',camC,'f',cfit.x[6],'rms',np.sqrt(np.mean(camfun(cfit.x)**2)),flush=True)
frames=[]
for i in range(593):
 q=rots[i].as_quat();axis=markeraxis[i];x=np.cross([0,1,0],axis);x/=np.linalg.norm(x);y=np.cross(axis,x);mq=Rotation.from_matrix(np.column_stack([x,y,axis])).as_quat()
 frames.append({'frame':i,'right_root_position':pos[i].tolist(),'right_root_quaternion':[float(q[3]),*q[:3].tolist()],'opening_m':opening(i),'marker_position':np.asarray(markerpos[i]).tolist(),'marker_quaternion':[float(mq[3]),*mq[:3].tolist()]})
# Preserve axial orientation as well as the marker centerline during attachment.
from marker_rotation import enforce_rigid_marker_rotation
enforce_rigid_marker_rotation(frames)
result={'frame_count':593,'method':'Approximate multi-view nonlinear pose fit to manual keypoints and automatic wrist-light tracks, with smooth interpolation and continuous marker attachment/release. Not robot telemetry.','gripper_scale':SCALE,'gripper_local_tip_y':TIP,'right_camera_local_position':camC.tolist(),'right_camera_local_quaternion':camquat.tolist(),'right_camera_focal_px':float(cfit.x[6]),'fit_keyframes':stats,'attachment_frame':235,'release_frame':457,'frames':frames}
(OUT/'motion.json').write_text(json.dumps(result,indent=2))
# Fitted landmark projections can be checked without rerendering Blender.
for i in [0,200,250,350,450,500,592]:
 im=cv2.imread(str(ROOT/'real_rgb'/'head'/f'{i:06}.png'));cap,gap,led,pads=points(pos[i],rots[i].as_matrix(),opening(i))
 for label,p in [('cap',cap),('grip',gap),('wrist',led),('pad0',pads[0]),('pad1',pads[1])]:
  u,v=project(p,'head')[0];cv2.circle(im,(round(u),round(v)),5,(0,0,255),2);cv2.putText(im,label,(round(u)+5,round(v)),0,.45,(0,0,255),1)
 cv2.imwrite(str(OUT/f'motion_fit_head_{i:06}.jpg'),im)
print('saved',OUT/'motion.json',flush=True)
