#!/usr/bin/env bash
# Rebuild the scene, render aligned frames, and package validated videos.
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
REUSE_SCENE=0
REUSE_FRAMES=0
RESUME=0
SAMPLES=64
THREADS=4
ENGINE=cycles

usage() {
  cat <<'EOF'
用法: bash scripts/run_pipeline.sh [选项]
  --use-existing-scene  使用 reconstruction/replay.blend，跳过场景重建
  --use-existing-frames 使用现有 sim_rgb 三视角帧，仅重新编码并验证视频
  --resume              使用现有场景，校验后跳过已渲染帧
  --engine cycles|eevee 渲染引擎，默认 Cycles，优先使用 OPTIX GPU
  --samples N           采样数，默认 64
  --threads N           Blender CPU 线程数，默认 4
  --help                显示帮助

默认依次运行 build_replay.py、环境穿模检查、render_sequence.py、package_videos.py。
工具路径优先读取 reconstruction/runtime.json，也可由 BLENDER_BIN、
FFMPEG_BIN、FFPROBE_BIN、PYTHON_BIN 环境变量指定。
EOF
}

while (($#)); do
  case "$1" in
    --use-existing-scene) REUSE_SCENE=1; shift ;;
    --use-existing-frames) REUSE_FRAMES=1; REUSE_SCENE=1; shift ;;
    --resume) RESUME=1; REUSE_SCENE=1; shift ;;
    --engine)
      if (($# < 2)) || [[ "$2" != cycles && "$2" != eevee ]]; then
        echo "--engine 需要 cycles 或 eevee。" >&2
        exit 2
      fi
      ENGINE="$2"; shift 2 ;;
    --samples|--threads)
      if (($# < 2)) || [[ ! "$2" =~ ^[1-9][0-9]*$ ]]; then
        echo "参数 $1 需要正整数。" >&2
        exit 2
      fi
      if [[ "$1" == --samples ]]; then SAMPLES="$2"; else THREADS="$2"; fi
      shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

resolve_tool() {
  "$PYTHON_BIN" - "$PROJECT_ROOT" "$1" "$2" <<'PY'
import json
from pathlib import Path
import shutil
import sys
root, name, override = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
manifest = root / 'reconstruction/runtime.json'
runtime = json.loads(manifest.read_text()) if manifest.is_file() else {}
for value in (override, runtime.get(name), shutil.which(name)):
    if not value:
        continue
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    if path.is_file():
        print(path.resolve())
        break
else:
    raise SystemExit('找不到 {}；请更新 reconstruction/runtime.json 或指定环境变量。'.format(name))
PY
}

FFMPEG_BIN="$(resolve_tool ffmpeg "${FFMPEG_BIN:-}")"
FFPROBE_BIN="$(resolve_tool ffprobe "${FFPROBE_BIN:-}")"
cd -- "$PROJECT_ROOT"
mkdir -p outputs/logs

if ((REUSE_FRAMES == 0)); then
  BLENDER_BIN="$(resolve_tool blender "${BLENDER_BIN:-}")"
  if ((REUSE_SCENE == 0)); then
    "$BLENDER_BIN" --background --threads "$THREADS" --python-exit-code 1 --python scripts/build_replay.py \
      2>&1 | tee outputs/logs/build_replay.log
  fi
  "$BLENDER_BIN" --background --threads "$THREADS" --python-exit-code 1 --python scripts/validate_environment.py -- \
    --blend reconstruction/replay.blend --fail-on-collision \
    2>&1 | tee outputs/logs/environment_validation.log
  RENDER_ARGS=(--view all --start 0 --end 592 --engine "$ENGINE" --samples "$SAMPLES")
  if ((RESUME)); then RENDER_ARGS+=(--resume); fi
  "$BLENDER_BIN" --background --threads "$THREADS" --python-exit-code 1 --python scripts/render_sequence.py -- "${RENDER_ARGS[@]}" \
    2>&1 | tee outputs/logs/render_sequence.log
fi

"$PYTHON_BIN" scripts/package_videos.py --stage all --fps 30 \
  --ffmpeg "$FFMPEG_BIN" --ffprobe "$FFPROBE_BIN" 2>&1 | tee outputs/logs/package_videos.log
echo "完成：outputs/videos/、outputs/frame_correspondence.csv、outputs/video_validation.json"
