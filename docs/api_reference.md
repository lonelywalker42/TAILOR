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

## tailor.parser.data_pipeline

数据管线 — 通道选择、时间窗口、坐标变换、重采样、滤波。

### ChannelSpec

```python
@dataclass
class ChannelSpec:
    message: str           # uORB 消息名，如 "vehicle_attitude"
    field: str             # 字段名，如 "q[0]"
    display_name: str      # 显示名，如 "Attitude Qw"
    unit: str = ""         # 物理单位
    category: str = ""     # "state", "control", "derived"
    coord_frame: str = CoordFrame.FRD
```

### PipelineConfig

```python
@dataclass
class PipelineConfig:
    channels: list[ChannelSpec]
    t_start: Optional[float]          # 时间窗口起点 (秒)
    t_end: Optional[float]            # 时间窗口终点 (秒)
    target_frame: CoordFrame          # 目标坐标系
    resample_rate: Optional[float]    # 重采样频率 (Hz)
    resample_method: ResampleMethod   # 插值方法
    flight_phase: Optional[str]       # "multirotor", "fixedwing", "transition"
    apply_lowpass: bool               # 是否低通滤波
    lowpass_cutoff: Optional[float]   # 截止频率 (Hz)
    detrend: bool                     # 是否去趋势
```

### DataPipeline

```python
class DataPipeline:
    def run(raw_data, config, attitude_quat=None, flight_mode_segments=None) -> PipelineResult
```

### PipelineResult

```python
@dataclass
class PipelineResult:
    data: pd.DataFrame               # 对齐后的数据 (列=通道显示名)
    metadata: dict                   # 管线配置摘要
    channel_specs: list[ChannelSpec]
```

---

## tailor.parser.export

数据导出 — CSV、MAT、Parquet。

```python
class DataExporter:
    def export_csv(result: PipelineResult, file_path, include_header=True, separator=",") -> Path
    def export_mat(result: PipelineResult, file_path) -> Path
    def export_parquet(result: PipelineResult, file_path) -> Path
```

---

## tailor.dynamics.excitation

激励段自动检测。

### ExcitationSegment

```python
@dataclass
class ExcitationSegment:
    t_start: float
    t_end: float
    duration: float
    excitation_type: ExcitationType   # STEP, DOUBLET, SWEEP, HIGH_VARIANCE
    channel: str
    quality_score: float              # 0-1
    amplitude: float
```

### ExcitationDetector

```python
class ExcitationDetector:
    def detect(time, signal, channel_name="") -> list[ExcitationSegment]
    def _detect_steps(time, signal) -> list[ExcitationSegment]
    def _detect_doublets(time, signal) -> list[ExcitationSegment]
    def _detect_high_variance(time, signal) -> list[ExcitationSegment]
    def _detect_sweeps(time, signal) -> list[ExcitationSegment]
```

### 便捷函数

```python
find_identification_segments(time, signals, min_duration=0.5) -> list[ExcitationSegment]
```

---

## tailor.dynamics.identifier

系统辨识 — ARX、OE、频域方法。

### TransferFunctionModel

```python
@dataclass
class TransferFunctionModel:
    num: np.ndarray              # 分子系数
    den: np.ndarray              # 分母系数
    dt: float                    # 采样时间
    method: IdentificationMethod # ARX, OE, FREQUENCY_DOMAIN
    fit_percent: float           # VAF 拟合率
    aic: float                   # AIC 准则
    bic: float                   # BIC 准则
    order_num: int               # 分子阶次
    order_den: int               # 分母阶次
    input_channel: str
    output_channel: str

    def simulate(u) -> np.ndarray
    def get_poles() -> np.ndarray
    def get_zeros() -> np.ndarray
    def is_stable() -> bool
    def to_dict() -> dict
    def from_dict(d) -> TransferFunctionModel
```

### SystemIdentifier

```python
class SystemIdentifier:
    def identify_arx(u, y, na=2, nb=2, nk=0, dt=0.01, ...) -> TransferFunctionModel
    def identify_oe(u, y, nf=2, nb=2, nk=0, dt=0.01, ...) -> TransferFunctionModel
    def identify_frequency(u, y, order=4, dt=0.01, ...) -> TransferFunctionModel
    def auto_select_order(u, y, max_order=10, dt=0.01, method=IdentificationMethod.ARX) -> tuple[int, TransferFunctionModel]
```

---

## tailor.dynamics.validation

模型验证与性能指标。

### StepResponseMetrics

```python
@dataclass
class StepResponseMetrics:
    rise_time_s: float
    settling_time_s: float
    overshoot_pct: float
    dc_gain: float
    peak_value: float
    peak_time_s: float
```

