import pytest

from pension_ldi.liquidity import LiquidityTerms, RateStress, StressInputs, liquidity_stress


def test_liquidity_waterfall_and_margin_sign():
    terms = LiquidityTerms(300, 350, 100, 100, 4)
    repricing = RateStress(200, 0.80, 0.92, -0.20)
    stress = StressInputs()
    receive_fixed = liquidity_stress(terms, repricing, stress, 600)
    assert receive_fixed.resources == pytest.approx(120.22)
    assert receive_fixed.outflows == pytest.approx(144)
    assert receive_fixed.liquidity_buffer == pytest.approx(-23.78)
    assert receive_fixed.coverage == pytest.approx(120.22 / 144)
    pay_fixed = liquidity_stress(terms, repricing, stress, -600)
    assert pay_fixed.variation_margin == 0
    assert pay_fixed.resources == receive_fixed.resources
    assert pay_fixed.outflows == pytest.approx(24)


def test_no_outflows_has_no_coverage_ratio():
    zero = LiquidityTerms(300, 350, 100, 100, 0)
    result = liquidity_stress(zero, RateStress(0, 1, 1, 0), StressInputs(0, 0, 0), 0)
    assert result.coverage is None
    assert result.liquidity_buffer == result.resources


def test_wrong_shock_or_negative_resource_input_raises():
    with pytest.raises(ValueError, match="long_bonds_value"):
        LiquidityTerms(100, -30, 30, 10, 5)
    with pytest.raises(ValueError, match="match"):
        liquidity_stress(LiquidityTerms(300, 350, 100, 100, 4), RateStress(0, 1, 1, 0),
                         StressInputs(), 0)
