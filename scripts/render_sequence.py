"""Render saved Blender camera animation into frame-aligned RGB PNG sequences.

Example:
    blender -b --python scripts/render_sequence.py -- --view all --start 0 --end 592

Source PNG frame n maps to Blender frame n+1. Camera transforms, parenting,
intrinsics and animation are read from the saved scene and are never refitted.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
import zlib

import bpy


ROOT = Path(__file__).resolve().parents[1]
VIEWS = ("head", "hand_left", "hand_right")


def root_path(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def valid_png(path, width=640, height=480):
    """Check dimensions and every PNG chunk CRC before trusting a resume frame."""
    try:
        with path.open("rb") as handle:
            if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                return False
            found_header, found_data = False, False
            while True:
                header = handle.read(8)
                if len(header) != 8:
                    return False
                length, kind = struct.unpack(">I4s", header)
                if length > 32 * 1024 * 1024:
                    return False
                data = handle.read(length)
                crc = handle.read(4)
                if len(data) != length or len(crc) != 4:
                    return False
                if zlib.crc32(kind + data) & 0xffffffff != struct.unpack(">I", crc)[0]:
                    return False
                if kind == b"IHDR":
                    if len(data) != 13 or struct.unpack(">II", data[:8]) != (width, height):
                        return False
                    found_header = True
                elif kind == b"IDAT":
                    found_data = True
                elif kind == b"IEND":
                    return found_header and found_data and length == 0 and handle.read(1) == b""
    except (OSError, struct.error):
        return False


def save_json(path, value):
    temporary = path.with_suffix(".partial.json")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def configure_engine(scene, engine, samples):
    if engine == "eevee":
        scene.render.engine = "BLENDER_EEVEE_NEXT"
        scene.eevee.taa_render_samples = samples
        return {"backend": "EEVEE", "device": "renderer_default"}
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.cycles.use_adaptive_sampling = False
    scene.render.use_persistent_data = True
    preferences = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            preferences.compute_device_type = backend
            preferences.get_devices()
            devices = [device for device in preferences.devices if device.type == backend]
            if not devices:
                continue
            for device in preferences.devices:
                device.use = device.type == backend
            scene.cycles.device = "GPU"
            scene.cycles.denoiser = "OPTIX" if backend == "OPTIX" else "OPENIMAGEDENOISE"
            names = [device.name for device in devices]
            print("RENDER_DEVICE backend={} devices={}".format(backend, names), flush=True)
            return {"backend": backend, "device": "GPU", "devices": names,
                    "denoiser": scene.cycles.denoiser, "persistent_data": True}
        except (TypeError, RuntimeError, ValueError):
            continue
    scene.cycles.device = "CPU"
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    print("RENDER_DEVICE No supported Cycles GPU found; falling back to CPU rendering.", flush=True)
    return {"backend": "CPU", "device": "CPU", "denoiser": scene.cycles.denoiser,
            "persistent_data": True}


def main():
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blend", default="reconstruction/replay.blend")
    parser.add_argument("--view", choices=("all",) + VIEWS, default="all")
    parser.add_argument("--start", type=int, default=0, help="Inclusive source frame index")
    parser.add_argument("--end", type=int, default=592, help="Inclusive source frame index")
    parser.add_argument("--resume", action="store_true", help="Skip existing valid PNGs from the same saved scene")
    parser.add_argument("--engine", choices=("cycles", "eevee"), default="cycles")
    parser.add_argument("--samples", type=int, default=64, help="Render samples, default 64")
    parser.add_argument("--output-dir", default="sim_rgb", help="Absolute or project-relative directory")
    args = parser.parse_args(arguments)
    if not 0 <= args.start <= args.end <= 592:
        parser.error("Require 0 <= --start <= --end <= 592")
    if args.samples < 1:
        parser.error("--samples must be positive")
    blend_path = root_path(args.blend)
    if not blend_path.is_file():
        parser.error("Saved scene does not exist: {}".format(blend_path))
    output = root_path(args.output_dir)
    scene_hash = hashlib.sha256(blend_path.read_bytes()).hexdigest()
    if Path(bpy.data.filepath).resolve() != blend_path:
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    scene = bpy.context.scene
    if scene.frame_start > args.start + 1 or scene.frame_end < args.end + 1:
        raise RuntimeError("Saved scene animation does not cover the requested frame range")
    device_info = configure_engine(scene, args.engine, args.samples)
    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 30
    scene.render.film_transparent = False
    scene.render.use_file_extension = True
    views = VIEWS if args.view == "all" else (args.view,)
    for view in views:
        camera = bpy.data.objects.get(view)
        if camera is None or camera.type != "CAMERA":
            raise RuntimeError("The saved scene has no camera named '{}'".format(view))
        directory = output / view
        directory.mkdir(parents=True, exist_ok=True)
        manifest_path = output / ("render_manifest_{}.json".format(view))
        old = json.loads(manifest_path.read_text()) if manifest_path.is_file() else None
        if args.resume and old and old.get("source_scene_sha256") != scene_hash:
            raise RuntimeError("{} was rendered from a different .blend; rerun without --resume".format(view))
        if args.resume and old and old.get("samples") != args.samples:
            raise RuntimeError("{} has different render samples; rerun without --resume or use --samples {}".format(
                view, old.get("samples")))
        if args.resume and old and old.get("engine") != scene.render.engine:
            raise RuntimeError("{} has a different render engine; rerun without --resume".format(view))
        rendered, skipped = 0, 0
        started = time.monotonic()
        manifest = {
            "view": view, "source_scene": str(blend_path), "source_scene_sha256": scene_hash,
            "source_frame_range_inclusive": [args.start, args.end], "blender_frame_offset": 1,
            "camera_object": camera.name, "camera_pose_source": "saved_scene_animation_unchanged",
            "engine": scene.render.engine, "samples": args.samples, "width": 640, "height": 480,
            "render_device": device_info,
            "fps": scene.render.fps / scene.render.fps_base,
            "resume": args.resume, "completed": False,
        }
        scene.camera = camera
        for index in range(args.start, args.end + 1):
            target = directory / ("{:06d}.png".format(index))
            if args.resume and valid_png(target):
                skipped += 1
            else:
                scene.frame_set(index + 1)
                # This frame owns a temporary path so interrupted writes cannot be reused.
                temporary = directory / (".{:06d}.rendering.png".format(index))
                scene.render.filepath = str(temporary)
                bpy.ops.render.render(write_still=True)
                if not valid_png(temporary):
                    raise RuntimeError("Blender produced an invalid PNG: {}".format(temporary))
                temporary.replace(target)
                rendered += 1
            manifest.update({"last_completed_source_frame": index, "rendered_this_run": rendered,
                             "skipped_this_run": skipped, "elapsed_seconds": round(time.monotonic() - started, 3)})
            if index == args.start or (index + 1) % 20 == 0 or index == args.end:
                save_json(manifest_path, manifest)
                print("RENDER_PROGRESS view={} source_frame={:06d}/{} rendered={} skipped={}".format(
                    view, index, args.end, rendered, skipped), flush=True)
        manifest["completed"] = True
        save_json(manifest_path, manifest)
        print("RENDER_VIEW_COMPLETE {}: {} rendered, {} resumed, {:.1f}s".format(
            view, rendered, skipped, time.monotonic() - started), flush=True)
    print("RENDER_COMPLETE source n -> Blender n+1 -> sim_rgb/view/n.png", flush=True)


if __name__ == "__main__":
    main()
