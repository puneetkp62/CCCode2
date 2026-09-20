"""
EmpStats — Employee Health Management System
Flask backend with JWT auth, SQL Server, and opaque-ID anonymisation.
"""

import io, os, re, json, string, secrets, math
from datetime import datetime, date, timedelta, timezone

import bcrypt
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import create_engine, text, func, or_, and_, desc, case
from sqlalchemy.orm import sessionmaker, scoped_session

from models import (
    Base, EmployeeIdentity, Employee, HealthRecord, EmployeeProfile,
    Consultation, Medicine, ConsultationReading, Goal, User, GoalType,
    CheckupType
)

load_dotenv()

# ── App setup ────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder='public', static_url_path='')
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET', 'change-me')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=10)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB upload limit

jwt = JWTManager(app)
limiter = Limiter(get_remote_address, app=app, default_limits=[])

# ── Database ─────────────────────────────────────────────────────────────────

DB_USER   = os.getenv('DB_USER', 'sa')
DB_PWD    = os.getenv('DB_PWD', '')
DB_SERVER = os.getenv('DB_SERVER', 'localhost')
DB_NAME   = os.getenv('DB_NAME', 'EmpStats')

conn_str = (
    f"mssql+pyodbc://{DB_USER}:{DB_PWD}@{DB_SERVER}/{DB_NAME}"
    f"?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
)
engine = create_engine(conn_str, pool_pre_ping=True, pool_recycle=1800)
Session = scoped_session(sessionmaker(bind=engine))

# ── IST helpers ──────────────────────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))

def now_ist():
    return datetime.now(IST).replace(tzinfo=None)

def today_ist():
    return datetime.now(IST).date()

# ── Utility helpers ──────────────────────────────────────────────────────────

MONTH_MAP = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12
}
MONTH_NAMES = {v: k.capitalize() for k, v in MONTH_MAP.items()}


def parse_month(val):
    if val is None:
        return None
    if isinstance(val, (int, float)) and not math.isnan(val):
        return int(val)
    s = str(val).strip().lower()
    if s.isdigit():
        return int(s)
    return MONTH_MAP.get(s)


def fmt_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.strftime('%Y-%m-%d')


def parse_date(s):
    if not s:
        return None
    if isinstance(s, date):
        return s
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None


