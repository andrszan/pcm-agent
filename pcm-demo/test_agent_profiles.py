from __future__ import annotations

import unittest

from steps.step_02_project_intake.step import DECISION_LOOP_SPEC as PROJECT_INTAKE
from steps.step_05_project_readiness.step import DECISION_LOOP_SPEC as PROJECT_READINESS
from steps.step_06_project_bootstrap.step import (
    DECISION_LOOP_SPEC as PROJECT_BOOTSTRAP,
    TAILWIND_THEME_DECISION_LOOP_SPEC as TAILWIND_THEME,
)
from steps.step_07_solution_design.step import DECISION_LOOP_SPEC as SOLUTION_DESIGN
from steps.step_09_engineering_architecture.step import (
    DECISION_LOOP_SPEC as ENGINEERING_ARCHITECTURE,
)
from steps.step_10_ui_ux_framework.step import DECISION_LOOP_SPEC as UI_UX_FRAMEWORK
from steps.step_11_requirement_breakdown.step import (
    DECISION_LOOP_SPEC as REQUIREMENT_BREAKDOWN,
)


class AgentProfileTest(unittest.TestCase):
    def test_project_level_profiles(self) -> None:
        expected = {
            PROJECT_INTAKE: ("high", "high"),
            PROJECT_READINESS: ("high", "high"),
            PROJECT_BOOTSTRAP: ("medium", "high"),
            TAILWIND_THEME: ("medium", "high"),
            SOLUTION_DESIGN: ("high", "high"),
            ENGINEERING_ARCHITECTURE: ("high", "high"),
            UI_UX_FRAMEWORK: ("high", "high"),
            REQUIREMENT_BREAKDOWN: ("high", "high"),
        }

        for spec, profile in expected.items():
            with self.subTest(skill=spec.skill_name):
                self.assertEqual((spec.model_tier, spec.effort), profile)


if __name__ == "__main__":
    unittest.main()
