# Examples and fixtures

| Directory | Purpose | Run / consumers |
|---|---|---|
| `synthetic_probability/` | Generated text, Hebrew, PDF and PPTX fixtures | Root `demo.py`, ingestion and efficiency tests |
| [audit_course](audit_course/README.md) | Generated course with checked rubrics and source revisions | `tests/test_audit_course_e2e.py` |
| [educational_evaluation](educational_evaluation/README.md) | 16 reviewed generated submissions and graph images | `scripts/evaluate_education.py`, evaluation tests |
| [beta_courses](beta_courses/README.md) | Upcoming public beta course fixtures | Pending beta courses |

Start with `python demo.py` for a synthetic end-to-end walkthrough.
Real courses live in the gitignored `local-courses/` folder and are not included.
Only a course's student export folder should be served to learners; keep original
sources, teacher keys and authoring exports private.
