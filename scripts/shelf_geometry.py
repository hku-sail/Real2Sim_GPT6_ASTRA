"""Detailed three-dimensional shop shelf, observed in real_rgb/hand_left.

build_shelf(parent=None, location=(0,0,0), rotation=0) returns a dictionary.
Local X is depth (open front faces -X); local Y is shelf width. Default extents
are X +/-0.19, Y +/-0.40 and Z -0.72..+0.33 metres. Rotate/place only the root.
No photographs, external textures or external assets are required.
"""

import math
import random
import bpy
from mathutils import Matrix, Vector


def _material(name, color, roughness=.45, metallic=0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*color, 1)
    bs = mat.node_tree.nodes.get('Principled BSDF')
    bs.inputs['Base Color'].default_value = (*color, 1)
    bs.inputs['Roughness'].default_value = roughness
    bs.inputs['Metallic'].default_value = metallic
    return mat


def _empty(name, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    obj.parent = parent
    return obj


def _mesh(name, vertices, faces, materials, parent=None):
    data = bpy.data.meshes.new(name + ' mesh')
    data.from_pydata(vertices, [], faces)
    data.update()
    for material in materials:
        data.materials.append(material)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.parent = parent
    return obj


def _box(name, center, dimensions, material, parent=None, bevel=.001):
    x, y, z = center
    a, b, c = [v/2 for v in dimensions]
    verts = [(x+sx*a, y+sy*b, z+sz*c) for sx,sy,sz in
             [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]]
    faces = [(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]
    obj = _mesh(name, verts, faces, [material], parent)
    if bevel:
        mod = obj.modifiers.new('Small manufactured edge roundover','BEVEL')
        mod.width = bevel
        mod.segments = 2
        obj.modifiers.new('Weighted normals','WEIGHTED_NORMAL')
    return obj


def _rod(name, a, b, radius, material, parent=None, segments=20):
    a, b = Vector(a), Vector(b)
    bpy.ops.mesh.primitive_cylinder_add(vertices=segments, radius=radius, depth=(b-a).length,
                                       location=(a+b)/2)
    obj = bpy.context.object
    obj.name = name
    obj.parent = parent
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = (b-a).to_track_quat('Z','Y')
    obj.data.materials.append(material)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def _box_group(name, boxes, material, parent):
    vertices, faces = [], []
    for center, dimensions in boxes:
        x,y,z=center
        a,b,c=[v/2 for v in dimensions]
        start=len(vertices)
        vertices.extend((x+sx*a,y+sy*b,z+sz*c) for sx,sy,sz in
                        [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)])
        faces.extend(tuple(start+i for i in face) for face in
                     [(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)])
    return _mesh(name,vertices,faces,[material],parent)


def _film_material():
    mat = _material('Shelf | clear crinkled packaging film', (.93,.95,.92), .13)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bs = nodes.get('Principled BSDF')
    bs.inputs['IOR'].default_value = 1.46
    bs.inputs['Coat Weight'].default_value = .5
    bs.inputs['Coat Roughness'].default_value = .08
    noise = nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 145
    noise.inputs['Detail'].default_value = 2
    bump = nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .24
    bump.inputs['Distance'].default_value = .0012
    links.new(noise.outputs['Fac'], bump.inputs['Height'])
    links.new(bump.outputs['Normal'], bs.inputs['Normal'])
    transparent = nodes.new('ShaderNodeBsdfTransparent')
    mix = nodes.new('ShaderNodeMixShader')
    mix.inputs[0].default_value = .115
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(bs.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], nodes.get('Material Output').inputs['Surface'])
    # A transparent-plus-reflective thin-film approximation avoids treating the
    # entire air-filled pouch as solid glass, while retaining actual bag geometry.
    return mat