def safe_json_loads(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def like_pattern(q):
    escaped = q.replace('[', '[[]').replace('%', '[%]').replace('_', '[_]')
    return f'%{escaped}%'


def generate_opaque_id(length=8):
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def _json_safe(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat() if obj else None
    return obj


def _data_error(msg, code=400):
    return jsonify({'error': msg}), code


# ── Risk auto-calculation ────────────────────────────────────────────────────

def parse_range(normal_range):
    if not normal_range:
        return None, None
    s = str(normal_range).strip()
    m = re.match(r'^[<≤]\s*([\d.]+)$', s)
    if m:
        return None, float(m.group(1))
    m = re.match(r'^[>≥]\s*([\d.]+)$', s)
    if m:
        return float(m.group(1)), None
    m = re.match(r'^([\d.]+)\s*[-–—]\s*([\d.]+)$', s)
    if m:
        return float(m.group(1)), float(m.group(2))
    parts = s.split('-')
    if len(parts) == 2:
        try:
            return float(parts[0].strip()), float(parts[1].strip())
        except ValueError:
            pass
    return None, None


def calculate_risk(value, normal_range):
    lo, hi = parse_range(normal_range)
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None:
        if lo <= value <= hi:
            return '1 Normal'
        span = hi - lo if hi > lo else 1
        if value < lo:
            pct = (lo - value) / span
        else:
            pct = (value - hi) / span
    elif hi is not None:
        if value <= hi:
            return '1 Normal'
        pct = (value - hi) / hi if hi else 1
    else:
        if value >= lo:
            return '1 Normal'
        pct = (lo - value) / lo if lo else 1

    if pct <= 0.2:
        return '2 Low Risk'
    elif pct <= 0.5:
        return '3 Medium Risk'
    else:
        return '4 High Risk'


# ── Opaque-ID resolution ────────────────────────────────────────────────────

def get_or_create_opaque_id(session, employee_id, employee_name,
                            designation, title, year, month):
    month_int = parse_month(month) if not isinstance(month, int) else month
    existing = session.query(EmployeeIdentity).filter(
        EmployeeIdentity.employee_id == str(employee_id)
    ).first()
    oid = existing.opaque_id if existing else generate_opaque_id()
    row = session.query(EmployeeIdentity).filter(
        EmployeeIdentity.opaque_id == oid,
        EmployeeIdentity.year == int(year),
        EmployeeIdentity.month == month_int
    ).first()
    if row:
        row.employee_name = str(employee_name) if employee_name else row.employee_name
        row.designation = str(designation) if designation else row.designation
        row.title = str(title) if title else row.title
    else:
        row = EmployeeIdentity(
            opaque_id=oid, year=int(year), month=month_int,
            employee_id=str(employee_id),
            employee_name=str(employee_name) if employee_name else '',
            designation=str(designation) if designation else None,
            title=str(title) if title else None
        )
        session.add(row)
    return oid, month_int


def resolve_opaque_id(session, employee_id):
    row = session.query(EmployeeIdentity).filter(
        EmployeeIdentity.employee_id == str(employee_id)
    ).first()
    return row.opaque_id if row else None


def get_identity(session, opaque_id):
    return session.query(EmployeeIdentity).filter(
        EmployeeIdentity.opaque_id == opaque_id
    ).order_by(desc(EmployeeIdentity.year), desc(EmployeeIdentity.month)).first()


# ── Latest employee snapshot SQL ─────────────────────────────────────────────

def latest_employee_sql():
    return text("""
        SELECT e.*, ei.employee_id, ei.employee_name, ei.designation, ei.title
        FROM employees e
        JOIN employee_identity ei
          ON ei.opaque_id = e.opaque_id AND ei.year = e.year AND ei.month = e.month
        WHERE e.year = (SELECT MAX(e2.year) FROM employees e2
                        WHERE e2.opaque_id = e.opaque_id)
          AND e.month = (SELECT MAX(e3.month) FROM employees e3
                         WHERE e3.opaque_id = e.opaque_id
                           AND e3.year = e.year)
    """)


def get_latest_employee(session, opaque_id):
    sql = text("""
        SELECT TOP 1 e.*, ei.employee_id, ei.employee_name, ei.designation, ei.title
        FROM employees e
        JOIN employee_identity ei
          ON ei.opaque_id = e.opaque_id AND ei.year = e.year AND ei.month = e.month
        WHERE e.opaque_id = :oid
        ORDER BY e.year DESC, e.month DESC
    """)
    row = session.execute(sql, {'oid': opaque_id}).mappings().first()
    return dict(row) if row else None


# ── Auth decorator ───────────────────────────────────────────────────────────

def role_required(*roles):
    from functools import wraps
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            identity = get_jwt_identity()
            parts = identity.split(':', 1)
            if len(parts) != 2 or parts[0] not in roles:
                return _data_error('Forbidden.', 403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def current_user():
    identity = get_jwt_identity()
    parts = identity.split(':', 1)
    return {'role': parts[0], 'username': parts[1] if len(parts) > 1 else ''}


# ── Excel download helper ───────────────────────────────────────────────────

def _excel_download(rows, columns, filename):
    df = pd.DataFrame(rows, columns=columns)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='Data')
    buf.seek(0)
    return send_file(buf, download_name=filename, as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ── Serve frontend ───────────────────────────────────────────────────────────

@app.route('/')
def serve_index():
    return send_from_directory('public', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('public', path)


# ══════════════════════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({'orgName': os.getenv('ORG_NAME', 'Employee Health Centre')})


@app.route('/api/login', methods=['POST'])
@limiter.limit('10/minute')
def login():
    data = request.get_json(silent=True) or {}
    role     = (data.get('role') or '').strip().lower()
    username = (data.get('username') or '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'ok': False, 'error': 'Please enter your username and password.'})
    if role not in ('doctor', 'hr', 'org', 'admin'):
        return jsonify({'ok': False, 'error': 'Invalid role.'})

    s = Session()
    try:
        user = s.query(User).filter(User.username == username).first()
        if not user or user.role != role:
            return jsonify({'ok': False, 'error': 'Invalid credentials.'})
        if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            return jsonify({'ok': False, 'error': 'Invalid credentials.'})
        token = create_access_token(identity=f'{role}:{username}')
        return jsonify({'ok': True, 'token': token, 'role': role, 'username': username})
    finally:
        Session.remove()


@app.route('/api/verify', methods=['POST'])
@jwt_required()
def verify():
    u = current_user()
    return jsonify({'ok': True, 'role': u['role'], 'username': u['username']})


# ══════════════════════════════════════════════════════════════════════════════
# DOCTOR ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/employees/search', methods=['GET'])
@role_required('doctor', 'hr', 'org', 'admin')
def search_employees():
    q = (request.args.get('q') or '').strip()
    if len(q) < 3:
        return jsonify({'results': []})
    s = Session()
    try:
        pattern = like_pattern(q)
        sql = text("""
            SELECT DISTINCT TOP 15
                ei.opaque_id, ei.employee_id, ei.employee_name,
                ei.designation, e.location
            FROM employee_identity ei
            JOIN employees e ON e.opaque_id = ei.opaque_id
                AND e.year = ei.year AND e.month = ei.month
            WHERE (ei.employee_name LIKE :pat OR ei.employee_id LIKE :pat)
              AND e.year = (SELECT MAX(e2.year) FROM employees e2
                            WHERE e2.opaque_id = ei.opaque_id)
              AND e.month = (SELECT MAX(e3.month) FROM employees e3
                             WHERE e3.opaque_id = ei.opaque_id
                               AND e3.year = e.year)
            ORDER BY ei.employee_name
        """)
        rows = s.execute(sql, {'pat': pattern}).mappings().all()
        results = [dict(r) for r in rows]
        return jsonify({'results': results})
    finally:
        Session.remove()


@app.route('/api/employee/<oid>', methods=['GET'])
@role_required('doctor', 'hr', 'org', 'admin')
def get_employee(oid):
    s = Session()
    try:
        emp = get_latest_employee(s, oid)
        if not emp:
            identity = s.query(EmployeeIdentity).filter(
                EmployeeIdentity.employee_id == oid
            ).order_by(desc(EmployeeIdentity.year), desc(EmployeeIdentity.month)).first()
            if identity:
                emp = get_latest_employee(s, identity.opaque_id)
            if not emp:
                return _data_error('Employee not found.', 404)
        for k in list(emp.keys()):
            emp[k] = _json_safe(emp[k])
        return jsonify(emp)
    finally:
        Session.remove()


@app.route('/api/patient/<oid>', methods=['GET'])
@role_required('doctor')
def get_patient(oid):
    s = Session()
    try:
        emp = get_latest_employee(s, oid)
        if not emp:
            return _data_error('Employee not found.', 404)
        for k in list(emp.keys()):
            emp[k] = _json_safe(emp[k])

        profile = s.query(EmployeeProfile).filter(
            EmployeeProfile.opaque_id == oid
        ).first()
        profile_data = None
        if profile:
            profile_data = {
                'blood_group': profile.blood_group,
                'family_history': profile.family_history,
                'allergies': profile.allergies,
                'chronic_conditions': profile.chronic_conditions
            }

        consults = s.execute(text("""
            SELECT c.*, ei.employee_name
            FROM consultations c
            JOIN employee_identity ei ON ei.opaque_id = c.opaque_id
              AND ei.year = (SELECT MAX(ei2.year) FROM employee_identity ei2
                             WHERE ei2.opaque_id = c.opaque_id)
              AND ei.month = (SELECT MAX(ei3.month) FROM employee_identity ei3
                              WHERE ei3.opaque_id = c.opaque_id AND ei3.year = ei.year)
            WHERE c.opaque_id = :oid
            ORDER BY c.visit_date DESC, c.id DESC
        """), {'oid': oid}).mappings().all()

        consult_list = []
        for c in consults:
            cd = {k: _json_safe(v) for k, v in dict(c).items()}
            cd['exercise'] = safe_json_loads(cd.get('exercise'))
            cid = cd['id']
            meds = s.query(Medicine).filter(Medicine.consultation_id == cid).all()
            cd['medicines'] = [{'name': m.name, 'dose': m.dose,
                                'frequency': m.frequency, 'duration': m.duration}
                               for m in meds]
            readings = s.query(ConsultationReading).filter(
                ConsultationReading.consultation_id == cid
            ).all()
            cd['readings'] = [{
                'parameter_name': r.parameter_name, 'value': r.value,
                'unit': r.unit, 'normal_range': r.normal_range,
                'reading_date': fmt_date(r.reading_date),
                'risk_level': r.risk_level, 'risk_override': r.risk_override
            } for r in readings]
            goals = s.query(Goal).filter(Goal.consultation_id == cid).all()
            cd['goals'] = [{
                'id': g.id, 'goal_type': g.goal_type, 'custom_text': g.custom_text,
                'target_value': g.target_value, 'target_date': fmt_date(g.target_date),
                'status': g.status, 'set_on': fmt_date(g.set_on),
                'closed_on': fmt_date(g.closed_on), 'points': g.points
            } for g in goals]
            consult_list.append(cd)

        ahc_rows = s.execute(text("""
            SELECT parameter_name, value, value_unit, normal_range,
                   risk_level, category, report_year,
                   appointment_completed_on
            FROM health_records
            WHERE opaque_id = :oid
            ORDER BY report_year DESC, category, parameter_name
        """), {'oid': oid}).mappings().all()
        ahc = [{k: _json_safe(v) for k, v in dict(r).items()} for r in ahc_rows]

        open_goals = s.query(Goal).filter(
            Goal.opaque_id == oid, Goal.status == 'open'
        ).order_by(desc(Goal.set_on)).all()
        open_goals_list = [{
            'id': g.id, 'goal_type': g.goal_type, 'custom_text': g.custom_text,
            'target_value': g.target_value, 'target_date': fmt_date(g.target_date),
            'status': g.status, 'set_on': fmt_date(g.set_on)
        } for g in open_goals]

        consult_count = s.query(func.count(Consultation.id)).filter(
            Consultation.opaque_id == oid
        ).scalar() or 0

        return jsonify({
            'employee': emp,
            'profile': profile_data,
            'consultations': consult_list,
            'ahc': ahc,
            'open_goals': open_goals_list,
            'consultation_count': consult_count
        })
    finally:
        Session.remove()


@app.route('/api/consultation', methods=['POST'])
@role_required('doctor')
def save_consultation():
    data = request.get_json(silent=True) or {}
    u = current_user()
    oid = data.get('opaque_id', '').strip()
    if not oid:
        return _data_error('Missing opaque_id.')

    s = Session()
    try:
        visit_date = parse_date(data.get('visit_date')) or today_ist()

        prof = s.query(EmployeeProfile).filter(
            EmployeeProfile.opaque_id == oid
        ).first()
        if not prof:
            prof = EmployeeProfile(opaque_id=oid)
            s.add(prof)
        if data.get('blood_group'):
            prof.blood_group = data['blood_group']
        if data.get('family_history'):
            prof.family_history = data['family_history']
        if data.get('allergies'):
            prof.allergies = data['allergies']
        if data.get('chronic_conditions'):
            prof.chronic_conditions = data['chronic_conditions']
        prof.updated_at = now_ist()

        c = Consultation(
            opaque_id=oid,
            visit_date=visit_date,
            doctor_name=u['username'],
            bp=data.get('bp'),
            pulse=data.get('pulse'),
            weight=data.get('weight'),
            height=data.get('height'),
            bmi=data.get('bmi'),
            complaint=data.get('complaint'),
            diagnosis=data.get('diagnosis'),
            prev_medicine_history=data.get('prev_medicine_history'),
            diet=data.get('diet'),
            exercise=json.dumps(data.get('exercise')) if data.get('exercise') else None,
            follow_up_date=parse_date(data.get('follow_up_date')),
            referral=data.get('referral'),
            goal_notes=data.get('goal_notes'),
            goal_doctor_score=data.get('goal_doctor_score'),
            progress_verdict=data.get('progress_verdict'),
            progress_note=data.get('progress_note'),
            created_at=now_ist()
        )
        s.add(c)
        s.flush()

        for m in (data.get('medicines') or []):
            if not m.get('name'):
                continue
            s.add(Medicine(
                consultation_id=c.id, name=m['name'],
                dose=m.get('dose'), frequency=m.get('frequency'),
                duration=m.get('duration')
            ))

        for r in (data.get('readings') or []):
            if not r.get('parameter') and not r.get('parameter_name'):
                continue
            param = r.get('parameter') or r.get('parameter_name')
            val = r.get('value')
            try:
                val_float = float(val)
            except (TypeError, ValueError):
                continue
            nr = r.get('normal_range', '')
            risk = r.get('risk_level')
            override = bool(r.get('risk_override', False))
            if not risk or not override:
                auto_risk = calculate_risk(val_float, nr)
                if not override:
                    risk = auto_risk or risk
            s.add(ConsultationReading(
                consultation_id=c.id, opaque_id=oid,
                parameter_name=param, value=val_float,
                unit=r.get('unit'), normal_range=nr,
                reading_date=parse_date(r.get('reading_date')) or visit_date,
                risk_level=risk, risk_override=override,
                created_at=now_ist()
            ))

        for g in (data.get('goals') or []):
            if not g.get('type') and not g.get('goal_type'):
                continue
            s.add(Goal(
                consultation_id=c.id, opaque_id=oid,
                goal_type=g.get('type') or g.get('goal_type'),
                custom_text=g.get('custom_text'),
                target_value=g.get('target_value'),
                target_date=parse_date(g.get('target_date')),
                status='open',
                set_on=visit_date
            ))

        for gr in (data.get('goal_reviews') or []):
            gid = gr.get('goal_id')
            if not gid:
                continue
            goal = s.query(Goal).filter(Goal.id == gid, Goal.opaque_id == oid).first()
            if not goal:
                continue
            action = gr.get('action', '')
            if action == 'close':
                goal.status = 'closed'
                goal.closed_on = visit_date
                goal.closed_in_consultation_id = c.id
                goal.points = gr.get('points')
            elif action == 'update':
                if gr.get('target_value'):
                    goal.target_value = gr['target_value']
                if gr.get('target_date'):
                    goal.target_date = parse_date(gr['target_date'])

        s.commit()
        return jsonify({'ok': True, 'id': c.id})
    except Exception as ex:
        s.rollback()
        return _data_error(f'Save failed: {str(ex)}', 500)
    finally:
        Session.remove()


@app.route('/api/consultation-count/<oid>', methods=['GET'])
@role_required('doctor')
def consultation_count(oid):
    s = Session()
    try:
        cnt = s.query(func.count(Consultation.id)).filter(
            Consultation.opaque_id == oid
        ).scalar() or 0
        return jsonify({'count': cnt})
    finally:
        Session.remove()


@app.route('/api/checkup-types', methods=['GET'])
@role_required('doctor', 'admin')
def list_checkup_types():
    s = Session()
    try:
        rows = s.query(CheckupType).filter(
            CheckupType.is_active == True
        ).order_by(CheckupType.name).all()
        return jsonify([{
            'id': r.id, 'name': r.name, 'unit': r.unit,
            'normal_range': r.normal_range
        } for r in rows])
    finally:
        Session.remove()


@app.route('/api/goal-types', methods=['GET'])
@role_required('doctor', 'admin')
def list_goal_types():
    s = Session()
    try:
        rows = s.query(GoalType).filter(
            GoalType.is_active == True
        ).order_by(GoalType.name).all()
        return jsonify([{'id': r.id, 'name': r.name} for r in rows])
    finally:
        Session.remove()


# ══════════════════════════════════════════════════════════════════════════════
# ORG DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/org/dashboard', methods=['GET'])
@role_required('org', 'admin')
def org_dashboard():
    s = Session()
    try:
        filters = _build_slicer_filters(request.args)

        emp_sql = text("""
            SELECT e.opaque_id, e.age, e.age_range, e.gender, e.division,
                   e.location, e.band, e.zone, e.vertical,
                   ei.employee_name, ei.designation
            FROM employees e
            JOIN employee_identity ei ON ei.opaque_id = e.opaque_id
              AND ei.year = e.year AND ei.month = e.month
            WHERE e.year = (SELECT MAX(e2.year) FROM employees e2
                            WHERE e2.opaque_id = e.opaque_id)
              AND e.month = (SELECT MAX(e3.month) FROM employees e3
                             WHERE e3.opaque_id = e.opaque_id AND e3.year = e.year)
        """)
        all_emps = [dict(r) for r in s.execute(emp_sql).mappings().all()]
        emps = _apply_slicer(all_emps, filters)
        oid_set = {e['opaque_id'] for e in emps}

        # AHC risk data
        hr_sql = text("""
            SELECT opaque_id, parameter_name, value, value_unit, normal_range,
                   risk_level, category, overall_risk_category, risk_stage,
                   cardiac_stage, blood_stage, hepatic_stage, renal_stage,
                   diabetic_stage, vitamind_stage, thyroid_stage, report_year
            FROM health_records
        """)
        all_hr = [dict(r) for r in s.execute(hr_sql).mappings().all()]
        hr = [r for r in all_hr if r['opaque_id'] in oid_set]

        # Consultation readings risk data (UNION with AHC)
        cr_sql = text("""
            SELECT opaque_id, parameter_name, value, unit AS value_unit,
                   normal_range, risk_level, reading_date
            FROM consultation_readings
            WHERE risk_level IS NOT NULL
        """)
        all_cr = [dict(r) for r in s.execute(cr_sql).mappings().all()]
        cr = [r for r in all_cr if r['opaque_id'] in oid_set]

        # Abnormal by employee (AHC high risk)
        abnormal_by_emp = {}
        for r in hr:
            if r.get('risk_level') == '4 High Risk':
                oid = r['opaque_id']
                if oid not in abnormal_by_emp:
                    abnormal_by_emp[oid] = []
                abnormal_by_emp[oid].append(r['parameter_name'])

        # Also include consultation readings with high risk
        for r in cr:
            if r.get('risk_level') == '4 High Risk':
                oid = r['opaque_id']
                if oid not in abnormal_by_emp:
                    abnormal_by_emp[oid] = []
                abnormal_by_emp[oid].append(r['parameter_name'])

        # Flagged readings (high risk count by parameter)
        flagged = {}
        for r in hr:
            if r.get('risk_level') == '4 High Risk' and r.get('parameter_name'):
                flagged[r['parameter_name']] = flagged.get(r['parameter_name'], 0) + 1
        for r in cr:
            if r.get('risk_level') == '4 High Risk' and r.get('parameter_name'):
                flagged[r['parameter_name']] = flagged.get(r['parameter_name'], 0) + 1

        # Risk distribution by category (blood sugar, lipid, thyroid)
        def risk_dist(stage_key):
            counts = {'Normal': 0, 'Low Risk': 0, 'Medium Risk': 0, 'High Risk': 0, 'Not Available': 0}
            seen = set()
            for r in hr:
                oid = r['opaque_id']
                if oid in seen:
                    continue
                stage = r.get(stage_key, 'Not Available') or 'Not Available'
                if 'Normal' in stage:
                    counts['Normal'] += 1
                elif 'Low' in stage:
                    counts['Low Risk'] += 1
                elif 'Medium' in stage:
                    counts['Medium Risk'] += 1
                elif 'High' in stage:
                    counts['High Risk'] += 1
                else:
                    counts['Not Available'] += 1
                seen.add(oid)
            return counts

        blood_sugar = risk_dist('diabetic_stage')
        lipid = risk_dist('cardiac_stage')
        thyroid = risk_dist('thyroid_stage')

        # Overall risk distribution
        overall = {'Excellent': 0, 'Good': 0, 'Average': 0,
                   'Below Average': 0, 'Concerning': 0}
        seen_overall = set()
        for r in hr:
            oid = r['opaque_id']
            if oid in seen_overall:
                continue
            cat = r.get('overall_risk_category', 'Good') or 'Good'
            if cat in overall:
                overall[cat] += 1
            seen_overall.add(oid)

        # In-house consultations
        inhouse_sql = text("""
            SELECT c.opaque_id, c.visit_date, c.doctor_name, c.complaint,
                   c.diagnosis, ei.employee_name
            FROM consultations c
            JOIN employee_identity ei ON ei.opaque_id = c.opaque_id
              AND ei.year = (SELECT MAX(ei2.year) FROM employee_identity ei2
                             WHERE ei2.opaque_id = c.opaque_id)
              AND ei.month = (SELECT MAX(ei3.month) FROM employee_identity ei3
                              WHERE ei3.opaque_id = c.opaque_id AND ei3.year = ei.year)
            ORDER BY c.visit_date DESC
        """)
        inhouse_all = [dict(r) for r in s.execute(inhouse_sql).mappings().all()]
        inhouse = [r for r in inhouse_all if r['opaque_id'] in oid_set]
        for r in inhouse:
            r['visit_date'] = _json_safe(r['visit_date'])

        return jsonify({
            'emp_list': emps,
            'total_employees': len(emps),
            'abnormal_by_emp': abnormal_by_emp,
            'flagged_readings': flagged,
            'blood_sugar': blood_sugar,
            'lipid': lipid,
            'thyroid': thyroid,
            'overall_risk': overall,
            'inhouse': inhouse[:100]
        })
    finally:
        Session.remove()


@app.route('/api/org/trend', methods=['GET'])
@role_required('org', 'admin')
def org_trend():
    s = Session()
    try:
        sql = text("""
            SELECT report_year, overall_risk_category, COUNT(DISTINCT opaque_id) AS cnt
            FROM health_records
            WHERE report_year IS NOT NULL AND overall_risk_category IS NOT NULL
            GROUP BY report_year, overall_risk_category
            ORDER BY report_year
        """)
        rows = s.execute(sql).mappings().all()
        result = {}
        for r in rows:
            yr = r['report_year']
            if yr not in result:
                result[yr] = {}
            result[yr][r['overall_risk_category']] = r['cnt']
        return jsonify(result)
    finally:
        Session.remove()


# ══════════════════════════════════════════════════════════════════════════════
# HR DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/hr/dashboard', methods=['GET'])
@role_required('hr', 'admin')
def hr_dashboard():
    s = Session()
    try:
        filters = _build_slicer_filters(request.args)

        emp_sql = text("""
            SELECT e.opaque_id, e.division, e.location, e.band, e.zone, e.vertical,
                   ei.employee_name, ei.designation
            FROM employees e
            JOIN employee_identity ei ON ei.opaque_id = e.opaque_id
              AND ei.year = e.year AND ei.month = e.month
            WHERE e.year = (SELECT MAX(e2.year) FROM employees e2
                            WHERE e2.opaque_id = e.opaque_id)
              AND e.month = (SELECT MAX(e3.month) FROM employees e3
                             WHERE e3.opaque_id = e.opaque_id AND e3.year = e.year)
        """)
        all_emps = [dict(r) for r in s.execute(emp_sql).mappings().all()]
        emps = _apply_slicer(all_emps, filters)
        oid_set = {e['opaque_id'] for e in emps}

        # Goals
        goals_sql = text("""
            SELECT g.*, c.visit_date, c.doctor_name, ei.employee_name
            FROM goals g
            JOIN consultations c ON c.id = g.consultation_id
            JOIN employee_identity ei ON ei.opaque_id = g.opaque_id
              AND ei.year = (SELECT MAX(ei2.year) FROM employee_identity ei2
                             WHERE ei2.opaque_id = g.opaque_id)
              AND ei.month = (SELECT MAX(ei3.month) FROM employee_identity ei3
                              WHERE ei3.opaque_id = g.opaque_id AND ei3.year = ei.year)
        """)
        all_goals = [dict(r) for r in s.execute(goals_sql).mappings().all()]
        goals = [g for g in all_goals if g['opaque_id'] in oid_set]
        for g in goals:
            for k in list(g.keys()):
                g[k] = _json_safe(g[k])

        # Employee scores from consultations
        scores_sql = text("""
            SELECT c.opaque_id, c.goal_doctor_score, c.visit_date,
                   c.doctor_name, ei.employee_name
            FROM consultations c
            JOIN employee_identity ei ON ei.opaque_id = c.opaque_id
              AND ei.year = (SELECT MAX(ei2.year) FROM employee_identity ei2
                             WHERE ei2.opaque_id = c.opaque_id)
              AND ei.month = (SELECT MAX(ei3.month) FROM employee_identity ei3
                              WHERE ei3.opaque_id = c.opaque_id AND ei3.year = ei.year)
            WHERE c.goal_doctor_score IS NOT NULL
            ORDER BY c.visit_date DESC
        """)
        all_scores = [dict(r) for r in s.execute(scores_sql).mappings().all()]
        scores = [sc for sc in all_scores if sc['opaque_id'] in oid_set]
        for sc in scores:
            sc['visit_date'] = _json_safe(sc['visit_date'])

        # Rated goals (closed with points)
        rated = [g for g in goals if g.get('status') == 'closed' and g.get('points')]

        return jsonify({
            'goals': goals,
            'employee_scores': scores,
            'rated_goals': rated,
            'total_employees': len(emps)
        })
    finally:
        Session.remove()


# ── Slicer helpers ───────────────────────────────────────────────────────────

def _build_slicer_filters(args):
    filters = {}
    for key in ('division', 'location', 'band', 'zone', 'vertical',
                'age_group', 'gender'):
        val = args.get(key, '').strip()
        if val:
            filters[key] = val
    return filters


def _apply_slicer(rows, filters):
    if not filters:
        return rows
    out = []
    for r in rows:
        match = True
        for k, v in filters.items():
            if k == 'age_group':
                if r.get('age_range') != v:
                    match = False
                    break
            elif r.get(k) != v:
                match = False
                break
        if match:
            out.append(r)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# DATA EXPLORER ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/data/employees', methods=['GET'])
@role_required('hr', 'org', 'admin')
def data_employees():
    s = Session()
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        search = (request.args.get('search') or '').strip()
        page = request.args.get('page', 1, type=int)
        export = request.args.get('export') == '1'

        sql_parts = ["""
            SELECT e.*, ei.employee_id, ei.employee_name, ei.designation, ei.title
            FROM employees e
            JOIN employee_identity ei ON ei.opaque_id = e.opaque_id
              AND ei.year = e.year AND ei.month = e.month
            WHERE 1=1
        """]
        params = {}

        if year:
            sql_parts.append("AND e.year = :year")
            params['year'] = year
        if month:
            sql_parts.append("AND e.month = :month")
            params['month'] = month
        if search:
            sql_parts.append("AND (ei.employee_name LIKE :search OR ei.employee_id LIKE :search)")
            params['search'] = like_pattern(search)

        count_sql = "SELECT COUNT(*) FROM (" + ' '.join(sql_parts) + ") t"
        total = s.execute(text(count_sql), params).scalar()

        sql_parts.append("ORDER BY e.year DESC, e.month DESC, ei.employee_name")

        if export:
            rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
            data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]
            cols = list(data[0].keys()) if data else []
            return _excel_download([[r.get(c) for c in cols] for r in data],
                                   cols, 'employees.xlsx')

        per_page = 50
        offset = (page - 1) * per_page
        sql_parts.append(f"OFFSET {offset} ROWS FETCH NEXT {per_page} ROWS ONLY")
        rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
        data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]

        return jsonify({'rows': data, 'total': total, 'page': page,
                        'pages': math.ceil(total / per_page)})
    finally:
        Session.remove()


@app.route('/api/data/health', methods=['GET'])
@role_required('hr', 'org', 'admin')
def data_health():
    s = Session()
    try:
        year = request.args.get('year', type=int)
        search = (request.args.get('search') or '').strip()
        page = request.args.get('page', 1, type=int)
        export = request.args.get('export') == '1'

        sql_parts = ["""
            SELECT hr.*, ei.employee_id, ei.employee_name
            FROM health_records hr
            JOIN employee_identity ei ON ei.opaque_id = hr.opaque_id
              AND ei.year = (SELECT MAX(ei2.year) FROM employee_identity ei2
                             WHERE ei2.opaque_id = hr.opaque_id)
              AND ei.month = (SELECT MAX(ei3.month) FROM employee_identity ei3
                              WHERE ei3.opaque_id = hr.opaque_id AND ei3.year = ei.year)
            WHERE 1=1
        """]
        params = {}

        if year:
            sql_parts.append("AND hr.report_year = :year")
            params['year'] = year
        if search:
            sql_parts.append("AND (ei.employee_name LIKE :search OR ei.employee_id LIKE :search)")
            params['search'] = like_pattern(search)

        count_sql = "SELECT COUNT(*) FROM (" + ' '.join(sql_parts) + ") t"
        total = s.execute(text(count_sql), params).scalar()

        sql_parts.append("ORDER BY hr.ahc_id DESC")

        if export:
            rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
            data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]
            cols = list(data[0].keys()) if data else []
            return _excel_download([[r.get(c) for c in cols] for r in data],
                                   cols, 'annual_checkup.xlsx')

        per_page = 50
        offset = (page - 1) * per_page
        sql_parts.append(f"OFFSET {offset} ROWS FETCH NEXT {per_page} ROWS ONLY")
        rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
        data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]

        return jsonify({'rows': data, 'total': total, 'page': page,
                        'pages': math.ceil(total / per_page)})
    finally:
        Session.remove()


@app.route('/api/data/consultations', methods=['GET'])
@role_required('hr', 'org', 'admin')
def data_consultations():
    s = Session()
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        search = (request.args.get('search') or '').strip()
        page = request.args.get('page', 1, type=int)
        export = request.args.get('export') == '1'

        sql_parts = ["""
            SELECT c.*, ei.employee_id, ei.employee_name
            FROM consultations c
            JOIN employee_identity ei ON ei.opaque_id = c.opaque_id
              AND ei.year = (SELECT MAX(ei2.year) FROM employee_identity ei2
                             WHERE ei2.opaque_id = c.opaque_id)
              AND ei.month = (SELECT MAX(ei3.month) FROM employee_identity ei3
                              WHERE ei3.opaque_id = c.opaque_id AND ei3.year = ei.year)
            WHERE 1=1
        """]
        params = {}

        if year:
            sql_parts.append("AND YEAR(c.visit_date) = :year")
            params['year'] = year
        if month:
            sql_parts.append("AND MONTH(c.visit_date) = :month")
            params['month'] = month
        if search:
            sql_parts.append("AND (ei.employee_name LIKE :search OR ei.employee_id LIKE :search)")
            params['search'] = like_pattern(search)

        count_sql = "SELECT COUNT(*) FROM (" + ' '.join(sql_parts) + ") t"
        total = s.execute(text(count_sql), params).scalar()

        sql_parts.append("ORDER BY c.visit_date DESC, c.id DESC")

        if export:
            rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
            data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]
            cols = list(data[0].keys()) if data else []
            return _excel_download([[r.get(c) for c in cols] for r in data],
                                   cols, 'consultations.xlsx')

        per_page = 50
        offset = (page - 1) * per_page
        sql_parts.append(f"OFFSET {offset} ROWS FETCH NEXT {per_page} ROWS ONLY")
        rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
        data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]

        return jsonify({'rows': data, 'total': total, 'page': page,
                        'pages': math.ceil(total / per_page)})
    finally:
        Session.remove()


