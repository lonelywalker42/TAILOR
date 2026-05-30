"""Report generator — HTML/PDF technical reports with charts and analysis.

Uses Jinja2 templates to render flight analysis reports including:
- Flight metadata and statistics
- Key channel plots (embedded as base64 PNG)
- System identification results
- PID tuning comparison
"""

from __future__ import annotations

import base64
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

# Jinja2 for templating
try:
    from jinja2 import Template, Environment, BaseLoader
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False

# Matplotlib for chart export (headless)
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{{ title }} — TAILOR 分析报告</title>
<style>
body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; color: #333; }
h1 { color: #1a5276; border-bottom: 3px solid #2980b9; padding-bottom: 10px; }
h2 { color: #2980b9; border-bottom: 1px solid #bdc3c7; padding-bottom: 6px; margin-top: 30px; }
h3 { color: #555; }
table { border-collapse: collapse; width: 100%; margin: 15px 0; }
th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
th { background-color: #2980b9; color: white; }
tr:nth-child(even) { background-color: #f9f9f9; }
.metric-box { display: inline-block; background: #eaf2f8; border-left: 4px solid #2980b9; padding: 10px 15px; margin: 5px 10px 5px 0; min-width: 150px; }
.metric-value { font-size: 24px; font-weight: bold; color: #1a5276; }
.metric-label { font-size: 12px; color: #666; }
.chart { text-align: center; margin: 20px 0; }
.chart img { max-width: 100%; border: 1px solid #ddd; border-radius: 4px; }
.footer { margin-top: 40px; padding-top: 10px; border-top: 1px solid #ddd; color: #999; font-size: 12px; }
.warning { background: #fef9e7; border-left: 4px solid #f39c12; padding: 10px 15px; margin: 10px 0; }
.good { color: #27ae60; font-weight: bold; }
.bad { color: #e74c3c; font-weight: bold; }
</style>
</head>
<body>

<h1>{{ title }}</h1>
<p><strong>生成时间:</strong> {{ generated_at }} &nbsp;|&nbsp; <strong>TAILOR</strong> v{{ version }}</p>

<h2>1. 飞行信息</h2>
<table>
<tr><th>项目</th><th>值</th></tr>
{% for key, value in flight_info.items() %}
<tr><td>{{ key }}</td><td>{{ value }}</td></tr>
{% endfor %}
</table>

{% if key_metrics %}
<h2>2. 关键指标</h2>
<div>
{% for m in key_metrics %}
<div class="metric-box">
<div class="metric-value">{{ m.value }}</div>
<div class="metric-label">{{ m.label }}</div>
</div>
{% endfor %}
</div>
{% endif %}

{% if charts %}
<h2>3. 数据图表</h2>
{% for chart in charts %}
<div class="chart">
<h3>{{ chart.title }}</h3>
<img src="data:image/png;base64,{{ chart.image }}" alt="{{ chart.title }}">
{% if chart.description %}<p>{{ chart.description }}</p>{% endif %}
</div>
{% endfor %}
{% endif %}

{% if identification_results %}
<h2>4. 系统辨识结果</h2>
<table>
<tr><th>通道</th><th>方法</th><th>阶次</th><th>拟合%</th><th>带宽(Hz)</th><th>相位裕度</th><th>超调%</th></tr>
{% for r in identification_results %}
<tr>
<td>{{ r.channel }}</td>
<td>{{ r.method }}</td>
<td>{{ r.order }}</td>
<td>{{ r.fit_percent }}%</td>
<td>{{ r.bandwidth_hz }}</td>
<td>{{ r.phase_margin_deg }}°</td>
<td>{{ r.overshoot_pct }}%</td>
</tr>
{% endfor %}
</table>
{% endif %}

{% if pid_comparison %}
<h2>5. PID 调参对比</h2>
<table>
<tr><th>参数</th><th>原始值</th><th>优化值</th><th>变化</th></tr>
{% for row in pid_comparison %}
<tr>
<td>{{ row.param }}</td>
<td>{{ row.original }}</td>
<td>{{ row.optimized }}</td>
<td class="{{ 'good' if row.improvement else '' }}">{{ row.change }}</td>
</tr>
{% endfor %}
</table>

{% if pid_performance %}
<h3>性能对比</h3>
<table>
<tr><th>指标</th><th>优化前</th><th>优化后</th></tr>
{% for p in pid_performance %}
<tr>
<td>{{ p.metric }}</td>
<td>{{ p.before }}</td>
<td class="{{ 'good' if p.improvement else 'bad' }}">{{ p.after }}</td>
</tr>
{% endfor %}
</table>
{% endif %}
{% endif %}

{% if recommendations %}
<h2>6. 建议</h2>
<ul>
{% for rec in recommendations %}
<li>{{ rec }}</li>
{% endfor %}
</ul>
{% endif %}

<div class="footer">
<p>由 TAILOR (Tail-sitter Analysis, Identification, Log & Optimization Resource) 自动生成</p>
</div>
</body>
</html>"""


class ReportGenerator:
    """Generate analysis reports from flight data and identification results."""

    def __init__(self, version: str = "0.1.0"):
        self.version = version

    def generate_html(
        self,
        title: str = "飞行分析报告",
        flight_info: Optional[dict] = None,
        key_metrics: Optional[list[dict]] = None,
        charts: Optional[list[dict]] = None,
        identification_results: Optional[list[dict]] = None,
        pid_comparison: Optional[list[dict]] = None,
        pid_performance: Optional[list[dict]] = None,
        recommendations: Optional[list[str]] = None,
        output_path: Optional[Path] = None,
    ) -> str:
        """Generate HTML report.

        Args:
            title: Report title.
            flight_info: Dict of flight metadata.
            key_metrics: List of {label, value} dicts.
            charts: List of {title, image (base64), description} dicts.
            identification_results: List of ID result dicts.
            pid_comparison: PID before/after comparison.
            pid_performance: Performance before/after.
            recommendations: List of recommendation strings.
            output_path: If provided, write HTML to this file.

        Returns:
            HTML string.
        """
        if not HAS_JINJA2:
            raise ImportError("jinja2 required: pip install Jinja2")

        template = Template(HTML_TEMPLATE)
        html = template.render(
            title=title,
            version=self.version,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            flight_info=flight_info or {},
            key_metrics=key_metrics or [],
            charts=charts or [],
            identification_results=identification_results or [],
            pid_comparison=pid_comparison or [],
            pid_performance=pid_performance or [],
            recommendations=recommendations or [],
        )

        if output_path:
            output_path = Path(output_path)
            output_path.write_text(html, encoding="utf-8")

        return html

    def generate_pdf(
        self,
        html_content: str,
        output_path: Path,
    ) -> Path:
        """Convert HTML to PDF using WeasyPrint.

        Args:
            html_content: HTML string.
            output_path: Output PDF path.

        Returns:
            Path to the generated PDF.
        """
        try:
            from weasyprint import HTML
        except ImportError:
            raise ImportError("WeasyPrint required for PDF: pip install WeasyPrint")

        output_path = Path(output_path)
        HTML(string=html_content).write_pdf(str(output_path))
        return output_path

    @staticmethod
    def figure_to_base64(fig) -> str:
        """Convert a matplotlib figure to base64 PNG string.

        Args:
            fig: matplotlib Figure object.

        Returns:
            Base64-encoded PNG string.
        """
        if not HAS_MATPLOTLIB:
            return ""

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")

    @staticmethod
    def plot_time_series(
        time: np.ndarray,
        signals: dict[str, np.ndarray],
        title: str = "Time Series",
        xlabel: str = "Time (s)",
        ylabel: str = "Value",
    ) -> str:
        """Create a time series plot and return as base64 PNG."""
        if not HAS_MATPLOTLIB:
            return ""

        fig, ax = plt.subplots(figsize=(10, 4))
        for name, data in signals.items():
            ax.plot(time[:len(data)], data, label=name, linewidth=1)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        b64 = ReportGenerator.figure_to_base64(fig)
        plt.close(fig)
        return b64

    @staticmethod
    def plot_comparison(
        time_before: np.ndarray,
        y_before: np.ndarray,
        time_after: np.ndarray,
        y_after: np.ndarray,
        title: str = "Before / After Comparison",
        label_before: str = "Before",
        label_after: str = "After",
    ) -> str:
        """Create a before/after comparison plot."""
        if not HAS_MATPLOTLIB:
            return ""

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(time_before, y_before, label=label_before, linewidth=1.5, alpha=0.7)
        ax.plot(time_after, y_after, label=label_after, linewidth=1.5, alpha=0.7)
        ax.set_xlabel("Time (s)")
        ax.set_title(title)
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        b64 = ReportGenerator.figure_to_base64(fig)
        plt.close(fig)
        return b64

    @staticmethod
    def plot_bode(
        freq_hz: np.ndarray,
        mag_db: np.ndarray,
        phase_deg: np.ndarray,
        title: str = "Bode Plot",
        label: str = "",
    ) -> str:
        """Create a Bode plot (magnitude + phase)."""
        if not HAS_MATPLOTLIB:
            return ""

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

        ax1.semilogx(freq_hz, mag_db, label=label, linewidth=1.5)
        ax1.set_ylabel("Magnitude (dB)")
        ax1.set_title(title)
        ax1.grid(True, alpha=0.3, which="both")
        if label:
            ax1.legend()

        ax2.semilogx(freq_hz, phase_deg, label=label, linewidth=1.5)
        ax2.set_ylabel("Phase (deg)")
        ax2.set_xlabel("Frequency (Hz)")
        ax2.grid(True, alpha=0.3, which="both")

        fig.tight_layout()
        b64 = ReportGenerator.figure_to_base64(fig)
        plt.close(fig)
        return b64


def build_flight_report(
    log_metadata: dict,
    channels: Optional[dict[str, np.ndarray]] = None,
    time: Optional[np.ndarray] = None,
    identification_results: Optional[list] = None,
    tuning_result=None,
    output_path: Optional[Path] = None,
) -> str:
    """Convenience function to build a complete flight analysis report.

    Args:
        log_metadata: Dict from UlogParser.get_metadata().
        channels: Dict of channel_name -> data array.
        time: Time array.
        identification_results: List of TransferFunctionModel.
        tuning_result: TuningResult from PIDOptimizer.
        output_path: If provided, write HTML to this file.

    Returns:
        HTML string.
    """
    gen = ReportGenerator()

    # Flight info
    flight_info = {
        "文件": log_metadata.get("file_name", ""),
        "固件版本": log_metadata.get("firmware_version", ""),
        "机架类型": log_metadata.get("airframe_type", ""),
        "飞行时长": f"{log_metadata.get('duration_s', 0):.1f} 秒",
        "消息数量": str(log_metadata.get("message_count", 0)),
        "丢包率": f"{log_metadata.get('drop_rate', 0) * 100:.2f}%",
    }

    # Key metrics
    key_metrics = []
    if log_metadata.get("duration_s"):
        key_metrics.append({"label": "飞行时长", "value": f"{log_metadata['duration_s']:.1f}s"})

    # Charts
    charts = []
    if channels and time is not None:
        # Plot up to 3 channel groups
        plotted = 0
        for name, data in list(channels.items())[:6]:
            if plotted >= 3:
                break
            b64 = gen.plot_time_series(time[:len(data)], {name: data}, title=name)
            if b64:
                charts.append({"title": name, "image": b64, "description": ""})
                plotted += 1

    # Identification results
    id_results = []
    if identification_results:
        for model in identification_results:
            from tailor.dynamics.validation import ModelValidator
            fm = ModelValidator.frequency_metrics(model)
            id_results.append({
                "channel": f"{model.input_channel} → {model.output_channel}",
                "method": model.method.value,
                "order": f"{model.order_den},{model.order_num}",
                "fit_percent": f"{model.fit_percent:.1f}",
                "bandwidth_hz": f"{fm.bandwidth_hz:.2f}",
                "phase_margin_deg": f"{fm.phase_margin_deg:.1f}",
                "overshoot_pct": "—",
            })

    # PID comparison
    pid_comp = []
    pid_perf = []
    if tuning_result:
        orig = tuning_result.original_gains
        opt = tuning_result.optimized_gains
        for param in ["kp", "ki", "kd", "kff"]:
            ov = getattr(orig, param)
            nv = getattr(opt, param)
            change = nv - ov
            pid_comp.append({
                "param": param.upper(),
                "original": f"{ov:.4f}",
                "optimized": f"{nv:.4f}",
                "change": f"{change:+.4f}",
                "improvement": abs(change) > 1e-6,
            })
        pid_perf = [
            {"metric": "带宽 (Hz)", "before": f"{tuning_result.before_bandwidth_hz:.2f}",
             "after": f"{tuning_result.after_bandwidth_hz:.2f}",
             "improvement": tuning_result.after_bandwidth_hz > tuning_result.before_bandwidth_hz},
            {"metric": "相位裕度 (°)", "before": f"{tuning_result.before_phase_margin_deg:.1f}",
             "after": f"{tuning_result.after_phase_margin_deg:.1f}",
             "improvement": tuning_result.after_phase_margin_deg > tuning_result.before_phase_margin_deg},
            {"metric": "超调 (%)", "before": f"{tuning_result.before_overshoot_pct:.1f}",
             "after": f"{tuning_result.after_overshoot_pct:.1f}",
             "improvement": tuning_result.after_overshoot_pct < tuning_result.before_overshoot_pct},
        ]

    # Recommendations
    recs = []
    if tuning_result:
        if tuning_result.after_phase_margin_deg < 35:
            recs.append("相位裕度偏低，建议降低增益或增加微分时间常数")
        if tuning_result.after_overshoot_pct > 20:
            recs.append("超调量较大，建议增加微分增益或降低比例增益")
        if tuning_result.after_bandwidth_hz < 1.0:
            recs.append("带宽较低，响应可能偏慢，可适当增加比例增益")

    return gen.generate_html(
        title="飞行分析报告",
        flight_info=flight_info,
        key_metrics=key_metrics,
        charts=charts,
        identification_results=id_results,
        pid_comparison=pid_comp,
        pid_performance=pid_perf,
        recommendations=recs,
        output_path=output_path,
    )
