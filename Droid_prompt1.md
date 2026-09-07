Blender 安装与环境验收
主要工作
安装并锁定 Blender LTS 版本。
默认候选为 Blender 4.5 LTS；版本确定后全项目保持一致。Blender LTS
优先使用官方便携版或固定安装包，避免系统自动升级改变 Python API。
检查操作系统、GPU、显存、驱动和磁盘空间。
验证 Eevee 和 Cycles；GPU 不可用时保留 CPU 渲染回退。
验证 Blender 内置 Python、bpy、NumPy及项目脚本依赖。
确定 Panda URDF 的导入方式；若第三方 URDF 插件不稳定，则编写受控的资产转换/导入脚本。
验证无界面批量运行：
blender --background test_scene.blend --python smoke_test.py
Blender 官方支持通过 --background 进行无界面渲染，适合后续服务器批处理。命令行渲染文档
冒烟测试
环境验收时创建一个最小场景，完成：
导入一个简单机器人或测试 mesh；
创建指定内参和外参的相机；
设置一帧机器人关节状态；
输出固定分辨率的 RGB；
输出深度图；
输出实例分割或对象索引；
在无图形界面模式下重复运行；
检查输出路径、帧编号和文件格式。
交付物
environment/
├── README.md
├── blender_version.txt
├── environment_manifest.json
├── install_blender.md
├── smoke_test.py
├── test_scene.blend
└── smoke_test_output/
    ├── rgb/
    ├── depth/
    └── instance_mask/
environment_manifest.json 至少记录：
{
  "blender_version": "待P-1冻结",
  "render_engine": "BLENDER_EEVEE_NEXT",
  "platform": "linux",
  "gpu_backend": "待检测",
  "python_version": "待检测",
  "panda_asset_version": "待冻结",
  "headless_render_verified": true
}
阶段验收
满足以下条件后才能进入正式数据处理：
blender --version 与锁定版本一致；
GUI和无界面模式均能启动；
Python脚本可以创建场景、设置相机并控制物体；
Panda资产能够正确导入；
能成功渲染 RGB、深度和实例分割；
输出尺寸、坐标方向和文件命名正确；
GPU渲染可用，或已确认CPU回退方案；
同一测试场景重复运行没有明显结果漂移。

