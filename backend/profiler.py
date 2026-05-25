from sqlalchemy.orm import Session
from sqlalchemy import func
import datetime
import numpy as np

from backend.models import Transaction, Account, Alert

class BehavioralProfiler:
    def __init__(self, db: Session):
        self.db = db

    def profile_account(self, account_id: str):
        """
        Compute rolling statistics (over the last 30 days) for the account.
        Instead of static thresholds, compute:
          - avg transaction amount
          - frequency per time window
          - in/out ratio
          - active hours pattern
        """
        thirty_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=30)
        
        # Pull last 30 days transactions for this account
        txns = self.db.query(Transaction).filter(
            (Transaction.sender_id == account_id) | (Transaction.receiver_id == account_id),
            Transaction.timestamp >= thirty_days_ago
        ).all()

        if not txns:
            return 0.0, []

        amounts = [t.amount for t in txns]
        
        mean_amt = np.mean(amounts)
        std_amt = np.std(amounts) if len(amounts) > 1 else 0.0
        
        # Calculate in/out ratio
        in_amt = sum(t.amount for t in txns if t.receiver_id == account_id)
        out_amt = sum(t.amount for t in txns if t.sender_id == account_id)
        
        in_out_ratio = out_amt / in_amt if in_amt > 0 else float('inf')

        score = 0.0
        anomalies = []

        # Find Z-score of recent transaction if there is a massive spike
        latest = sorted(txns, key=lambda x: x.timestamp)[-1]
        
        if std_amt > 0:
            z_score = (latest.amount - mean_amt) / std_amt
            if z_score > 3.0:
                score += 15.0
                anomalies.append(f"Z-score {z_score:.1f} deviation in transaction amount")

        hour_counts = {}
        for t in txns:
            hr = t.timestamp.hour
            hour_counts[hr] = hour_counts.get(hr, 0) + 1
            
        total_tx = len(txns)
        latest_hr_pct = hour_counts.get(latest.timestamp.hour, 0) / total_tx
        
        if total_tx > 10 and latest_hr_pct < 0.05:
            score += 10.0
            anomalies.append("Active hours pattern anomaly (< 5% historical frequency)")

        if in_amt > 0 and in_out_ratio > 5.0 and total_tx > 5:
            score += 10.0
            anomalies.append("High Out/In ratio")

        return score, anomalies
