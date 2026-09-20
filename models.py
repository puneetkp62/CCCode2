from sqlalchemy import (
    Column, String, Integer, BigInteger, Float, Date, DateTime, Text,
    ForeignKeyConstraint, ForeignKey, CheckConstraint, UniqueConstraint,
    Boolean, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class EmployeeIdentity(Base):
    __tablename__ = 'employee_identity'
    opaque_id     = Column(String(10),  primary_key=True)
    year          = Column(Integer,     primary_key=True)
    month         = Column(Integer,     primary_key=True)
    employee_id   = Column(String(20),  nullable=False)
    employee_name = Column(String(100), nullable=False)
    designation   = Column(String(150))
    title         = Column(String(100))


class Employee(Base):
    __tablename__ = 'employees'
    opaque_id               = Column(String(10),  primary_key=True)
    year                    = Column(Integer,      primary_key=True)
    month                   = Column(Integer,      primary_key=True)
    sr_no                   = Column(Integer)
    location                = Column(String(100))
    date_of_joining         = Column(Date)
    technova_experience     = Column(Float)
    outside_experience      = Column(Float)
    total_experience        = Column(Float)
    total_experience_range  = Column(String(20))
    date_of_birth           = Column(Date)
    age                     = Column(Integer)
    age_range               = Column(String(20))
    gender                  = Column(String(10))
    core_group              = Column(String(100))
    super_function          = Column(String(100))
    function                = Column(String(100))
    division                = Column(String(100))
    vertical                = Column(String(100))
    role                    = Column(String(100))
    role_function           = Column(String(100))
    employee_category       = Column(String(50))
    employee_sub_category   = Column(String(50))
    band                    = Column(String(20))
    level                   = Column(String(20))
    basic_qualification     = Column(String(150))
    other_qualifications    = Column(String(250))
    qualification_category  = Column(String(100))
    zone                    = Column(String(50))
    budget_code             = Column(String(50))
    blood_group             = Column(String(10))
    level_code              = Column(String(20))
    sub_sect                = Column(String(50))
    city                    = Column(String(50))
    pin_code                = Column(String(10))
    state                   = Column(String(50))

    __table_args__ = (
        ForeignKeyConstraint(
            ['opaque_id', 'year', 'month'],
            ['employee_identity.opaque_id', 'employee_identity.year', 'employee_identity.month']
        ),
    )


class HealthRecord(Base):
    __tablename__ = 'health_records'
    ahc_id                   = Column(BigInteger,  primary_key=True)
    case_id                  = Column(BigInteger)
    application_id           = Column(BigInteger)
    user_id                  = Column(BigInteger)
    opaque_id                = Column(String(10),  nullable=False)
    gender                   = Column(String(10))
    age_group                = Column(String(20))
    city                     = Column(String(50))
    state                    = Column(String(50))
    dc_name                  = Column(String(150))
    appointment_booked_on    = Column(DateTime)
    appointment_completed_on = Column(DateTime)
    reports_upload_on        = Column(DateTime)
    overall_health_score     = Column(Integer)
    overall_risk_category    = Column(String(50))
    risk_stage               = Column(Integer)
    cardiac_stage            = Column(String(50))
    blood_stage              = Column(String(50))
    hepatic_stage            = Column(String(50))
    renal_stage              = Column(String(50))
    diabetic_stage           = Column(String(50))
    vitamind_stage           = Column(String(50))
    thyroid_stage            = Column(String(50))
    cancer_stage             = Column(String(50))
    parameter_name           = Column(String(200))
    value                    = Column(Float)
    value_unit               = Column(String(50))
    normal_range             = Column(String(100))
    risk_level               = Column(String(50))
    category                 = Column(String(100))
    normal                   = Column(String(5))
    low_risk                 = Column(String(5))
    medium_risk              = Column(String(5))
    high_risk                = Column(String(5))
    rn                       = Column(Integer)
    report_year              = Column(Integer)


class EmployeeProfile(Base):
    __tablename__ = 'employee_profiles'
    id                  = Column(Integer, primary_key=True, autoincrement=True)
    opaque_id           = Column(String(10), nullable=False, unique=True)
    blood_group         = Column(String(10))
    family_history      = Column(Text)
    allergies           = Column(Text)
    chronic_conditions  = Column(Text)
    updated_at          = Column(DateTime)


class Consultation(Base):
    __tablename__ = 'consultations'
    id                      = Column(Integer, primary_key=True, autoincrement=True)
    opaque_id               = Column(String(10), nullable=False)
    visit_date              = Column(Date, nullable=False)
    doctor_name             = Column(String(100))
    bp                      = Column(String(20))
    pulse                   = Column(String(10))
    weight                  = Column(String(10))
    height                  = Column(String(10))
    bmi                     = Column(String(10))
    complaint               = Column(Text)
    diagnosis               = Column(Text)
    prev_medicine_history   = Column(Text)
    diet                    = Column(Text)
    exercise                = Column(Text)
    follow_up_date          = Column(Date)
    referral                = Column(String(200))
    goal_notes              = Column(Text)
    goal_doctor_score       = Column(Integer)
    progress_verdict        = Column(String(20))
    progress_note           = Column(String(500))
    new_checkup_reports     = Column(Text)
    created_at              = Column(DateTime)

    medicines = relationship('Medicine', back_populates='consultation',
                             cascade='all, delete-orphan', passive_deletes=True)
    readings  = relationship('ConsultationReading', back_populates='consultation',
                             cascade='all, delete-orphan', passive_deletes=True)

    __table_args__ = (
        CheckConstraint(
            "progress_verdict IS NULL OR progress_verdict IN ('improved','no_change','worsened')",
            name='ck_progress_verdict'
        ),
    )


class Medicine(Base):
    __tablename__ = 'medicines'
    id              = Column(Integer, primary_key=True, autoincrement=True)
    consultation_id = Column(Integer, ForeignKey('consultations.id', ondelete='CASCADE'), nullable=False)
    name            = Column(String(200))
    dose            = Column(String(100))
    frequency       = Column(String(100))
    duration        = Column(String(100))

    consultation = relationship('Consultation', back_populates='medicines')


class ConsultationReading(Base):
    __tablename__ = 'consultation_readings'
    id              = Column(Integer, primary_key=True, autoincrement=True)
    consultation_id = Column(Integer, ForeignKey('consultations.id', ondelete='CASCADE'), nullable=False)
    opaque_id       = Column(String(10), nullable=False)
    parameter_name  = Column(String(200), nullable=False)
    value           = Column(Float, nullable=False)
    unit            = Column(String(50))
    normal_range    = Column(String(100))
    reading_date    = Column(Date, nullable=False)
    risk_level      = Column(String(50))
    risk_override   = Column(Boolean, nullable=False, default=False)
    created_at      = Column(DateTime)

    consultation = relationship('Consultation', back_populates='readings')


class Goal(Base):
    __tablename__ = 'goals'
    id                          = Column(Integer, primary_key=True, autoincrement=True)
    consultation_id             = Column(Integer, ForeignKey('consultations.id'), nullable=False)
    opaque_id                   = Column(String(10), nullable=False)
    goal_type                   = Column(String(50))
    custom_text                 = Column(String(200))
    target_value                = Column(String(100))
    target_date                 = Column(Date)
    status                      = Column(String(20), nullable=False, default='open')
    set_on                      = Column(Date)
    closed_on                   = Column(Date)
    closed_in_consultation_id   = Column(Integer, ForeignKey('consultations.id'))
    points                      = Column(Integer)


class User(Base):
    __tablename__ = 'users'
    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(String(50), nullable=False, unique=True)
    role          = Column(String(20), nullable=False)
    password_hash = Column(String(255), nullable=False)


class GoalType(Base):
    __tablename__ = 'goal_types'
    id        = Column(Integer, primary_key=True, autoincrement=True)
    name      = Column(String(100), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True)


class CheckupType(Base):
    __tablename__ = 'checkup_types'
    id           = Column(Integer, primary_key=True, autoincrement=True)
    name         = Column(String(200), nullable=False, unique=True)
    unit         = Column(String(50))
    normal_range = Column(String(100))
    is_active    = Column(Boolean, nullable=False, default=True)
    created_at   = Column(DateTime)
