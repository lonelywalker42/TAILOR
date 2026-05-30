# TAILOR - PX4 Flight Log Analysis & PID Tuning Platform

## Project Overview
TAILOR (Tail-sitter Analysis, Identification, Log & Optimization Resource) is a desktop application for analyzing PX4 flight logs, performing system identification, and optimizing PID controllers — with special focus on tail-sitter / VTOL vehicles.

## Tech Stack
- **Language**: Python 3.11+
- **GUI**: PySide6 (Qt for Python)
- **Plotting**: pyqtgraph + OpenGL 3D
- **Log parsing**: pyulog
- **Numerics**: NumPy, SciPy, pandas
- **Control/ID**: python-control, SIPPY
- **Database**: SQLite + SQLAlchemy
- **Reports**: Jinja2 + WeasyPrint

## Project Structure
```
tailor/
  __init__.py          # Version, app name
  main.py              # Entry point
  core/
    config.py          # App configuration, constants, uORB message list
  data/
    models.py          # SQLAlchemy ORM models
    database.py        # DB session management
    manager.py         # Vehicle, FlightLog, Config managers (CRUD)
  parser/
    ulog_parser.py     # .ulg parser wrapping pyulog
    coordinate.py      # Coordinate frame transforms (FRD/NED/ENU/Wind/ThrustVert)
    data_pipeline.py   # Channel selection, time windowing, resampling, coord transform
    export.py          # Data export: CSV, MAT, Parquet with metadata headers
  dynamics/
    excitation.py      # Auto-detect excitation segments (step, doublet, sweep)
    identifier.py      # ARX, OE, frequency-domain identification, auto order selection
    validation.py      # Model validation, step/freq metrics, model comparison
  control/             # (Phase 4) PID optimization
  ui/
    main_window.py     # Main application window
    vehicle_panel.py   # Vehicle list sidebar
    log_panel.py       # Flight log table
    config_panel.py    # Configuration editor
    log_viewer.py      # pyqtgraph time series viewer, mode indicator, channel selector
    ident_panel.py     # System identification wizard (data select → preprocess → identify → results)
tests/
  test_models.py       # ORM and manager tests
  test_parser.py       # Parser and coordinate transform tests
  test_database.py     # Database lifecycle tests
  test_pipeline.py     # Data pipeline and export tests
  test_dynamics.py     # Excitation detection, identification, validation tests
```

## Development Milestones
- **M1 (Wk 6)**: Project skeleton, DB models, vehicle/log/config CRUD, basic UI **[DONE]**
- **M2 (Wk 12)**: Full .ulg parsing, coordinate system engine, log viewer **[DONE]**
- **M3 (Wk 20)**: System identification and dynamic analysis **[DONE]**
- **M4 (Wk 28)**: PID optimization and report generation
- **M5 (Wk 34)**: Testing, packaging, release

## Key Design Decisions
- SQLite with WAL mode for local-first data storage
- SQLAlchemy ORM for all data (vehicles, logs, configs, results, tuning history)
- Background threads (QThread) for heavy operations (import, parsing, optimization)
- Mode-aware coordinate transforms for tail-sitter: thrust-vertical view in hover, FRD in cruise
- Data pipeline: channel selection → time window → coord transform → resample → filter
- JSON-serialized parameter storage for flexibility across different vehicle types

## Running
```bash
# Install dependencies
pip install -e ".[dev]"

# Run the app
python -m tailor.main

# Run tests
pytest tests/ -v
```

## Tail-sitter Coordinate System
The coordinate manager handles mode-specific transforms:
- **Multirotor hover**: Thrust-vertical view (body z rotated to world up)
- **Fixed-wing cruise**: Standard FRD (Front-Right-Down)
- **Transition**: Linear interpolation between views, or dual-view with labels
