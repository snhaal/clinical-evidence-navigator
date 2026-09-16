import argparse
import asyncio
import json
import glob
from app.adapters.clinicaltrials import ClinicalTrialsClient
from app.pipeline.act import normalize_study
from app.pipeline.ground import decompose_eligibility_criteria
from evals.schemas import GoldCaseSet

parser = argparse.ArgumentParser(description="Diagnose eval reports and criteria alignment.")
parser.add_argument("--dump-false-matches", action="store_true", help="Dump all false positive matches")
args, _ = parser.parse_known_args()

# 1. Inspect why any criteria did not match parsed criteria
with open("evals/gold_cases.json", "r", encoding="utf-8") as f:
    gold_set = GoldCaseSet(**json.load(f))

ct = ClinicalTrialsClient()

print("=== Checking Warning Criteria Alignment ===")
unmatched_count = 0
for case in gold_set.cases:
    for nct_id in case.expected_trial_nct_ids:
        raw_study = asyncio.run(ct.get_study(nct_id))
        trial = normalize_study(raw_study)
        parsed_criteria = decompose_eligibility_criteria(trial.nct_id, trial.eligibility_text)
        parsed_texts = [c.raw_text for c in parsed_criteria]
        for gc in case.criteria:
            if gc.nct_id == nct_id and gc.raw_text not in parsed_texts:
                # Find the closest matching line in parsed criteria
                candidates = [p for p in parsed_texts if any(w in p for w in gc.raw_text.split()[:4])]
                print(f"\n[UNMATCHED in {nct_id}]")
                print(f"  Gold file has  : {gc.raw_text[:80]}")
                if candidates:
                    print(f"  API parsed as  : {candidates[0][:80]}")
                else:
                    print("  No close candidate found in parsed criteria.")
                unmatched_count += 1
if unmatched_count == 0:
    print("All criteria aligned with parsed criteria.")

# 2. Inspect the latest discrepancies / false matches
latest = sorted(glob.glob("evals/reports/run_*.json"))[-1]
with open(latest, "r", encoding="utf-8") as f:
    rep = json.load(f)

print("\n" + "=" * 60)
print(f"=== Discrepancies from {latest} ===")
comps = rep.get("comparisons", [])
if not comps:
    print("Run report did not contain 'comparisons' key.")
else:
    false_match_count = 0
    mismatch_count = 0
    for c in comps:
        exp = c.get("expected")
        pred = c.get("predicted")
        is_false_match = (exp in ["no_match", "unclear"] and pred == "match")
        is_mismatch = (exp != pred)

        if args.dump_false_matches:
            if is_false_match:
                false_match_count += 1
                print(f"🚨 [FALSE MATCH] #{false_match_count}")
                print(f"  Trial/Type: [{c.get('nct_id')}] {c.get('criterion_type')} #{c.get('criterion_index')}")
                print(f"  Criterion : {c.get('criterion')}")
                print(f"  Expected  : {str(exp).upper()} | Predicted: {str(pred).upper()}")
                print(f"  Cited     : {c.get('cited_text')}")
                print()
        else:
            if is_mismatch:
                mismatch_count += 1
                tag = "🚨 [FALSE MATCH]" if is_false_match else "⚠️ [MISMATCH]"
                print(f"{tag}")
                print(f"  Criterion: {c.get('criterion')[:90]}...")
                print(f"  Expected : {str(exp).upper()} | Predicted: {str(pred).upper()}")
                print()
    if args.dump_false_matches:
        print(f"Total false matches dumped: {false_match_count}")
    else:
        print(f"Total discrepancies: {mismatch_count}")