@app.route('/api/data/consultation-readings', methods=['GET'])
@role_required('hr', 'org', 'admin')
def data_consultation_readings():
    s = Session()
    try:
        search = (request.args.get('search') or '').strip()
        page = request.args.get('page', 1, type=int)
        export = request.args.get('export') == '1'

        sql_parts = ["""
            SELECT cr.*, ei.employee_id, ei.employee_name
            FROM consultation_readings cr
            JOIN employee_identity ei ON ei.opaque_id = cr.opaque_id
              AND ei.year = (SELECT MAX(ei2.year) FROM employee_identity ei2
                             WHERE ei2.opaque_id = cr.opaque_id)
              AND ei.month = (SELECT MAX(ei3.month) FROM employee_identity ei3
                              WHERE ei3.opaque_id = cr.opaque_id AND ei3.year = ei.year)
            WHERE 1=1
        """]
        params = {}

        if search:
            sql_parts.append("AND (ei.employee_name LIKE :search OR ei.employee_id LIKE :search OR cr.parameter_name LIKE :search)")
            params['search'] = like_pattern(search)

        count_sql = "SELECT COUNT(*) FROM (" + ' '.join(sql_parts) + ") t"
        total = s.execute(text(count_sql), params).scalar()

        sql_parts.append("ORDER BY cr.reading_date DESC, cr.id DESC")

        if export:
            rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
            data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]
            cols = list(data[0].keys()) if data else []
            return _excel_download([[r.get(c) for c in cols] for r in data],
                                   cols, 'consultation_readings.xlsx')

        per_page = 50
        offset = (page - 1) * per_page
        sql_parts.append(f"OFFSET {offset} ROWS FETCH NEXT {per_page} ROWS ONLY")
        rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
        data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]

        return jsonify({'rows': data, 'total': total, 'page': page,
                        'pages': math.ceil(total / per_page)})
    finally:
        Session.remove()


