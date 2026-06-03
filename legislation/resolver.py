'''Resolver that maps a date interval to the applicable legislation rules.

`LegislationResolver.resolve(start, end)` splits `[start, end]` into
contiguous subintervals where each subinterval has exactly one active
`CorrectionRule`, `InterestRule` and (optionally) `UnificationRule`. The
calculation engine (Sprint 4) iterates over these segments to apply the
correct factors.

The split boundaries are derived from the union of the start/end dates of
every rule that overlaps the requested interval. Open-ended vigência
(`end_date IS NULL`) is treated as "+infinity".
'''

from dataclasses import dataclass
from datetime import date, timedelta

from .models import CorrectionRule, InterestRule, UnificationRule


@dataclass(frozen=True)
class ResolvedSegment:
    '''One subinterval with its three resolved rules.'''

    start_date: date
    end_date: date
    correction_rule: CorrectionRule
    interest_rule: InterestRule
    unification_rule: UnificationRule | None

    @property
    def is_unified(self) -> bool:
        return (
            self.unification_rule is not None
            and self.unification_rule.unifies_correction_and_interest
        )


class LegislationResolver:
    '''Splits an interval into segments anchored by rule transitions.'''

    def resolve(self, start: date, end: date) -> list[ResolvedSegment]:
        if start > end:
            raise ValueError('start_date posterior a end_date.')

        correction_rules = self._overlapping(CorrectionRule, start, end)
        interest_rules = self._overlapping(InterestRule, start, end)
        unification_rules = self._overlapping(UnificationRule, start, end)

        boundaries = self._boundaries(
            start,
            end,
            correction_rules + interest_rules + unification_rules,
        )

        segments: list[ResolvedSegment] = []
        for i in range(len(boundaries) - 1):
            seg_start = boundaries[i]
            seg_end = boundaries[i + 1] - timedelta(days=1)
            correction = self._active_at(correction_rules, seg_start)
            interest = self._active_at(interest_rules, seg_start)
            unification = self._active_at(unification_rules, seg_start)
            if correction is None or interest is None:
                raise LookupError(
                    f'Faltam regras para o intervalo {seg_start.isoformat()} → {seg_end.isoformat()}.'
                )
            segments.append(
                ResolvedSegment(
                    start_date=seg_start,
                    end_date=seg_end,
                    correction_rule=correction,
                    interest_rule=interest,
                    unification_rule=unification,
                )
            )
        return segments

    @staticmethod
    def _overlapping(model, start: date, end: date) -> list:
        from django.db.models import Q
        queryset = model.objects.filter(
            Q(start_date__lte=end) & (Q(end_date__isnull=True) | Q(end_date__gte=start))
        ).order_by('start_date')
        return list(queryset)

    @staticmethod
    def _boundaries(start: date, end: date, rules: list) -> list[date]:
        boundaries = {start, end + timedelta(days=1)}
        for rule in rules:
            if start < rule.start_date <= end:
                boundaries.add(rule.start_date)
            if rule.end_date is not None and start <= rule.end_date < end:
                boundaries.add(rule.end_date + timedelta(days=1))
        return sorted(boundaries)

    @staticmethod
    def _active_at(rules: list, day: date):
        for rule in rules:
            if rule.start_date <= day and (rule.end_date is None or rule.end_date >= day):
                return rule
        return None
