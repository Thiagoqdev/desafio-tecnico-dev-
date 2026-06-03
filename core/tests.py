'''Tests for shared abstractions in the core module.'''

from django.db import models
from django.test import SimpleTestCase

from core.models import TimeStampedModel


class TimeStampedModelTests(SimpleTestCase):
    '''Verify TimeStampedModel is correctly defined as an abstract base.'''

    def test_model_is_abstract(self):
        self.assertTrue(TimeStampedModel._meta.abstract)

    def test_exposes_created_at_and_updated_at_fields(self):
        field_names = {field.name for field in TimeStampedModel._meta.get_fields()}
        self.assertIn('created_at', field_names)
        self.assertIn('updated_at', field_names)

    def test_created_at_is_set_on_insert_only(self):
        field = TimeStampedModel._meta.get_field('created_at')
        self.assertIsInstance(field, models.DateTimeField)
        self.assertTrue(field.auto_now_add)
        self.assertFalse(field.auto_now)

    def test_updated_at_is_set_on_every_save(self):
        field = TimeStampedModel._meta.get_field('updated_at')
        self.assertIsInstance(field, models.DateTimeField)
        self.assertTrue(field.auto_now)
        self.assertFalse(field.auto_now_add)
