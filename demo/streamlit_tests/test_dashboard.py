"""Offline UI tests using genuine bundled records; no server or API credentials."""

import unittest

from streamlit.testing.v1 import AppTest

from app.tests.test_demo_data import case_documents, case_zip
from toxoracle_app.demo_data import ROOT, load_baseline, load_case_zip, read_json
from toxoracle_app.demo_visuals import molecule_svg, pose_chart, unique_features


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()

    def assert_clean(self):
        self.assertFalse(self.app.exception, [e.message for e in self.app.exception])
        self.assertFalse(self.app.error, [e.value for e in self.app.error])

    def test_all_pages_and_presenter_notes_render(self):
        self.assert_clean()
        self.assertEqual(self.app.metric[0].value, "3")
        self.app.toggle(key="presenter_notes").set_value(True).run()
        for page in ["Candidate explorer", "Discovery lab", "Model & provenance", "Load a study", "Overview"]:
            with self.subTest(page=page):
                self.app.radio(key="page").set_value(page).run()
                self.assert_clean()
        self.assertEqual(len(self.app.get("download_button")), 3)

    def test_candidate_switching_and_atom_highlight_preserve_scores(self):
        self.app.radio(key="page").set_value("Candidate explorer").run()
        study = load_baseline()
        for result in study.results:
            compound_id = result["compound_id"]
            self.app.selectbox(key="candidate").select(compound_id).run()
            self.assert_clean()
            self.assertEqual(self.app.metric[0].value, f"{result['assessment']['risk_score']:.3f}")
            self.app.selectbox(key=f"feature_{compound_id}").select_index(1).run()
            self.app.toggle(key=f"atom_labels_{compound_id}").set_value(True).run()
            self.assert_clean()

    def test_structure_view_and_verified_cached_pose(self):
        study = load_baseline()
        evidence = study.results[0]["structural_evidence"]
        groups = unique_features(evidence["fragments"])
        self.assertLess(len(groups), len(evidence["fragments"]))
        feature = next(g for g in groups if g["ambiguous"])
        self.assertGreater(len(feature["fragments"]), 1)
        svg = molecule_svg(evidence["atom_mapped_smiles"], list(feature["atom_map_ids"]))
        self.assertIn("<svg", svg)
        with self.assertRaises(ValueError):
            molecule_svg(evidence["atom_mapped_smiles"], [999999])
        folder = ROOT / "demo/examples/nvidia_diffdock"
        run = read_json(folder / "run.json")
        figure = pose_chart((folder / run["pose_file"]).read_text(), (folder / run["protein_file"]).read_text())
        self.assertEqual(len(figure.data[-1].x), 21)
        self.assertEqual(figure.data[0].name, "Protein Cα trace")

    def test_complete_case_can_be_opened_and_switched_back_to_builtin(self):
        self.app.session_state["pending_study"] = load_case_zip(case_zip(case_documents()))
        self.app.run()
        self.assert_clean()
        self.assertEqual(self.app.selectbox(key="study_picker").value, "Uploaded study")
        self.app.radio(key="page").set_value("Candidate explorer").run()
        self.assert_clean()
        self.assertTrue(any("Consider targeted human-relevant liver validation" in item.value for item in self.app.markdown))
        self.app.radio(key="page").set_value("Discovery lab").run()
        self.assert_clean()
        self.app.selectbox(key="study_picker").select("Public DILI study").run()
        self.app.radio(key="page").set_value("Overview").run()
        self.assert_clean()
        self.assertEqual(self.app.metric[0].value, "3")


if __name__ == "__main__":
    unittest.main()
