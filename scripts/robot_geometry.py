"""Editable RGB reconstruction of DH-style adaptive grippers and visible wrists.

Public interface: build_gripper(name, materials) -> Blender root Object;
set_gripper_opening(root, width_m); build_arm(name, gripperroot) -> arm root.
Local +Y points to the fingertips, +Z is the top. Root objects may be keyframed.
The original DH AG95 CAD shell is reused; extended links, pads, camera enclosure,
and unidentified white arm are visual approximations fitted to the RGB footage.
"""
from pathlib import Path
import math
import bpy
from mathutils import Vector

ASSET_ROOT = Path(__file__).resolve().parents[1] / 'reconstruction/assets/robot/dh_ag95'
_MATERIALS = {}
FINGER_REACH = 0.67


def _material(materials, key):
    if key in materials:
        return materials[key]
    fallback = bpy.data.materials.get('Robot_' + key) or bpy.data.materials.new('Robot_' + key)
    colors = {'black': (.025, .029, .025, 1), 'rubber': (.013, .018, .014, 1),
              'metal': (.45, .47, .48, 1), 'white': (.72, .75, .74, 1),
              'green_led': (.02, .8, .15, 1)}
    fallback.diffuse_color = colors.get(key, (.1, .1, .1, 1))
    return fallback


def _parent(obj, parent):
    obj.parent = parent
    return obj


def _empty(name, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    obj.empty_display_type = 'PLAIN_AXES'
    obj.empty_display_size = .04
    obj.parent = parent
    return obj


def _box(name, loc, dim, mat, parent, bevel=.004):
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.object
    obj.name = name
    obj.location = loc
    obj.dimensions = dim
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        mod = obj.modifiers.new('Rounded machined edges', 'BEVEL')
        mod.width = bevel
        mod.segments = 3
    obj.data.materials.append(mat)
    return _parent(obj, parent)


def _sphere(name, loc, dim, mat, parent):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16)
    obj = bpy.context.object
    obj.name = name
    obj.location = loc
    obj.scale = Vector(dim) / 2
    obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return _parent(obj, parent)


def _cylinder(name, loc, radius, depth, mat, parent, axis='Z'):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=radius, depth=depth)
    obj = bpy.context.object
    obj.name = name
    obj.location = loc
    if axis == 'Y':
        obj.rotation_euler.x = math.pi / 2
    elif axis == 'X':
        obj.rotation_euler.y = math.pi / 2
    obj.data.materials.append(mat)
    mod = obj.modifiers.new('Machined edge', 'BEVEL')
    mod.width = .0015
    mod.segments = 2
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return _parent(obj, parent)


def _wire(name, points, radius, mat, parent):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = '3D'
    data.bevel_depth = radius
    data.bevel_resolution = 3
    spline = data.splines.new('BEZIER')
    spline.bezier_points.add(len(points)-1)
    for bp, co in zip(spline.bezier_points, points):
        bp.co = co
        bp.handle_left_type = bp.handle_right_type = 'AUTO'
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    return _parent(obj, parent)


def _cad_shell(name, parent, materials):
    """CAD was authored in mm, with its forward axis +Z and top side -Y."""
    for meshname, material in [('gripper_body', 'black'), ('base_link', 'metal')]:
        path = ASSET_ROOT / 'meshes/visual' / (meshname + '.stl')
        if not path.exists():
            return False
        bpy.ops.wm.stl_import(filepath=str(path))
        obj = bpy.context.object
        obj.name = name + '_' + meshname
        # Bake the axis conversion into mesh data, leaving a simple parentable mesh.
        for vertex in obj.data.vertices:
            x, y, z = vertex.co
            vertex.co = (x * .001, z * .001 - .13, -y * .00125)
        obj.data.materials.clear()
        obj.data.materials.append(_material(materials, material))
        for poly in obj.data.polygons:
            poly.use_smooth = True
        _parent(obj, parent)
        obj['asset_source'] = 'DH AG95 STL; see reconstruction/assets/robot/dh_ag95/provenance.json'
    return True


