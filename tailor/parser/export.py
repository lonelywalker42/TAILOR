"""Data export: CSV, MAT, Parquet with metadata headers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from tailor.parser.data_pipeline import PipelineResult


class DataExporter:
    """Export pipeline results to various file formats."""

    def export_csv(
        self,
        result: PipelineResult,
        file_path: Path,
        include_header: bool = True,
        separator: str = ",",
    ) -> Path:
        """Export to CSV with optional metadata header.

        Args:
            result: Pipeline result to export.
            file_path: Output file path.
            include_header: If True, prepend metadata as comments.
            separator: Column separator.

        Returns:
            Path to the exported file.
        """
        file_path = Path(file_path)
        df = result.data.copy()

        # Reset index to make timestamp a column
        df = df.reset_index()
        if "index" in df.columns:
            df = df.rename(columns={"index": "timestamp_s"})

        with open(file_path, "w", encoding="utf-8") as f:
            if include_header:
                f.write(f"# TAILOR Data Export\n")
                f.write(f"# Channels: {result.metadata.get('n_channels', 0)}\n")
                f.write(f"# Samples: {result.metadata.get('n_samples', 0)}\n")
                f.write(f"# Time: {result.metadata.get('t_start', 0):.3f}s - {result.metadata.get('t_end', 0):.3f}s\n")
                f.write(f"# Frame: {result.metadata.get('target_frame', 'frd')}\n")
                if result.metadata.get("resample_rate"):
                    f.write(f"# Resample: {result.metadata['resample_rate']} Hz\n")
                f.write(f"#\n")
                # Channel info
                for spec in result.channel_specs:
                    f.write(f"# Channel: {spec.display_name} | {spec.message}.{spec.field}")
                    if spec.unit:
                        f.write(f" | {spec.unit}")
                    f.write(f" | {spec.category}\n")
                f.write(f"#\n")

            df.to_csv(f, sep=separator, index=False, lineterminator="\n")

        return file_path

    def export_mat(
        self,
        result: PipelineResult,
        file_path: Path,
    ) -> Path:
        """Export to MATLAB .mat file.

        Args:
            result: Pipeline result to export.
            file_path: Output .mat file path.

        Returns:
            Path to the exported file.
        """
        from scipy.io import savemat

        file_path = Path(file_path)
        df = result.data.copy()

        mat_dict = {
            "timestamp_s": df.index.values if isinstance(df.index, pd.RangeIndex) is False else np.arange(len(df)) / 100.0,
        }

        # Add each channel as a separate variable
        for col in df.columns:
            # Sanitize column name for MATLAB (no spaces, special chars)
            var_name = col.replace(" ", "_").replace("-", "_").replace(".", "_")
            mat_dict[var_name] = df[col].values

        # Add metadata as a struct
        mat_dict["metadata"] = {
            "n_channels": result.metadata.get("n_channels", 0),
            "n_samples": result.metadata.get("n_samples", 0),
            "target_frame": result.metadata.get("target_frame", "frd"),
            "channel_names": [s.display_name for s in result.channel_specs],
            "channel_units": [s.unit for s in result.channel_specs],
        }

        savemat(str(file_path), mat_dict, do_compression=True)
        return file_path

    def export_parquet(
        self,
        result: PipelineResult,
        file_path: Path,
    ) -> Path:
        """Export to Apache Parquet format.

        Args:
            result: Pipeline result to export.
            file_path: Output .parquet file path.

        Returns:
            Path to the exported file.
        """
        file_path = Path(file_path)
        df = result.data.copy()

        # Reset index to make timestamp a column
        df = df.reset_index()
        if "index" in df.columns:
            df = df.rename(columns={"index": "timestamp_s"})

        # Store metadata in pandas metadata
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pandas(df)

        # Add custom metadata
        existing_meta = table.schema.metadata or {}
        custom_meta = {
            b"tailor_version": b"0.1.0",
            b"tailor_n_channels": str(result.metadata.get("n_channels", 0)).encode(),
            b"tailor_target_frame": result.metadata.get("target_frame", "frd").encode(),
            b"tailor_channel_info": json.dumps([
                {"name": s.display_name, "message": s.message, "field": s.field, "unit": s.unit}
                for s in result.channel_specs
            ]).encode(),
        }
        merged_meta = {**existing_meta, **custom_meta}
        table = table.replace_schema_metadata(merged_meta)

        pq.write_table(table, str(file_path), compression="snappy")
        return file_path

    def export(
        self,
        result: PipelineResult,
        file_path: Path,
        format: Optional[str] = None,
    ) -> Path:
        """Auto-detect format from extension and export.

        Args:
            result: Pipeline result.
            file_path: Output path (extension determines format).
            format: Override format ("csv", "mat", "parquet"). If None, use extension.

        Returns:
            Path to the exported file.
        """
        file_path = Path(file_path)

        if format is None:
            ext = file_path.suffix.lower()
            format_map = {".csv": "csv", ".mat": "mat", ".parquet": "parquet"}
            format = format_map.get(ext, "csv")

        if format == "mat":
            return self.export_mat(result, file_path)
        elif format == "parquet":
            return self.export_parquet(result, file_path)
        else:
            return self.export_csv(result, file_path)
