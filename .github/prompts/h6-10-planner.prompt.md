---
description: Implement H6–10 planning and clarification
---

Implement the H6–10 milestone in analyst/planner.py using the validated plan and clarification contracts in analyst/plan.py. Add an offline preset and one live provider adapter. Give the provider the question and approved catalog only. Route validated comparisons to the existing executor.

Use stubbed responses to test the main question and a paraphrase, missing comparison dates, unsupported metrics, invalid output and timeout. Assert clarification and planner errors issue no metric query. Allow explicit offline selection after a live error. Document how to run a separate credentialed smoke test. Keep Streamlit and daily trend execution for H10–14.

Run the complete pytest suite and report branch, revision, command and result.