@app.route('/api/data/goals', methods=['GET'])
@role_required('hr', 'org', 'admin')
def data_goals():
    s = Session()
    try:
        status = (request.args.get('status') or '').strip()
        search = (request.args.get('search') or '').strip()
        page = request.args.get('page', 1, type=int)
        export = request.args.get('export') == '1'

        sql_parts = ["""
            SELECT g.*, ei.employee_id, ei.employee_name, c.visit_date, c.doctor_name
            FROM goals g
            JOIN consultations c ON c.id = g.consultation_id
            JOIN employee_identity ei ON ei.opaque_id = g.opaque_id
              AND ei.year = (SELECT MAX(ei2.year) FROM employee_identity ei2
                             WHERE ei2.opaque_id = g.opaque_id)
              AND ei.month = (SELECT MAX(ei3.month) FROM employee_identity ei3
                              WHERE ei3.opaque_id = g.opaque_id AND ei3.year = ei.year)
            WHERE 1=1
        """]
        params = {}

        if status:
            sql_parts.append("AND g.status = :status")
            params['status'] = status
        if search:
            sql_parts.append("AND (ei.employee_name LIKE :search OR ei.employee_id LIKE :search)")
            params['search'] = like_pattern(search)

        count_sql = "SELECT COUNT(*) FROM (" + ' '.join(sql_parts) + ") t"
        total = s.execute(text(count_sql), params).scalar()

        sql_parts.append("ORDER BY g.set_on DESC, g.id DESC")

        if export:
            rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
            data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]
            cols = list(data[0].keys()) if data else []
            return _excel_download([[r.get(c) for c in cols] for r in data],
                                   cols, 'goals.xlsx')

        per_page = 50
        offset = (page - 1) * per_page
        sql_parts.append(f"OFFSET {offset} ROWS FETCH NEXT {per_page} ROWS ONLY")
        rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
        data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]

        return jsonify({'rows': data, 'total': total, 'page': page,
                        'pages': math.ceil(total / per_page)})
    finally:
        Session.remove()


