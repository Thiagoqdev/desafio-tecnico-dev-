'''Tests for the legislation module: seeds, resolver and capped-mode.'''

from datetime import date, timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from .models import CorrectionRule, InterestRule, UnificationRule
from .resolver import LegislationResolver
from .services import apply_ipca_plus_capped, monthly_factor_from_annual


# ---------------------------------------------------------------------------
# Data-migration seeds
# ---------------------------------------------------------------------------


class LegislationSeedTests(TestCase):
    '''The data migration must seed sections 6.1, 6.2 and 6.3.'''

    def test_correction_rules_seeded_with_four_rows(self):
        rules = list(CorrectionRule.objects.order_by('start_date'))
        self.assertEqual(len(rules), 4)

        legal_bases = [rule.legal_basis for rule in rules]
        self.assertEqual(legal_bases, ['', '', 'EC 113/2021', 'EC 136/2025'])

        codes = [rule.index_type.code for rule in rules]
        self.assertEqual(codes, ['INPC', 'IPCA-E', 'SELIC', 'IPCA'])

    def test_interest_rules_seeded_with_four_rows(self):
        rules = list(InterestRule.objects.order_by('start_date'))
        self.assertEqual(len(rules), 4)

        self.assertEqual(rules[0].monthly_rate, Decimal('0.010000'))
        self.assertEqual(rules[1].monthly_rate, Decimal('0.005000'))
        self.assertTrue(rules[2].uses_selic)
        self.assertEqual(rules[2].mode, 'selic')
        self.assertEqual(rules[3].mode, 'ipca_plus_capped')

    def test_unification_rule_active_after_2021_12_09(self):
        rules = list(UnificationRule.objects.all())
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].start_date, date(2021, 12, 9))
        self.assertIsNone(rules[0].end_date)
        self.assertTrue(rules[0].unifies_correction_and_interest)
        self.assertEqual(rules[0].legal_basis, 'EC 113/2021')

    def test_ipca_plus_capped_rule_has_extra_rate_and_cap_index(self):
        rule = CorrectionRule.objects.get(mode='ipca_plus_capped')
        self.assertEqual(rule.extra_rate, Decimal('0.020000'))
        self.assertEqual(rule.index_type.code, 'IPCA')
        self.assertIsNotNone(rule.selic_cap_index)
        self.assertEqual(rule.selic_cap_index.code, 'SELIC')


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class LegislationResolverTests(TestCase):
    '''Subinterval slicing must align with EC 113/2021 and EC 136/2025.'''

    def setUp(self):
        self.resolver = LegislationResolver()

    def test_single_segment_when_interval_fully_inside_one_rule(self):
        segments = self.resolver.resolve(date(1995, 6, 1), date(1995, 12, 31))

        self.assertEqual(len(segments), 1)
        segment = segments[0]
        self.assertEqual(segment.start_date, date(1995, 6, 1))
        self.assertEqual(segment.end_date, date(1995, 12, 31))
        self.assertEqual(segment.correction_rule.index_type.code, 'IPCA-E')
        self.assertEqual(segment.interest_rule.monthly_rate, Decimal('0.010000'))
        self.assertIsNone(segment.unification_rule)
        self.assertFalse(segment.is_unified)

    def test_resolver_splits_at_1991_1992_transition(self):
        segments = self.resolver.resolve(date(1991, 12, 1), date(1992, 1, 31))

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].start_date, date(1991, 12, 1))
        self.assertEqual(segments[0].end_date, date(1991, 12, 31))
        self.assertEqual(segments[0].correction_rule.index_type.code, 'INPC')
        self.assertEqual(segments[1].start_date, date(1992, 1, 1))
        self.assertEqual(segments[1].end_date, date(1992, 1, 31))
        self.assertEqual(segments[1].correction_rule.index_type.code, 'IPCA-E')

    def test_resolver_splits_at_ec_113_transition(self):
        segments = self.resolver.resolve(date(2021, 12, 1), date(2021, 12, 31))

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].end_date, date(2021, 12, 8))
        self.assertEqual(segments[0].correction_rule.index_type.code, 'IPCA-E')
        self.assertFalse(segments[0].is_unified)

        self.assertEqual(segments[1].start_date, date(2021, 12, 9))
        self.assertEqual(segments[1].correction_rule.index_type.code, 'SELIC')
        self.assertEqual(segments[1].correction_rule.legal_basis, 'EC 113/2021')
        self.assertTrue(segments[1].is_unified)

    def test_resolver_splits_at_ec_136_transition(self):
        segments = self.resolver.resolve(date(2025, 9, 1), date(2025, 10, 31))

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].end_date, date(2025, 9, 30))
        self.assertEqual(segments[0].correction_rule.index_type.code, 'SELIC')
        self.assertEqual(segments[0].correction_rule.mode, 'single_index')
        self.assertTrue(segments[0].is_unified)

        self.assertEqual(segments[1].start_date, date(2025, 10, 1))
        self.assertEqual(segments[1].correction_rule.mode, 'ipca_plus_capped')
        self.assertEqual(segments[1].correction_rule.legal_basis, 'EC 136/2025')
        self.assertEqual(segments[1].correction_rule.extra_rate, Decimal('0.020000'))
        self.assertTrue(segments[1].is_unified)

    def test_resolver_handles_long_interval_with_multiple_transitions(self):
        '''The interest rule also breaks on 2009-07-01 (1% → 0,5% a.m.),
        which produces an extra segment within IPCA-E. The resolver must
        respect both correction and interest boundaries.
        '''
        segments = self.resolver.resolve(date(1991, 6, 1), date(2025, 10, 31))

        triples = [
            (
                seg.correction_rule.index_type.code,
                seg.correction_rule.mode,
                seg.interest_rule.mode,
            )
            for seg in segments
        ]
        self.assertEqual(
            triples,
            [
                ('INPC', 'single_index', 'fixed_monthly'),
                ('IPCA-E', 'single_index', 'fixed_monthly'),
                ('IPCA-E', 'single_index', 'fixed_monthly'),
                ('SELIC', 'single_index', 'selic'),
                ('IPCA', 'ipca_plus_capped', 'ipca_plus_capped'),
            ],
        )
        self.assertEqual(segments[1].interest_rule.monthly_rate, Decimal('0.010000'))
        self.assertEqual(segments[2].interest_rule.monthly_rate, Decimal('0.005000'))
        self.assertEqual(segments[1].end_date, date(2009, 6, 30))
        self.assertEqual(segments[2].start_date, date(2009, 7, 1))

    def test_resolver_rejects_inverted_interval(self):
        with self.assertRaises(ValueError):
            self.resolver.resolve(date(2020, 12, 31), date(2020, 1, 1))

    def test_resolver_segments_are_contiguous_and_cover_full_interval(self):
        start, end = date(2021, 1, 1), date(2025, 12, 31)
        segments = self.resolver.resolve(start, end)

        self.assertEqual(segments[0].start_date, start)
        self.assertEqual(segments[-1].end_date, end)
        for previous, current in zip(segments, segments[1:]):
            self.assertEqual(
                current.start_date,
                previous.end_date + timedelta(days=1),
                msg=f'gap entre {previous.end_date} e {current.start_date}',
            )


