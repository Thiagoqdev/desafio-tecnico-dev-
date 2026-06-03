'''Helpers that interpret the `ipca_plus_capped` mode (EC 136/2025, S6).

These functions are pure: they take Decimal factors and return Decimal
factors. The calculation engine (Sprint 4) is responsible for fetching
the cumulative IPCA / SELIC factors from `indices.services` for the
period and for applying any final quantization. Keeping the helpers
isolated makes them trivial to unit-test without touching the database.
'''

from decimal import Decimal, localcontext


ONE = Decimal('1')
MONTHS_PER_YEAR = Decimal('12')


def monthly_factor_from_annual(annual_rate, months):
    '''Compound an annual rate over `months` months returning a Decimal factor.

    Equivalent to `(1 + annual_rate) ** (months / 12)`. The exponent can
    be fractional, so we use `Decimal.ln()` + `Decimal.exp()` under a
    local context with extended precision.
    '''
    if annual_rate is None:
        raise ValueError('annual_rate é obrigatório.')
    annual = Decimal(annual_rate)
    months_decimal = Decimal(months)
    if months_decimal == 0:
        return ONE
    with localcontext() as ctx:
        ctx.prec = 50
        base = ONE + annual
        exponent = months_decimal / MONTHS_PER_YEAR
        return (base.ln() * exponent).exp()


def apply_ipca_plus_capped(ipca_factor, selic_factor, extra_period_factor):
    '''Combine IPCA + extra-rate and cap the result at the SELIC factor.

    All inputs are cumulative factors for the same period, e.g.
    `Decimal('1.05')` meaning the period accumulated 5%. The caller
    composes `extra_period_factor` via `monthly_factor_from_annual`.
    Returns the smaller of `ipca_factor * extra_period_factor` and
    `selic_factor` — ties resolve to the cap (S6).
    '''
    if ipca_factor is None or selic_factor is None or extra_period_factor is None:
        raise ValueError('Fatores são obrigatórios.')
    ipca = Decimal(ipca_factor)
    selic = Decimal(selic_factor)
    extra = Decimal(extra_period_factor)
    combined = ipca * extra
    return combined if combined < selic else selic
