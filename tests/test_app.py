import csv
import io
import json
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app, initialize, HEADERS, travel_state


@pytest.fixture
def app(tmp_path):
    app = create_app(tmp_path / 'test.sqlite', secure=False)
    app.config['TESTING'] = True
    initialize(app, 'admin', 'Test-password-2026', demo=True)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged(client):
    result = client.post('/api/login', json={'username':'admin','password':'Test-password-2026'})
    assert result.status_code == 200
    return client, {'X-CSRF-Token': result.json['csrf']}


def test_protected_endpoints(client):
    for route in ['/api/data','/api/session','/api/audit','/api/template.csv']:
        response = client.get(route)
        assert response.status_code == 401
        assert response.headers['Cache-Control'] == 'no-store'
    assert client.post('/api/passengers',json={'name':'intruso'}).status_code == 401


def test_csrf_origin_cookie_logout(logged):
    client, headers = logged
    assert client.post('/api/passengers',json={'name':'X'}).status_code == 403
    assert client.post('/api/passengers',json={'name':'X'},headers={**headers,'Origin':'https://evil.invalid'}).status_code == 403
    assert client.post('/api/passengers',json={'name':'X'},headers={**headers,'Sec-Fetch-Site':'cross-site'}).status_code == 403
    assert client.post('/api/logout',json={},headers=headers).status_code == 200
    assert client.get('/api/data').status_code == 401


def test_secure_cookie_and_hsts(tmp_path):
    app = create_app(tmp_path/'secure.sqlite', secure=True)
    initialize(app,'admin','Test-password-2026')
    response = app.test_client().post('/api/login',json={'username':'admin','password':'Test-password-2026'})
    cookie = response.headers['Set-Cookie']
    assert 'Secure;' in cookie and 'HttpOnly;' in cookie and 'SameSite=Strict' in cookie
    assert 'max-age' in response.headers['Strict-Transport-Security']


def test_throttling_is_persisted(client):
    for _ in range(5):
        assert client.post('/api/login',json={'username':'admin','password':'bad'}).status_code == 401
    assert client.post('/api/login',json={'username':'admin','password':'Test-password-2026'}).status_code == 429


def test_idle_and_absolute_session_expiry(app, logged):
    client, headers = logged
    with app.app_context():
        app.db().execute('UPDATE sessions SET last_seen=0')
        app.db().commit()
    assert client.get('/api/data').status_code == 401
    response = client.post('/api/login',json={'username':'admin','password':'Test-password-2026'})
    assert response.status_code == 200
    with app.app_context():
        app.db().execute('UPDATE sessions SET expires=0')
        app.db().commit()
    assert client.get('/api/data').status_code == 401


def booking(pid=1, **updates):
    result = {'passenger_id':pid,'reference':'TEST01','origin':'MAD','destination':'BOG','flight':'TD001',
              'departure':'2026-11-05T10:00:00+01:00','arrival':'2026-11-05T19:00:00+01:00',
              'stops':'Directo','status':'confirmada','total':'100.25'}
    result.update(updates)
    return result


def test_passenger_booking_payment_lifecycle(logged):
    client, headers = logged
    p = client.post('/api/passengers',json={'name':'Persona Prueba','email':'prueba@example.invalid'},headers=headers)
    assert p.status_code == 201
    pid = p.json['id']
    b = client.post('/api/bookings',json=booking(pid),headers=headers)
    assert b.status_code == 201
    bid = b.json['id']
    assert client.post('/api/bookings',json=booking(pid),headers=headers).status_code == 409
    assert client.post(f'/api/bookings/{bid}/payments',json={'amount':'30.10','method':'transferencia'},headers=headers).status_code == 201
    assert client.post(f'/api/bookings/{bid}/payments',json={'amount':'70.16','method':'efectivo'},headers=headers).status_code == 400
    assert client.put(f'/api/bookings/{bid}',json=booking(pid,total='20.00'),headers=headers).status_code == 400
    payload = client.get('/api/data').json
    record = next(b for b in payload['bookings'] if b['id']==bid)
    assert record['total'] == 10025 and record['paid'] == 3010
    payment = next(p for p in payload['payments'] if p['booking_id']==bid)
    assert client.delete(f"/api/payments/{payment['id']}",json={},headers=headers).status_code == 200
    assert client.put(f'/api/passengers/{pid}',json={'name':'Editado'},headers=headers).status_code == 200
    assert client.delete(f'/api/passengers/{pid}',json={},headers=headers).status_code == 200
    assert not any(b['id']==bid for b in client.get('/api/data').json['bookings'])
    audit = client.get('/api/audit').json['events']
    assert any(e['action']=='erase' for e in audit)
    assert 'Persona Prueba' not in json.dumps(audit)


