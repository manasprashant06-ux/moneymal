"""Quick API test — uploads CSV and prints results using async polling."""
import requests
import json
import sys
import time

if len(sys.argv) > 1:
    csv_path = sys.argv[1]
else:
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    path_parent = os.path.join(current_dir, "..", "test_transactions.csv")
    path_grandparent = os.path.join(current_dir, "..", "..", "test_transactions.csv")
    csv_path = path_grandparent if os.path.exists(path_grandparent) else path_parent
url = "http://localhost:8000/api/analyze"

print(f"Uploading {csv_path} to {url}...")
with open(csv_path, "rb") as f:
    resp = requests.post(url, files={"file": (csv_path, f, "text/csv")})

if resp.status_code != 200:
    print(f"ERROR submitting job: status {resp.status_code}")
    print(resp.text)
    sys.exit(1)

data = resp.json()
job_id = data["job_id"]
status = data["status"]
print(f"Job submitted successfully. Job ID: {job_id}, Status: {status}")

# Poll /api/result/{job_id} until completed
result_url = f"http://localhost:8000/api/result/{job_id}"
while True:
    time.sleep(1)
    resp = requests.get(result_url)
    if resp.status_code != 200:
        print(f"ERROR polling job: status {resp.status_code}")
        print(resp.text)
        sys.exit(1)
    
    job_data = resp.json()
    status = job_data.get("status")
    print(f"Polling... Current status: {status}")
    if status == "done":
        result = job_data["result"]
        graph = job_data["graph"]
        break
    elif status == "error":
        print(f"Job failed with error: {job_data.get('detail')}")
        sys.exit(1)

summary = result["summary"]

print(f"\n=== Analysis Summary ===")
print(json.dumps(summary, indent=2))
print(f"\nGraph: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
print(f"Suspicious accounts: {len(result['suspicious_accounts'])}")
print(f"Fraud rings: {len(result['fraud_rings'])}")

if result["fraud_rings"]:
    print("\nFraud Rings:")
    for ring in result["fraud_rings"]:
        print(f"  {ring['ring_id']}  type={ring['pattern_type']}  members={len(ring['member_accounts'])}  risk={ring['risk_score']}")

print("\nAll OK!")