# ---------------------------------------------------------------------------
# ipca_plus_capped helpers
# ---------------------------------------------------------------------------


class IpcaPlusCappedTests(SimpleTestCase):
    '''Pure helpers — no database access required.'''

    PRECISION = Decimal('0.00000001')

    def assertDecimalAlmostEqual(self, a, b):
        self.assertLess(abs(a - b), self.PRECISION, msg=f'{a} vs {b}')

    def test_monthly_factor_for_12_months_equals_one_plus_rate(self):
        factor = monthly_factor_from_annual(Decimal('0.02'), 12)
        self.assertDecimalAlmostEqual(factor, Decimal('1.02'))

    def test_monthly_factor_for_6_months_equals_sqrt_one_plus_rate(self):
        factor = monthly_factor_from_annual(Decimal('0.02'), 6)
        self.assertDecimalAlmostEqual(factor, Decimal('1.02').sqrt())

    def test_monthly_factor_zero_months(self):
        self.assertEqual(monthly_factor_from_annual(Decimal('0.02'), 0), Decimal('1'))

    def test_apply_capped_returns_combined_when_below_selic(self):
        result = apply_ipca_plus_capped(
            ipca_factor=Decimal('1.05'),
            selic_factor=Decimal('1.10'),
            extra_period_factor=Decimal('1.02'),
        )
        self.assertEqual(result, Decimal('1.05') * Decimal('1.02'))

    def test_apply_capped_returns_selic_when_combined_exceeds_cap(self):
        result = apply_ipca_plus_capped(
            ipca_factor=Decimal('1.20'),
            selic_factor=Decimal('1.10'),
            extra_period_factor=Decimal('1.02'),
        )
        self.assertEqual(result, Decimal('1.10'))

    def test_apply_capped_returns_selic_when_exactly_equal(self):
        selic = Decimal('1.10')
        ipca = Decimal('1.10') / Decimal('1.02')
        result = apply_ipca_plus_capped(
            ipca_factor=ipca,
            selic_factor=selic,
            extra_period_factor=Decimal('1.02'),
        )
        self.assertEqual(result, selic)

    def test_apply_capped_uses_decimal_precision(self):
        ipca = Decimal('1.05123456')
        extra = Decimal('1.00164797')  # roughly (1.02)^(1/12)
        selic = Decimal('1.10000000')
        result = apply_ipca_plus_capped(
            ipca_factor=ipca,
            selic_factor=selic,
            extra_period_factor=extra,
        )
        self.assertEqual(result, ipca * extra)
        self.assertIsInstance(result, Decimal)