### FrequencyMetrics

```python
@dataclass
class FrequencyMetrics:
    bandwidth_hz: float
    gain_margin_db: float
    phase_margin_deg: float
    dc_gain_db: float
    resonance_peak_db: float
    resonance_freq_hz: float
```

### ModelValidator

```python
class ModelValidator:
    @staticmethod
    def step_response_metrics(model, t_duration=10.0) -> StepResponseMetrics
    def frequency_metrics(model) -> FrequencyMetrics
    def residual_analysis(model, u, y) -> dict
    def compare_models(models, ranking="bic") -> ModelComparison
```

### 便捷函数

```python
compute_step_response_data(model, t_duration) -> (time, response)
compute_frequency_response_data(model) -> (freq_hz, mag_db, phase_deg)
compute_bode_comparison(models, labels) -> dict
```

---

## tailor.control.pid_controller

PX4 标准 PID 控制器模型。

### PIDGains

```python
@dataclass
class PIDGains:
    kp: float = 0.0
    ki: float = 0.0
    kd: float = 0.0
    kff: float = 0.0
```

### PIDStructure

```python
class PIDStructure(Enum):
    P = "p"
    P_FF = "p_ff"
    PI_FF = "pi_ff"
    PID_FF = "pid_ff"
```

### ControllerParams

```python
@dataclass
class ControllerParams:
    axes: dict[str, AxisConfig]

    def to_px4_params() -> dict[str, float]
    def from_px4_params(params) -> ControllerParams
```

### PIDController

```python
class PIDController:
    def __init__(self, structure=PIDStructure.PI_FF)
    def _controller_tf(gains) -> tuple[np.ndarray, np.ndarray]
    def get_open_loop_tf(gains, plant_tf) -> tuple
    def get_closed_loop_tf(gains, plant_tf) -> tuple
    def simulate_closed_loop(gains, plant_tf, ref, dt) -> (time, output, control)
    def evaluate_performance(gains, plant_tf, dt) -> dict
```

### 便捷函数

```python
default_rate_gains(axis: ControlAxis) -> AxisConfig
extract_px4_params(px4_params, axis) -> PIDGains
```

---

## tailor.control.optimizer

多目标 PID 优化。

### TuningObjective

```python
@dataclass
class TuningObjective:
    target_bandwidth_hz: float = 5.0
    min_phase_margin_deg: float = 35.0
    max_overshoot_pct: float = 15.0
    max_settling_time_s: float = 0.5
    max_control_effort: float = 1.0
    weight_bandwidth: float = 1.0
    weight_margin: float = 1.0
    weight_overshoot: float = 1.0
    weight_settling: float = 0.5
```

### PIDOptimizer

```python
class PIDOptimizer:
    def optimize(plant_tf, initial_gains, objective, axis, structure, dt, method) -> TuningResult
    def optimize_all_axes(plant_tfs, initial_params, objective, dt, method) -> dict[str, TuningResult]
```

### TuningMethod

```python
class TuningMethod(Enum):
    ZIEGLER_NICHOLS = "ziegler_nichols"
    SIMC = "simc"
    OPTIMIZER = "optimizer"
    MANUAL = "manual"
```

### 便捷函数

```python
quick_tune(plant_tf, method, axis, dt) -> TuningResult
```

---

## tailor.control.report

HTML/PDF 报告生成。

### ReportGenerator

```python
class ReportGenerator:
    def __init__(self, version="0.1.0")
    def generate_html(title, flight_info, key_metrics, charts, identification_results,
                      pid_comparison, pid_performance, recommendations, output_path) -> str
    def generate_pdf(html_content, output_path) -> Path
    def figure_to_base64(fig) -> str
    def plot_time_series(time, signals, title, xlabel, ylabel) -> str
    def plot_comparison(time_before, y_before, time_after, y_after, title, ...) -> str
    def plot_bode(freq_hz, mag_db, phase_deg, title, label) -> str
```

### 便捷函数

```python
build_flight_report(log_metadata, channels, time, identification_results,
                    tuning_result, output_path) -> str
```

---

## tailor.ui.log_viewer

时序数据查看器与响应分析工具。

```python
class LogViewerWidget(QWidget):
    def load_data(raw_data, available_messages, message_fields, flight_mode_segments)
    def clear()
```

### 自动派生通道

`load_data` 调用时自动计算以下处理通道：

