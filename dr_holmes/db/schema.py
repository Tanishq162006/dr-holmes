from __future__ import annotations
from sqlalchemy import (
    create_engine, Column, Integer, Float, Text, String,
    UniqueConstraint, Index, event
)
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.engine import Engine
import os


class Base(DeclarativeBase):
    pass


class DiseasePrior(Base):
    __tablename__ = "disease_priors"
    id           = Column(Integer, primary_key=True)
    disease_name = Column(Text, nullable=False)
    icd10        = Column(Text, nullable=True)
    prior_prob   = Column(Float, nullable=False)
    source       = Column(Text, default="ddxplus")
    __table_args__ = (UniqueConstraint("disease_name", "source"),)


class DemographicsPrior(Base):
    __tablename__ = "demographics_priors"
    id           = Column(Integer, primary_key=True)
    disease_name = Column(Text, nullable=False)
    age_min      = Column(Integer, nullable=True)
    age_max      = Column(Integer, nullable=True)
    sex          = Column(String(8), default="any")
    prior_prob   = Column(Float, nullable=False)
    source       = Column(Text, default="ddxplus")


class SymptomLikelihood(Base):
    __tablename__ = "symptom_likelihoods"
    id                      = Column(Integer, primary_key=True)
    disease_name            = Column(Text, nullable=False)
    symptom_name            = Column(Text, nullable=False)
    p_symptom_given_disease = Column(Float, nullable=False)
    p_symptom_given_other   = Column(Float, nullable=False)
    source                  = Column(Text, default="ddxplus")
    __table_args__ = (
        UniqueConstraint("disease_name", "symptom_name", "source"),
        Index("ix_sl_disease", "disease_name"),
        Index("ix_sl_symptom", "symptom_name"),
    )


class TestCharacteristic(Base):
    __tablename__ = "test_characteristics"
    id           = Column(Integer, primary_key=True)
    test_name    = Column(Text, nullable=False)
    disease_name = Column(Text, nullable=False)
    sensitivity  = Column(Float, nullable=False)
    specificity  = Column(Float, nullable=False)
    source       = Column(Text, default="manual")
    notes        = Column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("test_name", "disease_name", "source"),)


def get_engine(db_path: str = "./data/bayes.db"):
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    @event.listens_for(engine, "connect")
    def set_pragmas(conn, _):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def get_session(engine) -> Session:
    return Session(engine)