def _wood_material():
    mat = _material('Shelf | honey oak side panel', (.45,.285,.115), .58)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    tex = nodes.new('ShaderNodeTexCoord')
    mapping = nodes.new('ShaderNodeVectorMath'); mapping.operation = 'MULTIPLY'
    mapping.inputs[1].default_value = (12,15,.8)
    noise = nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value = 4
    noise.inputs['Detail'].default_value = 3
    links.new(tex.outputs['Generated'],mapping.inputs[0])
    links.new(mapping.outputs[0],noise.inputs['Vector'])
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = (.26,.145,.054,1)
    ramp.color_ramp.elements[1].color = (.56,.365,.16,1)
    links.new(noise.outputs['Fac'],ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'],nodes.get('Principled BSDF').inputs['Base Color'])
    return mat


def _pouch(name, position, width, height, depth, color_index, mats, rng, parent):
    root = _empty(name, parent)
    root.location = position
    root.rotation_euler = (rng.uniform(-.10,.10),rng.uniform(-.09,.09),rng.uniform(-.10,.10))
    root['asset_type'] = '3D transparent snack pouch with enclosed food, seals and labels'
    # Separate front/back grids are joined around every edge: an inflated,
    # irregular closed pouch, with flattened upper and lower heat seals.
    nu, nv = 12, 16
    verts, faces = [], []
    for sign in (-1,1):
        for iz in range(nv+1):
            t=iz/nv
            for iy in range(nu+1):
                u=iy/nu
                swelling=(max(0,math.sin(math.pi*u))*max(0,math.sin(math.pi*t)))**.42
                wrinkle=.0011*math.sin(31*u+19*t+color_index)*math.sin(math.pi*u)*math.sin(math.pi*t)
                x=sign*(.0014+depth*.5*swelling)+wrinkle
                y=(u-.5)*width*(.96+.04*math.sin(math.pi*t))
                z=t*height+.0015*math.sin(23*u+3*t)*math.sin(math.pi*t)
                verts.append((x,y,z))
    stride=(nu+1)*(nv+1)
    for layer in range(2):
        for iz in range(nv):
            for iy in range(nu):
                i=layer*stride+iz*(nu+1)+iy
                f=(i,i+1,i+nu+2,i+nu+1)
                faces.append(tuple(reversed(f)) if layer==0 else f)
    for iy in range(nu):
        faces.append((iy,iy+stride,iy+stride+1,iy+1))
        i=nv*(nu+1)+iy
        faces.append((i,i+1,i+stride+1,i+stride))
    for iz in range(nv):
        i=iz*(nu+1)
        faces.append((i,i+nu+1,i+nu+1+stride,i+stride))
        i+=nu
        faces.append((i,i+stride,i+stride+nu+1,i+nu+1))
    shell=_mesh(name+' | inflated clear film',verts,faces,[mats['film']],root)
    for polygon in shell.data.polygons:polygon.use_smooth=True
    colored=mats['wrapper_'+str(color_index%5)]
    # Narrow coloured crimps rather than opaque boxes leave most contents visible.
    seal_ribs=[]
    for z in (.007,height-.008):
        _box(name+' | heat-sealed crimp',(0,0,z),(.0032,width*.97,.012),colored,root,.0008)
        for j in range(8):
            seal_ribs.append(((-.002,-width*.44+j*width*.125,z),(.0006,.0012,.011)))
    _box_group(name+' | fine crimp ribs',seal_ribs,mats['seal'],root)
    for sign in (-1,1):
        _box(name+' | side seal',(0,sign*width*.49,height*.5),(.0028,.0025,height*.94),
             mats['seal'],root,.0006)
    # Front label and printed header. Thin actual geometry follows the -X face.
    front=-depth*.51-.002
    label_z=height*.62
    _box(name+' | paper product label',(front,0,label_z),(.0007,width*.53,height*.26),
         mats['label'],root,.0013)
    _box(name+' | colored label heading',(front-.0006,0,label_z+height*.083),
         (.0004,width*.48,height*.050),colored,root,.0004)
    # Three print rules and a tiny barcode provide scale without fictitious branding.
    print_shapes=[]
    for line in range(3):
        print_shapes.append(((front-.0007,0,label_z+height*(.025-line*.028)),
                             (.00035,width*(.34-.025*line),.00065)))
    for bar in range(9):
        print_shapes.append(((front-.0007,-width*.15+bar*width*.018,label_z-height*.075),
                             (.00035,.00055 if bar%3 else .0011,height*.040)))
    _box_group(name+' | label print and barcode',print_shapes,mats['ink'],root)
    # Individual irregular food pieces inside the volume: one efficient combined
    # mesh with per-piece colour, bevelled corners, and independently rotated chunks.
    food_verts, food_faces, material_indices = [], [], []
    for item in range(rng.randint(10,15)):
        center=Vector((rng.uniform(-depth*.24,depth*.24),rng.uniform(-width*.32,width*.32),
                       rng.uniform(height*.14,height*.76)))
        size=Vector((rng.uniform(.007,.013),rng.uniform(.009,.018),rng.uniform(.008,.016)))
        rot=Matrix.Rotation(rng.uniform(-.8,.8),3,'X') @ Matrix.Rotation(rng.uniform(-.5,.5),3,'Y')
        start=len(food_verts)
        for signs in [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]:
            p=center+rot@Vector([s*v for s,v in zip(signs,size)])
            food_verts.append(tuple(p))
        for face in [(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]:
            food_faces.append(tuple(start+i for i in face));material_indices.append((item+color_index)%4)
    food=_mesh(name+' | separate visible food chunks',food_verts,food_faces,[mats['food_'+str(i)] for i in range(4)],root)
    for poly,index in zip(food.data.polygons,material_indices):poly.material_index=index
    bevel=food.modifiers.new('Rounded irregular biscuit edges','BEVEL');bevel.width=.002;bevel.segments=2
    food.modifiers.new('Food surface normals','WEIGHTED_NORMAL')
    return root


def build_shelf(parent=None, location=(0,0,0), rotation=0, depth=.38, width=.80,
                height=1.05, floor_z=-.72, side_panel=True, side_panel_sign=1,
                seed=31, name='Shelf'):
    """Create shelf and goods, returning root/frame/trays/panels/packages/materials.

    ``rotation`` accepts yaw radians or a three-component Euler tuple. All
    geometry is local to root. ``side_panel_sign`` chooses Y=-width/2 or +width/2.
    The local opening faces -X; root location and rotation are left to layout.
    """
    before=set(bpy.data.objects)
    root=_empty(name,parent)
    root.location=location
    root.rotation_euler=(0,0,rotation) if isinstance(rotation,(int,float)) else rotation
    root['opening_local_direction']=[-1,0,0]
    root['dimensions_m']=[depth,width,height]
    mats={
        'green':_material('Shelf | teal green enamel tubular frame',(.025,.255,.182),.30,.32),
        'tray':_material('Shelf | painted green thin metal trays',(.06,.20,.14),.48,.25),
        'metal':_material('Shelf | steel fasteners',(.32,.34,.32),.28,.75),
        'wood':_wood_material(),
        'back':_material('Shelf | warm pale wood backboard',(.40,.34,.24),.74),
        'film':_film_material(),
        'seal':_material('Shelf | translucent heat sealed plastic',(.78,.76,.61),.27),
        'label':_material('Shelf | cream printed paper labels',(.84,.78,.61),.78),
        'ink':_material('Shelf | dark product label ink',(.085,.045,.025),.83),
        'rubber':_material('Shelf | black foot pads',(.01,.015,.013),.73),
    }
    for i,color in enumerate([(.66,.31,.035),(.62,.055,.030),(.75,.64,.33),(.16,.33,.13),(.38,.16,.045)]):
        mats['wrapper_'+str(i)]=_material('Shelf | printed wrapper color '+str(i),color,.40)
    for i,color in enumerate([(.56,.29,.085),(.70,.46,.16),(.30,.105,.035),(.76,.59,.30)]):
        mats['food_'+str(i)]=_material('Shelf | visible dried food '+str(i),color,.79)
    frame=_empty(name+' | tubular structure',root)
    top=floor_z+height
    front,back=-depth/2+.014,depth/2-.014
    for x in (front,back):
        for y in (-width/2+.015,width/2-.015):
            _rod(name+' | round green upright',(x,y,floor_z+.012),(x,y,top),.013,mats['green'],frame)
            _box(name+' | square foot pad',(x,y,floor_z+.005),(.033,.033,.010),mats['rubber'],frame,.002)
    trays=[]
    levels=[floor_z+.065+i*(height-.16)/3 for i in range(4)]
    for level,z in enumerate(levels):
        tray=_box(name+' | thin tray '+str(level),(0,0,z),(depth-.025,width-.025,.008),mats['tray'],root,.001)
        trays.append(tray)
        _rod(name+' | prominent round green front rail '+str(level),(front,-width/2+.01,z+.016),
             (front,width/2-.01,z+.016),.0145,mats['green'],frame)
        _rod(name+' | rear green rail '+str(level),(back,-width/2+.01,z+.014),
             (back,width/2-.01,z+.014),.009,mats['green'],frame)
        for sign in (-1,1):
            _rod(name+' | green tray side rim '+str(level),(front,sign*(width/2-.014),z+.013),
                 (back,sign*(width/2-.014),z+.013),.008,mats['green'],frame)
            _rod(name+' | front rail bolt '+str(level),(front-.016,sign*(width/2-.035),z+.016),
                 (front-.019,sign*(width/2-.035),z+.016),.004,mats['metal'],frame,12)
    panels=[]
    wood_panel=None
    if side_panel:
        side_y=(-1 if side_panel_sign<0 else 1)*(width/2+.006)
        panel=_box(name+' | thick honey oak side partition',(-.015,side_y,(floor_z+top)/2),
                   (depth+.060,.022,height),mats['wood'],root,.0025)
        panels.append(panel)
        wood_panel=panel
        _box(name+' | pale side panel edge',(-depth/2-.045,side_y,(floor_z+top)/2),
             (.008,.024,height),mats['label'],root,.001)
    panels.append(_box(name+' | thin wood back panel',(depth/2+.003,0,(floor_z+top)/2),
                       (.012,width,height),mats['back'],root,.001))
    rng=random.Random(seed)
    packages=[]
    for level,z in enumerate(levels[:3]):
        for row,count in ((0,6),(1,5)):
            for j in range(count):
                y=-width*.415+(j+.35*(row>0))*width*.83/(count-1)
                x=-depth*.27 if row==0 else depth*.12
                h=rng.uniform(.15,.205)
                package=_pouch(name+' | snack pouch L{} R{} P{}'.format(level,row,j),
                               (x+rng.uniform(-.008,.008),y,z+.007),
                               rng.uniform(.090,.112),h,rng.uniform(.035,.050),
                               (j+level+row)%5,mats,rng,root)
                packages.append(package)
    # Loosely stacked transparent bags and small jars on the upper shelf.
    for j in range(5):
        package=_pouch(name+' | top miscellaneous pouch '+str(j),
                       (-.035,-width*.34+j*width*.16,levels[-1]+.009),
                       .097,rng.uniform(.070,.095),.038,j%5,mats,rng,root)
        packages.append(package)
    for j,y in enumerate((-.25,.23)):
        _rod(name+' | small storage jar '+str(j),(.105,y,levels[-1]+.008),(.105,y,top-.006),
             .025,mats['film'],root,28)
        _rod(name+' | storage jar cap '+str(j),(.105,y,top-.012),(.105,y,top),
             .026,mats['wrapper_'+str(j)],root,28)
    generated=[obj for obj in bpy.data.objects if obj not in before]
    root['generated_object_count']=len(generated)
    root['package_count']=len(packages)
    return {'root':root,'frame':frame,'trays':trays,'panels':panels,'wood_panel':wood_panel,'packages':packages,
            'materials':mats,'objects':generated,'object_count':len(generated)}