DROID 参数提取与逐帧仿真重建实施计划
版本：2026-09-06
一、项目目标
从 DROID episode 中提取 CodeEngine 所需的机器人与场景状态，并在 Blender 中进行状态驱动的逐帧回放，最终生成与真实 RGB 对齐的代理仿真数据，包括：
机器人轨迹与夹爪状态；
机器人三维关键点及相机投影；
刚体物体的几何代理和逐帧估计位姿；
仿真 RGB、深度、实例分割；
真实图像与仿真图像的逐帧配对关系。
首期目标是验证数据提取与视觉回放流程，不声称恢复真实接触力或动力学。
二、首期范围
首期先完成1条完整样例，再根据实际成本决定批量扩展。
样例选择要求：
单臂 Franka Panda 操作；
简单刚体拿取或放置任务；
外部相机在 episode 内保持固定；
目标物体清晰、遮挡较少；
具有 raw trajectory.h5、高清 RGB 和匹配标定；
优先选择补充 cam2base 标定覆盖的 episode；
第二外部相机可用于物体重建和交叉验证。
首期暂不处理：
laptop、抽屉等关节物体；
软体和透明、强反光物体；
多物体复杂交互；
自由交互动力学验证；
实时生成和视觉模型训练。
三、统一数据约定
世界坐标系：Franka 机器人基座坐标系。
长度：米；夹爪开口额外导出毫米。
角度：弧度。
四元数输出：显式采用 wxyz。
DROID/SciPy 内部四元数为 xyzw 时必须重排。
DROID Cartesian 姿态后三维按 xyz 欧拉角解析，再转换为旋转向量。
T_base_from_cam 表示 camera → base。
T_cam_from_base 表示 base → camera，用于投影。
不以零值代替缺失数据；使用 null、valid=false 和原因字段。
插值状态、视觉估计和遮挡补偿必须标记来源。
四个既定字段固定为：
{
  "robot_state": [],
  "contacts": [],
  "logical_action": "",
  "logical_state": []
}
四、输出文件约定
1. planned_trajectory.jsonl
保留既定文件名，但在 metadata.json 中注明它主要包含观测状态和记录到的控制器动作，不代表重新规划的轨迹。
每行包含：
frame
timestamp
source_step
source_frames
ee_position_m_world_xyz
ee_axis_angle_rad
joint_positions_rad
gripper_joint_positions
gripper_separation_mm
raw_controller_action
四个固定空字段
raw_controller_action 必须保留实际来源、动作空间、单位和归一化方式；无法取得时置为 null，不得由状态反推后冒充原始动作。
2. robot_keypoints.jsonl
robot.embodiment 固定为经 CodeEngine 冻结的 Franka 枚举，例如 franka_panda。
keypoint_source 为 fk。
使用固定 Panda URDF 版本、关节名称、顺序和关键点定义。
每个二维投影必须绑定 camera_id。
多相机建议采用 projections 数组。
visible 不能仅由投影落入画面判断。
confidence 必须注明来源和含义。
3. object_trajectory.jsonl
每个物体至少包含：
稳定唯一的 instance_id
category
geometry_id
motion_mode
position_m
quaternion_wxyz
visible
confidence
estimate_source
valid
首期所有物体位姿均标记为视觉重建估计，不表述为 DROID 真值。
五、执行阶段
阶段
时间
工作与交付
P0 数据审计与样例选择
检查实际 HDF5/RLDS 字段、相机序列号、标定、视频、时间戳；建立候选表并选定主样例
P1 Schema 与机器人状态导出
冻结 JSONL schema；转换末端姿态、关节、夹爪和动作；生成 metadata.json、frame_index.jsonl、planned_trajectory.jsonl
P2 机器人与相机对齐
导入固定版本的 Panda/夹爪资产；按观测关节 FK 回放；完成相机坐标转换和多帧投影质检
P3 场景与物体代理建模
根据多视角建立桌面、目标物体和必要环境代理；冻结物体局部坐标系和资产版本
P4 物体逐帧轨迹重建
完成分割、跟踪、位姿拟合、静止约束和抓取阶段短时夹爪约束；生成 object_trajectory.jsonl
P5 渲染与配对
按统一索引渲染 RGB、深度和实例 mask；生成 pairs.jsonl、quality.jsonl 和对比视频
P6 主样例验收
汇总误差、失败帧、人工成本和可扩展性，决定后续批量规模
六、关键验收标准
所有 JSON/JSONL 可解析，字段类型和维度正确。
每个输出帧均能追溯至机器人 step 和各相机原视频帧。
不存在系统性时间偏移；抓取和释放误差初始目标不超过1个输出帧。
可见机器人关键点的平均投影误差初始目标不超过图像对角线的1%，同时报告 P95。
主样例人工标注约20个关键帧，用于独立评估物体轮廓。
物体静止区间无明显漂移，抓取附近无明显跳变和穿插。
实测、确定性换算、视觉估计、插值和遮挡补偿可以明确区分。
被剔除帧仍保留索引和剔除原因。
同一 episode 的相邻帧不得拆分到训练集和测试集。
物体 IoU ≥0.85 仅作为主样例的初始建议，必须基于人工标注 mask，并在主样例完成后重新冻结。
七、单条 episode 交付结构
episode_<id>/
├── metadata.json
├── frame_index.jsonl
├── planned_trajectory.jsonl
├── robot_keypoints.jsonl
├── object_trajectory.jsonl
├── camera.jsonl
├── pairs.jsonl
├── quality.jsonl
├── scene.blend
├── build_scene.py
├── scene_config.json
├── assets/
├── real_rgb/
├── sim_rgb/
├── sim_depth/
├── sim_instance_mask/
└── comparison.mp4
八、开工前必须确认
DROID 数据位置、版本和可下载范围；
主样例 episode ID；
raw、RLDS、高清视频、SVO和补充标定的实际可用情况；
“逐帧”指观测时刻还是原视频所有帧；
主相机、辅助相机和目标分辨率；
object_trajectory.jsonl 最终 schema；
CodeEngine 是否必须直接读取这些 JSONL；
Franka URDF、夹爪最大宽度、末端参考 frame 和 embodiment 枚举；
xy_normalized 的具体归一化公式。