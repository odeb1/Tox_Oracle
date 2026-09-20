"""Recorded generation evidence must stay distinct from candidate-level studies."""

from copy import deepcopy
import unittest

from toxoracle_app.demo_data import ROOT, StudyError, read_json
from toxoracle_app.demo_generation import EVIDENCE_PATH, load_generation_demo, validate_generation_summary


class GenerationDemoTests(unittest.TestCase):
    def test_loads_recorded_evidence_without_fabricating_candidate_results(self):
        demo = load_generation_demo()
        self.assertEqual(demo.report, read_json(ROOT / EVIDENCE_PATH))
        self.assertEqual(demo.report['generation']['returned_count'], 40)
        self.assertEqual(demo.report['generation']['accepted_unique_count'], 29)
        self.assertEqual(demo.selected, 20)
        self.assertEqual(demo.shortlisted, 2)
        self.assertEqual(demo.report['held_shortlist_count'], 2)
        self.assertEqual(demo.report['dili_calls'], {'positive': 20})
        self.assertNotIn('results', demo.report)
        self.assertEqual(demo.request['mode'], 'generate_screen')
        self.assertNotIn('compounds', demo.request)
        self.assertEqual(demo.supplied_request['mode'], 'screen')

    def test_inconsistent_or_invalid_counts_are_rejected(self):
        demo = load_generation_demo()
        changes = [
            ('generation', 'selected_count', 21),
            ('generation', 'returned_count', True),
            ('generation_rejection_counts', 'duplicate', 8),
            ('dili_calls', 'positive', 19),
            ('fitting_membership', 'excluded', 21),
        ]
        for section, key, value in changes:
            with self.subTest(section=section, key=key):
                report = deepcopy(demo.report)
                report[section][key] = value
                with self.assertRaises(StudyError):
                    validate_generation_summary(report, demo.protocol)

    def test_shortlist_and_protocol_must_match_recorded_evidence(self):
        demo = load_generation_demo()
        for changes in ({'held_shortlist_count': 3}, {'protocol': 'other_protocol'},
                        {'date_london': 'invalid'}, {'generation': {}}):
            with self.subTest(changes=changes):
                with self.assertRaises(StudyError):
                    validate_generation_summary(dict(demo.report, **changes), demo.protocol)


if __name__ == '__main__':
    unittest.main()
