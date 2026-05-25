import pandas as pd
import json

csv_path = r'C:\Users\Manas\Downloads\ibm_aml_15k_upload (1).csv'
json_path = r'C:\Users\Manas\Downloads\analysis_results (2).json'

print('Loading JSON and CSV...')
with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

df = pd.read_csv(csv_path)
df.columns = [c.lower().strip() for c in df.columns]

# Fuzzy matching columns
df_cols = list(df.columns)
def get_col(candidates):
    for c in candidates:
        if c in df_cols: return c
    return candidates[0]

sender_col = get_col(['sender_id', 'from_account', 'payer_id', 'originator', 'sender'])
receiver_col = get_col(['receiver_id', 'to_account', 'payee_id', 'beneficiary', 'destination'])
amount_col = get_col(['amount', 'txn_amount', 'transaction_amount', 'amt', 'value'])
time_col = get_col(['timestamp', 'date', 'txn_date', 'created_at', 'datetime'])

suspicious = data.get('suspicious_accounts', [])
if not suspicious:
    print('No suspicious accounts in JSON!')
    exit()

suspicious.sort(key=lambda x: x['suspicion_score'], reverse=True)
top_acc = suspicious[0]
acc_id = str(top_acc['account_id'])
score = top_acc['suspicion_score']
patterns = top_acc.get('detected_patterns', [])

print(f'\n--- Cross-Checking Account: {acc_id} ---')
print(f'JSON Score: {score}')
print(f'JSON Patterns: {patterns}')

# Format CSV
df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
df[time_col] = pd.to_datetime(df[time_col], errors='coerce')
df.sort_values(time_col, inplace=True)

df[sender_col] = df[sender_col].astype(str)
df[receiver_col] = df[receiver_col].astype(str)

tx_out = df[df[sender_col] == acc_id]
tx_in = df[df[receiver_col] == acc_id]

print(f'\nTotal Transactions Sent: {len(tx_out)}')
print(f'Total Transactions Received: {len(tx_in)}')
print(f'Total Volume Sent: {tx_out[amount_col].sum()}')
print(f'Total Volume Received: {tx_in[amount_col].sum()}')

if len(tx_out) > 1:
    min_gap = tx_out[time_col].diff().min().total_seconds()
    print(f'\nShortest time between outgoing transactions: {min_gap} seconds')

print('\nUnique Senders to this account:', tx_in[sender_col].nunique())
print('Unique Receivers from this account:', tx_out[receiver_col].nunique())

print('\nTop 3 Recent Incoming Transactions:')
for _, row in tx_in.tail(3).iterrows():
    print(f"  {row[time_col]} - From: {row[sender_col]} - Amount: {row[amount_col]}")
    
print('\nTop 3 Recent Outgoing Transactions:')
for _, row in tx_out.tail(3).iterrows():
    print(f"  {row[time_col]} - To: {row[receiver_col]} - Amount: {row[amount_col]}")