@pytest.mark.parametrize('updates',[
    {'arrival':'2026-01-01T00:00:00Z'}, {'departure':'2026-11-05T10:00'},
    {'origin':'<x>'},{'origin':'BOG'},{'passenger_id':999},{'total':'NaN'},
    {'total':'0.001'},{'total':'-1'},{'status':'en tránsito'},{'reference':''},
])
def test_booking_validation(logged,updates):
    client, headers = logged
    assert client.post('/api/bookings',json=booking(**updates),headers=headers).status_code == 400


def test_cancelled_booking_rejects_new_payment(logged):
    client, headers=logged
    b=client.post('/api/bookings',json=booking(status='cancelada'),headers=headers).json
    assert client.post(f"/api/bookings/{b['id']}/payments",json={'amount':'1','method':'efectivo'},headers=headers).status_code == 400


def test_itinerary_state_boundaries():
    b={'status':'confirmada','departure':'2026-11-01T10:00:00+00:00','arrival':'2026-11-01T20:00:00+00:00'}
    for hour,expected in [(9,'próximo'),(10,'en tránsito'),(19,'en tránsito'),(20,'finalizado')]:
        assert travel_state(b,datetime(2026,11,1,hour,tzinfo=timezone.utc)) == expected
    b['status']='cancelada'
    assert travel_state(b)=='cancelado'


def import_row(**updates):
    row={'nombre':'Importado Uno','email':'import@example.invalid','telefono':'000','localizador':'IMP001',
         'origen':'MAD','destino':'LIM','vuelo':'TD900','salida':'2026-11-12T10:00:00+01:00',
         'llegada':'2026-11-12T23:00:00+01:00','escalas':'BOG','estado':'confirmada','importe':'900.50','pagado':'100.20'}
    row.update(updates)
    return [row[h] for h in HEADERS]


def upload_csv(client,headers,rows):
    data=io.StringIO();writer=csv.writer(data);writer.writerow(HEADERS);writer.writerows(rows)
    return client.post('/api/import/preview',data={'file':(io.BytesIO(data.getvalue().encode()),'import.csv')},headers=headers)


def test_csv_preview_atomic_commit_replay_duplicate(logged):
    client, headers=logged
    before=len(client.get('/api/data').json['bookings'])
    preview=upload_csv(client,headers,[import_row()])
    assert preview.status_code == 200 and not preview.json['errors']
    assert len(client.get('/api/data').json['bookings'])==before
    result=client.post('/api/import/commit',json={'token':preview.json['token']},headers=headers)
    assert result.json['imported']==1
    assert len(client.get('/api/data').json['bookings'])==before+1
    assert client.post('/api/import/commit',json={'token':preview.json['token']},headers=headers).status_code==400
    duplicate=upload_csv(client,headers,[import_row()])
    assert duplicate.json['errors']


def test_invalid_import_cannot_partially_commit(logged):
    client, headers=logged
    preview=upload_csv(client,headers,[import_row(),import_row(nombre='Otro',pagado='9999')])
    assert preview.json['errors'][0]['row']==3
    before=client.get('/api/data').json
    assert client.post('/api/import/commit',json={'token':preview.json['token']},headers=headers).status_code==400
    assert client.get('/api/data').json['bookings']==before['bookings']


def test_preview_token_bound_to_session_and_expiry(app,logged):
    client, headers=logged
    preview=upload_csv(client,headers,[import_row()]).json
    other=app.test_client()
    csrf=other.post('/api/login',json={'username':'admin','password':'Test-password-2026'}).json['csrf']
    assert other.post('/api/import/commit',json={'token':preview['token']},headers={'X-CSRF-Token':csrf}).status_code==400
    with app.app_context():
        app.db().execute('UPDATE imports SET expires=0');app.db().commit()
    assert client.post('/api/import/commit',json={'token':preview['token']},headers=headers).status_code==400


