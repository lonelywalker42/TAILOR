# 模块 API 参考

## tailor.core.config

应用级配置与常量。

### 常量

| 常量 | 类型 | 说明 |
|------|------|------|
| `APP_DATA_DIR` | Path | 应用数据目录（跨平台） |
| `DB_PATH` | Path | SQLite 数据库文件路径 |
| `DATABASE_URL` | str | SQLAlchemy 数据库连接 URL |
| `CORE_UORB_MESSAGES` | list[str] | 需解析的 24 种 uORB 消息名 |
| `DEFAULT_VEHICLE_PARAMS` | dict | 默认飞行器参数模板 |

### NavState

PX4 导航状态分类器。

```python
NavState.classify(nav_state: int) -> str
# 返回: "multirotor" | "fixedwing" | "transition" | "unknown"

NavState.MULTIROTOR_STATES   # {0, 1, 2, 4, 17, 18}
NavState.FIXEDWING_STATES    # {3, 5, 8, 9}
NavState.VTOL_STATES         # {24}
```

---

## tailor.data.models

SQLAlchemy ORM 模型定义。

### Vehicle

飞行器实体。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int (PK) | 自增主键 |
| name | str (unique) | 飞行器名称 |
| frame_type | str | 机架类型 (quad_x, tiltrotor, tailsitter...) |
| firmware_version | str | 固件版本 |
| num_motors | int | 电机数量 |
| num_servos | int | 舵机数量 |
| params | JSON | 物理参数 (质量/惯量/电机系数等) |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

关系：`logs` → FlightLog[], `configurations` → Configuration[]

### FlightLog

飞行日志记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int (PK) | 自增主键 |
| vehicle_id | int (FK) | 关联飞行器 |
| file_path | str | 文件绝对路径 |
| file_name | str | 文件名 |
| file_size | int | 文件大小 (bytes) |
| file_hash | str | SHA-256 哈希 |
| firmware_version | str | 固件版本 |
| airframe_type | str | 机架类型 |
| duration_s | float | 飞行时长 (秒) |
| start_time | datetime | 起飞时间 |
| flight_mode_label | str | 飞行模式标签 |
| fault_label | str | 故障标签 |
| title | str | 用户标题 |
| notes | str | 用户备注 |

关系：`vehicle` → Vehicle, `tags` → Tag[], `analysis_results` → AnalysisResult[], `pid_tunings` → PIDTuning[]

### Configuration

配置快照/模板。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int (PK) | 自增主键 |
| vehicle_id | int (FK) | 关联飞行器 |
| name | str | 配置名称 |
| is_template | bool | 是否为模板 |
| params | JSON | 参数快照 |

### AnalysisResult

系统辨识结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int (PK) | 自增主键 |
| log_id | int (FK) | 关联日志 |
| result_type | str | 结果类型 (transfer_function, step_response...) |
| flight_phase | str | 飞行阶段 (multirotor, fixedwing, transition) |
| input_channel | str | 输入通道 |
| output_channel | str | 输出通道 |
| model_data | JSON | 模型数据 (传递函数系数等) |
| fit_percent | float | 拟合率 (VAF) |
| bandwidth_hz | float | 带宽 (Hz) |
| phase_margin_deg | float | 相位裕度 (°) |
| gain_margin_db | float | 增益裕度 (dB) |
| overshoot_pct | float | 超调量 (%) |

### PIDTuning

PID 调参记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int (PK) | 自增主键 |
| log_id | int (FK) | 关联日志 |
| iteration | int | 迭代编号 |
| pid_params | JSON | PID 参数集 |
| method | str | 调参方法 (manual, ziegler_nichols, simc, optimizer) |
| before_* / after_* | float | 调参前后性能指标 |

---

## tailor.data.database

数据库会话管理。

### Database

```python
class Database:
    def __init__(self, database_url: str = DATABASE_URL)
    def create_tables(self)           # 创建所有表
    def drop_tables(self)             # 删除所有表
    def session_scope() -> Session    # 上下文管理器，自动提交/回滚
    def get_session() -> Session      # 获取新会话（需手动关闭）
```

### 便捷函数

```python
get_database() -> Database           # 获取默认数据库单例
init_database(url) -> Database       # 用自定义 URL 初始化（测试用）
```

---

## tailor.data.manager

数据访问层。

### VehicleManager

```python
class VehicleManager:
    def __init__(self, session: Session)
    def create(name, frame_type, **kwargs) -> Vehicle
    def get(vehicle_id: int) -> Vehicle | None
    def get_by_name(name: str) -> Vehicle | None
    def list_all() -> list[Vehicle]
    def update(vehicle, **kwargs) -> Vehicle
    def delete(vehicle_id: int) -> bool
```

### FlightLogManager

