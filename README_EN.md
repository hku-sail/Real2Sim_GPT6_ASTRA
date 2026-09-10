# Three-View Robot RGB Scene Reconstruction and Action Replay

[中文](README.md) | **English**

[Robot case study and general video-to-Blender Efficient ASTRA pipeline (Chinese)](docs/efficient_astra_3d_pipeline_zh-CN.md)

## Repository Contents and Data Preparation

The Git repository contains the modeling, fitting, rendering, and validation code; the required visual-estimation parameters; robot-asset licenses; and the editable `reconstruction/replay.blend` scene. Approximately 1 GB of frame-by-frame PNG images under `real_rgb/` and `sim_rgb/`, along with videos, logs, and validation reports, are local inputs or reproducible outputs and are therefore excluded by `.gitignore`.

Before running the project, place the input frames in `real_rgb/{head,hand_left,hand_right}/`. Filenames must use consecutive six-digit frame indices. Install the Python dependencies:

```bash
python3 -m pip install -r requirements.txt
cp reconstruction/runtime.example.json reconstruction/runtime.json
```

Then enter the local paths to Blender, FFmpeg, and ffprobe in `reconstruction/runtime.json`. If these commands are already available through `PATH`, you may instead use environment variables or remove the corresponding placeholder values.

This project reconstructs the table, green panda pen holder, black marker, robot grippers, and room in Blender from the three `real_rgb` image streams, then replays the visible manipulation using geometric vision. The scene is stored in `reconstruction/replay.blend`, which can be opened to edit the models, cameras, and animation.

Only RGB frames were provided. Camera calibration, depth, ground-truth joint angles, control commands, and dynamics data were unavailable. Scale, occluded regions, camera parameters, and motion trajectories are estimated from the images. This is a visually approximate replay and must not be treated as an exact recovery of the real robot's joints or physical dynamics.

Known visible differences include the wrist pitch during the lifting phase in `hand_right`, the projected scale of the nearby gripper in `hand_left`, and details of the robot's appearance. The model of the white robot arm cannot be identified from these partial views, so hidden arm segments are completed geometrically and driven by analytic geometric inverse kinematics. The black marker maintains a complete rigid relative pose while grasped, and its post-release falling trajectory is animated by interpolation. See `outputs/reconstruction_validation.json` for detailed checks. Frame correspondence means that the same source-frame index is used; it does not imply complete agreement at the pixel or ground-truth joint level.

The latest environment correction repositioned the walls and metal cage shelving and removed the full wooden partition that blocked the shelf on the right. The right shelf is an independent 3D model containing a green tubular frame, four thin metal shelves, wood-colored side and back panels, and 38 product bags. Each transparent plastic bag includes a bulged body, sealed edges, a label, and food pieces inside. After its orientation and position were adjusted, the products are visible on the right side of the left-hand camera view. All 593 recorded poses were checked after the correction, with no geometric intersections detected between the environment and the table or robot, using a contact tolerance of 0.2 mm. The pipeline writes the results and shelf-visibility checks to `outputs/environment_validation.json`. These checks apply to the reconstructed geometry and do not replace validation of the real robot's dynamics.

## Frames and Views

- The three views are `head`, `hand_left`, and `hand_right`.
- Each view contains 593 frames named `000000.png` through `000592.png`, at a resolution of 640×480.
- Frame-mapping rule: **source frame n → Blender frame n+1 → output-video frame n**. All three views use the same frame indices, with no frame sampling during packaging.
- The source frames contain no usable timing metadata, so all videos assume 30 fps and have a duration of approximately 19.767 seconds. The time column represents the specified playback time rather than recovered capture timestamps.
- Index synchronization means that files correspond frame by frame; it does not mean that poses estimated from the images exactly match the real robot poses.

## Outputs

```text
real_rgb/{head,hand_left,hand_right}/000000.png … 000592.png
sim_rgb/{head,hand_left,hand_right}/000000.png … 000592.png
reconstruction/replay.blend
outputs/videos/real_rgb.mp4
outputs/videos/sim_rgb.mp4
outputs/videos/real_rgb/{head,hand_left,hand_right}.mp4
outputs/videos/sim_rgb/{head,hand_left,hand_right}.mp4
outputs/videos/real_sim_three_views.mp4
outputs/compare.html
outputs/frame_correspondence.csv
outputs/video_validation.json
outputs/environment_validation.json
```

