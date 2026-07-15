from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import hashlib
import os

Base = declarative_base()

# ---------------- Database connection ----------------
# On Streamlit Cloud: reads DATABASE_URL from Streamlit secrets (a cloud
# Postgres database, e.g. Supabase) so data survives app restarts/redeploys.
# On your own laptop: falls back to the local attendance.db SQLite file, so
# nothing changes for local development.
DB_URL = None
try:
    import streamlit as st
    DB_URL = st.secrets.get("DATABASE_URL", None)
except Exception:
    DB_URL = None

if not DB_URL:
    DB_URL = os.environ.get("DATABASE_URL", "sqlite:///attendance.db")

engine = create_engine(DB_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

class Teacher(Base):
    __tablename__ = "teachers"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password_hash = Column(String)
    display_name = Column(String)

class Class(Base):
    __tablename__ = "classes"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    teacher_id = Column(Integer)

class Student(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    class_id = Column(Integer)
    photo_path = Column(String)
    encoding_json = Column(String)

class AttendanceSession(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True)
    class_id = Column(Integer)
    photo_path = Column(String)
    threshold = Column(Float)
    created_at = Column(DateTime, default=datetime.now)

class AttendanceRecord(Base):
    __tablename__ = "records"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer)
    student_id = Column(Integer)
    student_name = Column(String)
    status = Column(String)

Base.metadata.create_all(engine)

def _hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_teacher(username, password, display_name=None):
    db = Session()
    existing = db.query(Teacher).filter_by(username=username).first()
    if existing:
        return None
    t = Teacher(username=username, password_hash=_hash_password(password), display_name=display_name or username)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t

def authenticate_teacher(username, password):
    db = Session()
    t = db.query(Teacher).filter_by(username=username).first()
    if t and t.password_hash == _hash_password(password):
        return t
    return None

def get_all_teachers():
    """Used by the Student Portal to let students pick their teacher (no login needed)"""
    db = Session()
    return db.query(Teacher).all()

def create_class(name, teacher_id):
    db = Session()
    cls = Class(name=name, teacher_id=teacher_id)
    db.add(cls)
    db.commit()
    db.refresh(cls)
    return cls

def get_classes_for_teacher(teacher_id):
    db = Session()
    return db.query(Class).filter_by(teacher_id=teacher_id).all()

def delete_class(class_id):
    """Deletes the class along with its students, sessions, and attendance records"""
    db = Session()
    sessions = db.query(AttendanceSession).filter_by(class_id=class_id).all()
    session_ids = [s.id for s in sessions]
    if session_ids:
        db.query(AttendanceRecord).filter(AttendanceRecord.session_id.in_(session_ids)).delete(synchronize_session=False)
    db.query(AttendanceSession).filter_by(class_id=class_id).delete(synchronize_session=False)
    db.query(Student).filter_by(class_id=class_id).delete(synchronize_session=False)
    db.query(Class).filter_by(id=class_id).delete(synchronize_session=False)
    db.commit()
    return True

def get_students_by_class(class_id):
    db = Session()
    return db.query(Student).filter_by(class_id=class_id).all()

def add_student(name, class_id, photo_path, encoding_list):
    import json
    db = Session()
    s = Student(name=name, class_id=class_id, photo_path=photo_path, encoding_json=json.dumps(encoding_list))
    db.add(s)
    db.commit()
    db.refresh(s)
    return s

def delete_student(student_id):
    db = Session()
    s = db.query(Student).filter_by(id=student_id).first()
    if s:
        db.delete(s)
        db.commit()
        return True
    return False

def create_attendance_session(class_id, photo_path, threshold):
    db = Session()
    sess = AttendanceSession(class_id=class_id, photo_path=photo_path, threshold=threshold)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess

def save_attendance_record(session_id, student_id, student_name, status):
    db = Session()
    rec = AttendanceRecord(session_id=session_id, student_id=student_id, student_name=student_name, status=status)
    db.add(rec)
    db.commit()

def update_attendance_status(record_id, new_status):
    db = Session()
    rec = db.query(AttendanceRecord).filter_by(id=record_id).first()
    if rec:
        rec.status = new_status
        db.commit()
        return True
    return False

def get_sessions_for_class(class_id):
    db = Session()
    return db.query(AttendanceSession).filter_by(class_id=class_id).order_by(AttendanceSession.created_at.desc()).all()

def get_records_for_session(session_id):
    db = Session()
    return db.query(AttendanceRecord).filter_by(session_id=session_id).all()

def get_attendance_history_for_student(student_id):
    """Used by the Student Portal's 'Check My Attendance' feature"""
    db = Session()
    records = db.query(AttendanceRecord).filter_by(student_id=student_id).all()
    history = []
    for r in records:
        sess = db.query(AttendanceSession).filter_by(id=r.session_id).first()
        history.append({"date": sess.created_at if sess else None, "status": r.status})
    history.sort(key=lambda x: x["date"] or datetime.min, reverse=True)
    return history