```python
class FlightLogManager:
    def __init__(self, session: Session)

    @staticmethod
    def compute_file_hash(file_path: Path) -> str   # SHA-256

    def import_ulg(file_path, vehicle_id=None, metadata=None) -> FlightLog
    def import_batch(file_paths, vehicle_id=None) -> tuple[list[FlightLog], list[tuple[Path, str]]]

    def get(log_id: int) -> FlightLog | None
    def list_all(vehicle_id=None, tag_name=None, flight_mode=None, limit=500) -> list[FlightLog]
    def search(query: str) -> list[FlightLog]

    def update(log, **kwargs) -> FlightLog
    def delete(log_id: int) -> bool

    def add_tag(log_id, tag_name, color="#4A90D9") -> Tag
    def remove_tag(log_id, tag_name) -> bool
```

### ConfigurationManager

```python
class ConfigurationManager:
    def __init__(self, session: Session)
    def create(vehicle_id, name, params, description="", is_template=False) -> Configuration
    def get(config_id: int) -> Configuration | None
    def list_for_vehicle(vehicle_id: int) -> list[Configuration]
    def list_templates() -> list[Configuration]
    def update(config, **kwargs) -> Configuration
    def delete(config_id: int) -> bool
    def duplicate_as_template(config_id, template_name) -> Configuration
```

---

## tailor.parser.ulog_parser

PX4 uLog 解析器。

### UlogParser

```python
class UlogParser:
    def __init__(self, file_path: Path)
    def open(self)                              # 打开并解析 .ulg
    def get_metadata(self) -> dict              # 提取元数据
    def get_available_messages(self) -> list[str]

    def get_message_data(message_name: str) -> DataFrame  # 单消息提取
    def get_core_data(self) -> dict[str, DataFrame]       # 所有核心消息

    def get_flight_mode_segments(self) -> list[dict]       # 飞行模式段
    def get_actuator_data(self) -> dict[str, DataFrame]    # 执行器数据
    def get_sensor_data(self) -> dict[str, DataFrame]      # 传感器数据
    def get_attitude_data(self) -> dict[str, DataFrame]    # 姿态数据
    def get_position_data(self) -> dict[str, DataFrame]    # 位置数据
    def get_parameter_changes(self) -> DataFrame           # 参数变更
```

### extract_metadata_quick

```python
def extract_metadata_quick(file_path: Path) -> dict
# 快速提取元数据（用于导入预览），不进行完整解析
```

---

## tailor.parser.coordinate

坐标系变换引擎。

### CoordinateTransformer

静态方法，提供基础向量变换。

```python
class CoordinateTransformer:
    @staticmethod
    def frd_to_ned(vec_frd, quat_frd_to_ned) -> ndarray
    def ned_to_frd(vec_ned, quat_frd_to_ned) -> ndarray
    def ned_to_enu(vec_ned) -> ndarray
    def enu_to_ned(vec_enu) -> ndarray
    def quat_to_euler_deg(quat) -> ndarray     # [roll, pitch, yaw] 度
    def quat_to_euler_rad(quat) -> ndarray     # [roll, pitch, yaw] 弧度
    def compute_aoa_sideslip(velocity_frd) -> tuple[float, float]
```

支持批量变换：输入 shape (N, 3) 输出 shape (N, 3)。

### TailSitterCoordinateManager

尾座式飞行器专用坐标管理。

```python
class TailSitterCoordinateManager:
    def transform_for_mode(
        vec_frd, quat_frd_to_ned, flight_mode,
        alpha_blend=0.0, target_frame=CoordFrame.THRUST_VERT
    ) -> ndarray

    def get_mode_blend_factor(
        airspeed, transition_airspeed_start=5.0, transition_airspeed_end=15.0
    ) -> float   # 0.0 (multirotor) → 1.0 (fixedwing)
```

### CoordFrame

```python
class CoordFrame(Enum):
    FRD = "frd"
    NED = "ned"
    ENU = "enu"
    WIND = "wind"
    THRUST_VERT = "thrust_vertical"
```

---

## 已规划模块（待实现）

### tailor.dynamics（Phase 3）

- `ExcitationDetector`: 激励信号自动检测
- `SystemIdentifier`: 线性系统辨识 (ARX, OE, 子空间, 频域)
- `DynamicPerformanceAnalyzer`: 时域/频域指标提取

### tailor.control（Phase 4）

- `PIDController`: PX4 标准 PID 结构建模
- `PIDOptimizer`: 多目标优化调参
- `GainScheduler`: 增益调度表管理

### tailor.ui.log_viewer（Phase 2）

- `LogViewerWidget`: pyqtgraph 时序绘图
- `ModeIndicatorBar`: 飞行模式色标指示条
- `ChannelSelector`: 通道选择器
