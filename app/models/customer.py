"""
AML System — Customer Model
============================
Implements FATF Recommendations 10 (CDD), 12 (PEPs), and 22 (DNFBPs).

Tables
------
  customers          — KYC/KYB subject profiles
  sanctions_checks   — history of every sanctions/PEP screening result

Design notes
------------
  · UUID primary key (uuid-ossp, server-side default for bulk inserts)
  · TIMESTAMPTZ everywhere — stored in UTC, rendered per-user timezone in UI
  · JSONB for pep_details / metadata — avoids ALTER TABLE for new data fields
  · search_vector (TSVECTOR) maintained by PostgreSQL trigger (see schema.sql)
  · Partial indexes on is_pep=TRUE and is_sanctioned=TRUE — keeps hot-path
    queries fast without scanning the full table
  · next_review_date index filtered to is_active=TRUE (EDD batch job target)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import (
    CustomerType,
    KYCStatus,
    RiskRating,
    SanctionsCheckType,
    SanctionsMatchStatus,
)

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.alert import Alert


# ──────────────────────────────────────────────────────────────────
# Customer
# ──────────────────────────────────────────────────────────────────

class Customer(Base):
    """
    Central KYC/KYB profile.

    Risk score (0–100) is computed by RiskScoringEngine and stored here
    so that analysts can filter/sort without re-running the engine.

    A dedicated risk_score column avoids a join to a separate risk table
    (BCBS239 Principle 3 — data accuracy and integrity).
    """

    __tablename__ = "customers"

    # ── Identity ─────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.uuid_generate_v4(),
        comment="Internal surrogate key — never exposed to customer",
    )
    external_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="Identifier from core banking system (CIF number, etc.)",
    )
    customer_type: Mapped[CustomerType] = mapped_column(
        String(30),
        nullable=False,
        comment="individual | corporate | financial_institution",
    )

    # ── Individual fields ─────────────────────────────────────────────
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    date_of_birth: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment="Used for DOB cross-validation in sanctions screening",
    )
    national_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        comment="Passport, national ID card, or driving licence number",
    )

    # ── Corporate / entity fields ─────────────────────────────────────
    company_name: Mapped[Optional[str]] = mapped_column(String(255))
    registration_number: Mapped[Optional[str]] = mapped_column(
        String(100),
        comment="Company registration / trade licence number",
    )
    business_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        comment="Business classification (FATF DNFBP scoring)",
    )

    # ── Geography — ISO 3166-1 alpha-3 ───────────────────────────────
    nationality: Mapped[Optional[str]] = mapped_column(String(3))
    country_of_residence: Mapped[Optional[str]] = mapped_column(String(3))
    country_of_incorporation: Mapped[Optional[str]] = mapped_column(String(3))

    # ── Contact ───────────────────────────────────────────────────────
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    address_line1: Mapped[Optional[str]] = mapped_column(String(255))
    address_city: Mapped[Optional[str]] = mapped_column(String(100))
    address_postcode: Mapped[Optional[str]] = mapped_column(String(20))

    # ── Risk profile ──────────────────────────────────────────────────
    risk_rating: Mapped[RiskRating] = mapped_column(
        String(20),
        nullable=False,
        default=RiskRating.low,
        index=True,
        comment="Computed by RiskScoringEngine — updated on every CDD review",
    )
    risk_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="Numeric score 0–100; higher = more risk",
    )
    is_pep: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Politically Exposed Person flag (FATF Rec.12)",
    )
    is_sanctioned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Confirmed match on an active sanctions list",
    )
    pep_details: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        comment="Structured PEP metadata: type (foreign/domestic/RCA), position, country",
    )
    adverse_media_flag: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Set when negative news screening returns a hit",
    )

    # ── KYC lifecycle ─────────────────────────────────────────────────
    kyc_status: Mapped[KYCStatus] = mapped_column(
        String(20),
        nullable=False,
        default=KYCStatus.pending,
        index=True,
    )
    kyc_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_review_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment="Next scheduled CDD review — driven by risk_rating cycle",
    )
    enhanced_due_diligence: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True when FATF Rec.19 EDD measures are required",
    )

    # ── Full-text search ──────────────────────────────────────────────
    search_vector: Mapped[Optional[str]] = mapped_column(
        TSVECTOR,
        comment="Auto-maintained by PostgreSQL trigger update_customer_search_vector()",
    )

    # ── Source of funds ───────────────────────────────────────────────
    source_of_funds: Mapped[Optional[str]] = mapped_column(String(255))
    source_of_wealth: Mapped[Optional[str]] = mapped_column(
        Text,
        comment="Narrative SOW declaration — mandatory for PEPs and high-risk",
    )
    expected_annual_turnover: Mapped[Optional[float]] = mapped_column(Float)
    expected_transaction_volume: Mapped[Optional[int]] = mapped_column(
        String(50),
        comment="Qualitative band: low | medium | high | very_high",
    )

    # ── Metadata ──────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    onboarded_by: Mapped[Optional[str]] = mapped_column(
        String(100),
        comment="User ID of the analyst who completed onboarding",
    )
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        comment="Extensible field for integration-specific attributes",
    )

    # ── Timestamps ────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="customer",
        lazy="select",
        cascade="save-update, merge",
    )
    alerts: Mapped[list["Alert"]] = relationship(
        "Alert",
        back_populates="customer",
        lazy="select",
        cascade="save-update, merge",
    )
    sanctions_checks: Mapped[list["SanctionsCheck"]] = relationship(
        "SanctionsCheck",
        back_populates="customer",
        lazy="select",
        cascade="all, delete-orphan",
        order_by="SanctionsCheck.created_at.desc()",
    )

    # ── Constraints & indexes ─────────────────────────────────────────
    __table_args__ = (
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_customer_risk_score"),
        # Partial indexes on boolean flags — only rows where flag=TRUE are indexed
        Index("ix_customers_is_pep",        "is_pep",        postgresql_where="is_pep = TRUE"),
        Index("ix_customers_is_sanctioned",  "is_sanctioned", postgresql_where="is_sanctioned = TRUE"),
        Index("ix_customers_next_review",    "next_review_date",
              postgresql_where="is_active = TRUE"),
        # Trigram indexes for fuzzy name search (sanctions screening)
        Index("ix_customers_first_name_trgm",  "first_name",
              postgresql_ops={"first_name": "gin_trgm_ops"}, postgresql_using="gin"),
        Index("ix_customers_last_name_trgm",   "last_name",
              postgresql_ops={"last_name": "gin_trgm_ops"}, postgresql_using="gin"),
        Index("ix_customers_company_trgm",     "company_name",
              postgresql_ops={"company_name": "gin_trgm_ops"}, postgresql_using="gin"),
        Index("ix_customers_search_vector",    "search_vector", postgresql_using="gin"),
        Index("ix_customers_risk_rating",      "risk_rating"),
        {"comment": "KYC/KYB customer profiles — FATF Rec.10/12/22"},
    )

    # ── Helpers ───────────────────────────────────────────────────────

    @property
    def full_name(self) -> str:
        """Display name regardless of individual / corporate type."""
        if self.customer_type == CustomerType.individual:
            parts = [self.first_name, self.last_name]
            return " ".join(p for p in parts if p) or self.external_id
        return self.company_name or self.external_id

    @property
    def is_high_risk(self) -> bool:
        return self.risk_rating in (RiskRating.high, RiskRating.prohibited)

    def __repr__(self) -> str:
        return (
            f"<Customer id={self.id} external_id={self.external_id!r} "
            f"type={self.customer_type} rating={self.risk_rating}>"
        )


# ──────────────────────────────────────────────────────────────────
# SanctionsCheck
# ──────────────────────────────────────────────────────────────────

class SanctionsCheck(Base):
    """
    Individual screening result against a single sanctions / PEP list.

    One customer may have many SanctionsCheck rows (one per list per run).
    The most recent row per (customer_id, list_name, check_type) is the
    authoritative match status for that combination.

    FATF Recommendation 6 — Targeted Financial Sanctions
    """

    __tablename__ = "sanctions_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.uuid_generate_v4(),
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # ── Screening details ─────────────────────────────────────────────
    check_type: Mapped[SanctionsCheckType] = mapped_column(
        String(30),
        nullable=False,
        comment="sanctions | pep | adverse_media",
    )
    list_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="OFAC SDN | UN Security Council | EU Consolidated | UK HMT",
    )
    match_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Fuzzy match confidence score 0–100",
    )
    match_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        comment="The name that was matched on the list",
    )
    input_name: Mapped[Optional[str]] = mapped_column(
        String(500),
        comment="The name string that was submitted for screening",
    )
    match_details: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        comment="Full match context: entity_id, program, dob_match, nationality_match, etc.",
    )

    # ── Adjudication ─────────────────────────────────────────────────
    status: Mapped[SanctionsMatchStatus] = mapped_column(
        String(30),
        nullable=False,
        default=SanctionsMatchStatus.no_match,
        index=True,
    )
    screened_by: Mapped[Optional[str]] = mapped_column(
        String(100),
        comment="'system' for automated runs, or analyst user ID for manual",
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(
        String(100),
        comment="Analyst who adjudicated the potential match",
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text)

    # ── Timestamps ────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ── Relationships ─────────────────────────────────────────────────
    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="sanctions_checks",
    )

    __table_args__ = (
        CheckConstraint("match_score >= 0 AND match_score <= 100", name="ck_sanctions_match_score"),
        Index("ix_sanctions_checks_customer_id", "customer_id"),
        Index("ix_sanctions_checks_status",      "status"),
        Index(
            "ix_sanctions_checks_potential",
            "customer_id",
            postgresql_where="status = 'potential_match'",
        ),
        {"comment": "Sanctions/PEP screening history — FATF Rec.6/12"},
    )

    def __repr__(self) -> str:
        return (
            f"<SanctionsCheck id={self.id} customer={self.customer_id} "
            f"list={self.list_name!r} score={self.match_score} status={self.status}>"
        )