"""
AML System - Database Models
All tables follow BCBS239 and FATF Recommendation 16 data requirements.
"""

import enum
import uuid
from datetime import datetime
from sqlalchemy import (
    String, Float, Boolean, DateTime, Text, Enum as SAEnum,
    ForeignKey, Integer, JSON, Index, text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


# ─────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────

class CustomerType(str, enum.Enum):
    individual = "individual"
    corporate = "corporate"
    financial_institution = "financial_institution"


class RiskRating(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    prohibited = "prohibited"


class TransactionType(str, enum.Enum):
    wire_transfer = "wire_transfer"
    cash_deposit = "cash_deposit"
    cash_withdrawal = "cash_withdrawal"
    card_payment = "card_payment"
    internal_transfer = "internal_transfer"
    crypto_exchange = "crypto_exchange"


class AlertStatus(str, enum.Enum):
    open = "open"
    under_review = "under_review"
    escalated = "escalated"
    closed_false_positive = "closed_false_positive"
    closed_sar_filed = "closed_sar_filed"
    closed_no_action = "closed_no_action"


class AlertSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class CaseStatus(str, enum.Enum):
    open = "open"
    investigation = "investigation"
    pending_sar = "pending_sar"
    sar_filed = "sar_filed"
    closed = "closed"


class SanctionsMatchStatus(str, enum.Enum):
    no_match = "no_match"
    potential_match = "potential_match"
    confirmed_match = "confirmed_match"
    false_positive = "false_positive"


# ─────────────────────────────────────────────
# Customer (KYC/KYB subject)
# ─────────────────────────────────────────────

class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    customer_type: Mapped[CustomerType] = mapped_column(SAEnum(CustomerType), nullable=False)

    # Individual fields
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    date_of_birth: Mapped[datetime | None] = mapped_column(DateTime)
    national_id: Mapped[str | None] = mapped_column(String(100))

    # Corporate fields
    company_name: Mapped[str | None] = mapped_column(String(255))
    registration_number: Mapped[str | None] = mapped_column(String(100))
    business_type: Mapped[str | None] = mapped_column(String(100))

    # Common
    nationality: Mapped[str | None] = mapped_column(String(3))   # ISO 3166-1 alpha-3
    country_of_residence: Mapped[str | None] = mapped_column(String(3))
    country_of_incorporation: Mapped[str | None] = mapped_column(String(3))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))

    # Risk profile
    risk_rating: Mapped[RiskRating] = mapped_column(SAEnum(RiskRating), default=RiskRating.low)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)   # 0.0 – 100.0
    is_pep: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sanctioned: Mapped[bool] = mapped_column(Boolean, default=False)
    pep_details: Mapped[dict | None] = mapped_column(JSONB)

    # KYC lifecycle
    kyc_status: Mapped[str] = mapped_column(String(50), default="pending")
    kyc_completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_review_date: Mapped[datetime | None] = mapped_column(DateTime)
    enhanced_due_diligence: Mapped[bool] = mapped_column(Boolean, default=False)

    # Meta
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)

    # Relationships
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="customer", lazy="select")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="customer", lazy="select")
    sanctions_checks: Mapped[list["SanctionsCheck"]] = relationship(back_populates="customer", lazy="select")

    __table_args__ = (
        Index("ix_customers_external_id", "external_id"),
        Index("ix_customers_risk_rating", "risk_rating"),
        Index("ix_customers_is_pep", "is_pep"),
    )


# ─────────────────────────────────────────────
# Transaction
# ─────────────────────────────────────────────

class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)

    transaction_type: Mapped[TransactionType] = mapped_column(SAEnum(TransactionType), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)   # ISO 4217
    amount_usd: Mapped[float | None] = mapped_column(Float)            # Normalised

    # Counterparty
    counterparty_name: Mapped[str | None] = mapped_column(String(255))
    counterparty_account: Mapped[str | None] = mapped_column(String(100))
    counterparty_bank_bic: Mapped[str | None] = mapped_column(String(11))
    counterparty_country: Mapped[str | None] = mapped_column(String(3))

    # Channel
    channel: Mapped[str | None] = mapped_column(String(50))   # mobile, branch, atm, online
    ip_address: Mapped[str | None] = mapped_column(String(45))
    device_id: Mapped[str | None] = mapped_column(String(100))

    # Status
    status: Mapped[str] = mapped_column(String(50), default="completed")
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Description / narrative
    description: Mapped[str | None] = mapped_column(Text)
    purpose_code: Mapped[str | None] = mapped_column(String(10))

    # Timestamps
    transaction_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationships
    customer: Mapped["Customer"] = relationship(back_populates="transactions")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="transaction", lazy="select")

    __table_args__ = (
        Index("ix_transactions_customer_id", "customer_id"),
        Index("ix_transactions_transaction_date", "transaction_date"),
        Index("ix_transactions_is_flagged", "is_flagged"),
        Index("ix_transactions_amount", "amount"),
    )