Open `outputs/videos/real_rgb.mp4` and `outputs/videos/sim_rgb.mp4` to view the real and simulated three-view videos in horizontal layouts. Each video is 1920×480, with columns ordered as `head`, `hand_left`, and `hand_right`, and contains 593 frames at 30 fps.

The six-panel comparison video, `real_sim_three_views.mp4`, is 1920×960. The top row contains the real images, the bottom row contains the simulated images, and both rows use the same column order. All six individual videos retain their original resolutions. The CSV lists the source filename, Blender frame number, video frame number, and playback time for all 593 frames.

After running the pipeline, open the frame-by-frame comparison viewer at `outputs/compare.html` directly in a browser; no network connection or dependency installation is required. Drag the slider, enter a frame number from 0 to 592, click the previous/next buttons, or use the left and right arrow keys to inspect all six original PNG images at the same frame. Press Space to play or pause. The viewer switches frames only after all six images have loaded and preloads adjacent frames. Keep the project directory structure intact so the page can access `real_rgb` and `sim_rgb` at the same project level.

`video_validation.json` records checks of input continuity, dimensions, encoded frame counts, frame rates, and frame-by-frame presentation timestamps, and verifies every output through complete OpenCV decoding. When only source videos are packaged, the report is written to `outputs/source_video_validation.json`.

## Reproducing the Pipeline

The pipeline requires Blender 4.5, FFmpeg/ffprobe with an H.264 encoder, and Python 3 with the dependencies listed in `requirements.txt`. Local tool paths can be entered in `reconstruction/runtime.json`, copied from `reconstruction/runtime.example.json`, or specified through the `BLENDER_BIN`, `FFMPEG_BIN`, `FFPROBE_BIN`, and `PYTHON_BIN` environment variables.

Run the following commands from the project directory:

```bash
# Rebuild the scene, check all 593 frames for environment intersections,
# render every frame from all three views, encode the videos, and validate them
bash scripts/run_pipeline.sh

# Use the currently saved scene, checking for environment intersections before rendering
bash scripts/run_pipeline.sh --use-existing-scene

# Resume an interrupted render with the same scene and sampling settings;
# the default is Cycles with 64 samples
bash scripts/run_pipeline.sh --resume

# Re-encode and validate existing complete sim_rgb frames only
bash scripts/run_pipeline.sh --use-existing-frames
```

After preparing the scene and before rendering the full sequence, the pipeline runs `scripts/validate_environment.py --fail-on-collision` across all 593 recorded poses. It stops if an environment intersection is detected and writes the result to `outputs/environment_validation.json`. `--use-existing-frames` only re-encodes existing images and does not trigger modeling or geometric validation.

For an individual render, specify the camera and source-frame range. All paths are relative to the project root:

```bash
/path/to/blender --background --python scripts/render_sequence.py -- \
  --view hand_right --start 0 --end 592 --engine cycles --samples 64 --resume

python3 scripts/package_videos.py --stage real
python3 scripts/package_videos.py --stage sim
```

The renderer uses Cycles with 64 samples, denoising, and persistent scene caching by default, preferring an OPTIX GPU. If no supported GPU is available, it falls back to the CPU and prints an explanatory message. You may also use `--engine eevee`. The rendering script reads the cameras and animation already stored in the scene and does not refit the cameras. `--resume` validates PNG integrity and skips existing frames. If the `.blend` file, engine, or sampling settings change, omit `--resume` and render again. The reconstruction entry point, `scripts/build_replay.py`, uses the saved observations, calibration, and motion estimates in `reconstruction`. The environment, shelf, and robot models are defined in `scripts/environment_geometry.py`, `scripts/shelf_geometry.py`, and `scripts/robot_geometry.py`, respectively.

## Citation

If this project helps your research, please cite it as follows:

```bibtex
@misc{ding2026GPTReal2Sim,
  title        = {{GPT6\_ASTRA is A Zero-Shot Engine for Real-to-Simulation Generation}},
  author       = {Ding, Kaixin and You, Linjing and Zhao, Hengshuang},
  year         = {2026},
  howpublished = {GitHub},
  url          = {https://github.com/hku-sail/Real2Sim_GPT6_ASTRA}
}
```
