# TAILOR

**Tail-sitter Analysis, Identification, Log & Optimization Resource**

PX4 尾座式飞行器日志分析与 PID 调参平台

---

## 简介

TAILOR 是一款面向 PX4 尾座式（Tail-sitter）/ 垂直起降固定翼（VTOL）飞行器的专业日志分析与控制优化桌面平台。它从飞行数据管理出发，覆盖 uLog 解析、坐标系变换、系统辨识、PID 自动调参到报告生成的完整闭环。

### 核心能力

| 模块 | 功能 |
|------|------|
| 飞行数据管理 | 多源 .ulg 批量导入、飞机配置档案、标签与版本管理、多维检索 |
| uLog 解析 | 全面 uORB 消息解析（传感器/姿态/位置/执行器/状态） |
| 坐标系引擎 | FRD/NED/ENU/Wind 变换，尾座式模式敏感视图（悬停推力垂向、巡航 FRD、过渡段混合） |
| 系统辨识 | 激励检测、ARX/OE/子空间/频域辨识、模型验证与动态性能量化 |
| PID 调参 | 基于模型的多目标优化、Ziegler-Nichols/SIMC 整定、增益调度、PX4 参数导出 |
| 可视化与报告 | 多通道时序图、3D 轨迹回放、一键 HTML/PDF 技术报告 |

## 安装

### 环境要求

- Python 3.11+
- 操作系统：Windows / Linux / macOS

### 安装步骤

```bash
# 克隆仓库
git clone <repo-url>
cd TAILOR--px4logger

# 创建虚拟环境（推荐）
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 安装（开发模式）
pip install -e ".[dev]"

# 安装 PDF 报告支持（可选）
pip install -e ".[pdf]"
```

### 依赖说明

| 依赖 | 用途 |
|------|------|
| PySide6 | GUI 框架 |
| pyqtgraph | 高性能时序绘图 |
| pyulog | PX4 .ulg 日志解析 |
| NumPy / SciPy / pandas | 数值计算、信号处理、数据对齐 |
| SQLAlchemy | ORM 数据持久化 |
| python-control / SIPPY | 控制系统分析 / 系统辨识 |
| Jinja2 | 报告模板渲染 |

## 快速开始

### 启动应用

```bash
python -m tailor.main
```

### 基本工作流

1. **添加飞行器**：点击左侧"添加"按钮，输入飞行器名称和机架类型
2. **导入日志**：点击"导入日志"选择 .ulg 文件（支持批量导入）
3. **配置参数**：在底部面板编辑飞行器物理参数（质量、惯量、电机系数等）
4. **分析日志**：切换到"日志分析"标签页查看时序数据（Phase 2）
5. **系统辨识**：选择数据段进行模型辨识（Phase 3）
6. **PID 调参**：基于辨识模型优化控制器参数（Phase 4）

### 运行测试

```bash
pytest tests/ -v
```

## 项目结构

```
TAILOR--px4logger/
├── pyproject.toml              # 项目配置与依赖
├── CLAUDE.md                   # 开发者文档（AI 辅助开发上下文）
├── README.md                   # 本文件
├── docs/                       # 详细文档
│   ├── architecture.md         # 架构设计
│   ├── coordinate_systems.md   # 坐标系详解
│   └── api_reference.md        # 模块 API 参考
├── tailor/                     # 源码
│   ├── __init__.py
│   ├── main.py                 # 入口点
│   ├── core/                   # 核心配置
│   │   └── config.py
│   ├── data/                   # 数据管理
│   │   ├── models.py           # ORM 模型
│   │   ├── database.py         # 数据库会话
│   │   └── manager.py          # 数据管理器
│   ├── parser/                 # 日志解析
│   │   ├── ulog_parser.py      # uLog 解析器
│   │   └── coordinate.py       # 坐标变换
│   ├── dynamics/               # 系统辨识（Phase 3）
│   ├── control/                # PID 优化（Phase 4）
│   └── ui/                     # 用户界面
│       ├── main_window.py
│       ├── vehicle_panel.py
│       ├── log_panel.py
│       └── config_panel.py
└── tests/                      # 测试套件
    ├── test_models.py
    ├── test_parser.py
    └── test_database.py
```

## 开发里程碑

| 里程碑 | 周期 | 内容 | 状态 |
|--------|------|------|------|
| M1 | 第 6 周 | 项目骨架、数据库模型、基础 UI | **已完成** |
| M2 | 第 12 周 | 完整日志解析、坐标系引擎 | 进行中 |
| M3 | 第 20 周 | 系统辨识与动态分析 | 计划中 |
| M4 | 第 28 周 | PID 优化与报告系统 | 计划中 |
| M5 | 第 34 周 | 测试、打包、发布 | 计划中 |

## 许可证

MIT License
