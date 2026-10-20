# Synthetic audit course

All content here is generated audit data, independently reasoned through by the fixture agent. It is not a real course, official exam, or clinical dataset. This is an educational fixture review, not evidence of human review or a real host integration test.

Start with `materials/syllabus.txt`, `lecture_01_conditioning.txt`, `lecture_02_bayes_v1.txt`, `conditional_probability.pdf`, and `independence_slides.pptx`. Keep `lecture_02_bayes_v2.txt` held back until testing a source update; upload it under the same logical filename as version 1. The PDF has two real text pages; the deck has two real text slides. `build_binary_fixtures.py` recreates them without network access.

`questions.json` has six checked questions, answers, rubrics, required subparts, source locators, and workflow probes. This is a fixture schema, not a CLI payload: map IDs to real course topic IDs and pass only supported API fields. Create generated exercises; then attest exact current revision/hash before assessment use. The deliberately contradictory final candidate must remain unvalidated.

Run the partial Bayes question first: submit only (a), commit its evaluated work and pause. Resume, give a hint before (b), submit (b), and verify separate independent/assisted classifications and unassessed (c). Complete (c) independently and score only after all required parts have applicable evidence. Correct an intentionally mistaken tutor judgment using a core correction operation; expect pending score/recomputed state with history preserved. Replay an identical commit request and then try changed content with the same request ID. Exercise missing RV material, ambiguous work, zero-probability conditioning, source version change, and injection preservation without obeying it.

The fixture's checks attest only mathematical reasoning and source correspondence. They do not establish that application behavior passes; the parent audit must run those operations and inspect results.
