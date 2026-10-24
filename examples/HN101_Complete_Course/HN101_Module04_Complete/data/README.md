# Data dictionary and provenance

Every numeric case is synthetic, assigned for teaching, and not participant data. Force is in N; perpendicular moment arm in m; moment magnitude in N·m. Values describe one external-force component. No signs, full net joint moments, individual muscle forces, or injury probabilities are supplied. HINGE-A/B use bar mass 40 kg with g=9.81 m/s². Other rows supply force directly.

M04_profiles.csv contains three samples per profile, not a continuous measured curve. Start/middle/end do not establish target muscle length. M04_force_cases.csv includes intentionally similar case names; do not merge their geometries.

exercise_cards.json and exercise_cards.csv contain identical 31 authored cards; EXERCISE_LIBRARY.md is the readable rendering. Import one representation or deduplicate by id. action is a course search category, not an exhaustive anatomy code. equipment is a required setup tag, not an inventory of equipment the learner owns. No tolerability or medical status field is known from an equipment tag. Unknown observations are not zeros, confirmed defects, or confirmed acceptable performance.