| 派生消息名 | 来源 | 字段 | 说明 |
|-----------|------|------|------|
| `derived_attitude_deg` | `vehicle_attitude` 四元数 | `roll_deg`, `pitch_deg`, `yaw_deg` | 姿态角（度） |
| `derived_angular_rate_setpoint` | `vehicle_rates_setpoint` | `roll_rate_sp`, `pitch_rate_sp`, `yaw_rate_sp` | 角速度设定值 |
| `derived_gyro_rad_s` | `sensor_gyro` | `gyro_x`, `gyro_y`, `gyro_z` | 陀螺仪原始数据 |
| `derived_velocity_m_s` | `vehicle_local_position` | `vx`, `vy`, `vz` | 速度（m/s） |
| `derived_position_m` | `vehicle_local_position` | `x`, `y`, `z` | 位置（m） |

派生通道自动选中并绘图，叠加飞行模式色块。

### 绘图模式

| 模式 | 说明 |
|------|------|
| 重叠绘图 | 所有选中通道绘制在同一坐标轴 |
| 分开绘图 | 每个通道独占一个子图，共享时间轴 |
| 按类别绘图 | 同一消息类型的通道合并为一组子图 |

### 响应分析

选择指令（setpoint）和响应（state）通道进行等效阶跃响应分析：

**时域指标**（`_compute_step_metrics`）：
- 自动检测 setpoint 阶跃跳变位置
- 上升时间：10%-90% 阈值穿越
- 超调量：峰值偏差 / 阶跃幅度
- 调节时间：最后超出 ±2% 带的时间
- 稳态误差：末段平均误差
- RMSE：均方根误差

**振荡特性**：
- 振荡次数：误差信号过零点计数
- 阻尼比：对数衰减法从峰值包络估计
- 振荡频率：过零点间隔的平均周期

**频域指标**（`_compute_freq_metrics`）：
- 带宽（-3dB 点）
- 相位裕度
- 谐振峰值与频率
- 直流增益

### 包含组件
- `StatisticsPanel`: 实时跟随光标的通道数值统计
- `ModeIndicatorBar`: 飞行模式色标指示条（多旋翼=蓝、固定翼=绿、过渡=橙），带时间轴和光标位置
- `ChannelSelector`: 通道选择器（树形结构，搜索框，预设分组，展开/折叠按钮，类型和单位列）

---

## tailor.ui.ident_panel

系统辨识面板（向导式界面）。

```python
class IdentPanel(QWidget):
    def load_data(flat_data: dict[str, np.ndarray], time: np.ndarray = None)
    def auto_setup_pairs(flat_data: dict[str, np.ndarray], time: np.ndarray = None)
    def clear()
```

流程：数据选择 → 激励检测 → 预处理 → 模型配置 → 执行辨识 → 结果展示

### 自动通道匹配

`auto_setup_pairs` 根据 PX4 uORB 消息命名规则自动匹配 12 种标准通道对：

| 类别 | 轴 | 指令通道 | 响应通道 |
|------|-----|---------|---------|
| angular_rate | roll | `vehicle_rates_setpoint.roll_rate_sp` | `sensor_gyro.gyro_x` |
| angular_rate | pitch | `vehicle_rates_setpoint.pitch_rate_sp` | `sensor_gyro.gyro_y` |
| angular_rate | yaw | `vehicle_rates_setpoint.yaw_rate_sp` | `sensor_gyro.gyro_z` |
| attitude | roll | `vehicle_attitude_setpoint.roll_body` | `derived_attitude_deg.roll_deg` |
| attitude | pitch | `vehicle_attitude_setpoint.pitch_body` | `derived_attitude_deg.pitch_deg` |
| attitude | yaw | `vehicle_attitude_setpoint.yaw_body` | `derived_attitude_deg.yaw_deg` |
| velocity | x | `vehicle_local_position_setpoint.vx` | `derived_velocity_m_s.vx` |
| velocity | y | `vehicle_local_position_setpoint.vy` | `derived_velocity_m_s.vy` |
| velocity | z | `vehicle_local_position_setpoint.vz` | `derived_velocity_m_s.vz` |
| position | x | `vehicle_local_position_setpoint.x` | `derived_position_m.x` |
| position | y | `vehicle_local_position_setpoint.y` | `derived_position_m.y` |
| position | z | `vehicle_local_position_setpoint.z` | `derived_position_m.z` |

未匹配成功的通道对由用户通过类别/轴下拉框手动指定。

---

## tailor.ui.pid_panel

PID 调参面板。

```python
class PIDPanel(QWidget):
    def load_plant_model(model: TransferFunctionModel)
    def clear()
```

功能：增益编辑、优化目标设置、调参方法选择、阶跃响应/伯德图对比、PX4 参数导出
