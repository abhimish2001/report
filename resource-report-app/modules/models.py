"""
models.py
SQLAlchemy Code-First models for Team Resource Utilization Reporting System.
Defines entity schemas for Microsoft SQL Server persistence.
"""

from __future__ import annotations
import datetime
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Upload(Base):
    __tablename__ = "uploads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    filename = Column(String(500), nullable=True)
    period_label = Column(String(255), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    employee_hint = Column(String(255), nullable=True)
    row_count = Column(Integer, nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    upload_id = Column(Integer, nullable=True)
    date = Column(String(50), nullable=True)
    service = Column(String(255), nullable=True)
    employee = Column(String(255), nullable=True, index=True)
    task = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String(100), nullable=True)
    expected_hrs = Column(Float, nullable=True)
    actual_hrs = Column(Float, nullable=True)
    task_type = Column(String(255), nullable=True)
    stack = Column(String(255), nullable=True)
    priority = Column(String(100), nullable=True)
    start_date = Column(String(50), nullable=True)
    end_date = Column(String(50), nullable=True)
    week = Column(String(100), nullable=True)
    university = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class NormalizationLog(Base):
    __tablename__ = "normalization_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    field_name = Column(String(100), nullable=True)
    raw_value = Column(String(500), nullable=True)
    normalized_value = Column(String(500), nullable=True)
    row_count_affected = Column(Integer, nullable=True)
    logged_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    period_label = Column(String(255), nullable=True)
    cadence = Column(String(50), default="monthly", nullable=True)
    summary_json = Column(Text, nullable=True)
    variance_json = Column(Text, nullable=True)
    ai_insights_json = Column(Text, nullable=True)
    generated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

