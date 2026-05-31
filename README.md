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
| uLog 解析 | 全面 uORB 消息解析（传感器/姿态/位置/执行器/状态），自动派生姿态角/角速度/速度/位置 |
| 坐标系引擎 | FRD/NED/ENU/Wind 变换，尾座式模式敏感视图（悬停推力垂向、巡航 FRD、过渡段混合） |
| 系统辨识 | 激励检测、ARX/OE/频域辨识、自动阶次选择、模型验证与动态性能量化 |
| PID 调参 | 基于模型的多目标优化、Ziegler-Nichols/SIMC 整定、PX4 参数导出 |
| 可视化与报告 | 多通道时序图、飞行模式指示、自动派生通道绘图、一键 HTML/PDF 技术报告 |

## 安装

### 环境要求

- Python 3.11+
- 操作系统：Windows / Linux / macOS

### 安装步骤

```bash
# 克隆仓库
git clone https://github.com/lonelywalker42/TAILOR.git
cd TAILOR

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
| python-control | 控制系统分析 |
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
4. **分析日志**：在飞行日志表格中选中日志，点击"分析选中日志"按钮（或双击条目）进入分析视图
   - 系统自动派生处理通道：姿态角、角速度、速度、位置
   - 派生通道自动绘图，叠加飞行模式色块（蓝=多旋翼、绿=固定翼、橙=过渡）
   - 可在左侧通道选择器中选择更多原始数据通道手动绘制
5. **系统辨识**：在"系统辨识"标签页选择数据通道、检测激励段、执行辨识
6. **PID 调参**：在"PID 调参"标签页基于辨识模型优化控制器参数，导出 PX4 参数
7. **生成报告**：在"报告"标签页一键生成 HTML 分析报告

### 运行测试

```bash
pytest tests/ -v
```

## 项目结构

```
TAILOR/
├── pyproject.toml              # 项目配置与依赖
├── CLAUDE.md                   # 开发者文档
├── README.md                   # 本文件
├── CHANGELOG.md                # 版本变更日志
├── tailor.spec                 # PyInstaller 打包配置
├── docs/                       # 详细文档
│   ├── architecture.md         # 架构设计
│   ├── coordinate_systems.md   # 坐标系详解
│   └── api_reference.md        # 模块 API 参考
├── scripts/
│   └── build.py                # 打包构建脚本
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI
├── tailor/                     # 源码
│   ├── __init__.py
│   ├── main.py                 # 入口点
│   ├── core/
│   │   └── config.py           # 应用配置、uORB 消息列表
│   ├── data/
│   │   ├── models.py           # SQLAlchemy ORM 模型
│   │   ├── database.py         # 数据库会话管理
│   │   └── manager.py          # 数据管理器 (CRUD)
│   ├── parser/
│   │   ├── ulog_parser.py      # .ulg 解析器
│   │   ├── coordinate.py       # 坐标系变换引擎
│   │   ├── data_pipeline.py    # 数据管线 (通道选择/重采样/滤波)
│   │   └── export.py           # 数据导出 (CSV/MAT/Parquet)
│   ├── dynamics/
│   │   ├── excitation.py       # 激励段自动检测
│   │   ├── identifier.py       # 系统辨识 (ARX/OE/频域)
│   │   └── validation.py       # 模型验证与性能指标
│   ├── control/
│   │   ├── pid_controller.py   # PID 控制器模型
│   │   ├── optimizer.py        # 多目标 PID 优化
│   │   └── report.py           # HTML/PDF 报告生成
│   └── ui/
│       ├── main_window.py      # 主窗口
│       ├── vehicle_panel.py    # 飞行器列表面板
│       ├── log_panel.py        # 飞行日志表格
│       ├── config_panel.py     # 配置编辑器
│       ├── log_viewer.py       # 时序数据查看器
│       ├── ident_panel.py      # 系统辨识面板
│       └── pid_panel.py        # PID 调参面板
└── tests/                      # 测试套件 (130 tests)
    ├── test_models.py
    ├── test_parser.py
    ├── test_database.py
    ├── test_pipeline.py
    ├── test_dynamics.py
    ├── test_control.py
    ├── test_integration.py     # 跨模块集成测试
    └── test_gui.py             # GUI 冒烟测试
```

## 开发里程碑

| 里程碑 | 周期 | 内容 | 状态 |
|--------|------|------|------|
| M1 | 第 6 周 | 项目骨架、数据库模型、基础 UI | **已完成** |
| M2 | 第 12 周 | 完整日志解析、坐标系引擎、数据管线 | **已完成** |
| M3 | 第 20 周 | 系统辨识与动态分析 | **已完成** |
| M4 | 第 28 周 | PID 优化与报告系统 | **已完成** |
| M5 | 第 34 周 | 测试、打包、发布 | **已完成** |

## 构建独立可执行文件

```bash
# 安装打包依赖
pip install -e ".[build]"

# 运行打包脚本
python scripts/build.py

# 输出位于 dist/TAILOR/ 目录
```

## 许可证

MIT License
