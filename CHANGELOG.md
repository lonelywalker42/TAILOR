# Changelog

All notable changes to TAILOR will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-05-31

### Added

#### Data Management
- Vehicle management with CRUD operations
- Flight log import with SHA-256 deduplication
- Batch import support for multiple .ulg files
- SQLite database with WAL mode for local-first storage
- SQLAlchemy ORM models for vehicles, logs, configs, tags, analysis results, and PID tuning history

#### Log Parsing
- PX4 .ulg file parsing via pyulog
- 24 uORB message types supported
- Tail-sitter coordinate system engine:
  - FRD body frame
  - NED/ENU world frames
  - Thrust-vertical mode-sensitive view
  - Airspeed-based blend factor for transitions
- Data pipeline: channel selection, time windowing, coordinate transform, resampling, detrend, lowpass filter
- Data export: CSV (with metadata headers), MATLAB .mat, Apache Parquet

#### System Identification
- ARX model identification (least squares)
- Output-Error (OE) model identification (Nelder-Mead optimization)
- Frequency-domain identification (ETFE + Sanathanan-Koerner fitting)
- Automatic model order selection via BIC criterion
- Model validation: VAF fit%, step response metrics, frequency response metrics, residual analysis
- Excitation detection: step, doublet, sweep, high-variance segments

#### PID Optimization
- PX4-compatible PID controller model (PI+FF, PID+FF, P, P+FF structures)
- Multi-objective gain optimization (SLSQP + differential evolution)
- Classical tuning rules: Ziegler-Nichols, SIMC (Skogestad IMC)
- Constraint-based search with stability, margins, and actuator limits
- PX4 parameter export (.params format)

#### Visualization & Reports
- PySide6 desktop GUI with 5 main tabs:
  - Flight log table with search and filtering
  - Log viewer with pyqtgraph time series plots, mode indicator, channel selector
  - System identification wizard (data select, preprocess, identify, results)
  - PID tuning panel with gain editors, optimizer, step/Bode comparison
  - One-click HTML report generation
- Dockable panels for vehicle list and configuration editor
- HTML report generation with embedded charts (Jinja2 + matplotlib)
- PDF export via WeasyPrint

#### Testing & CI
- 130 unit tests across 8 test files
- Integration tests covering full pipeline: data -> identification -> PID tuning -> report
- GUI smoke tests for all widget panels
- GitHub Actions CI workflow (lint + test on Ubuntu/Windows, Python 3.11/3.12)
- PyInstaller packaging configuration

### Known Limitations
- PDF export requires WeasyPrint (optional dependency)
- No real-time log streaming
- Transition mode detection is heuristic-based
