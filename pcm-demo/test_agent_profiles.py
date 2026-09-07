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
            PROJECT_INTAKE: "project_intake",
            PROJECT_READINESS: "project_readiness",
            PROJECT_BOOTSTRAP: "project_bootstrap",
            TAILWIND_THEME: "tailwind_theme",
            SOLUTION_DESIGN: "solution_design",
            ENGINEERING_ARCHITECTURE: "engineering_architecture",
            UI_UX_FRAMEWORK: "ui_ux_framework",
            REQUIREMENT_BREAKDOWN: "requirement_breakdown",
        }

        for spec, task in expected.items():
            with self.subTest(skill=spec.skill_name):
                self.assertEqual(spec.task, task)


if __name__ == "__main__":
    unittest.main()
