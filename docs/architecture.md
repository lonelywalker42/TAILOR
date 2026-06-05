# TAILOR 架构设计文档

## 总体架构

TAILOR 采用分层架构设计，各层职责清晰，通过定义良好的接口通信。

```
┌─────────────────────────────────────────────────────┐
│                    UI Layer (PySide6)                │
│  MainWindow │ VehiclePanel │ LogPanel │ ConfigPanel  │
│  LogViewer  │ IdentWizard  │ PIDPanel │ ReportPanel  │
├─────────────────────────────────────────────────────┤
│                  Application Layer                   │
│  DataPipeline │ CoordinateManager │ SystemIdentifier │
│  PIDOptimizer │ ReportGenerator   │ ExcitationDetector│
├─────────────────────────────────────────────────────┤
│                    Core Layer                        │
│  Database │ Managers │ Config │ Models               │
├─────────────────────────────────────────────────────┤
│                 External Libraries                   │
│  pyulog │ SciPy │ python-control │ NumPy │ pandas    │
└─────────────────────────────────────────────────────┘
```

## 模块职责

### `core/` — 核心配置

- **config.py**: 应用级常量与配置
  - 数据库路径（跨平台 APPDATA 目录）
  - uORB 消息列表（25 种核心消息类型）
  - PX4 NavState 飞行模式分类器
  - 默认飞行器参数模板

### `data/` — 数据管理

- **models.py**: SQLAlchemy ORM 模型

  | 模型 | 说明 | 关键字段 |
  |------|------|----------|
  | Vehicle | 飞行器实体 | name, frame_type, params (JSON) |
  | FlightLog | 飞行日志 | file_path, file_hash, duration_s, metadata |
  | Configuration | 配置快照 | vehicle_id, params (JSON), is_template |
  | Tag | 标签 | name, color |
  | AnalysisResult | 辨识结果 | model_data (JSON), fit_percent, margins |
  | PIDTuning | 调参记录 | pid_params (JSON), before/after metrics |

  关系图：
  ```
  Vehicle 1──N FlightLog
  Vehicle 1──N Configuration
  FlightLog N──N Tag (via log_tags)
  FlightLog 1──N AnalysisResult
  FlightLog 1──N PIDTuning
  ```

- **database.py**: 数据库生命周期管理
  - SQLite + WAL 模式（提升并发读性能）
  - `session_scope()` 上下文管理器自动提交/回滚
  - 外键约束启用

- **manager.py**: 数据访问层（Repository 模式）
  - `VehicleManager`: CRUD、按名称查询
  - `FlightLogManager`: 批量导入（SHA-256 去重）、搜索、标签操作、过滤
  - `ConfigurationManager`: CRUD、模板管理、复制为模板

### `parser/` — 日志解析

- **ulog_parser.py**: PX4 uLog 解析器
  - 基于 pyulog 的 .ulg 文件解析
  - 提取元数据（固件版本、机架类型、时长等）
  - 按 uORB 消息类型提取为 pandas DataFrame
  - 飞行模式段检测（基于 vehicle_status.nav_state）
  - 传感器/姿态/位置/执行器数据分类提取

- **coordinate.py**: 坐标系变换引擎
  - `CoordinateTransformer`: 基础向量变换
    - FRD ↔ NED（四元数旋转）
    - NED ↔ ENU（轴交换）
    - AoA/侧滑角计算
  - `TailSitterCoordinateManager`: 尾座式专用
    - 模式敏感变换（multirotor/fixedwing/transition）
    - 推力垂向视图（hover 时 body-z 映射为世界垂向）
    - 基于空速的过渡段混合因子

### `ui/` — 用户界面

- **main_window.py**: 主窗口
  - 菜单栏（文件/视图/工具/帮助）
  - 工具栏
  - 标签页容器（日志/分析/辨识/调参/报告）
  - 可停靠面板（飞行器列表、配置编辑器）

- **vehicle_panel.py**: 飞行器管理
  - 列表视图 + 搜索过滤
  - 创建/编辑/删除对话框
  - 选择信号发射（通知日志面板和配置面板）

- **log_panel.py**: 日志管理
  - 表格视图（10 列：ID/文件名/飞行器/时长/固件/机架/模式/标签/时间/备注）
  - 后台线程导入（QThread）
  - 进度条显示
  - 飞行模式过滤
  - "分析选中日志"按钮（选中日志后点击进入分析视图）
  - 右键菜单（分析日志/查看详情/添加标签/关联飞行器/删除）
  - 双击条目也可直接进入分析

