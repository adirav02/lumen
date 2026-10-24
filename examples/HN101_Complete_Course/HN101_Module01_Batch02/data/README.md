# Data dictionary and interval conventions

Dataset status: entirely synthetic. No personal or participant data are included.

| Field | Unit/type | Interpretation |
| --- | --- | --- |
| day | Integer, 0–28 inclusive | Morning observation index; not a calendar date |
| morning_weight_kg | kg, decimal | Weight at the start of that day |
| intake_kcal_following_interval | kcal | Intake after that morning observation and before the next morning |
| record_status | String | Synthetic observation, missing field, or structural endpoint marker |

There are 29 weight timestamps and 28 modeled daily intake intervals. Use rows 0–27 for intake aligned to weight change 0→28. A blank on intake row 28 means the file ends before a following interval is observed. It is not zero and is not a failure of the complete file.

The missing variant independently removes morning weight on day 12 and intake on day 19 (the interval 19→20). Preserve these as missing. Do not borrow values from the complete version during a missing-data evaluation unless the task authorizes recovery from that separate source.

The daily energy values are interval totals in kcal, not an instantaneous rate. Since intervals are one day long, their numerical mean can be expressed as kcal/day.

Exact weekly windows used in the lessons: 1–7, 8–14, 15–21, 22–28. A trailing seven-observation rolling mean also exists at day 6 using observations 0–6; that is a different window from days 1–7. Never confuse plotted endpoint timestamps with the centers used in the weekly trend comparison.

No data point is an estimate of body-fat percentage. Neither CSV contains measured TDEE or a ground-truth physiological maintenance value.
