"""`chart.html` — history plus three labelled scenario paths.

**No volatility band.** `annualised_vol` travels in the forecast JSON for Phase 2's
Monte Carlo, and it is not drawn here. Shading a cone around three point paths
would render a distribution nobody has computed, and a reader would take the
picture as the claim. Three point estimates are three point estimates; the chart
says so in as many words.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from mapf.core.models import Forecast, PriceWindow, Scenario

_COLOURS = {"bullish": "#2e7d32", "base_case": "#1565c0", "bearish": "#c62828"}
_LABELS = {"bullish": "Bullish", "base_case": "Base case", "bearish": "Bearish"}

DISCLAIMER = (
    "Scenario paths, not a forecast distribution. Each line is a single point estimate "
    "interpolated from spot; the shaded cone you might expect is deliberately absent "
    "because no distribution has been computed. Volatility is carried in forecast.json "
    "for Phase 2 and is not drawn here."
)


def _path_dates(start: date, horizon_days: int) -> list[date]:
    """Calendar days as a stand-in for trading days.

    Phase 1 draws a shape, not a schedule. A real trading calendar matters for
    scoring and belongs with the evaluation harness, not with a picture.
    """
    return [start + timedelta(days=offset) for offset in range(horizon_days + 1)]


def _path_prices(spot: float, scenario: Scenario, horizon_days: int) -> list[float]:
    # `horizon_days >= 1` is validated on Forecast, so no zero guard is needed here.
    end = spot * (1.0 + scenario.price_modifier_pct / 100.0)
    growth = (end / spot) ** (1.0 / horizon_days)
    return [spot * growth**step for step in range(horizon_days + 1)]


def build_figure(window: PriceWindow, forecast: Forecast) -> Any:
    import plotly.graph_objects as go

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=[bar.date for bar in window.bars],
            y=[bar.close for bar in window.bars],
            mode="lines",
            name=f"{forecast.ticker} close ({window.adjustment})",
            line={"color": "#37474f", "width": 1.5},
        )
    )

    start = window.last_trading_date
    days = _path_dates(start, forecast.horizon_days)
    for name in ("bullish", "base_case", "bearish"):
        scenario: Scenario = getattr(forecast.scenarios, name)
        figure.add_trace(
            go.Scatter(
                x=days,
                y=_path_prices(forecast.spot_price, scenario, forecast.horizon_days),
                mode="lines",
                name=(
                    f"{_LABELS[name]} — p={scenario.probability_weight:.2f}, "
                    f"{scenario.price_modifier_pct:+.1f}%"
                ),
                line={"color": _COLOURS[name], "width": 2, "dash": "dot"},
            )
        )

    figure.update_layout(
        title=(
            f"{forecast.ticker} — {forecast.horizon_days} trading-day scenarios "
            f"(as of {start.isoformat()})"
        ),
        xaxis_title="Date",
        yaxis_title=f"Price ({window.adjustment})",
        template="plotly_white",
        annotations=[
            {
                "text": DISCLAIMER,
                "xref": "paper",
                "yref": "paper",
                "x": 0,
                "y": -0.22,
                "showarrow": False,
                "align": "left",
                "font": {"size": 10, "color": "#616161"},
            }
        ],
        margin={"b": 130},
    )
    return figure


def write_chart(window: PriceWindow, forecast: Forecast, path: Path) -> Path:
    """Write a single self-contained HTML file — no server, no CDN."""
    path.parent.mkdir(parents=True, exist_ok=True)
    figure = build_figure(window, forecast)
    figure.write_html(str(path), include_plotlyjs="inline", full_html=True)
    return path
