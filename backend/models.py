import uuid
import datetime
from sqlalchemy import Column, String, Float, DateTime, JSON, ForeignKey
from .database import Base

class Account(Base):
    __tablename__ = "accounts"

    account_id = Column(String, primary_key=True, index=True)
    graph_score = Column(Float, default=0.0)
    behavior_score = Column(Float, default=0.0)
    anomaly_score = Column(Float, default=0.0)
    final_score = Column(Float, default=0.0)
    patterns = Column(JSON, default=list)

class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id = Column(String, primary_key=True, index=True)
    sender_id = Column(String, ForeignKey("accounts.account_id"), index=True)
    receiver_id = Column(String, ForeignKey("accounts.account_id"), index=True)
    amount = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)

class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String, ForeignKey("accounts.account_id"), index=True)
    final_score = Column(Float, nullable=False)
    explanation = Column(String, nullable=True)
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