@app.route('/api/data/employee-scores', methods=['GET'])
@role_required('hr', 'org', 'admin')
def data_employee_scores():
    s = Session()
    try:
        search = (request.args.get('search') or '').strip()
        page = request.args.get('page', 1, type=int)
        export = request.args.get('export') == '1'

        sql_parts = ["""
            SELECT c.opaque_id, ei.employee_id, ei.employee_name,
                   ei.designation, c.goal_doctor_score, c.visit_date,
                   c.doctor_name
            FROM consultations c
            JOIN employee_identity ei ON ei.opaque_id = c.opaque_id
              AND ei.year = (SELECT MAX(ei2.year) FROM employee_identity ei2
                             WHERE ei2.opaque_id = c.opaque_id)
              AND ei.month = (SELECT MAX(ei3.month) FROM employee_identity ei3
                              WHERE ei3.opaque_id = c.opaque_id AND ei3.year = ei.year)
            WHERE c.goal_doctor_score IS NOT NULL
        """]
        params = {}

        if search:
            sql_parts.append("AND (ei.employee_name LIKE :search OR ei.employee_id LIKE :search)")
            params['search'] = like_pattern(search)

        count_sql = "SELECT COUNT(*) FROM (" + ' '.join(sql_parts) + ") t"
        total = s.execute(text(count_sql), params).scalar()

        sql_parts.append("ORDER BY c.visit_date DESC")

        if export:
            rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
            data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]
            cols = list(data[0].keys()) if data else []
            return _excel_download([[r.get(c) for c in cols] for r in data],
                                   cols, 'employee_scores.xlsx')

        per_page = 50
        offset = (page - 1) * per_page
        sql_parts.append(f"OFFSET {offset} ROWS FETCH NEXT {per_page} ROWS ONLY")
        rows = s.execute(text(' '.join(sql_parts)), params).mappings().all()
        data = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]

        return jsonify({'rows': data, 'total': total, 'page': page,
                        'pages': math.ceil(total / per_page)})
    finally:
        Session.remove()


