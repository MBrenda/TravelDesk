"""TravelDesk: single-agency private passenger manager. No external services."""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Flask, abort, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent
UTC = timezone.utc
BOOKING_STATES = {'pendiente', 'confirmada', 'cancelada'}
HEADERS = ['nombre', 'email', 'telefono', 'localizador', 'origen', 'destino',
           'vuelo', 'salida', 'llegada', 'escalas', 'estado', 'importe', 'pagado']


def now_iso():
    return datetime.now(UTC).isoformat()


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 1000000 or amount.as_tuple().exponent < -2:
            raise ValueError()
        return int(amount * 100)
    except (InvalidOperation, ValueError, TypeError):
        abort(400, 'Importe inválido: usa un número positivo con hasta dos decimales.')


def text_field(data, key, required=False, limit=180):
    value = data.get(key, '')
    if value is None:
        value = ''
    if not isinstance(value, str):
        abort(400, f'{key}: debe ser texto.')
    value = value.strip()
    if len(value) > limit or (required and not value) or any(ord(c) < 32 for c in value):
        abort(400, f'{key}: campo obligatorio o longitud/formato incorrecto.')
    return value


def valid_date(value):
    try:
        date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if not date.tzinfo:
            raise ValueError()
        return date.astimezone(UTC)
    except (ValueError, TypeError):
        abort(400, 'Fecha inválida. Usa ISO 8601 con zona horaria, por ejemplo 2026-11-05T10:00:00+01:00.')


def travel_state(booking, at=None):
    if booking['status'] == 'cancelada':
        return 'cancelado'
    at = at or datetime.now(UTC)
    if at < datetime.fromisoformat(booking['departure']):
        return 'próximo'
    if at < datetime.fromisoformat(booking['arrival']):
        return 'en tránsito'
    return 'finalizado'


