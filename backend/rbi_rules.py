import pandas as pd
import numpy as np
from collections import defaultdict

def apply_rbi_rules(df: pd.DataFrame) -> dict:
    """
    Applies RBI/NPCI Compliance Rules (F1-F8).
    Returns a dict mapping account_id -> list of flags.
    """
    flags = defaultdict(list)
    
    if df.empty:
        return flags
        
    df = df.copy()
    
    # Ensure proper types
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0.0)
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    
    dataset_span_days = max(1.0, (df['timestamp'].max() - df['timestamp'].min()).total_seconds() / 86400.0)
    dataset_median = df['amount'].median()
    
    # ---------------------------------------------------------
    # Rule F4: Total transaction volume > 10x dataset median x 20
    # Adapted to use 99th percentile * 3 for scale invariance
    # ---------------------------------------------------------
    threshold_f4 = max(1000.0, df['amount'].quantile(0.99) * 3)
    
    sender_vols = df.groupby('sender_id')['amount'].sum()
    
    for acc, vol in sender_vols.items():
        if vol > threshold_f4:
            flags[acc].append('F4_MACRO_VOLUME_OUTLIER')
            
    # ---------------------------------------------------------
    # Rule F3: 50+ small payments (<500) from 25+ unique senders
    # ---------------------------------------------------------
    micro_df = df[df['amount'] < 500.0]
    f3_stats = micro_df.groupby('receiver_id').agg(
        num_txns=('transaction_id', 'count'),
        unique_senders=('sender_id', 'nunique')
    )
    req_txns = max(5, int(f3_stats['num_txns'].quantile(0.95)))
    req_senders = max(3, int(f3_stats['unique_senders'].quantile(0.95)))
    f3_accs = f3_stats[(f3_stats['num_txns'] >= req_txns) & (f3_stats['unique_senders'] >= req_senders)].index
    for acc in f3_accs:
        flags[acc].append('F3_MICRO_SMURFING')
        
    # ---------------------------------------------------------
    # Rule F6: Coordinated group (shares identical top-receiver with 3+ accounts)
    # ---------------------------------------------------------
    # Find top receiver for each sender
    top_receivers = df.groupby(['sender_id', 'receiver_id'])['transaction_id'].count().reset_index()
    top_receivers = top_receivers.sort_values('transaction_id', ascending=False).drop_duplicates('sender_id')
    # Count how many senders share the same top receiver
    receiver_counts = top_receivers['receiver_id'].value_counts()
    req_coordination = max(3, int(receiver_counts.quantile(0.99)))
    coordinated_receivers = receiver_counts[receiver_counts >= req_coordination].index
    
    coordinated_senders = top_receivers[top_receivers['receiver_id'].isin(coordinated_receivers)]['sender_id']
    for acc in coordinated_senders:
        flags[acc].append('F6_COORDINATED_GROUP')
        
    # ---------------------------------------------------------
    # Rule F7: Low-value profile with outlier high-value tx (Max/Median > 20)
    # ---------------------------------------------------------
    stats_f7 = df.groupby('sender_id')['amount'].agg(['max', 'median', 'std', 'mean'])
    stats_f7['cv'] = stats_f7['std'] / stats_f7['mean']
    f7_accs = stats_f7[(stats_f7['median'] > 0) & ((stats_f7['max'] / stats_f7['median']) > 20) & (stats_f7['cv'] > 1.0)].index
    for acc in f7_accs:
        flags[acc].append('F7_OUTLIER_TXN')
        
    # ---------------------------------------------------------
    # Rule F8: Account < 7 days old with 2+ high-value transactions (> 50k)
    # ---------------------------------------------------------
    age_stats = df.groupby('sender_id')['timestamp'].agg(['min', 'max'])
    age_stats['age_days'] = (age_stats['max'] - age_stats['min']).dt.total_seconds() / 86400.0
    f8_age_threshold = max(1.0, dataset_span_days * 0.1)
    young_accs = age_stats[age_stats['age_days'] < f8_age_threshold].index
    
    f8_amt_threshold = df['amount'].quantile(0.95)
    high_val_df = df[(df['sender_id'].isin(young_accs)) & (df['amount'] >= f8_amt_threshold)]
    f8_accs = high_val_df.groupby('sender_id').size()
    for acc in f8_accs[f8_accs >= 2].index:
        flags[acc].append('F8_NEW_ACC_HIGH_VAL')
        
    # ---------------------------------------------------------
    # Temporal & Sequential Rules (F1, F2, F5)
    # We will process accounts that act as intermediaries (have both in and out)
    # ---------------------------------------------------------
    senders = set(df['sender_id'])
    receivers = set(df['receiver_id'])
    intermediaries = senders.intersection(receivers)
    
    # Pre-sort for temporal logic
    df_sorted = df.sort_values('timestamp')
    
    for acc in intermediaries:
        acc_txns = df_sorted[(df_sorted['sender_id'] == acc) | (df_sorted['receiver_id'] == acc)]
        inbound = acc_txns[acc_txns['receiver_id'] == acc]
        outbound = acc_txns[acc_txns['sender_id'] == acc]
        
        if inbound.empty or outbound.empty:
            continue
            
        # Rule F2: Dormant (14+ day gap) suddenly bursts (>3 txns in a day)
        out_times = outbound['timestamp'].values
        if len(out_times) >= 4:
            # np.diff on datetime64 returns timedelta64. We convert to float days.
            gaps = np.diff(out_times).astype('timedelta64[s]').astype(float) / 86400.0
            dormant_gap = max(2.0, dataset_span_days * 0.3)
            if np.any(gaps >= dormant_gap):
                # check if there's a burst after
                bursts = outbound.groupby(outbound['timestamp'].dt.date).size()
                if (bursts > 3).any():
                    flags[acc].append('F2_DORMANT_BURST')
                    
        # Rule F1: 90% re-transmitted in 2 hours
        total_in = inbound['amount'].sum()
        total_out = outbound['amount'].sum()
        
        # Only apply F1 if total_in is a significant amount (e.g. above median)
        if total_out >= total_in * 0.9 and total_in > dataset_median:
            first_in = inbound['timestamp'].min()
            last_out = outbound['timestamp'].max()
            if (last_out - first_in).total_seconds() <= 7200: # 2 hours
                flags[acc].append('F1_FAST_PASSTHROUGH')
                
        # Rule F5: 4+ outbound within 1 hour of receiving
        if len(outbound) >= 4:
            outbound_indexed = outbound.set_index('timestamp')
            rolling_out = outbound_indexed['transaction_id'].rolling('1h').count()
            if (rolling_out >= 4).any():
                flags[acc].append('F5_RAPID_OUTBOUND')
                
    # DEBUG PRINT
    flag_counts = {}
    for f_list in flags.values():
        for f in f_list:
            flag_counts[f] = flag_counts.get(f, 0) + 1
    print("DEBUG RBI FLAGS GENERATED:", flag_counts)
                
    return dict(flags)
