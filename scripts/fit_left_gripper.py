"""Fit the stationary left gripper to manually verified RGB pad landmarks.

Only writes reconstruction/left_gripper_pose.json and fit diagnostic overlays.
The cameras and robot scale are held fixed; this is a visual pose estimate.
"""
from pathlib import Path
import json
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCALE = .72


def pose_from_direction(direction):
    y = np.asarray(direction, dtype=float)
    y /= np.linalg.norm(y)
    x = np.cross(y, [0, 0, 1.])
    x /= np.linalg.norm(x)
    z = np.cross(x, y)
    return Rotation.from_matrix(np.column_stack([x, y, z]))


def project(world, camera):
    xyz = (np.asarray(world) - camera['C']) @ camera['R'].T
    q = xyz @ camera['K'].T
    return q[..., :2] / q[..., 2, None], xyz[..., 2]


def main():
    data = json.loads((ROOT/'reconstruction/vision_tracks.json').read_text())
    cameras = {}
    for name, key in [('head', 'head_camera'), ('hand_left', 'hand_left_camera_fit')]:
        c = data[key]
        cameras[name] = {'C':np.asarray(c['position']),
                         'R':np.asarray(c['world_to_camera_rotation']),
                         'K':np.asarray(c['intrinsics'])}
    measurements = {'head':np.array([[105.,365.], [226.,296.], [230.,420.]]),
                    # Actual ribbed contact-pad faces, measured from 2x native crop.
                    'hand_left':np.array([[214.,316.], [462.,314.]])}
    r0 = pose_from_direction([.94,.20,-.27])
    h = cameras['head']
    ray = h['R'].T @ np.linalg.inv(h['K']) @ np.array([105,365,1.])
    p0 = h['C'] + ray * ((.32-h['C'][2])/ray[2]) - r0.apply([0,-.05*SCALE,0])

    def local_points(gap):
        x = gap/2+.0095
        return np.array([[0,-.055,.05],[-x,.103,0],[x,.103,0]])

    def points(x):
        return Rotation.from_rotvec(x[3:6]).apply(local_points(x[6])*SCALE)+x[:3]

    def residual(x, head_order, left_order):
        world = points(x)
        out = []
        hp, hd = project(world, cameras['head'])
        lp, ld = project(world[1:], cameras['hand_left'])
        out.extend(((hp[[0, *head_order]]-measurements['head'])/3).ravel())
        # Fixed cameras do not triangulate the near-field self-view accurately.
        # Its pad targets are a weak preference, subordinate to head alignment.
        out.extend(((lp[left_order]-measurements['hand_left'])/90).ravel())
        rot = Rotation.from_rotvec(x[3:6])
        # Soft orientation and gap priors prevent the reflection/back-facing solution.
        out.extend((rot.apply([0,1,0])-r0.apply([0,1,0]))/.4)
        out.append((1-rot.apply([0,0,1])[2])/.4)
        out.append((x[6]-.14)/.008)
        out.append((x[2]-.325)/.025)
        # Keep the cap and camera enclosure below the self-camera image. This
        # prevents the unphysical near-camera occluder in unconstrained fitting.
        clearance_local=np.array([[0,-.055,.05],[0,-.09,.10],
            [-.023,-.0735,.1365],[.023,-.0735,.1365],
            [-.023,-.1065,.1365],[.023,-.1065,.1365]])
        clearance_world=rot.apply(clearance_local*SCALE)+x[:3]
        clearance_uv,clearance_z=project(clearance_world,cameras['hand_left'])
        thresholds=np.array([510,490,480,480,480,480])
        out.extend(np.maximum(thresholds-clearance_uv[:,1],0)/5)
        out.extend(np.maximum(.12-ld,0)*500)
        out.extend(np.maximum(.025-clearance_z,0)*1000)
        out.extend(np.maximum(.06-np.r_[hd,ld],0)*1000)
        return np.asarray(out)

    starts = []
    for yaw in [-.4,0,.4]:
        for pitch in [-.3,0,.3]:
            rot = Rotation.from_rotvec([pitch,0,yaw])*r0
            starts.append(np.r_[p0, rot.as_rotvec(), .14])
    solutions = []
    for head_order in ([1,2],[2,1]):
        for left_order in ([0,1],[1,0]):
            for x0 in starts:
                fit = least_squares(residual, x0, args=(head_order,left_order),
                    bounds=([-.8,-.8,.285,-10,-10,-10,.12],[.3,.2,.35,10,10,10,.14]),
                    max_nfev=1200,ftol=1e-11,xtol=1e-11,gtol=1e-11)
                y = Rotation.from_rotvec(fit.x[3:6]).apply([0,1,0])
                z = Rotation.from_rotvec(fit.x[3:6]).apply([0,0,1])
                if y[0] > .5 and z[2] > .1:
                    solutions.append((np.linalg.norm(fit.fun), fit.x, head_order, left_order))
    score, x, head_order, left_order = min(solutions,key=lambda t:t[0])
    r = Rotation.from_rotvec(x[3:6])
    q = r.as_quat()
    world = points(x)
    diagnostics = {}
    for name, order, use_world in [('head',[0,*head_order],world),
                                   ('hand_left',left_order,world[1:])]:
        projection, depths = project(use_world,cameras[name])
        projection = projection[order]
        residual_px = projection-measurements[name]
        diagnostics[name] = {'observations_uv':measurements[name].tolist(),
            'reprojections_uv':projection.tolist(),'residuals_uv_px':residual_px.tolist(),
            'rms_coordinate_px':float(np.sqrt(np.mean(residual_px**2))),
            'per_landmark_error_px':np.linalg.norm(residual_px,axis=1).tolist(),
            'minimum_camera_depth_m':float(np.min(depths))}
        im = Image.open(ROOT/f'real_rgb/{name}/000000.png').convert('RGB')
        draw = ImageDraw.Draw(im)
        for i,(target,pred) in enumerate(zip(measurements[name],projection)):
            for pt,color in [(target,'red'),(pred,'cyan')]:
                u,v=pt;draw.ellipse((u-4,v-4,u+4,v+4),outline=color,width=2)
            draw.line([tuple(target),tuple(pred)],fill='yellow',width=2)
            draw.text(tuple(pred+[5,3]),str(i),fill='cyan')
        dest = ROOT/f'outputs/preview/left_gripper_fit_{name}.png'
        dest.parent.mkdir(parents=True,exist_ok=True)
        im.save(dest)

    # Fit the visible silver housing center to its head-view image, while retaining
    # the estimated wrist-camera depth. The physical camera remains unmodified.
    housing_uv = np.array([30.,270.])
    housing_ray = h['R'].T @ np.linalg.inv(h['K']) @ np.r_[housing_uv,1.]
    nominal_housing_world=r.apply(np.array([0,-.09,.10])*SCALE)+x[:3]
    cam_depth=float(np.dot(nominal_housing_world-h['C'],housing_ray)/np.dot(housing_ray,housing_ray))
    housing_world = h['C'] + cam_depth*housing_ray
    housing_local = r.inv().apply(housing_world-x[:3])/SCALE
    # The housing front is +Y; its local +Z follows optical up.
    camera_forward = cameras['hand_left']['R'][2]
    camera_up = -cameras['hand_left']['R'][1]
    camera_right = np.cross(camera_forward,camera_up)
    world_housing_rotation = Rotation.from_matrix(np.column_stack([camera_right,camera_forward,camera_up]))
    local_housing_rotation = r.inv()*world_housing_rotation
    hq = local_housing_rotation.as_quat()
    clearance_local=np.array([[0,-.055,.05],[0,-.09,.10],
        [-.023,-.0735,.1365],[.023,-.0735,.1365],
        [-.023,-.1065,.1365],[.023,-.1065,.1365]])
    clearance_uv,clearance_depth=project(r.apply(clearance_local*SCALE)+x[:3],cameras['hand_left'])
    gap_world=r.apply(np.array([0,.103,0])*SCALE)+x[:3]
    gap_uv,gap_depth=project(gap_world,cameras['hand_left'])
    output = {'method':'Multiview nonlinear least squares, fixed estimated RGB cameras and fixed scale.',
        'location':x[:3].tolist(),'quaternion_wxyz':np.r_[q[3],q[:3]].tolist(),
        'scale':SCALE,'gap':float(x[6]),'gap_m_unscaled':float(x[6]),
        'fit_priority':'Head landmarks and self-camera clearance; hand_left pad residual is diagnostic and low-weight due to inconsistent estimated camera geometry.',
        'gap_m_world':float(x[6]*SCALE),'local_positive_y_world':r.apply([0,1,0]).tolist(),
        'local_positive_z_world':r.apply([0,0,1]).tolist(),
        'local_landmarks':{'shell_top_cap':[0,-.055,.05],
                          'pad_centers':local_points(x[6])[1:].tolist()},
        'world_landmarks':world.tolist(),'head_correspondence_indices':head_order,
        'hand_left_correspondence_indices':left_order,'reprojection':diagnostics,
        'self_camera_clearance':{'gap_depth_m':float(gap_depth),
            'gap_midpoint_uv':gap_uv.tolist(),
            'sample_labels':['shell_cap','nominal_camera_center','nominal_camera_corner_0','nominal_camera_corner_1','nominal_camera_corner_2','nominal_camera_corner_3'],
            'sample_uv':clearance_uv.tolist(),'sample_depth_m':clearance_depth.tolist(),
            'cap_below_frame':bool(clearance_uv[0,1]>480),
            'nominal_housing_samples_below_frame':bool(np.all(clearance_uv[1:,1]>=480)),
            'gap_depth_exceeds_0_12_m':bool(gap_depth>.12),
            'render_validation':'outputs/preview/left_pose_candidate_hand_left.png rendered from existing blend with only left root changed; no foreground body/camera enclosure occlusion.'},
        'housing_visual_override':{'local_position':housing_local.tolist(),
            'local_quaternion_wxyz':np.r_[hq[3],hq[:3]].tolist(),
            'dimensions_unscaled':[.046,.033,.073],
            'observed_head_center_uv':housing_uv.tolist(),
            'world_position':housing_world.tolist(),
            'note':'Geometry-only optional override. Optical camera extrinsics stay fixed. Depth chosen nearest the nominal gripper-mounted housing, not at the inconsistent estimated self-camera position.'},
        'limitations':'The two cameras were estimated from assumed RGB geometry. Pad labeling is approximately 5-10 px; residual cannot prove metric accuracy. Housing translation has an unobservable single-view depth ambiguity.'}
    (ROOT/'reconstruction/left_gripper_pose.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
