# Module 2 data dictionary

All rows are synthetic. There is no real product, participant, or nutrient database in these CSVs.

## M02_energy_cases.csv

- case_id identifies a particular set of assumptions. Similar IDs do not make rows interchangeable.
- estimated_tdee_kcal_day is the supplied baseline estimate, not a measured true requirement.
- planned_change_percent is signed: negative for deficit, positive for surplus. Its denominator is the estimated TDEE.
- planned_intake_kcal_day is derived from that baseline and percentage.
- status records that these are teaching assumptions.

No row contains an observed muscle-gain outcome, predicted fat-loss guarantee, or clinical recommendation.

## M02_synthetic_foods.csv

Every nutrient amount refers to basis_g = 100 g in the named state. GRAIN-DRY and GRAIN-COOKED are separate concentration records. Their values do not supply a cooking yield. POWDER-A has 80 g protein per 100 g powder, so serving mass is not protein mass.

The simplified energy calculation uses 4 kcal/g protein, 4 carbohydrate, and 9 fat. No real label-energy claim is made. Blank values in any later variant should mean unknown unless explicitly stated otherwise, not zero.

## Symbols and scope

FFM is a mass compartment in kg. In the macro equation, F denotes dietary-fat grams. In earlier RMR equations, an F symbol may denote FFM. A symbol's meaning is local to its stated equation; retrieve the definition with the formula.

The image-only PX-2 label is stored under evaluation/. It is a separate synthetic challenge; do not infer that its container data were supplied by either CSV.