def create_app(database=None, secure=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=2 * 1024 * 1024,
                      DATABASE=str(database or os.environ.get('TRAVELDESK_DB', ROOT / 'instance' / 'traveldesk.sqlite')),
                      SECURE_COOKIE=(os.environ.get('TRAVELDESK_HTTPS') == '1') if secure is None else secure)
    # Enable only behind the single reverse proxy in compose.yaml.
    if os.environ.get('TRAVELDESK_PROXY') == '1':
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=0)

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=10)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @app.teardown_appcontext
    def close_db(error=None):
        if 'db' in g:
            g.db.close()

    def audit(action, entity='', entity_id=''):
        db().execute('INSERT INTO audit(at,action,entity,entity_id) VALUES(?,?,?,?)',
                     (now_iso(), action, entity, str(entity_id)))

    def auth(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            raw = request.cookies.get('td_session', '')
            token_hash = hashlib.sha256(raw.encode()).hexdigest()
            session = db().execute('SELECT * FROM sessions WHERE token=?', (token_hash,)).fetchone()
            if not session or session['expires'] < time.time() or session['last_seen'] < time.time() - 1800:
                abort(401, 'La sesión ha caducado. Vuelve a entrar.')
            if request.method != 'GET':
                if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session['csrf']):
                    abort(403, 'Validación de seguridad fallida. Recarga la página.')
            g.session = session
            db().execute('UPDATE sessions SET last_seen=? WHERE token=?', (time.time(), token_hash))
            db().commit()
            return fn(*args, **kwargs)
        return wrapped

    @app.before_request
    def same_origin():
        if request.method in {'POST', 'PUT', 'DELETE', 'PATCH'}:
            if request.headers.get('Sec-Fetch-Site') == 'cross-site':
                abort(403, 'Origen no permitido.')
            origin = request.headers.get('Origin')
            if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
                abort(403, 'Origen no permitido.')
            if request.path != '/api/import/preview' and not request.is_json:
                abort(415, 'Se requiere JSON.')
            if request.is_json and not isinstance(request.get_json(), dict):
                abort(400, 'Se requiere un objeto JSON.')

    @app.after_request
    def security_headers(response):
        response.headers.update({
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        })
        if app.config['SECURE_COOKIE']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        app.logger.error('Error interno: %s', type(error).__name__)
        return jsonify(error='Error interno. La operación no se ha completado.'), 500

    @app.get('/')
    def home():
        return send_from_directory(ROOT / 'static', 'index.html')

    @app.get('/<path:path>')
    def static_file(path):
        return send_from_directory(ROOT / 'static', path)

    @app.post('/api/login')
    def login():
        data = request.get_json()
        username = text_field(data, 'username', True, 80)
        password = data.get('password')
        if not isinstance(password, str) or not 1 <= len(password) <= 200:
            abort(400, 'Contraseña inválida.')
        # Persisted account-wide throttling; independent of spoofable proxy IP headers.
        with db():
            db().execute('BEGIN IMMEDIATE')
            throttle = db().execute('SELECT * FROM throttle WHERE id=1').fetchone()
            if throttle['until_at'] > time.time():
                abort(429, 'Demasiados intentos. Espera 5 minutos.')
            user = db().execute('SELECT * FROM users WHERE id=1').fetchone()
            valid = check_password_hash(user['password'] if user else generate_password_hash('unused'), password)
            if not user or username != user['username'] or not valid:
                failures = throttle['failures'] + 1
                db().execute('UPDATE throttle SET failures=?,until_at=? WHERE id=1',
                             (failures if failures < 5 else 0, time.time() + 300 if failures >= 5 else 0))
                audit('login_failed')
                # Return instead of raising to commit the throttle update.
                return jsonify(error='Credenciales incorrectas.'), 401
            db().execute('UPDATE throttle SET failures=0,until_at=0 WHERE id=1')
            old_token = hashlib.sha256(request.cookies.get('td_session', '').encode()).hexdigest()
            db().execute('DELETE FROM sessions WHERE token=?', (old_token,))
            db().execute('DELETE FROM sessions WHERE expires<? OR last_seen<?', (time.time(), time.time()-1800))
            raw, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            db().execute('INSERT INTO sessions VALUES(?,?,?,?)',
                         (hashlib.sha256(raw.encode()).hexdigest(), csrf, time.time()+28800, time.time()))
            audit('login')
        response = jsonify(csrf=csrf, username=username)
        response.set_cookie('td_session', raw, httponly=True, secure=app.config['SECURE_COOKIE'], samesite='Strict', max_age=28800)
        return response

    @app.get('/api/session')
    @auth
    def session_info():
        return jsonify(csrf=g.session['csrf'], username=db().execute('SELECT username FROM users WHERE id=1').fetchone()[0])

    @app.post('/api/logout')
    @auth
    def logout():
        with db():
            db().execute('DELETE FROM sessions WHERE token=?', (g.session['token'],))
            audit('logout')
        response = jsonify(ok=True)
        response.delete_cookie('td_session')
        return response

    @app.get('/api/data')
    @auth
    def all_data():
        passengers = [dict(r) for r in db().execute('SELECT * FROM passengers ORDER BY name')]
        bookings = []
        for r in db().execute('SELECT b.*,p.name passenger_name,COALESCE(SUM(pay.amount),0) paid FROM bookings b JOIN passengers p ON p.id=b.passenger_id LEFT JOIN payments pay ON pay.booking_id=b.id GROUP BY b.id ORDER BY b.departure'):
            b = dict(r)
            b['travel_state'] = travel_state(b)
            bookings.append(b)
        payments = [dict(r) for r in db().execute('SELECT * FROM payments ORDER BY at DESC')]
        return jsonify(passengers=passengers, bookings=bookings, payments=payments, server_time=now_iso())

    def passenger_values(data):
        name = text_field(data, 'name', True, 100)
        email = text_field(data, 'email', limit=180)
        if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            abort(400, 'Email inválido.')
        return name, email, text_field(data, 'phone', limit=40), text_field(data, 'notes', limit=500)

    @app.post('/api/passengers')
    @auth
    def add_passenger():
        values = passenger_values(request.get_json())
        with db():
            cursor = db().execute('INSERT INTO passengers(name,email,phone,notes) VALUES(?,?,?,?)', values)
            audit('create', 'passenger', cursor.lastrowid)
        return jsonify(id=cursor.lastrowid), 201

    @app.put('/api/passengers/<int:pid>')
    @auth
    def edit_passenger(pid):
        values = passenger_values(request.get_json())
        with db():
            if not db().execute('UPDATE passengers SET name=?,email=?,phone=?,notes=? WHERE id=?', (*values, pid)).rowcount:
                abort(404, 'Pasajero no encontrado.')
            audit('update', 'passenger', pid)
        return jsonify(ok=True)

    @app.delete('/api/passengers/<int:pid>')
    @auth
    def delete_passenger(pid):
        # Explicit erasure also removes reservations and payments via FK cascade.
        with db():
            if not db().execute('DELETE FROM passengers WHERE id=?', (pid,)).rowcount:
                abort(404, 'Pasajero no encontrado.')
            audit('erase', 'passenger', pid)
        return jsonify(ok=True)

    def booking_values(data):
        try:
            pid = int(data['passenger_id'])
        except (KeyError, TypeError, ValueError):
            abort(400, 'Selecciona un pasajero.')
        if not db().execute('SELECT 1 FROM passengers WHERE id=?', (pid,)).fetchone():
            abort(400, 'Pasajero inexistente.')
        reference = text_field(data, 'reference', True, 20).upper()
        origin = text_field(data, 'origin', True, 3).upper()
        destination = text_field(data, 'destination', True, 3).upper()
        if not re.fullmatch('[A-Z]{3}', origin) or not re.fullmatch('[A-Z]{3}', destination) or origin == destination:
            abort(400, 'Usa aeropuertos distintos con código IATA de 3 letras.')
        departure, arrival = valid_date(data.get('departure')), valid_date(data.get('arrival'))
        if arrival <= departure:
            abort(400, 'La llegada debe ser posterior a la salida.')
        status = data.get('status', 'pendiente')
        if status not in BOOKING_STATES:
            abort(400, 'Estado de reserva inválido.')
        return (pid, reference, origin, destination, text_field(data, 'flight', True, 30), departure.isoformat(),
                arrival.isoformat(), text_field(data, 'stops', limit=180), status, money(data.get('total')))

    @app.post('/api/bookings')
    @auth
    def add_booking():
        values = booking_values(request.get_json())
        with db():
            try:
                cursor = db().execute('INSERT INTO bookings(passenger_id,reference,origin,destination,flight,departure,arrival,stops,status,total) VALUES(?,?,?,?,?,?,?,?,?,?)', values)
            except sqlite3.IntegrityError:
                abort(409, 'Ese pasajero ya tiene una reserva con este localizador.')
            audit('create', 'booking', cursor.lastrowid)
        return jsonify(id=cursor.lastrowid), 201

    @app.put('/api/bookings/<int:bid>')
    @auth
    def edit_booking(bid):
        values = booking_values(request.get_json())
        with db():
            db().execute('BEGIN IMMEDIATE')
            paid = db().execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE booking_id=?', (bid,)).fetchone()[0]
            if values[-1] < paid:
                abort(400, 'El importe no puede ser menor que los cobros registrados.')
            try:
                result = db().execute('UPDATE bookings SET passenger_id=?,reference=?,origin=?,destination=?,flight=?,departure=?,arrival=?,stops=?,status=?,total=? WHERE id=?', (*values, bid))
            except sqlite3.IntegrityError:
                abort(409, 'Reserva duplicada para ese pasajero y localizador.')
            if not result.rowcount:
                abort(404, 'Reserva no encontrada.')
            audit('update', 'booking', bid)
        return jsonify(ok=True)

    @app.post('/api/bookings/<int:bid>/payments')
    @auth
    def add_payment(bid):
        data = request.get_json()
        amount = money(data.get('amount'))
        method = data.get('method')
        if amount <= 0 or method not in {'transferencia', 'efectivo', 'tarjeta'}:
            abort(400, 'Indica un cobro positivo y un método válido.')
        with db():
            db().execute('BEGIN IMMEDIATE')
            b = db().execute('SELECT total,status FROM bookings WHERE id=?', (bid,)).fetchone()
            if not b:
                abort(404, 'Reserva no encontrada.')
            paid = db().execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE booking_id=?', (bid,)).fetchone()[0]
            if b['status'] == 'cancelada' or paid + amount > b['total']:
                abort(400, 'El cobro supera el saldo pendiente o la reserva está cancelada.')
            db().execute('INSERT INTO payments(booking_id,amount,method,at) VALUES(?,?,?,?)', (bid, amount, method, now_iso()))
            audit('payment', 'booking', bid)
        return jsonify(ok=True), 201

    @app.delete('/api/payments/<int:payment_id>')
    @auth
    def reverse_payment(payment_id):
        with db():
            if not db().execute('DELETE FROM payments WHERE id=?', (payment_id,)).rowcount:
                abort(404, 'Cobro no encontrado.')
            audit('reverse_payment', 'payment', payment_id)
        return jsonify(ok=True)

    @app.get('/api/audit')
    @auth
    def audit_log():
        return jsonify(events=[dict(r) for r in db().execute('SELECT * FROM audit ORDER BY id DESC LIMIT 200')])

    @app.get('/api/template.csv')
    @auth
    def template():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(HEADERS)
        writer.writerow(['Persona Ejemplo', 'persona@example.invalid', '+34000000000', 'DEMO01', 'MAD', 'BOG', 'TD101',
                         '2026-11-05T10:00:00+01:00', '2026-11-05T20:00:00+01:00', '', 'confirmada', '850.00', '200.00'])
        return app.response_class('\ufeff' + buffer.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=plantilla-traveldesk.csv'})

    @app.post('/api/import/preview')
    @auth
    def import_preview():
        upload = request.files.get('file')
        if not upload:
            abort(400, 'Selecciona un archivo CSV o XLSX.')
        raw = upload.read()
        filename = (upload.filename or '').lower()
        try:
            if filename.endswith('.csv'):
                decoded = raw.decode('utf-8-sig')
                try:
                    dialect = csv.Sniffer().sniff(decoded[:8192], delimiters=',;')
                except csv.Error:
                    dialect = csv.excel
                rows = list(csv.reader(io.StringIO(decoded), dialect))
            elif filename.endswith('.xlsx'):
                from openpyxl import load_workbook
                archive = zipfile.ZipFile(io.BytesIO(raw))
                if sum(x.file_size for x in archive.infolist()) > 20*1024*1024 or len(archive.infolist()) > 1000:
                    abort(400, 'Excel demasiado grande una vez descomprimido.')
                workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
                sheet = workbook.active
                rows = []
                for row in sheet.iter_rows():
                    if any(cell.data_type == 'f' for cell in row):
                        abort(400, 'El Excel contiene fórmulas. Convierte las celdas a valores antes de importar.')
                    rows.append([cell.value for cell in row])
                    if len(rows) > 501:
                        abort(400, 'Máximo 500 filas por importación.')
                workbook.close()
            else:
                abort(400, 'Solo se admiten .csv y .xlsx (no .xls).')
        except (UnicodeError, csv.Error, zipfile.BadZipFile, KeyError, ValueError):
            abort(400, 'Archivo ilegible. Usa CSV UTF-8 o un Excel XLSX válido.')
        if not rows or [str(x or '').strip().lower() for x in rows[0]] != HEADERS:
            abort(400, 'Las columnas deben coincidir con la plantilla descargable, en el mismo orden.')
        if len(rows) > 501:
            abort(400, 'Máximo 500 filas por importación.')
        items, errors_list, seen = [], [], set()
        for number, row in enumerate(rows[1:], 2):
            if not any(x is not None and str(x).strip() for x in row):
                continue
            try:
                if len(row) != len(HEADERS):
                    abort(400, 'Número de columnas incorrecto.')
                d = dict(zip(HEADERS, [str(x) if x is not None else '' for x in row]))
                name, email, phone, notes = passenger_values({'name': d['nombre'], 'email': d['email'], 'phone': d['telefono']})
                # Reuse booking validation without inserting any persistent record.
                preview_id = db().execute('SELECT id FROM passengers LIMIT 1').fetchone()
                if not preview_id:
                    # Validation uses temporary, rolled back passenger inside a savepoint.
                    db().execute('SAVEPOINT preview_passenger')
                    pid = db().execute("INSERT INTO passengers(name,email,phone,notes) VALUES('preview','','','')").lastrowid
                else:
                    pid = preview_id[0]
                b = {'passenger_id': pid, 'reference': d['localizador'], 'origin': d['origen'], 'destination': d['destino'],
                     'flight': d['vuelo'], 'departure': d['salida'], 'arrival': d['llegada'], 'stops': d['escalas'], 'status': d['estado'], 'total': d['importe']}
                try:
                    values = booking_values(b)
                finally:
                    if not preview_id:
                        db().execute('ROLLBACK TO preview_passenger')
                        db().execute('RELEASE preview_passenger')
                paid = money(d['pagado'])
                if paid > values[-1]:
                    abort(400, 'Pagado supera el importe.')
                key = (name.casefold(), email.casefold(), values[1])
                if key in seen or db().execute('SELECT 1 FROM bookings b JOIN passengers p ON p.id=b.passenger_id WHERE lower(p.name)=lower(?) AND lower(p.email)=lower(?) AND b.reference=?', (name, email, values[1])).fetchone():
                    abort(400, 'Reserva duplicada (pasajero + email + localizador).')
                seen.add(key)
                items.append({'name': name, 'email': email, 'phone': phone, 'booking': list(values[1:]), 'paid': paid})
            except HTTPException as error:
                errors_list.append({'row': number, 'message': error.description})
        token = secrets.token_urlsafe(32)
        with db():
            db().execute('DELETE FROM imports WHERE expires<?', (time.time(),))
            # One active preview per session, to bound storage.
            db().execute('DELETE FROM imports WHERE session=?', (g.session['token'],))
            db().execute('INSERT INTO imports VALUES(?,?,?,?,?)', (token, g.session['token'], json.dumps(items), time.time()+600, int(bool(errors_list))))
        return jsonify(token=token, rows=items, errors=errors_list)

    @app.post('/api/import/commit')
    @auth
    def import_commit():
        token = text_field(request.get_json(), 'token', True, 100)
        with db():
            db().execute('BEGIN IMMEDIATE')
            staged = db().execute('SELECT * FROM imports WHERE token=? AND session=? AND expires>?', (token, g.session['token'], time.time())).fetchone()
            if not staged or staged['invalid']:
                abort(400, 'Vista previa caducada o con errores. Revisa el archivo completo.')
            items = json.loads(staged['data'])
            for item in items:
                p = db().execute('SELECT id FROM passengers WHERE lower(name)=lower(?) AND lower(email)=lower(?)', (item['name'], item['email'])).fetchone()
                pid = p[0] if p else db().execute('INSERT INTO passengers(name,email,phone,notes) VALUES(?,?,?,?)', (item['name'], item['email'], item['phone'], '')).lastrowid
                try:
                    bid = db().execute('INSERT INTO bookings(passenger_id,reference,origin,destination,flight,departure,arrival,stops,status,total) VALUES(?,?,?,?,?,?,?,?,?,?)', (pid, *item['booking'])).lastrowid
                except sqlite3.IntegrityError:
                    abort(409, 'Hay duplicados nuevos. Genera otra vista previa; no se ha importado ninguna fila.')
                if item['paid']:
                    db().execute("INSERT INTO payments(booking_id,amount,method,at) VALUES(?,?,'importación',?)", (bid, item['paid'], now_iso()))
            db().execute('DELETE FROM imports WHERE token=?', (token,))
            audit('import', 'rows', len(items))
        return jsonify(imported=len(items))

    app.db = db
    return app


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY CHECK(id=1),username TEXT NOT NULL,password TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS passengers(id INTEGER PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL,notes TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY,passenger_id INTEGER NOT NULL REFERENCES passengers ON DELETE CASCADE,
reference TEXT NOT NULL,origin TEXT NOT NULL,destination TEXT NOT NULL,flight TEXT NOT NULL,departure TEXT NOT NULL,arrival TEXT NOT NULL,
stops TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('pendiente','confirmada','cancelada')),total INTEGER NOT NULL CHECK(total>=0),UNIQUE(passenger_id,reference));
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,booking_id INTEGER NOT NULL REFERENCES bookings ON DELETE CASCADE,amount INTEGER NOT NULL CHECK(amount>0),method TEXT NOT NULL,at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,csrf TEXT NOT NULL,expires REAL NOT NULL,last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS imports(token TEXT PRIMARY KEY,session TEXT NOT NULL REFERENCES sessions ON DELETE CASCADE,data TEXT NOT NULL,expires REAL NOT NULL,invalid INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS throttle(id INTEGER PRIMARY KEY,failures INTEGER NOT NULL,until_at REAL NOT NULL);
INSERT OR IGNORE INTO throttle VALUES(1,0,0);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT NOT NULL,action TEXT NOT NULL,entity TEXT NOT NULL,entity_id TEXT NOT NULL);
"""


def initialize(app, username, password, demo=False):
    username = username.strip()
    if not username or len(username) > 80:
        raise ValueError('El usuario debe tener de 1 a 80 caracteres.')
    if not 12 <= len(password) <= 200:
        raise ValueError('La contraseña debe tener entre 12 y 200 caracteres.')
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        db = app.db()
        db.executescript(SCHEMA)
        if db.execute('SELECT 1 FROM users').fetchone():
            raise ValueError('La base de datos ya está inicializada. No se ha modificado.')
        with db:
            db.execute('INSERT INTO users VALUES(1,?,?)', (username, generate_password_hash(password)))
            if demo:
                names = [('Lucía Torres', 'lucia@example.invalid'), ('Mateo Rivas', 'mateo@example.invalid'),
                         ('Sofía Delgado', 'sofia@example.invalid'), ('Daniel Vega', 'daniel@example.invalid'),
                         ('Valentina Cruz', 'valentina@example.invalid'), ('Diego Martín', 'diego@example.invalid')]
                now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
                routes = [('MAD', 'BOG', 'TD601', 1, 89000, 30000), ('BCN', 'LIM', 'TD204', 3, 112000, 112000),
                          ('MAD', 'EZE', 'TD350', 6, 98000, 0), ('BOG', 'MAD', 'TD602', 0, 76000, 76000),
                          ('MAD', 'MEX', 'TD710', 12, 105000, 25000), ('LIM', 'BCN', 'TD205', -8, 92000, 92000)]
                for i, ((name, email), (origin, destination, flight, days, total, paid)) in enumerate(zip(names, routes), 1):
                    db.execute('INSERT INTO passengers VALUES(?,?,?,?,?)', (i, name, email, '+34 600 000 00'+str(i), 'Ficha de demostración; datos ficticios.'))
                    departure = now + timedelta(days=days, hours=-2 if days == 0 else 0)
                    arrival = departure + timedelta(hours=11)
                    db.execute('INSERT INTO bookings VALUES(?,?,?,?,?,?,?,?,?,?,?)', (i, i, f'DEMO0{i}', origin, destination, flight, departure.isoformat(), arrival.isoformat(), 'Directo', 'confirmada' if i != 3 else 'pendiente', total))
                    if paid:
                        db.execute('INSERT INTO payments(booking_id,amount,method,at) VALUES(?,?,?,?)', (i, paid, 'transferencia', now_iso()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='TravelDesk privado')
    parser.add_argument('command', choices=['init', 'serve', 'password'])
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    application = create_app()
    if args.command == 'init':
        from getpass import getpass
        username = os.environ.get('TRAVELDESK_USER') or input('Usuario administrador: ')
        password = os.environ.get('TRAVELDESK_PASSWORD') or getpass('Contraseña (12+ caracteres): ')
        initialize(application, username, password, args.demo)
        print('TravelDesk inicializado. Datos ficticios.' if args.demo else 'TravelDesk inicializado sin pasajeros.')
    elif args.command == 'password':
        from getpass import getpass
        password = getpass('Nueva contraseña (12+ caracteres): ')
        if not 12 <= len(password) <= 200 or password != getpass('Repite la contraseña: '):
            raise SystemExit('Contraseñas distintas o demasiado cortas. Sin cambios.')
        with application.app_context():
            db = application.db()
            with db:
                db.execute('UPDATE users SET password=? WHERE id=1', (generate_password_hash(password),))
                db.execute('DELETE FROM imports')
                db.execute('DELETE FROM sessions')
        print('Contraseña actualizada. Todas las sesiones han sido revocadas.')
    else:
        if not Path(application.config['DATABASE']).exists():
            raise SystemExit('Primero ejecuta: python app.py init --demo')
        from waitress import serve
        print(f'TravelDesk: http://{args.host}:{args.port}', flush=True)
        serve(application, host=args.host, port=args.port, threads=4, max_request_body_size=2*1024*1024)