def test_excel_and_formula_rejection(logged):
    client, headers=logged
    for formula in (False,True):
        workbook=Workbook();sheet=workbook.active;sheet.append(HEADERS);row=import_row()
        if formula:row[0]='=1+1'
        sheet.append(row);buffer=io.BytesIO();workbook.save(buffer);buffer.seek(0)
        result=client.post('/api/import/preview',data={'file':(buffer,'sample.xlsx')},headers=headers)
        assert result.status_code==(400 if formula else 200)
        if not formula:assert not result.json['errors']


def test_empty_database_import(tmp_path):
    app=create_app(tmp_path/'empty.sqlite',secure=False);initialize(app,'admin','Test-password-2026')
    client=app.test_client();headers={'X-CSRF-Token':client.post('/api/login',json={'username':'admin','password':'Test-password-2026'}).json['csrf']}
    preview=upload_csv(client,headers,[import_row()])
    assert not preview.json['errors']
    assert client.get('/api/data').json['passengers']==[]
    assert client.post('/api/import/commit',json={'token':preview.json['token']},headers=headers).status_code==200


def test_payload_limits_and_security_headers(logged):
    client,headers=logged
    assert client.post('/api/passengers',json=[],headers=headers).status_code==400
    assert client.post('/api/passengers',json={'name':'A'*101},headers=headers).status_code==400
    assert client.post('/api/passengers',data='x',headers=headers).status_code==415
    assert client.post('/api/passengers',json={'name':'X'*2200000},headers=headers).status_code==413
    response=client.get('/')
    assert response.status_code==200
    assert "script-src 'self'" in response.headers['Content-Security-Policy']
    assert 'frame-ancestors' in response.headers['Content-Security-Policy']
    assert client.get('/app.py').status_code==404
    assert client.get('/instance/traveldesk.sqlite').status_code==404
    assert client.get('/manifest.webmanifest').status_code==200


def test_sql_injection_is_data(logged):
    client,headers=logged
    assert client.post('/api/passengers',json={'name':"Robert'); DROP TABLE passengers;--"},headers=headers).status_code==201
    assert len(client.get('/api/data').json['passengers'])==7


def test_init_never_overwrites(app):
    with pytest.raises(ValueError,match='inicializada'):
        initialize(app,'attacker','different-password')


def test_import_rolls_back_if_duplicate_created_after_preview(logged):
    client,headers=logged
    preview=upload_csv(client,headers,[import_row(nombre='Primero',localizador='IMP000'),import_row()]).json
    pid=client.post('/api/passengers',json={'name':'Importado Uno','email':'import@example.invalid'},headers=headers).json['id']
    assert client.post('/api/bookings',json=booking(pid,reference='IMP001'),headers=headers).status_code==201
    before=client.get('/api/data').json
    assert client.post('/api/import/commit',json={'token':preview['token']},headers=headers).status_code==409
    after=client.get('/api/data').json
    assert after['passengers']==before['passengers']
    assert after['bookings']==before['bookings']


def test_data_persists_between_app_instances(app,logged):
    client,headers=logged
    client.post('/api/passengers',json={'name':'Persistente'},headers=headers)
    reopened=create_app(app.config['DATABASE'],secure=False).test_client()
    assert reopened.get('/api/data').status_code==401
    reopened.post('/api/login',json={'username':'admin','password':'Test-password-2026'})
    assert any(p['name']=='Persistente' for p in reopened.get('/api/data').json['passengers'])


def test_consistent_backup_removes_sessions(app,logged,tmp_path):
    import sqlite3
    import subprocess
    client,headers=logged
    upload_csv(client,headers,[import_row()])
    destination=tmp_path/'backup.sqlite'
    result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'backup.py'),app.config['DATABASE'],str(destination)],capture_output=True,text=True)
    assert result.returncode==0, result.stderr
    with sqlite3.connect(destination) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM passengers').fetchone()[0]==6
        assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM imports').fetchone()[0]==0
