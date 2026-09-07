#!/usr/bin/env python3
"""Package synchronized real/sim RGB sequences without dropping or duplicating frames.

The input PNGs contain no source timing. By default, playback is assigned 30 fps;
the correspondence is by source frame index, not recovered wall-clock timestamps.
"""

import argparse
import csv
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from fractions import Fraction

import cv2
from PIL import Image


VIEWS = ("head", "hand_left", "hand_right")


def binary(name, explicit=None):
    candidates = [explicit, shutil.which(name)]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError("{} was not found; pass --{} /path/to/{}".format(name, name, name))


def run(command, capture=False):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError("Command failed: {}\n{}".format(" ".join(map(str, command)), result.stderr))
    return result.stdout


def audit_sequences(directory, expected=None):
    audit = {}
    reference = expected
    for view in VIEWS:
        paths = sorted((directory / view).glob("*.png"))
        if not paths:
            raise RuntimeError("No PNG frames in {}".format(directory / view))
        stems = [path.stem for path in paths]
        if any(not stem.isdigit() or len(stem) != 6 for stem in stems):
            raise RuntimeError("Expected six-digit frame names in {}".format(directory / view))
        indices = [int(stem) for stem in stems]
        if indices != list(range(len(indices))):
            raise RuntimeError("Frames must be consecutive from 000000: {}".format(directory / view))
        if reference is None:
            reference = indices
        if indices != reference:
            raise RuntimeError("Frame index mismatch in {}".format(directory / view))
        sizes = set()
        modes = set()
        metadata_keys = set()
        timing_metadata = []
        for path in paths:
            with Image.open(path) as frame:
                sizes.add(frame.size)
                modes.add(frame.mode)
                metadata_keys.update(frame.info)
                timing = {key: str(value) for key, value in frame.info.items()
                          if any(token in key.lower() for token in ("fps", "duration", "timestamp", "frame_rate"))}
                if timing:
                    timing_metadata.append({"file": str(path), "metadata": timing})
                frame.verify()
        if sizes != {(640, 480)}:
            raise RuntimeError("Expected 640x480 images in {}; found {}".format(directory / view, sizes))
        audit[view] = {
            "directory": str(directory / view), "frame_count": len(paths),
            "first_file": paths[0].name, "last_file": paths[-1].name,
            "width": 640, "height": 480, "modes": sorted(modes),
            "png_metadata_keys": sorted(metadata_keys), "timing_metadata": timing_metadata,
        }
    return audit, reference


def encode_sequence(ffmpeg, source, target, count, fps, threads):
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial.mp4")
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-framerate", str(fps), "-start_number", "0", "-i", str(source / "%06d.png"),
         "-frames:v", str(count), "-an", "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps), "-fps_mode", "cfr",
         "-threads", str(threads), "-movflags", "+faststart", str(partial)])
    partial.replace(target)


def encode_comparison(ffmpeg, videos, target, count, fps, threads):
    """Top: real head/left/right. Bottom: matching sim head/left/right."""
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for kind in ("real_rgb", "sim_rgb"):
        for view in VIEWS:
            command.extend(["-i", str(videos / kind / (view + ".mp4"))])
    font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    filters = []
    for index, (kind, view) in enumerate((kind, view) for kind in ("real_rgb", "sim_rgb") for view in VIEWS):
        title = "{} / {}".format(kind, view)
        font_option = "fontfile={}:".format(font) if font.is_file() else ""
        filters.append("[{}:v]setpts=PTS-STARTPTS,drawtext={}text='{}':x=12:y=12:"
                       "fontsize=23:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=6[v{}]".format(
                           index, font_option, title, index))
    filters.append("[v0][v1][v2]hstack=inputs=3:shortest=1[top]")
    filters.append("[v3][v4][v5]hstack=inputs=3:shortest=1[bottom]")
    filters.append("[top][bottom]vstack=inputs=2:shortest=1[out]")
    partial = target.with_name(target.stem + ".partial.mp4")
    command.extend(["-filter_complex_threads", str(threads), "-filter_complex", ";".join(filters),
                    "-map", "[out]", "-frames:v", str(count), "-an", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps),
                    "-fps_mode", "cfr", "-threads", str(threads), "-movflags", "+faststart", str(partial)])
    run(command)
    partial.replace(target)


