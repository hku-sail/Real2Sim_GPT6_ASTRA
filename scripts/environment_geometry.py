"""Procedural Blender environment reconstructed from the supplied RGB frames.

Public API: build_environment() -> dict. Units are metres; tabletop is Z=0.
The cup, panda and attached bamboo are children of the returned ``cup`` empty,
so the entire ceramic ornament can be animated as one object.
"""

import math
import random

import bpy
from mathutils import Matrix, Vector


def _material(name, color, roughness=0.45, metallic=0.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def _parent(obj, parent):
    if parent:
        obj.parent = parent
    return obj


def _empty(name, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    return _parent(obj, parent)


def _finish(obj, name, material, parent=None, smooth=True):
    obj.name = name
    if material:
        obj.data.materials.append(material)
    if smooth and obj.type == "MESH":
        for poly in obj.data.polygons:
            poly.use_smooth = True
    return _parent(obj, parent)


def _box(name, center, dimensions, material, parent=None, bevel=0.002):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    obj = _finish(bpy.context.object, name, material, parent, smooth=False)
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        mod = obj.modifiers.new("Soft manufactured edges", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        obj.modifiers.new("Weighted corner normals", "WEIGHTED_NORMAL")
    return obj


def _ellipsoid(name, center, scale, material, parent=None, rotation=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=40, ring_count=24, location=center)
    obj = _finish(bpy.context.object, name, material, parent)
    obj.scale = scale
    if rotation is not None:
        obj.rotation_euler = rotation
    return obj


def _rod(name, a, b, radius, material, parent=None, vertices=16):
    a, b = Vector(a), Vector(b)
    axis = b - a
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=axis.length,
                                       location=(a + b) * 0.5)
    obj = _finish(bpy.context.object, name, material, parent)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = axis.to_track_quat("Z", "Y")
    return obj


def _curve(name, coordinates, radius, material, parent=None, cyclic=False):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.resolution_u = 12
    data.bevel_depth = radius
    data.bevel_resolution = 2
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(len(coordinates) - 1)
    for point, xyz in zip(spline.bezier_points, coordinates):
        point.co = xyz
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    data.materials.append(material)
    return _parent(obj, parent)


def _cloth_material():
    mat = _material("Env • finely woven pale grey tablecloth", (0.76, 0.77, 0.75), 0.92)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    tex = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 95
    noise.inputs["Detail"].default_value = 2
    links.new(tex.outputs["Object"], noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.15
    ramp.color_ramp.elements[0].color = (0.65, 0.67, 0.65, 1)
    ramp.color_ramp.elements[1].position = 0.85
    ramp.color_ramp.elements[1].color = (0.81, 0.82, 0.80, 1)
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    weave = []
    for direction in ("X", "Y"):
        wave = nodes.new("ShaderNodeTexWave")
        wave.wave_type = "BANDS"
        wave.bands_direction = direction
        wave.inputs["Scale"].default_value = 1250
        wave.inputs["Distortion"].default_value = 0.5
        links.new(tex.outputs["Object"], wave.inputs["Vector"])
        weave.append(wave)
    multiply = nodes.new("ShaderNodeMath")
    multiply.operation = "MULTIPLY"
    links.new(weave[0].outputs["Fac"], multiply.inputs[0])
    links.new(weave[1].outputs["Fac"], multiply.inputs[1])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.13
    bump.inputs["Distance"].default_value = 0.00018
    links.new(multiply.outputs[0], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def _build_table(root, materials):
    table = _box("Table | pale laminated slab", (0.015, 0.01, -0.018), (1.27, 0.98, 0.035),
                 materials["table_edge"], root, 0.003)
    # A lightly undulating cloth surface retains a level, unobstructed work area.
    nx, ny = 64, 48
    vertices, faces = [], []
    for row in range(ny + 1):
        y = -0.48 + 0.98 * row / ny
        for col in range(nx + 1):
            x = -0.62 + 1.27 * col / nx
            z = 0.00012 * math.sin(17 * x + 11 * y) + 0.00010 * math.sin(40 * y + 8 * x)
            z += 0.00022 * math.exp(-((x - 0.18 - 0.12 * y) / 0.008) ** 2)
            z += 0.00014 * math.exp(-((y + 0.19 + 0.05 * x) / 0.006) ** 2)
            vertices.append((x, y, z))
    for row in range(ny):
        for col in range(nx):
            i = row * (nx + 1) + col
            faces.append((i, i + 1, i + nx + 2, i + nx + 1))
    mesh = bpy.data.meshes.new("Woven cloth surface mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    cloth = bpy.data.objects.new("Tablecloth | fine weave and shallow folds", mesh)
    bpy.context.collection.objects.link(cloth)
    _finish(cloth, cloth.name, materials["cloth"], root)
    solidify = cloth.modifiers.new("Thin cloth thickness", "SOLIDIFY")
    solidify.thickness = 0.0006
    solidify.offset = -1
    # Subtle hem and crease seams visible at grazing wrist-camera angles.
    for name, coords in (
        ("front hem", [(-0.61, -0.475, 0.0003), (0, -0.475, 0.0003), (0.64, -0.475, 0.0003)]),
        ("right hem", [(0.645, -0.47, 0.0003), (0.645, 0, 0.0003), (0.645, 0.49, 0.0003)]),
    ):
        _curve("Tablecloth | " + name, coords, 0.00028, materials["thread"], root)
    for x in (-0.50, 0.53):
        for y in (-0.38, 0.40):
            _box("Table | square steel leg", (x, y, -0.38), (0.038, 0.038, 0.69),
                 materials["steel"], root, 0.002)
    return table, cloth


def _build_cup(root, materials):
    cup = _empty("Cup assembly | hollow bamboo cup and panda", root)
    cup["reference_center_m"] = [0.0, 0.0, 0.0]
    cup["cup_height_m"] = 0.115
    cup["cup_outer_radii_m"] = [0.04, 0.065]
    cup["interior_depth_m"] = 0.105
    # Continuous outer wall -> rounded rim -> interior wall -> interior floor.
    # Closed underside and annular wall make a physically hollow ceramic cup.
    rings = [
        (0.002, 0.0345, 0.0558), (0.004, 0.0358, 0.0578),
        (0.015, 0.0362, 0.0586), (0.045, 0.0375, 0.0605),
        (0.079, 0.0384, 0.0622), (0.109, 0.0400, 0.0650),
        (0.113, 0.0402, 0.0650), (0.115, 0.0390, 0.0640),
        (0.114, 0.0352, 0.0590), (0.111, 0.0340, 0.0580),
        (0.080, 0.0328, 0.0557), (0.042, 0.0319, 0.0538),
        (0.011, 0.0303, 0.0515), (0.008, 0.0280, 0.0485),
    ]
    segments = 128
    vertices, faces, face_materials = [], [], []
    for ring_index, (z, rx, ry) in enumerate(rings):
        for j in range(segments):
            angle = 2 * math.pi * j / segments
            scallop = 1 + 0.012 * math.cos(7 * angle + 0.7) + 0.007 * math.sin(11 * angle)
            rim_z = 0.00065 * math.sin(5 * angle + 0.2) if 5 <= ring_index <= 9 else 0
            vertices.append((rx * math.cos(angle) * scallop, ry * math.sin(angle) * scallop, z + rim_z))
    for ring_index in range(len(rings) - 1):
        for j in range(segments):
            jj = (j + 1) % segments
            faces.append((ring_index * segments + j, ring_index * segments + jj,
                          (ring_index + 1) * segments + jj, (ring_index + 1) * segments + j))
            face_materials.append(0 if ring_index < 6 else 2 if ring_index < 9 else 1)
    underside = len(vertices)
    vertices.append((0, 0, 0.002))
    bottom = len(vertices)
    vertices.append((0, 0, 0.008))
    for j in range(segments):
        jj = (j + 1) % segments
        faces.append((underside, jj, j))
        face_materials.append(0)
        start = (len(rings) - 1) * segments
        faces.append((bottom, start + j, start + jj))
        face_materials.append(1)
    mesh = bpy.data.meshes.new("Hollow elliptical bamboo ceramic mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(materials["green"])
    mesh.materials.append(materials["inner_green"])
    mesh.materials.append(materials["rim_green"])
    mesh.update()
    body = bpy.data.objects.new("Cup | continuous hollow wall, open rim and inner floor", mesh)
    bpy.context.collection.objects.link(body)
    body.parent = cup
    for poly, mat_index in zip(mesh.polygons, face_materials):
        poly.use_smooth = True
        poly.material_index = mat_index
    for band, z in enumerate((0.021, 0.073)):
        t = z / 0.115
        rx, ry = 0.0355 + 0.0045 * t, 0.0577 + 0.0073 * t
        coordinates = []
        for j in range(32):
            a = 2 * math.pi * j / 32
            coordinates.append((rx * math.cos(a), ry * math.sin(a), z + 0.0007 * math.sin(3 * a)))
        _curve("Cup | bamboo node {:02d}".format(band), coordinates, 0.00065,
               materials["node_green"], cup, cyclic=True)
    # A few shallow moulded bamboo grain ridges, including the front side.
    for ridge, angle in enumerate((0.25, 1.2, 2.45, 3.40, 4.4, 5.5)):
        coordinates = []
        for z in (0.030, 0.045, 0.065, 0.090, 0.102):
            t = z / 0.115
            a = angle + 0.03 * math.sin(z * 40)
            coordinates.append(((0.0355 + 0.0045 * t) * math.cos(a),
                                (0.0577 + 0.0073 * t) * math.sin(a), z))
        _curve("Cup | fine vertical grain {:02d}".format(ridge), coordinates,
               0.00024, materials["node_green"], cup)
    return cup, body


def _build_panda(cup, materials):
    panda = _empty("Panda | attached ceramic figurine", cup)
    panda.location = (-0.065, -0.005, 0)
    forward = Vector((-0.8, -0.6, 0)).normalized()
    side = Vector((forward.y, -forward.x, 0))
    basis = Matrix(((side.x, forward.x, 0), (side.y, forward.y, 0), (0, 0, 1)))
    panda.rotation_euler = basis.to_euler()
    white, black = materials["panda_white"], materials["panda_black"]
    _ellipsoid("Panda | white round body", (0, -0.001, 0.042), (0.026, 0.023, 0.034), white, panda)
    _ellipsoid("Panda | black shoulder coat", (0, -0.0005, 0.056), (0.029, 0.024, 0.019), black, panda)
    _ellipsoid("Panda | white belly", (0, 0.013, 0.036), (0.021, 0.015, 0.025), white, panda)
    _ellipsoid("Panda | rounded ceramic head", (0, 0.002, 0.096), (0.031, 0.025, 0.033), white, panda)
    for sign in (-1, 1):
        _ellipsoid("Panda | {} black ear".format("left" if sign < 0 else "right"),
                   (sign * 0.0218, -0.001, 0.123), (0.0100, 0.0085, 0.0110), black, panda)
        patch = _ellipsoid("Panda | {} eye patch".format("left" if sign < 0 else "right"),
                           (sign * 0.0128, 0.0236, 0.099), (0.0070, 0.0025, 0.0104), black, panda)
        patch.rotation_euler[1] = sign * math.radians(-18)
        _ellipsoid("Panda | {} eye glossy center".format(sign),
                   (sign * 0.0120, 0.0260, 0.101), (0.0028, 0.0010, 0.0034), materials["eye"], panda)
        _ellipsoid("Panda | {} eye catchlight".format(sign),
                   (sign * 0.0120 - 0.0007, 0.0268, 0.1022), (0.00065, 0.00030, 0.00065), white, panda)
        _ellipsoid("Panda | {} soft muzzle".format(sign),
                   (sign * 0.0044, 0.0258, 0.086), (0.0075, 0.0034, 0.0055), white, panda)
        arm = _ellipsoid("Panda | {} hugging black arm".format(sign),
                         (sign * 0.0207, 0.0154, 0.045), (0.0093, 0.011, 0.024), black, panda)
        arm.rotation_euler[1] = sign * math.radians(-27)
        _ellipsoid("Panda | {} resting black foot".format(sign),
                   (sign * 0.017, 0.014, 0.011), (0.012, 0.0175, 0.010), black, panda)
    _ellipsoid("Panda | black oval nose", (0, 0.0300, 0.0890), (0.0041, 0.0022, 0.0030), black, panda)
    _curve("Panda | gentle mouth", [(-0.005, 0.0290, 0.0827), (0, 0.0297, 0.0807),
                                    (0.005, 0.0290, 0.0827)], 0.00055, black, panda)
    # A small red flower is present on the real ornament's forehead.
    for j in range(5):
        angle = j * 2 * math.pi / 5
        _ellipsoid("Panda | red flower petal {:02d}".format(j),
                   (-0.009 + 0.0042 * math.cos(angle), 0.014 + 0.0020 * math.sin(angle),
                    0.125 + 0.0032 * math.sin(angle)), (0.0035, 0.0021, 0.0033), materials["flower"], panda)
    _ellipsoid("Panda | flower golden center", (-0.009, 0.0163, 0.125),
               (0.0018, 0.0010, 0.0018), materials["flower_center"], panda)
    # Green folded leaves held between the two hands.
    _rod("Panda | held bamboo shoot", (-0.003, 0.024, 0.010), (0.003, 0.025, 0.060),
         0.0045, materials["leaf"], panda, 20)
    for j, (x, z, tilt) in enumerate(((-0.010, 0.029, -26), (0.011, 0.035, 30),
                                      (-0.008, 0.048, -22), (0.007, 0.051, 24))):
        leaf = _ellipsoid("Panda | moulded bamboo leaf {:02d}".format(j),
                          (x, 0.026, z), (0.0075, 0.0040, 0.019), materials["leaf"], panda)
        leaf.rotation_euler[1] = math.radians(tilt)
        _curve("Panda | leaf vein {:02d}".format(j), [(x - 0.002, 0.0302, z - 0.010),
                                                      (x, 0.0306, z), (x + 0.002, 0.0302, z + 0.010)],
               0.00025, materials["rim_green"], panda)
    # Ceramic bridge sits behind the figurine, joining it to the cup.
    _ellipsoid("Cup | green ceramic connection to panda", (-0.050, -0.005, 0.038),
               (0.017, 0.024, 0.027), materials["green"], cup)
    return panda


def _build_room(root, materials):
    """Room structures stay behind the table; the open shelf is beside the robot.

    The table ends at y=.50. Cage fronts are at y=.62, with no post,
    backing sheet or grid extending through the worktop or robot sweep.
    """
    _box("Room | grey workshop floor", (0, .65, -.754), (5, 5, .06),
         materials["floor"], root, 0)
    _box("Room | neutral rear wall", (0, 2.35, .45), (4, .05, 2.40),
         materials["wall"], root, 0)
    cages = _empty("Room | dark green metal equipment cages", root)
    cages["front_y_m"] = .62
    cages["layout_note"] = "Entire cage behind table back edge y=.50; no camera-specific hiding."
    for side in (-1, 1):
        x = side * .78
        for y in (.64, 1.65):
            _box("Cage | upright", (x,y,.21),(.035,.035,1.88),materials["cage"],cages,.002)
        for z in (-.66,-.20,.36,1.13):
            _box("Cage | horizontal rail", (x,1.145,z),(.027,1.045,.025),materials["cage"],cages,.0015)
        for j in range(13):
            y = .655+j*.08
            _rod("Cage | vertical wire",(x,y,-.62),(x,y,1.10),.0018,materials["wire"],cages,8)
        for j in range(22):
            z = -.62+j*.08
            _rod("Cage | horizontal wire",(x,.64,z),(x,1.64,z),.0018,materials["wire"],cages,8)
        _box("Cage | dark recessed equipment panel",(x+side*.045,1.145,.22),
             (.025,1.045,1.80),materials["cage"],cages,.003)
        _box("Cage | dark lower equipment cabinet",(x+side*.15,1.145,-.43),
             (.30,1.045,.56),materials["cage"],cages,.008)
    # The wrist view sees the far left equipment wall. Its inner face is
    # outside the entire left arm envelope (x >= -.80), not inside the table.
    outer_x = -1.01
    _box("Cage | outer left recessed panel",(outer_x-.035,.34,.22),
         (.022,1.88,1.80),materials["cage"],cages,.003)
    for y in (-.60,1.28):
        _box("Cage | outer left upright",(outer_x,y,.21),(.030,.030,1.88),materials["cage"],cages,.002)
    for z in (-.65,-.15,.38,1.12):
        _box("Cage | outer left horizontal rail",(outer_x,.34,z),(.028,1.88,.025),materials["cage"],cages,.002)
    for j in range(24):
        y=-.58+j*.08
        _rod("Cage | outer left vertical wire",(outer_x,y,-.62),(outer_x,y,1.10),.0018,materials["wire"],cages,8)
    for j in range(22):
        z=-.62+j*.08
        _rod("Cage | outer left horizontal wire",(outer_x,-.59,z),(outer_x,1.27,z),.0018,materials["wire"],cages,8)
    # Right room wall is behind the complete shelf, leaving its open face visible.
    _box("Room | right outer wall",(1.55,.25,.30),(.035,2.60,2.10),materials["wall"],root,.002)
    from shelf_geometry import build_shelf
    shelf = build_shelf(parent=root, location=(.99,-.64,0))
    shelf["root"].rotation_euler.z = math.radians(-25)
    shelf["root"]["placement_note"] = "Open face toward wrist views; beside table, outside robot sweep."
    return cages, shelf.get("wood_panel"), shelf["root"]


def build_environment():
    """Create static room/table and the movable cup assembly.

    Returns dict keys: environment_root, cup, cup_body, panda, table, cloth,
    cages, wood_panel, shelves, materials. Only ``cup`` should be animated.
    This function does not create cameras, lights, robots, pens, or trajectories.
    """
    root = _empty("Environment | source-video reconstruction")
    materials = {
        "table_edge": _material("Env • pale table edge", (0.60, 0.62, 0.60), 0.7),
        "cloth": _cloth_material(),
        "thread": _material("Env • white cloth hem thread", (0.70, 0.71, 0.69), 0.9),
        "steel": _material("Env • brushed table leg steel", (0.20, 0.23, 0.22), 0.38, 0.6),
        "green": _material("Cup • glazed bamboo green", (0.13, 0.39, 0.11), 0.30),
        "inner_green": _material("Cup • darker green interior glaze", (0.055, 0.235, 0.045), 0.35),
        "rim_green": _material("Cup • rounded light green rim", (0.20, 0.47, 0.155), 0.31),
        "node_green": _material("Cup • subtle bamboo node ridges", (0.16, 0.405, 0.12), 0.40),
        "panda_white": _material("Panda • warm white glazed ceramic", (0.86, 0.88, 0.84), 0.24),
        "panda_black": _material("Panda • charcoal black glazed ceramic", (0.012, 0.017, 0.014), 0.27),
        "eye": _material("Panda • glossy eye centers", (0.004, 0.006, 0.004), 0.12),
        "flower": _material("Panda • tiny red ceramic flower", (0.68, 0.07, 0.045), 0.33),
        "flower_center": _material("Panda • flower warm center", (0.85, 0.49, 0.08), 0.36),
        "leaf": _material("Panda • held green bamboo leaves", (0.22, 0.47, 0.13), 0.33),
        "floor": _material("Room • mid grey workshop floor", (0.24, 0.25, 0.23), 0.93),
        "wall": _material("Room • light grey wall", (0.55, 0.56, 0.54), 0.93),
        "cage": _material("Room • forest green cage frame", (0.025, 0.065, 0.049), 0.55, 0.2),
        "wire": _material("Room • dark cage wires", (0.09, 0.13, 0.11), 0.62, 0.25),
        "wood": _material("Room • honey wood partition", (0.45, 0.29, 0.115), 0.61),
        "shelf": _material("Room • teal green metal merchandise shelf", (0.025, 0.24, 0.19), 0.48, 0.18),
        "label": _material("Room • product label paper", (0.76, 0.70, 0.53), 0.75),
        "package_0": _material("Room • ochre snack packets", (0.52, 0.33, 0.065), 0.53),
        "package_1": _material("Room • red snack packets", (0.40, 0.06, 0.045), 0.52),
        "package_2": _material("Room • cream snack packets", (0.72, 0.60, 0.37), 0.58),
        "package_3": _material("Room • dark brown snack packets", (0.15, 0.095, 0.040), 0.50),
    }
    table, cloth = _build_table(root, materials)
    cup, body = _build_cup(root, materials)
    panda = _build_panda(cup, materials)
    cages, panel, shelves = _build_room(root, materials)
    # Mild procedural grain gives the large floor and wood planes natural variation.
    for key, scale, strength, distance in (("floor", 125, 0.18, 0.0015), ("wood", 6, 0.13, 0.0007)):
        nodes, links = materials[key].node_tree.nodes, materials[key].node_tree.links
        noise = nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = scale
        noise.inputs["Detail"].default_value = 2
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = strength
        bump.inputs["Distance"].default_value = distance
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], nodes.get("Principled BSDF").inputs["Normal"])
    return {"environment_root": root, "cup": cup, "cup_body": body, "panda": panda,
            "table": table, "cloth": cloth, "cages": cages, "wood_panel": panel,
            "shelves": shelves, "materials": materials}
