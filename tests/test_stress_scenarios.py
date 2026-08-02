import importlib.util
import json
import unittest
from pathlib import Path

from test_support import ROOT, WorkersGroupTestCase


class StressScenarioTraceabilityTests(WorkersGroupTestCase):
    def test_all_twenty_six_stress_scenarios_have_executable_evidence_tests(self):
        scenario_path = Path(__file__).parent / "scenarios" / "stress-scenarios.json"
        scenarios = json.loads(scenario_path.read_text(encoding="utf-8"))
        self.assertEqual([f"WG-STRESS-{index:03d}" for index in range(1, 27)], [item["id"] for item in scenarios])
        self.assertEqual(26, len({item["gate"] for item in scenarios}))
        for scenario in scenarios:
            with self.subTest(scenario=scenario["id"]):
                filename, method = scenario["evidenceTest"].split("::", 1)
                test_file = ROOT / ".agents" / "skills" / "orchestrating-workers-group" / "tests" / filename
                self.assertTrue(test_file.is_file(), scenario)
                evidence_test = self._load_evidence_test(test_file, method)
                result = unittest.TestResult()
                unittest.TestSuite([evidence_test]).run(result)
                details = {
                    "scenario": scenario,
                    "failures": [text for _, text in result.failures],
                    "errors": [text for _, text in result.errors],
                    "skipped": [reason for _, reason in result.skipped],
                }
                self.assertTrue(result.wasSuccessful(), details)
                self.assertFalse(result.skipped, details)

    def _load_evidence_test(self, test_file, method):
        module_name = f"workers_group_stress_{test_file.stem}_{method}"
        spec = importlib.util.spec_from_file_location(module_name, test_file)
        self.assertIsNotNone(spec, test_file)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        matches = []
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, unittest.TestCase)
                and hasattr(value, method)
            ):
                matches.append(value(method))
        self.assertEqual(1, len(matches), f"{test_file.name}::{method}")
        return matches[0]
