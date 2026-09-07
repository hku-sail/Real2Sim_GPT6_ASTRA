# 三视角机器人 RGB 场景重建与动作重放

## 仓库内容与数据准备

Git 仓库包含建模、拟合、渲染和验证代码，必要的视觉估计参数、机器人资产许可证，以及可编辑的 `reconstruction/replay.blend`。约 1 GB 的 `real_rgb/`、`sim_rgb/` 逐帧 PNG、视频、日志和验证报告属于本地输入或可再生成结果，因此由 `.gitignore` 排除。

运行前请将输入帧放入 `real_rgb/{head,hand_left,hand_right}/`，文件名为连续的六位帧号。安装 Python 依赖：

```bash
python3 -m pip install -r requirements.txt
cp reconstruction/runtime.example.json reconstruction/runtime.json
```

随后在 `reconstruction/runtime.json` 中填写 Blender、FFmpeg 和 ffprobe 的本机路径；如果这些命令已加入 `PATH`，也可直接使用环境变量或删除对应占位值。

本工程根据 `real_rgb` 的三路图像，在 Blender 中重建桌面、绿色熊猫笔筒、黑色记号笔、机器人夹爪与房间，并对可见操作进行几何视觉重放。场景保存在 `reconstruction/replay.blend`，可打开编辑模型、相机和动画。

仅提供了 RGB 帧，未提供相机标定、深度、真实关节角、控制指令或动力学数据。尺度、遮挡区域、相机参数和运动轨迹由图像估计；这是视觉近似重放，不能视为真实关节或物理动力学的精确恢复。

已知可见差异包括：`hand_right` 抬腕阶段的俯仰、`hand_left` 近处夹爪的投影比例，以及机器人外形细节。白色机械臂的型号无法从这些局部图像确认，隐藏臂段使用几何补全与解析几何 IK。黑笔在夹持阶段保持完整刚性相对姿态，释放后的落笔轨迹为动画插值。详细检查见 `outputs/reconstruction_validation.json`；逐帧对应指相同源帧索引，不代表像素或真实关节级的完全一致。

本次环境修复重新布置了墙体与金属笼架，并移除了遮挡右侧货架的整片木隔板。右侧货架采用独立三维模型，包含绿色圆管框架、4层薄金属板、木色侧背板和38袋商品；透明塑料袋具有鼓胀袋体、封边、标签与内部食品块。货架朝向与位置调整后可在左手视角右侧看到商品。修复后检查了全部593个记录姿态，未检测到环境与桌面、机器人的几何穿插；采用0.2毫米接触容差。结果及货架可见性检查见 [environment_validation.json](outputs/environment_validation.json)。这些检查针对已重建的几何，不替代真实机器人动力学验证。

## 帧与视角

- 三个视角均为 `head`、`hand_left`、`hand_right`。
- 每个视角包含 `000000.png` 至 `000592.png`，共 593 帧，分辨率 640×480。
- 帧对应规则：**原始帧 n → Blender 帧 n+1 → 输出视频帧 n**。三视角使用相同帧号，打包时不抽帧。
- 源帧没有可用时间元数据，因此统一假设 30fps，视频时长约 19.767 秒。时间列是指定播放时间，不是恢复的采集时间戳。
- 索引同步表示文件逐帧对应；它不表示图像估计得到的姿态与真机姿态完全相同。

## 输出

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

直接打开 `outputs/videos/real_rgb.mp4` 和 `outputs/videos/sim_rgb.mp4` 即可分别查看真实与模拟三视角横排视频：1920×480，列依次为 `head`、`hand_left`、`hand_right`，均为 593 帧、30fps。

六宫格对比视频 `real_sim_three_views.mp4` 为 1920×960：上排是真实图像，下排是模拟图像，列顺序相同。六路独立视频均保留各自原始分辨率。CSV 列出全部 593 帧的源文件名、Blender 帧号、视频帧号及播放时间。

用浏览器直接打开 [逐帧对比器](outputs/compare.html)，无需联网或安装依赖。拖动滑条、输入 0–592 的帧号、点击前后帧按钮或使用左右方向键，可检查六张原始 PNG 的同帧画面；空格可播放/暂停。页面在六张图像全部加载后一起切换，并预加载相邻帧。请保留工程目录结构，使页面可以读取同级工程下的 `real_rgb` 与 `sim_rgb`。

`video_validation.json` 记录输入连续性、尺寸、编码帧数、帧率及逐帧显示时间检查，并通过 OpenCV 完整解码复核全部输出。仅打包源视频时，报告为 `outputs/source_video_validation.json`。

## 重跑

需要 Blender 4.5、带 H.264 编码器的 FFmpeg/ffprobe，以及安装了 `requirements.txt` 依赖的 Python 3。本机工具路径可写入从 `reconstruction/runtime.example.json` 复制出的 `reconstruction/runtime.json`，或通过 `BLENDER_BIN`、`FFMPEG_BIN`、`FFPROBE_BIN`、`PYTHON_BIN` 环境变量指定。

在工程目录执行：

```bash
# 重建场景、检查全部593帧环境穿模、渲染三路全部帧、编码与验证
bash scripts/run_pipeline.sh

# 使用当前已保存场景，先检查环境穿模，再开始渲染
bash scripts/run_pipeline.sh --use-existing-scene

# 同一场景与采样设置下断点续渲；默认 Cycles 64 samples
bash scripts/run_pipeline.sh --resume

# 已有完整 sim_rgb 帧，只重新编码和验证
bash scripts/run_pipeline.sh --use-existing-frames
```

流水线会在场景准备好后、全序列渲染前运行 `scripts/validate_environment.py --fail-on-collision`，检查全部593个记录姿态；检测到环境穿模时停止，结果写入 `outputs/environment_validation.json`。`--use-existing-frames` 仅重新编码现有图像，不触发建模或几何检查。

单独渲染可指定相机和源帧区间，路径均以工程根目录为基准：

```bash
/path/to/blender --background --python scripts/render_sequence.py -- \
  --view hand_right --start 0 --end 592 --engine cycles --samples 64 --resume

python3 scripts/package_videos.py --stage real
python3 scripts/package_videos.py --stage sim
```

默认使用 Cycles、64 samples、降噪与持久场景缓存，优先选择 OPTIX GPU；没有支持的 GPU 时回退到 CPU 并打印说明。也可用 `--engine eevee`。渲染脚本读取场景中已保存的相机与动画，不重新拟合相机。`--resume` 验证 PNG 完整性并跳过已有帧；如 `.blend`、引擎或采样设置发生变化，应去掉 `--resume` 重新渲染。重建入口 `scripts/build_replay.py` 使用 `reconstruction` 中保存的观测、标定与运动估计数据；环境、货架和机器人模型分别位于 `scripts/environment_geometry.py`、`scripts/shelf_geometry.py`、`scripts/robot_geometry.py`。
