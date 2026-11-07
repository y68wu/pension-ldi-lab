import numpy as np
import pandas as pd
import pytest

from pension_ldi.market import FX_TICKER, TICKERS, YIELD_COLUMNS, align_market, load_curve


def fixture_panel():
    dates = pd.to_datetime(["2025-01-30", "2025-01-31", "2025-02-28", "2025-03-31", "2025-04-10"])
    quotes = pd.DataFrame(100.0, index=dates, columns=TICKERS)
    quotes[FX_TICKER] = [1.25, 1.25, 1.5, 1.5, 1.5]
    quotes.loc[dates[2], "XIU.TO"] = 110
    quotes.loc[dates[2], "VFV.TO"] = 120
    quotes.loc[dates[2], "IGF"] = 110
    quotes.loc[dates[2], "PSP"] = 110
    curve = pd.DataFrame(0.03, index=dates, columns=YIELD_COLUMNS)
    return quotes, curve


def test_monthly_alignment_cad_translation_and_rebalanced_proxy_returns():
    quotes, curve = fixture_panel()
    panel = align_market(quotes, curve, "2025-04-10")
    assert panel.index.tolist() == pd.to_datetime(
        ["2025-01-31", "2025-02-28", "2025-03-31"]
    ).tolist()
    np.testing.assert_allclose(panel["public_equity"], [100, 115, 115 * (1 / 1.1 + 1 / 1.2) / 2])
    np.testing.assert_allclose(panel["private_equity"], [100, 132, 120])
    np.testing.assert_allclose(panel["real_assets"], [100, 116, 116 * (1 + 1 / 1.1) / 2])


def test_alignment_rejects_missing_month_to_avoid_multimonth_shocks():
    quotes, curve = fixture_panel()
    with pytest.raises(ValueError, match="consecutive month"):
        align_market(quotes, curve.drop(pd.Timestamp("2025-02-28")), "2025-04-10")


def test_curve_csv_loads_one_observation_in_tenor_order(tmp_path):
    _, curve = fixture_panel()
    curve.iloc[0] = np.arange(len(YIELD_COLUMNS)) * 0.001
    path = tmp_path / "curve.csv"
    curve.iloc[[0], ::-1].rename_axis("date").to_csv(path)
    np.testing.assert_allclose(load_curve(path), curve.iloc[0])