@app.route('/api/data/filter-options', methods=['GET'])
@role_required('hr', 'org', 'admin')
def filter_options():
    s = Session()
    try:
        years = [r[0] for r in s.execute(text(
            "SELECT DISTINCT year FROM employees ORDER BY year DESC"
        )).all()]
        months = [r[0] for r in s.execute(text(
            "SELECT DISTINCT month FROM employees ORDER BY month"
        )).all()]
        return jsonify({'years': years, 'months': months})
    finally:
        Session.remove()


# ── Data delete endpoints ────────────────────────────────────────────────────

@app.route('/api/data/consultations/<int:cid>', methods=['DELETE'])
@role_required('admin')
def delete_consultation(cid):
    s = Session()
    try:
        c = s.query(Consultation).filter(Consultation.id == cid).first()
        if not c:
            return _data_error('Not found.', 404)
        s.delete(c)
        s.commit()
        return jsonify({'ok': True})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


@app.route('/api/data/health/<int:ahc_id>', methods=['DELETE'])
@role_required('admin')
def delete_health_record(ahc_id):
    s = Session()
    try:
        r = s.query(HealthRecord).filter(HealthRecord.ahc_id == ahc_id).first()
        if not r:
            return _data_error('Not found.', 404)
        s.delete(r)
        s.commit()
        return jsonify({'ok': True})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


@app.route('/api/data/goals/<int:gid>', methods=['DELETE'])
@role_required('admin')
def delete_goal(gid):
    s = Session()
    try:
        g = s.query(Goal).filter(Goal.id == gid).first()
        if not g:
            return _data_error('Not found.', 404)
        s.delete(g)
        s.commit()
        return jsonify({'ok': True})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

# ── User management ──────────────────────────────────────────────────────────

@app.route('/api/admin/users', methods=['GET'])
@role_required('admin')
def admin_list_users():
    s = Session()
    try:
        users = s.query(User).order_by(User.username).all()
        return jsonify([{'id': u.id, 'username': u.username, 'role': u.role}
                        for u in users])
    finally:
        Session.remove()


@app.route('/api/admin/users', methods=['POST'])
@role_required('admin')
def admin_add_user():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    role = (data.get('role') or '').strip().lower()

    if not username or not password:
        return _data_error('Username and password required.')
    if len(password) < 5:
        return _data_error('Password must be at least 5 characters.')
    if role not in ('doctor', 'hr', 'org', 'admin'):
        return _data_error('Invalid role.')

    s = Session()
    try:
        if s.query(User).filter(User.username == username).first():
            return _data_error('Username already exists.')
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        u = User(username=username, role=role, password_hash=pw_hash)
        s.add(u)
        s.commit()
        return jsonify({'ok': True, 'id': u.id})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


