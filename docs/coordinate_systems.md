# 坐标系详解

## 概述

PX4 飞行日志中的数据使用多种坐标系表示。TAILOR 的坐标系引擎负责在这些坐标系之间进行变换，并为尾座式飞行器提供模式敏感的分析视图。

## 支持的坐标系

### 1. FRD — 机体坐标系 (Front-Right-Down)

PX4 默认的机体坐标系：

```
        x (前)
        ↑
        │
   ┌────┼────┐
   │    │    │
y ←────●────→ y (右)
   │    │    │
   └────┼────┘
        │
        ↓
        z (下)
```

- **x 轴**: 指向飞行器前方
- **y 轴**: 指向飞行器右方
- **z 轴**: 指向飞行器下方

PX4 的 `sensor_accel`、`sensor_gyro`、`actuator_outputs` 等消息均使用此坐标系。

### 2. NED — 世界坐标系 (North-East-Down)

PX4 的世界参考坐标系：

```
        N (北)
        ↑
        │
   ┌────┼────┐
   │    │    │
E ←────●────→ E (东)
   │    │    │
   └────┼────┘
        │
        ↓
        D (下)
```

- **N 轴**: 地理北方
- **E 轴**: 地理东方
- **D 轴**: 垂直向下

`vehicle_local_position`、`vehicle_global_position` 使用此坐标系。

### 3. ENU — 世界坐标系 (East-North-Up)

另一种常用的世界坐标系（ROS、MAVLink 等使用）：

- **E 轴**: 地理东方
- **N 轴**: 地理北方
- **U 轴**: 垂直向上

变换关系：`ENU = [NED.y, NED.x, -NED.z]`

### 4. Wind — 风轴坐标系

基于来流方向的坐标系，用于气动分析：

- **x 轴**: 沿来流方向（空速矢量方向）
- **z 轴**: 在对称面内垂直于 x 轴向下
- **y 轴**: 完成右手系

需要计算攻角 (α) 和侧滑角 (β)。

### 5. Thrust Vertical — 推力垂向坐标系

TAILOR 为尾座式飞行器定义的特殊视图坐标系。

## 尾座式飞行器的坐标系挑战

尾座式（Tail-sitter）飞行器在不同飞行阶段的姿态特征差异巨大：

```
  悬停阶段 (多旋翼)              巡航阶段 (固定翼)
       ↑ 推力                       ──→ 飞行方向
       │                           ╱
       ●                           ●───→
      ╱│╲                         ╱
     ╱ │ ╲                       ╱
    ╱  │  ╲                     ╱
       │
       ↓ 重力
```

### 问题

在标准 FRD 坐标系下分析悬停阶段的数据：
- 推力沿 body-z 方向（向下），与直觉相反
- 垂向速度在 body-z 分量，容易与前后运动混淆
- 阶跃响应分析时，"上升"对应负 z 值

### 解决方案：模式敏感坐标变换

#### 多旋翼悬停模式 → 推力垂向视图

```
变换步骤：
1. 将 body FRD 向量通过四元数旋转到 NED
2. 取反 z 轴：NED_z → -NED_z (使向上为正)

效果：
- 推力方向 = +z (符合直觉)
- 垂向速度正值 = 上升
- 水平面保持 North-East 方向
```

#### 固定翼巡航模式 → 保持 FRD

巡航阶段保持标准 FRD，与常规固定翼分析一致：
- 空速沿 +x
- 舵面偏转在 y-z 平面
- 滚转绕 x 轴

#### 过渡段 → 线性混合

过渡段使用空速驱动的混合因子 α：

```
α = (airspeed - V_start) / (V_end - V_start)

V_start = 5 m/s  (开始过渡)
V_end   = 15 m/s (完成过渡)

输出 = (1 - α) × 推力垂向视图 + α × FRD 视图
```

这避免了在过渡点坐标系的突变。

## API 使用示例

### 基础向量变换

```python
from tailor.parser.coordinate import CoordinateTransformer
import numpy as np

# FRD → NED (需要四元数)
q_identity = np.array([1.0, 0.0, 0.0, 0.0])  # [w, x, y, z]
vec_frd = np.array([1.0, 0.0, 0.0])  # 向前
vec_ned = CoordinateTransformer.frd_to_ned(vec_frd, q_identity)
# 结果: [1.0, 0.0, 0.0] (北向)

# NED → ENU
vec_enu = CoordinateTransformer.ned_to_enu(vec_ned)
# 结果: [0.0, 1.0, 0.0] (东向)
```

### 尾座式模式变换

```python
from tailor.parser.coordinate import TailSitterCoordinateManager, CoordFrame

mgr = TailSitterCoordinateManager()

# 悬停阶段，推力向下 (-z in FRD)
vec_frd = np.array([0.0, 0.0, -10.0])  # 10 m/s² 向下
q_hover = np.array([1.0, 0.0, 0.0, 0.0])

# 推力垂向视图
result = mgr.transform_for_mode(
    vec_frd, q_hover, "multirotor",
    target_frame=CoordFrame.THRUST_VERT,
)
# 结果: [0.0, 0.0, 10.0] (向上为正)
```

### AoA 与侧滑角计算

```python
# 纯前飞，无 AoA
v_frd = np.array([10.0, 0.0, 0.0])
alpha, beta = CoordinateTransformer.compute_aoa_sideslip(v_frd)
# alpha = 0, beta = 0

# 带迎角的飞行
v_frd = np.array([10.0, 0.0, -5.0])  # 前飞 + 微上仰
alpha, beta = CoordinateTransformer.compute_aoa_sideslip(v_frd)
# alpha > 0 (正迎角)
```

## PX4 四元数约定

PX4 使用 Hamilton 四元数，存储顺序为 `[w, x, y, z]`：

```python
# PX4 vehicle_attitude 消息中的字段:
# q[0] = w (实部)
# q[1] = x
# q[2] = y
# q[3] = z

# scipy 使用 [x, y, z, w] 顺序，需要重排
from tailor.parser.coordinate import quat_to_rotation
R = quat_to_rotation(np.array([w, x, y, z]))
```

## 飞行模式检测

通过 `vehicle_status.nav_state` 字段自动检测当前飞行模式：

| nav_state | 模式 | 分类 |
|-----------|------|------|
| 0 | Manual | multirotor |
| 1 | Altitude Control | multirotor |
| 2 | Position Control | multirotor |
| 3 | Mission | fixedwing |
| 4 | Loiter | multirotor |
| 5 | RTL | fixedwing |
| 10 | Acro | multirotor |
| 14 | Offboard | multirotor |
| 17 | Takeoff | multirotor |
| 18 | Land | multirotor |
| 24 | VTOL Takeoff | transition |
