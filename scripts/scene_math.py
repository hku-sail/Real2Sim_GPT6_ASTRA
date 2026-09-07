"""Image-derived pinhole geometry, meters, Blender Z-up."""
import numpy as np
HEAD_F=600.0
HEAD_C=np.array([-.0631,-.4814,.7419])
HEAD_FORWARD=np.array([0,.625,-.7806247498])
HEAD_RIGHT=np.array([1.,0.,0.])
HEAD_UP=np.cross(HEAD_RIGHT,HEAD_FORWARD)
def head_ray(uv,z=0):
 d=HEAD_FORWARD+HEAD_RIGHT*((uv[0]-320)/HEAD_F)-HEAD_UP*((uv[1]-240)/HEAD_F)
 return HEAD_C+d*((z-HEAD_C[2])/d[2])
def head_project(p):
 v=np.asarray(p)-HEAD_C
 return np.array([320+HEAD_F*np.dot(v,HEAD_RIGHT)/np.dot(v,HEAD_FORWARD),240-HEAD_F*np.dot(v,HEAD_UP)/np.dot(v,HEAD_FORWARD)])
if __name__=='__main__':
 for uv in [(474,204),(527,269),(549,360),(105,365),(420,305),(235,315)]:
  print(uv,head_ray(uv,.20 if uv[1]>300 else .008))
 print('cup',head_project([0,0,0]),head_project([0,0,.115]))