@app.route('/api/admin/users/<int:uid>', methods=['PUT'])
@role_required('admin')
def admin_update_user(uid):
    data = request.get_json(silent=True) or {}
    s = Session()
    try:
        u = s.query(User).filter(User.id == uid).first()
        if not u:
            return _data_error('User not found.', 404)
        if data.get('password'):
            if len(data['password']) < 5:
                return _data_error('Password must be at least 5 characters.')
            u.password_hash = bcrypt.hashpw(
                data['password'].encode(), bcrypt.gensalt()
            ).decode()
        if data.get('role') and data['role'] in ('doctor', 'hr', 'org', 'admin'):
            u.role = data['role']
        s.commit()
        return jsonify({'ok': True})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


@app.route('/api/admin/users/<int:uid>', methods=['DELETE'])
@role_required('admin')
def admin_delete_user(uid):
    s = Session()
    try:
        u = s.query(User).filter(User.id == uid).first()
        if not u:
            return _data_error('User not found.', 404)
        s.delete(u)
        s.commit()
        return jsonify({'ok': True})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


# ── Goal types ───────────────────────────────────────────────────────────────

@app.route('/api/admin/goal-types', methods=['GET'])
@role_required('admin')
def admin_list_goal_types():
    s = Session()
    try:
        rows = s.query(GoalType).order_by(GoalType.name).all()
        return jsonify([{'id': r.id, 'name': r.name, 'is_active': r.is_active}
                        for r in rows])
    finally:
        Session.remove()


@app.route('/api/admin/goal-types', methods=['POST'])
@role_required('admin')
def admin_add_goal_type():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return _data_error('Name required.')
    s = Session()
    try:
        if s.query(GoalType).filter(GoalType.name == name).first():
            return _data_error('Goal type already exists.')
        gt = GoalType(name=name, is_active=True)
        s.add(gt)
        s.commit()
        return jsonify({'ok': True, 'id': gt.id})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


@app.route('/api/admin/goal-types/<int:gtid>', methods=['PUT'])
@role_required('admin')
def admin_toggle_goal_type(gtid):
    s = Session()
    try:
        gt = s.query(GoalType).filter(GoalType.id == gtid).first()
        if not gt:
            return _data_error('Not found.', 404)
        gt.is_active = not gt.is_active
        s.commit()
        return jsonify({'ok': True, 'is_active': gt.is_active})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


@app.route('/api/admin/goal-types/<int:gtid>', methods=['DELETE'])
@role_required('admin')
def admin_delete_goal_type(gtid):
    s = Session()
    try:
        gt = s.query(GoalType).filter(GoalType.id == gtid).first()
        if not gt:
            return _data_error('Not found.', 404)
        s.delete(gt)
        s.commit()
        return jsonify({'ok': True})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


# ── Checkup types ────────────────────────────────────────────────────────────

@app.route('/api/admin/checkup-types', methods=['GET'])
@role_required('admin')
def admin_list_checkup_types():
    s = Session()
    try:
        rows = s.query(CheckupType).order_by(CheckupType.name).all()
        return jsonify([{
            'id': r.id, 'name': r.name, 'unit': r.unit,
            'normal_range': r.normal_range, 'is_active': r.is_active
        } for r in rows])
    finally:
        Session.remove()


@app.route('/api/admin/checkup-types', methods=['POST'])
@role_required('admin')
def admin_add_checkup_type():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return _data_error('Name required.')
    s = Session()
    try:
        if s.query(CheckupType).filter(CheckupType.name == name).first():
            return _data_error('Checkup type already exists.')
        ct = CheckupType(name=name, unit=data.get('unit'),
                         normal_range=data.get('normal_range'),
                         is_active=True, created_at=now_ist())
        s.add(ct)
        s.commit()
        return jsonify({'ok': True, 'id': ct.id})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


@app.route('/api/admin/checkup-types/<int:ctid>', methods=['PUT'])
@role_required('admin')
def admin_toggle_checkup_type(ctid):
    s = Session()
    try:
        ct = s.query(CheckupType).filter(CheckupType.id == ctid).first()
        if not ct:
            return _data_error('Not found.', 404)
        ct.is_active = not ct.is_active
        s.commit()
        return jsonify({'ok': True, 'is_active': ct.is_active})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


@app.route('/api/admin/checkup-types/<int:ctid>', methods=['DELETE'])
@role_required('admin')
def admin_delete_checkup_type(ctid):
    s = Session()
    try:
        ct = s.query(CheckupType).filter(CheckupType.id == ctid).first()
        if not ct:
            return _data_error('Not found.', 404)
        s.delete(ct)
        s.commit()
        return jsonify({'ok': True})
    except Exception as ex:
        s.rollback()
        return _data_error(str(ex), 500)
    finally:
        Session.remove()


# ── CSV Import — Employees ───────────────────────────────────────────────────

@app.route('/api/admin/import/employees', methods=['POST'])
@role_required('admin')
def import_employees():
    f = request.files.get('file')
    if not f:
        return _data_error('No file uploaded.')
    try:
        df = pd.read_csv(f, encoding='latin1')
    except Exception as ex:
        return _data_error(f'Failed to read CSV: {ex}')

    required = ['Employee ID', 'Employee Name', 'Year', 'Month']
    missing = [c for c in required if c not in df.columns]
    if missing:
        return _data_error(f'Missing columns: {", ".join(missing)}')

    s = Session()
    try:
        imported = 0
        skipped = 0
        for _, row in df.iterrows():
            eid = str(row.get('Employee ID', '')).strip()
            ename = str(row.get('Employee Name', '')).strip()
            if not eid or not ename:
                skipped += 1
                continue

            year_val = int(row['Year'])
            month_val = parse_month(row['Month'])
            if not month_val:
                skipped += 1
                continue

            oid, month_int = get_or_create_opaque_id(
                s, eid, ename,
                str(row.get('Designation', '')) if pd.notna(row.get('Designation')) else None,
                str(row.get('Title', '')) if pd.notna(row.get('Title')) else None,
                year_val, month_int if isinstance(month_val, int) else month_val
            )

            existing = s.query(Employee).filter(
                Employee.opaque_id == oid,
                Employee.year == year_val,
                Employee.month == month_int
            ).first()

            def val(col):
                v = row.get(col)
                if pd.isna(v):
                    return None
                return str(v).strip() if isinstance(v, str) else v

            emp_data = dict(
                sr_no=int(val('Sr. No.')) if val('Sr. No.') else None,
                location=val('Location'),
                date_of_joining=parse_date(val('Date of Joining')),
                technova_experience=float(val('TechNova Experience')) if val('TechNova Experience') else None,
                outside_experience=float(val('Outside Experience')) if val('Outside Experience') else None,
                total_experience=float(val('Total Experience')) if val('Total Experience') else None,
                total_experience_range=val('Total Experience Range'),
                date_of_birth=parse_date(val('Date of Birth')),
                age=int(val('Age')) if val('Age') else None,
                age_range=val('Age Range'),
                gender=val('Gender'),
                core_group=val('Core Group'),
                super_function=val('Super Function'),
                function=val('Function'),
                division=val('Division'),
                vertical=val('Vertical'),
                role=val('Role'),
                role_function=val('Role Function'),
                employee_category=val('Employee Category'),
                employee_sub_category=val('Employee Sub Category'),
                band=val('Band'),
                level=val('Level'),
                basic_qualification=val('Basic Qualification'),
                other_qualifications=val('Other / Professional Qualifications'),
                qualification_category=val('Qualification Category'),
                zone=val('Zone'),
                budget_code=val('Budget code'),
                blood_group=val('Blood Group'),
                level_code=val('Level Code'),
                sub_sect=val('Sub-sect'),
                city=val('City'),
                pin_code=val('Pin Code'),
                state=val('State'),
            )

            if existing:
                for k, v in emp_data.items():
                    setattr(existing, k, v)
            else:
                emp = Employee(opaque_id=oid, year=year_val, month=month_int, **emp_data)
                s.add(emp)

            imported += 1
            if imported % 500 == 0:
                s.flush()

        s.commit()
        return jsonify({'ok': True, 'imported': imported, 'skipped': skipped})
    except Exception as ex:
        s.rollback()
        return _data_error(f'Import failed: {str(ex)}', 500)
    finally:
        Session.remove()


