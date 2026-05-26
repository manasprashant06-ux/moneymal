import pandas as pd
import json
import time

from backend.engine import ForensicsEngine

def main():
    print("Loading data...")
    df = pd.read_csv(r'C:\Users\Manas\Downloads\ibm_aml_15k_upload (1).csv')
    # Use subset for faster testing
    # df = df.head(5000)
    
    print("Initializing engine...")
    orchestrator = ForensicsEngine()
    orchestrator.load_data(df)
    
    print("Running detection...")
    start = time.time()
    results = orchestrator.run_all()
    print(f"Total time: {time.time() - start:.2f}s")
    
    suspicious = results.get('suspicious_accounts', [])
    print(f"Total Suspicious Accounts: {len(suspicious)}")
    
    f_flag_counts = {}
    for a in suspicious:
        patterns = a.get('detected_patterns', [])
        for p in patterns:
            if p.startswith('F'):
                f_flag_counts[p] = f_flag_counts.get(p, 0) + 1
                
    print("\nF-Flags Triggered:")
    for k, v in f_flag_counts.items():
        print(f"  {k}: {v} accounts")
        
    print("\nTop 5 Accounts with F-Flags:")
    f_accounts = [a for a in suspicious if any(p.startswith('F') for p in a.get('detected_patterns', []))]
    f_accounts.sort(key=lambda x: x['suspicion_score'], reverse=True)
    for a in f_accounts[:5]:
        print(f"Account {a['account_id']} | Score: {a['suspicion_score']} | Patterns: {[p for p in a['detected_patterns'] if p.startswith('F')]}")

if __name__ == '__main__':
    main()