- **config_panel.py**: 配置编辑器
  - 参数分组标签页（物理参数/动力系统/传感器偏移/备注）
  - 配置选择器（当前参数/已保存配置切换）
  - 保存/另存为模板/JSON 导入导出

- **log_viewer.py**: 日志分析查看器
  - pyqtgraph 时序绘图，支持三种绘图模式（重叠/分开/按类别）
  - 通道选择器：树形结构、搜索框、预设分组（含执行器输出预设）、展开/折叠
  - 飞行模式色标指示条：带时间轴、光标位置、点击导航
  - 统计面板：实时跟随光标的通道数值显示
  - 13 种自动派生通道：姿态角/角速度/速度/位置（含设定值）、执行器控制量、电机/舵面/PWM 输出、滤波角速度
  - 自动绘图 6 组子图：角速度、姿态角、速度、位置、执行器控制、执行器输出（电机+舵面+PWM）
  - 响应分析：指令/响应通道选择，等效阶跃响应分析
    - 时域指标：上升时间、超调量、调节时间、稳态误差、RMSE
    - 振荡特性：振荡次数、阻尼比（对数衰减法）、振荡频率
    - 频域指标：带宽、相位裕度、谐振峰值、直流增益
  - 两行垂直工具栏布局，避免控件重叠

- **ident_panel.py**: 系统辨识面板
  - 向导式流程：数据选择 → 激励检测 → 预处理 → 辨识 → 结果
  - 自动匹配 setpoint/status 通道对（12 种标准对：角速度/姿态/速度/位置 × roll/pitch/yaw）
  - 按类别和轴筛选通道对，支持手动指定

## 数据流

### 日志导入流程

```
用户选择 .ulg 文件
  │
  ▼
LogImportWorker (QThread)
  ├── extract_metadata_quick() → 提取元数据
  ├── FlightLogManager.import_ulg()
  │     ├── SHA-256 哈希 → 去重检查
  │     ├── 创建 FlightLog 记录
  │     └── 关联 vehicle_id
  └── progress/finished 信号 → UI 更新
```

### 坐标变换流程

```
原始 uLog 数据 (FRD body frame)
  │
  ▼
CoordinateManager
  ├── 读取 vehicle_attitude (四元数)
  ├── 读取 vehicle_status.nav_state → 模式分类
  │
  ├── multirotor 模式:
  │     FRD → NED → 推力垂向视图 (z-up)
  │
  ├── fixedwing 模式:
  │     保持 FRD
  │
  └── transition 模式:
        FRD → (1-α) × 推力垂向 + α × FRD
        α = f(airspeed)
  │
  ▼
输出 DataFrame (选定坐标系)
```

## 关键设计决策

### 1. JSON 参数存储

飞行器参数和辨识结果使用 JSON 字段存储，而非宽表。原因：
- 不同机架类型参数差异大，宽表会产生大量 NULL
- 新增参数无需数据库迁移
- 配置模板可以是任意结构

### 2. SHA-256 文件去重

导入时计算文件哈希，相同内容的文件只创建一条记录。避免：
- 用户重复导入同一文件
- 不同目录下的副本产生冗余记录

### 3. 后台线程处理

所有 I/O 密集和计算密集操作在 QThread 中执行：
- 日志导入（文件读取 + 哈希计算）
- 日志解析（Phase 2）
- 系统辨识（Phase 3）
- PID 优化（Phase 4）

通过信号槽机制与主线程通信，避免 UI 冻结。

### 4. 尾座式坐标系策略

尾座式飞行器在不同飞行阶段使用不同的坐标视图：
- **悬停**: 推力垂向视图，使推力/垂向速度分析符合直觉
- **巡航**: 标准 FRD，与固定翼分析一致
- **过渡**: 基于空速的线性混合，避免姿态突变

## 扩展点

### 新增辨识算法

在 `dynamics/` 中实现 `SystemIdentifier` 子类，注册到算法工厂。

### 新增控制结构

在 `control/` 中实现 `ControllerModel` 子类，定义传递函数结构和参数映射。

### 新增坐标系

在 `coordinate.py` 中添加 `CoordFrame` 枚举值和对应的变换矩阵。

### 新增导出格式

在 `DataPipeline` 中添加格式化器，支持 CSV/MAT/Parquet/自定义格式。