# ── Excel Import — AHC Health Records ────────────────────────────────────────

@app.route('/api/admin/import/health', methods=['POST'])
@role_required('admin')
def import_health():
    f = request.files.get('file')
    if not f:
        return _data_error('No file uploaded.')
    try:
        df = pd.read_excel(f, engine='openpyxl')
    except Exception as ex:
        return _data_error(f'Failed to read Excel: {ex}')

    if 'employee_id' not in df.columns or 'ahc_id' not in df.columns:
        return _data_error('Missing required columns: employee_id, ahc_id')

    col_map = {
        'Cardiac profile - stage': 'cardiac_stage',
        'Blood profile - stage': 'blood_stage',
        'Hepatic profile - stage': 'hepatic_stage',
        'Renal profile - stage': 'renal_stage',
        'Diabetic profile - stage': 'diabetic_stage',
        'Vitamin-D Profile - stage': 'vitamind_stage',
        'Thyroid Profile - stage': 'thyroid_stage',
        'Cancer Profile - stage': 'cancer_stage',
        'report_value_unit': 'value_unit',
        'parameters': 'parameter_name',
    }
    df.rename(columns=col_map, inplace=True)

    # Derive report_year from appointment_completed_on if not present
    if 'report_year' not in df.columns:
        if 'appointment_completed_on' in df.columns:
            df['report_year'] = pd.to_datetime(
                df['appointment_completed_on'], errors='coerce'
            ).dt.year
        else:
            df['report_year'] = None

    s = Session()
    try:
        imported = 0
        skipped = 0
        for _, row in df.iterrows():
            eid = str(row.get('employee_id', '')).strip()
            ahc_id = row.get('ahc_id')
            if not eid or pd.isna(ahc_id):
                skipped += 1
                continue

            oid = resolve_opaque_id(s, eid)
            if not oid:
                cust_name = str(row.get('customer_name', '')) if pd.notna(row.get('customer_name')) else eid
                oid, _ = get_or_create_opaque_id(
                    s, eid, cust_name, None, None,
                    int(row['report_year']) if pd.notna(row.get('report_year')) else 2026, 1
                )

            existing = s.query(HealthRecord).filter(
                HealthRecord.ahc_id == int(ahc_id)
            ).first()

            def val(col):
                v = row.get(col)
                if pd.isna(v) if isinstance(v, float) else (v is None):
                    return None
                return v

            hr_data = dict(
                case_id=int(val('case_id')) if val('case_id') else None,
                application_id=int(val('application_id')) if val('application_id') else None,
                user_id=int(val('user_id')) if val('user_id') else None,
                opaque_id=oid,
                gender=val('gender'),
                age_group=val('age_group'),
                city=val('city'),
                state=val('state'),
                dc_name=val('dc_name'),
                appointment_booked_on=pd.to_datetime(val('appointment_booked_on'), errors='coerce'),
                appointment_completed_on=pd.to_datetime(val('appointment_completed_on'), errors='coerce'),
                reports_upload_on=pd.to_datetime(val('reports_upload_on'), errors='coerce'),
                overall_health_score=int(val('overall_health_score')) if val('overall_health_score') else None,
                overall_risk_category=val('overall_risk_category'),
                risk_stage=int(val('risk_stage')) if val('risk_stage') else None,
                cardiac_stage=val('cardiac_stage'),
                blood_stage=val('blood_stage'),
                hepatic_stage=val('hepatic_stage'),
                renal_stage=val('renal_stage'),
                diabetic_stage=val('diabetic_stage'),
                vitamind_stage=val('vitamind_stage'),
                thyroid_stage=val('thyroid_stage'),
                cancer_stage=val('cancer_stage'),
                parameter_name=val('parameter_name'),
                value=float(val('value')) if val('value') else None,
                value_unit=val('value_unit'),
                normal_range=val('normal_range'),
                risk_level=val('risk_level'),
                category=val('category'),
                normal=val('normal'),
                low_risk=val('low_risk'),
                medium_risk=val('medium_risk'),
                high_risk=val('high_risk'),
                rn=int(val('rn')) if val('rn') else None,
                report_year=int(val('report_year')) if val('report_year') else None,
            )

            if existing:
                for k, v in hr_data.items():
                    setattr(existing, k, v)
            else:
                rec = HealthRecord(ahc_id=int(ahc_id), **hr_data)
                s.add(rec)

            imported += 1
            if imported % 500 == 0:
                s.flush()

        s.commit()

        # Auto-seed checkup_types from imported parameters
        _seed_checkup_types(s)

        return jsonify({'ok': True, 'imported': imported, 'skipped': skipped})
    except Exception as ex:
        s.rollback()
        return _data_error(f'Import failed: {str(ex)}', 500)
    finally:
        Session.remove()


def _seed_checkup_types(s):
    sql = text("""
        INSERT INTO checkup_types (name, unit, normal_range, is_active, created_at)
        SELECT sub.parameter_name, sub.value_unit, sub.normal_range, 1,
               DATEADD(MINUTE, 330, GETUTCDATE())
        FROM (
            SELECT parameter_name,
                   MAX(value_unit) AS value_unit,
                   MAX(normal_range) AS normal_range
            FROM health_records
            WHERE parameter_name IS NOT NULL AND LTRIM(RTRIM(parameter_name)) <> ''
            GROUP BY parameter_name
        ) sub
        WHERE NOT EXISTS (
            SELECT 1 FROM checkup_types ct WHERE ct.name = sub.parameter_name
        )
    """)
    try:
        s.execute(sql)
        s.commit()
    except Exception:
        s.rollback()


# ══════════════════════════════════════════════════════════════════════════════
# SLICER OPTIONS (for dashboards)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/slicer-options', methods=['GET'])
@role_required('hr', 'org', 'admin')
def slicer_options():
    s = Session()
    try:
        def distinct_vals(col):
            sql = text(f"""
                SELECT DISTINCT [{col}] FROM employees
                WHERE [{col}] IS NOT NULL AND [{col}] <> ''
                ORDER BY [{col}]
            """)
            return [r[0] for r in s.execute(sql).all()]

        return jsonify({
            'divisions': distinct_vals('division'),
            'locations': distinct_vals('location'),
            'bands': distinct_vals('band'),
            'zones': distinct_vals('zone'),
            'verticals': distinct_vals('vertical'),
            'age_ranges': distinct_vals('age_range'),
            'genders': distinct_vals('gender'),
        })
    finally:
        Session.remove()


# ══════════════════════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.getenv('PORT', 3001))
    debug = os.getenv('DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
