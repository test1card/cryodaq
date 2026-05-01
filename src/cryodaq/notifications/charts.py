"""Chart rendering for Telegram notifications.

Renders operator-facing charts as PNG bytes for Telegram sendPhoto.
Uses matplotlib non-interactive backend (Agg) — safe in headless engine.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


def render_temperature_chart(
    temps: dict[str, float | None],
    *,
    title: str = "Температуры",
) -> bytes | None:
    """Render a horizontal bar chart of temperature readings.

    Args:
        temps: mapping display_name → value_K (None values shown as missing).
        title: chart title.

    Returns:
        PNG bytes, or None if rendering fails or no data available.
    """
    valid = {k: v for k, v in temps.items() if v is not None}
    if not valid:
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415

        labels = list(valid.keys())
        values = [valid[k] for k in labels]

        fig, ax = plt.subplots(figsize=(8, max(3, len(labels) * 0.5 + 1)))
        bars = ax.barh(labels, values, color="#4C72B0", edgecolor="white")

        ax.set_xlabel("K", fontsize=11)
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.bar_label(bars, fmt="%.2f K", padding=4, fontsize=10)
        ax.margins(x=0.15)
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception as exc:
        logger.warning("render_temperature_chart failed: %s", exc)
        return None
