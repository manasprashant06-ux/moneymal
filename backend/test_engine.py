import sys
import json
import os
import pandas as pd
from engine import ForensicsEngine

if len(sys.argv) > 1:
    csv_path = sys.argv[1]
else:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    path_parent = os.path.join(current_dir, "..", "test_transactions.csv")
    path_grandparent = os.path.join(current_dir, "..", "..", "test_transactions.csv")
    csv_path = path_grandparent if os.path.exists(path_grandparent) else path_parent
print(f"Loading: {csv_path}")
e = ForensicsEngine()
e.load_data(pd.read_csv(csv_path))
r = e.run_all()
s = r["summary"]

print(f"Accounts analyzed: {s['total_accounts_analyzed']}")
print(f"Suspicious flagged: {s['suspicious_accounts_flagged']}")
print(f"Fraud rings: {s['fraud_rings_detected']}")
print(f"Processing time: {s['processing_time_seconds']}s")
print()

if r["suspicious_accounts"]:
    print("Top 5 suspicious accounts:")
    for a in r["suspicious_accounts"][:5]:
        print(f"  {a['account_id']}  score={a['suspicion_score']}  patterns={a['detected_patterns']}  ring={a['ring_id']}")
else:
    print("No suspicious accounts detected.")

print()
if r["fraud_rings"]:
    print("Fraud rings:")
    for ring in r["fraud_rings"]:
        print(f"  {ring['ring_id']}  type={ring['pattern_type']}  members={len(ring['member_accounts'])}  risk={ring['risk_score']}")
else:
    print("No fraud rings detected.")