def encode_three_views(ffmpeg, videos, kind, target, count, fps, threads):
    """One horizontal row, ordered head, hand_left, hand_right."""
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for view in VIEWS:
        command.extend(["-i", str(videos / kind / (view + ".mp4"))])
    font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font_option = "fontfile={}:".format(font) if font.is_file() else ""
    filters = []
    for index, view in enumerate(VIEWS):
        filters.append("[{}:v]setpts=PTS-STARTPTS,drawtext={}text='{} / {}':x=12:y=12:"
                       "fontsize=23:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=6[v{}]".format(
                           index, font_option, kind, view, index))
    filters.append("[v0][v1][v2]hstack=inputs=3:shortest=1[out]")
    partial = target.with_name(target.stem + ".partial.mp4")
    command.extend(["-filter_complex_threads", str(threads), "-filter_complex", ";".join(filters),
                    "-map", "[out]", "-frames:v", str(count), "-an", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps),
                    "-fps_mode", "cfr", "-threads", str(threads), "-movflags", "+faststart", str(partial)])
    run(command)
    partial.replace(target)


def validate_video(ffprobe, path, count, fps, width=640, height=480):
    probe = json.loads(run([ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
                            "-show_entries", "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,nb_read_frames,duration",
                            "-of", "json", str(path)], capture=True))["streams"][0]
    actual_fps = float(Fraction(probe["avg_frame_rate"]))
    if int(probe["nb_read_frames"]) != count or not math.isclose(actual_fps, fps, abs_tol=1e-7):
        raise RuntimeError("Frame count/fps mismatch in {}: {}".format(path, probe))
    if (probe["width"], probe["height"]) != (width, height):
        raise RuntimeError("Resolution mismatch in {}: {}".format(path, probe))
    frame_data = json.loads(run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_frames",
                                 "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(path)],
                                capture=True))["frames"]
    timestamps = [float(frame["best_effort_timestamp_time"]) for frame in frame_data]
    if len(timestamps) != count:
        raise RuntimeError("Presentation timestamp count mismatch in {}".format(path))
    max_timestamp_error = max(abs(timestamp - index / fps) for index, timestamp in enumerate(timestamps))
    if max_timestamp_error > 0.000002:
        raise RuntimeError("Presentation timestamps do not match frame indices in {}".format(path))
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError("OpenCV cannot open {}".format(path))
    decoded = 0
    while True:
        okay, frame = capture.read()
        if not okay:
            break
        if frame.shape[:2] != (height, width):
            raise RuntimeError("Decoded frame resolution mismatch in {}".format(path))
        decoded += 1
    capture.release()
    if decoded != count:
        raise RuntimeError("OpenCV decoded {} frames, expected {} in {}".format(decoded, count, path))
    return {
        "path": str(path), "codec": probe["codec_name"], "width": width, "height": height,
        "fps": actual_fps, "ffprobe_frame_count": int(probe["nb_read_frames"]),
        "opencv_decoded_frames": decoded, "duration_seconds": float(probe["duration"]),
        "first_presentation_time_seconds": timestamps[0], "last_presentation_time_seconds": timestamps[-1],
        "max_presentation_timestamp_error_seconds": max_timestamp_error, "passed": True,
    }