def build_gripper(name, materials):
    """Build a parentable gripper. Opening is inner pad separation in meters."""
    root = _empty(name)
    _MATERIALS[root.name] = materials
    root['geometry_type'] = 'DH_AG_visual_reconstruction'
    root['local_axes'] = '+Y fingertips; +Z top; wrist y=-0.13 m'
    if not _cad_shell(name, root, materials):
        _sphere(name+'_rounded_shell', (0,-.063,0), (.093,.145,.075),
                _material(materials,'black'), root)
    # Rounded opaque lid and sleeve seen on the experimental DH-style hand.
    _sphere(name+'_opaque_shell_cover', (0,-.063,.009), (.094,.139,.079), _material(materials,'black'), root)
    metal = _material(materials, 'metal')
    black = _material(materials, 'black')
    rubber = _material(materials, 'rubber')
    # The distributed CAD omits the smooth lid seen over the drive cavity in RGB.
    _sphere(name+'_smooth_drive_lid', (0,-.061,.024), (.085,.099,.032),black,root)
    for side in (-1, 1):
        finger = _empty(name + '_finger_' + str(side), root)
        finger['role'] = 'finger'
        finger['side'] = side
        _box(name + '_pad_' + str(side), (-side*.009, .154, 0),
             (.019,.063,.027), rubber, finger, .003)
        _box(name + '_finger_back_' + str(side), (side*.006, .141, 0),
             (.019,.062,.041), black, finger, .003)
        # Shallow transverse rubber tread, visible in the two wrist views.
        for k in range(10):
            _box(name+'_pad_tread_'+str(side)+'_'+str(k), (-side*.0185,.13+k*.0051,0),
                 (.0015,.0016,.026), black, finger, .0005)
        for z in (-.023, .023):
            bar = _box(name+'_outer_link_'+str(side)+'_'+str(z), (0,0,z),
                       (.018,1,.012), black, root, .004)
            bar['role'] = 'bar'
            bar['side'] = side
            bar['bar_z'] = z
            bar['link_type'] = 'outer'
        bar = _box(name+'_inner_link_'+str(side), (0,0,0),
                   (.015,1,.02), black, root, .003)
        bar['role'] = 'bar'
        bar['side'] = side
        bar['bar_z'] = 0.0
        bar['link_type'] = 'inner'
        for at in ('base','tip'):
            for z in (-.031,.031):
                bolt = _cylinder(name+'_bolt_'+str(side)+'_'+at+'_'+str(z), (0,0,z),
                                 .0053,.003,metal,root)
                bolt['role'] = 'bolt'
                bolt['side'] = side
                bolt['at'] = at
    # Reach reduction fitted against head-camera fingertip/body proportions.
    for part in root.children:
        if part.get('role') == 'finger':
            for child in part.children:
                child.location.y *= FINGER_REACH
                child.scale.y *= FINGER_REACH
    text_curve = bpy.data.curves.new(name+'_DH_label', 'FONT')
    text_curve.body='DH'; text_curve.size=.014; text_curve.align_x='CENTER'
    label = bpy.data.objects.new(name+'_DH_label', text_curve)
    bpy.context.collection.objects.link(label); label.parent=root
    label.location=(0,-.048,.049); label.data.materials.append(_material(materials,'white'))
    # Frame-mounted machine-vision camera body; scene camera is created elsewhere.
    _box(name+'_camera_bracket', (0,-.076,.048), (.042,.073,.025), black,root,.003)
    _box(name+'_camera_housing', (0,-.09,.10), (.046,.033,.073),metal,root,.004)
    _box(name+'_camera_face', (0,-.072,.10), (.037,.004,.061),black,root,.002)
    _cylinder(name+'_camera_lens', (-.009,-.068,.10), .008,.004,rubber,root,'Y')
    _cylinder(name+'_camera_sensor', (.010,-.068,.10), .004,.004,rubber,root,'Y')
    _wire(name+'_camera_cable', [(.02,-.1,.13),(.033,-.18,.16),(.045,-.24,.05),
                                 (.048,-.25,.009)], .004,black,root)
    _wire(name+'_gripper_cable', [(0,-.108,-.024),(.035,-.15,-.036),(.053,-.21,-.015)],
          .0035,black,root)
    set_gripper_opening(root, .14)
    return root


def _align_bar(obj, a, b):
    a, b = Vector(a), Vector(b)
    obj.location = (a+b)*.5
    obj.rotation_euler = (b-a).to_track_quat('Y','Z').to_euler()
    obj.scale.y = (b-a).length


def set_gripper_opening(root, width_m):
    """Set inner-pad gap in meters; call then keyframe child transforms if baking."""
    width = min(.14, max(.013, float(width_m)))
    root['opening_m'] = width
    for obj in root.children:
        role = obj.get('role')
        side = obj.get('side', 1)
        tip_x = side*(width*.5+.0185)
        if role == 'finger':
            obj.location.x = tip_x
        elif role == 'bar':
            z = obj['bar_z']
            if obj['link_type'] == 'outer':
                a, b = (side*.035,.008,z), (tip_x,.122,z)
            else:
                a, b = (side*.014,.018,z), (tip_x-side*.02,.132,z)
            a=(a[0],a[1]*FINGER_REACH,a[2]); b=(b[0],b[1]*FINGER_REACH,b[2])
            _align_bar(obj,a,b)
        elif role == 'bolt':
            if obj['at'] == 'base':
                obj.location.x, obj.location.y = side*.035,.008*FINGER_REACH
            else:
                obj.location.x, obj.location.y = tip_x,.122*FINGER_REACH
    return width


def build_arm(name, gripperroot):
    """Attach an approximate 0.3 m white wrist/forearm along the gripper's -Y."""
    arm = _empty(name, gripperroot)
    materials = _MATERIALS.get(gripperroot.name,{})
    white = _material(materials,'white')
    metal = _material(materials,'metal')
    black = _material(materials,'black')
    led = _material(materials,'green_led')
    _cylinder(name+'_flange', (0,-.14,0), .041,.018,metal,arm,'Y')
    _cylinder(name+'_status_ring', (0,-.153,0), .041,.005,led,arm,'Y')
    _sphere(name+'_wrist_shell', (0,-.198,0), (.09,.105,.096),white,arm)
    _sphere(name+'_forearm_shell', (0,-.322,.022), (.098,.236,.101),white,arm)
    _cylinder(name+'_wrist_side_joint', (0,-.207,0), .037,.094,white,arm,'X')
    for side in (-1,1):
        _cylinder(name+'_wrist_seam_'+str(side), (side*.047,-.207,0),.024,.0015,metal,arm,'X')
        for y,z in ((-.21,.021),(-.235,-.02),(-.30,.04)):
            _sphere(name+'_shell_fastener_'+str(side)+str(y),(side*.049,y,z),
                    (.002,.005,.005),black,arm)
    arm['geometry_note'] = 'White arm hardware unidentified: editable local visual approximation.'
    return arm
