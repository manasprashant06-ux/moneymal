import pandas as pd
from backend.engine import ForensicsEngine

csv_path = r'C:\Users\Manas\Downloads\ibm_aml_15k_upload (1).csv'
print(f'Loading {csv_path}...')
df = pd.read_csv(csv_path)
print(f'Loaded {len(df)} rows. Running engine...')

engine = ForensicsEngine()
engine.load_data(df)
engine.run_all()

graph_data = engine.generate_json()
suspicious = graph_data.get('suspicious_accounts', [])
print(f'\nTotal Flagged Accounts: {len(suspicious)}')

verdicts = {'APPROVE': 0, 'REVIEW': 0, 'BLOCK': 0}
for acc in suspicious:
    verdicts[acc['verdict']] = verdicts.get(acc['verdict'], 0) + 1

print('Verdicts breakdown:', verdicts)

print('\nTop 5 BLOCK Accounts:')
blocked = [a for a in suspicious if a['verdict'] == 'BLOCK']
blocked.sort(key=lambda x: x['suspicion_score'], reverse=True)
for acc in blocked[:5]:
    print(f"Account: {acc['account_id']} - Score: {acc['suspicion_score']}")
    print(f"  Role: {acc['structural_role']} - Patterns: {acc['detected_patterns']}")
    print(f"  Pillars: {acc['four_pillar_scores']}")

print('\nTop 5 REVIEW Accounts:')
reviewed = [a for a in suspicious if a['verdict'] == 'REVIEW']
reviewed.sort(key=lambda x: x['suspicion_score'], reverse=True)
for acc in reviewed[:5]:
    print(f"Account: {acc['account_id']} - Score: {acc['suspicion_score']}")
    print(f"  Role: {acc['structural_role']} - Patterns: {acc['detected_patterns']}")
    print(f"  Pillars: {acc['four_pillar_scores']}")