def write_correspondence(path, indices, fps):
    fields = ["source_frame_id", "blender_frame_1based", "video_frame_0based", "playback_time_seconds"]
    fields += ["{}_{}".format(kind, view) for kind in ("real_rgb", "sim_rgb") for view in VIEWS]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index in indices:
            row = {"source_frame_id": "{:06d}".format(index), "blender_frame_1based": index + 1,
                   "video_frame_0based": index, "playback_time_seconds": "{:.9f}".format(index / fps)}
            for kind in ("real_rgb", "sim_rgb"):
                for view in VIEWS:
                    row["{}_{}".format(kind, view)] = "{}/{}/{:06d}.png".format(kind, view, index)
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sim-input", type=Path, help="Rendered frame directory; defaults to ROOT/sim_rgb")
    parser.add_argument("--stage", choices=("real", "sim", "all"), default="all")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--ffprobe")
    args = parser.parse_args()
    if args.fps <= 0 or args.threads < 1:
        parser.error("--fps and --threads must be positive")
    root = args.root.resolve()
    output = root / "outputs"
    videos = output / "videos"
    output.mkdir(parents=True, exist_ok=True)
    ffmpeg, ffprobe = binary("ffmpeg", args.ffmpeg), binary("ffprobe", args.ffprobe)
    source_audit, indices = audit_sequences(root / "real_rgb")
    count = len(indices)
    write_correspondence(output / "frame_correspondence.csv", indices, args.fps)
    report = {
        "fps": args.fps, "fps_origin": "assumed_playback_rate_no_source_timing_metadata",
        "alignment_basis": "equal_source_frame_index_for_all_six_streams",
        "source_frame_count": count, "source_frame_range_inclusive": [indices[0], indices[-1]],
        "blender_frame_range_inclusive": [1, count], "video_frame_range_inclusive": [0, count - 1],
        "playback_duration_seconds": count / args.fps,
        "last_frame_start_seconds": (count - 1) / args.fps,
        "source_audit": source_audit, "videos": {},
        "three_view_layout": list(VIEWS),
        "comparison_layout": [["real_rgb/head", "real_rgb/hand_left", "real_rgb/hand_right"],
                              ["sim_rgb/head", "sim_rgb/hand_left", "sim_rgb/hand_right"]],
        "ffmpeg": ffmpeg, "ffprobe": ffprobe,
    }
    if args.stage in ("real", "all"):
        for view in VIEWS:
            target = videos / "real_rgb" / (view + ".mp4")
            print("Encoding {}".format(target), flush=True)
            encode_sequence(ffmpeg, root / "real_rgb" / view, target, count, args.fps, args.threads)
            report["videos"]["real_rgb/" + view] = validate_video(ffprobe, target, count, args.fps)
    if args.stage in ("sim", "all"):
        sim_root = args.sim_input.resolve() if args.sim_input else root / "sim_rgb"
        report["sim_audit"], _ = audit_sequences(sim_root, expected=indices)
        report["render_manifests"] = {}
        for view in VIEWS:
            manifest_path = sim_root / ("render_manifest_{}.json".format(view))
            if manifest_path.is_file():
                report["render_manifests"][view] = json.loads(manifest_path.read_text(encoding="utf-8"))
        for view in VIEWS:
            real_target = videos / "real_rgb" / (view + ".mp4")
            if "real_rgb/" + view not in report["videos"]:
                report["videos"]["real_rgb/" + view] = validate_video(ffprobe, real_target, count, args.fps)
            target = videos / "sim_rgb" / (view + ".mp4")
            print("Encoding {}".format(target), flush=True)
            encode_sequence(ffmpeg, sim_root / view, target, count, args.fps, args.threads)
            report["videos"]["sim_rgb/" + view] = validate_video(ffprobe, target, count, args.fps)
        comparison = videos / "real_sim_three_views.mp4"
        print("Encoding {}".format(comparison), flush=True)
        encode_comparison(ffmpeg, videos, comparison, count, args.fps, args.threads)
        report["videos"]["comparison"] = validate_video(ffprobe, comparison, count, args.fps, 1920, 960)
        for kind in ("real_rgb", "sim_rgb"):
            target = videos / (kind + ".mp4")
            print("Encoding {}".format(target), flush=True)
            encode_three_views(ffmpeg, videos, kind, target, count, args.fps, args.threads)
            report["videos"][kind + "_three_views"] = validate_video(ffprobe, target, count, args.fps, 1920, 480)
    report["complete"] = args.stage in ("sim", "all")
    report_path = output / ("source_video_validation.json" if args.stage == "real" else "video_validation.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Validated {} videos; report: {}".format(len(report["videos"]), report_path), flush=True)


if __name__ == "__main__":
    main()