# ─────────────────────────────────────────────
# Alert
# ─────────────────────────────────────────────

class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"))
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"))

    # Detection metadata
    rule_id: Mapped[str | None] = mapped_column(String(100))
    rule_name: Mapped[str | None] = mapped_column(String(255))
    detection_type: Mapped[str] = mapped_column(String(50))   # rule | ml | graph
    typology: Mapped[str | None] = mapped_column(String(100)) # smurfing | layering | etc.

    severity: Mapped[AlertSeverity] = mapped_column(SAEnum(AlertSeverity), default=AlertSeverity.medium)
    status: Mapped[AlertStatus] = mapped_column(SAEnum(AlertStatus), default=AlertStatus.open)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Investigation
    assigned_to: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict | None] = mapped_column(JSONB)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    due_date: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationships
    customer: Mapped["Customer"] = relationship(back_populates="alerts")
    transaction: Mapped["Transaction | None"] = relationship(back_populates="alerts")
    case: Mapped["Case | None"] = relationship(back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_customer_id", "customer_id"),
        Index("ix_alerts_status", "status"),
        Index("ix_alerts_severity", "severity"),
        Index("ix_alerts_created_at", "created_at"),
    )


# ─────────────────────────────────────────────
# SAR/STR Case
# ─────────────────────────────────────────────

class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)

    status: Mapped[CaseStatus] = mapped_column(SAEnum(CaseStatus), default=CaseStatus.open)
    priority: Mapped[str] = mapped_column(String(20), default="medium")

    # SAR / STR
    sar_reference: Mapped[str | None] = mapped_column(String(100))
    sar_filed_at: Mapped[datetime | None] = mapped_column(DateTime)
    regulator_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    reporting_entity: Mapped[str | None] = mapped_column(String(255))
    goaml_id: Mapped[str | None] = mapped_column(String(100))    # goAML filing reference

    # Narrative
    summary: Mapped[str | None] = mapped_column(Text)
    suspicious_activity_description: Mapped[str | None] = mapped_column(Text)
    typologies: Mapped[list | None] = mapped_column(JSONB)
    total_suspicious_amount: Mapped[float | None] = mapped_column(Float)
    suspected_crime: Mapped[str | None] = mapped_column(String(200))

    # Assignment
    assigned_analyst: Mapped[str | None] = mapped_column(String(100))
    assigned_supervisor: Mapped[str | None] = mapped_column(String(100))
    escalation_level: Mapped[int] = mapped_column(Integer, default=1)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    deadline: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationships
    alerts: Mapped[list["Alert"]] = relationship(back_populates="case", lazy="select")


# ─────────────────────────────────────────────
# Sanctions Check
# ─────────────────────────────────────────────

class SanctionsCheck(Base):
    __tablename__ = "sanctions_checks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)

    check_type: Mapped[str] = mapped_column(String(20))  # sanctions | pep | adverse_media
    list_name: Mapped[str] = mapped_column(String(100))  # OFAC SDN | UN | EU | UK HMT
    match_score: Mapped[float] = mapped_column(Float)    # 0-100 fuzzy score
    match_name: Mapped[str | None] = mapped_column(String(255))
    match_details: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[SanctionsMatchStatus] = mapped_column(SAEnum(SanctionsMatchStatus))
    screened_by: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)

    customer: Mapped["Customer"] = relationship(back_populates="sanctions_checks")

    __table_args__ = (
        Index("ix_sanctions_checks_customer_id", "customer_id"),
        Index("ix_sanctions_checks_status", "status"),
    )


# ─────────────────────────────────────────────
# Audit Log (WORM - Write Once Read Many)
# ─────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        # Postgres partial index — fast filtering by recent events
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
        {
            "postgresql_partition_by": "RANGE (created_at)"  # Monthly partitions
        }
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(100))
    actor_ip: Mapped[str | None] = mapped_column(String(45))

    before_state: Mapped[dict | None] = mapped_column(JSONB)
    after_state: Mapped[dict | None] = mapped_column(JSONB)
    diff: Mapped[dict | None] = mapped_column(JSONB)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    # hash_chain: SHA-256(prev_hash + event payload) — tamper evidence
    hash_chain: Mapped[str | None] = mapped_column(String(64))