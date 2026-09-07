"""Render a standalone overview of the reconstructed 3D workspace, without saving changes."""
from pathlib import Path
import bpy,sys
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from render_sequence import configure_engine
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'reconstruction/replay.blend'))
s=bpy.context.scene;s.frame_set(401)
d=bpy.data.cameras.new('Preview_overview');c=bpy.data.objects.new('Preview_overview',d);bpy.context.collection.objects.link(c)
c.location=(.95,-1.75,1.45);c.rotation_euler=(Vector((0,-.10,.03))-c.location).to_track_quat('-Z','Y').to_euler();d.lens=43
s.camera=c;s.render.resolution_x=1280;s.render.resolution_y=960;s.render.resolution_percentage=100
configure_engine(s,'cycles',64)
s.render.filepath=str(ROOT/'outputs/preview/scene_overview.png');bpy.ops.render.render(write_still=True)
