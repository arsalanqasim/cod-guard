# COD-Guard — 2-minute exhibition demo script

Setup: dashboard open on the Orders tab; benchmark + eval report already generated.

0:00–0:25 — THE PROBLEM. "In Pakistan most online orders are Cash on Delivery. Industry data from ~170,000 real orders shows only about 49 of every 100 COD orders end in money collected — the rest are fake, refused, or returned, and the seller pays the courier both ways. COD-Guard stops the loss BEFORE dispatch."

0:25–0:55 — RISK ENGINE. Orders tab: point at a 🔴 row, read its plain-words reasons (fraud-linked phone, 3 orders in a day, thin address). "Every order gets a risk score from rules plus a machine-learning model. No single signal can block an order alone — that is deliberate, so real customers are not wrongly blocked."

0:55–1:30 — VERIFICATION AGENT (the FP/FN answer). Verification tab: pick the 🔴 order, type the customer reply "Ji theek hai, bhej dein" → decision flips to SHIP. Then pick a 🟢 order, type "Nahi, mera order nahi hai" → decision HOLD_CANCEL. "The model catches patterns; the customer conversation catches the rest. A confirmation rescues a flagged real order — that kills false positives. A denial stops a passed fake order — that kills false negatives. It understands English, Roman Urdu, Urdu script, and Urdu voice notes."

1:30–1:50 — MEASURED, NOT CLAIMED. Metrics tab + EVAL_REPORT: "We measured both error types on a 6,000-order benchmark calibrated to published COD statistics: false-positive rate under 5% at our operating point, organised fakes caught at 87%, and total seller loss down 29% versus shipping everything."

1:50–2:00 — CLOSED LOOP. Mark one outcome (delivered/returned). "Every real outcome is recorded and retrains the next model version — the system learns from courier results, which is our difference from the confirmation tools already in the market, like Tasdeek and OrderWitness, that never learn from outcomes."

If asked about data honesty: "The benchmark is synthetic, calibrated to the OrderNation study — we say so openly. The method is what we are demonstrating; with one real seller's order history, the same pipeline trains on real data."
