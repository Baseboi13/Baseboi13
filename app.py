import os, json, sqlite3, secrets, functools, time, getpass
from pathlib import Path
from datetime import timedelta
from flask import Flask, request, session, jsonify, g, abort, render_template
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = Path(__file__).parent
state_dir = os.getenv('HOW2_STATE_DIR')
app = Flask(__name__, instance_relative_config=True, **({'instance_path': str(Path(state_dir).resolve())} if state_dir else {}))
Path(app.instance_path).mkdir(parents=True, exist_ok=True)
# Enable only behind the configured number of trusted reverse proxies.
proxy_hops = int(os.getenv('HOW2_PROXY_HOPS', '0'))
if proxy_hops:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops, x_proto=proxy_hops, x_host=0, x_port=0, x_prefix=0)
keyfile = Path(app.instance_path) / 'session.key'
if not keyfile.exists():
    try:
        fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f: f.write(secrets.token_hex(32))
    except FileExistsError: pass
app.config.update(SECRET_KEY=os.getenv('HOW2_SECRET_KEY') or keyfile.read_text(), DATABASE=os.getenv('HOW2_DATABASE', str(Path(app.instance_path)/'how2.sqlite')), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('HOW2_HTTPS')=='1', PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=1024*1024)

def db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'], timeout=20)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db
@app.teardown_appcontext
def close(_):
    if 'db' in g: g.db.close()
def rows(sql, args=()): return [dict(r) for r in db().execute(sql,args).fetchall()]
def run(sql,args=()):
    cur=db().execute(sql,args); db().commit(); return cur.lastrowid

def user():
    return next(iter(rows('SELECT id,email,name,role,preferences FROM users WHERE id=? AND auth_version=?',(session.get('uid',0),session.get('auth_version',-1)))),None)
def require(admin=False,owner=False):
    def decorate(fn):
        @functools.wraps(fn)
        def wrap(*a,**kw):
            u=user()
            if not u: abort(401, 'Please sign in to continue.')
            if admin and u['role'] not in ('owner','content'): abort(403)
            if owner and u['role']!='owner': abort(403)
            return fn(*a,**kw)
        return wrap
    return decorate
@app.before_request
def csrf():
    session.permanent=True
    if 'csrf' not in session: session['csrf']=secrets.token_hex(24)
    if request.method in ('POST','PUT','PATCH','DELETE') and request.headers.get('X-CSRF-Token')!=session['csrf']: abort(400,'Refresh the page and try again.')
@app.after_request
def headers(resp):
    resp.headers['X-Content-Type-Options']='nosniff'
    resp.headers['X-Frame-Options']='DENY'
    resp.headers['Referrer-Policy']='same-origin'
    resp.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; frame-src https://www.youtube-nocookie.com; script-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    if request.path.startswith('/api/'): resp.headers['Cache-Control']='no-store'
    return resp
@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(409)
@app.errorhandler(429)
def error(e): return jsonify(error=e.description),e.code

def init():
    db().executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'user',preferences TEXT DEFAULT '{}',auth_version INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,icon TEXT,color TEXT,position INTEGER DEFAULT 0,visible INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY,title TEXT NOT NULL,category_id INTEGER NOT NULL REFERENCES categories(id),description TEXT NOT NULL,minutes INTEGER DEFAULT 5,difficulty TEXT DEFAULT 'Beginner',content TEXT NOT NULL,example TEXT DEFAULT '',quiz TEXT DEFAULT '[]',keywords TEXT DEFAULT '',status TEXT DEFAULT 'draft',review_date TEXT DEFAULT '',sources TEXT DEFAULT '',needs_review INTEGER DEFAULT 1,updated TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS saved(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,lesson_id INTEGER REFERENCES lessons(id),created TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(user_id,lesson_id));
    CREATE TABLE IF NOT EXISTS progress(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,lesson_id INTEGER REFERENCES lessons(id),completed INTEGER DEFAULT 0,updated TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(user_id,lesson_id));
    CREATE TABLE IF NOT EXISTS recipes(id INTEGER PRIMARY KEY,name TEXT NOT NULL,ingredients TEXT NOT NULL,instructions TEXT NOT NULL,dietary TEXT DEFAULT 'vegetarian',source TEXT NOT NULL,review_date TEXT DEFAULT '',reviewed INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS paths(id INTEGER PRIMARY KEY,name TEXT,description TEXT,lessons TEXT DEFAULT '[]',status TEXT DEFAULT 'draft');
    CREATE TABLE IF NOT EXISTS user_paths(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,path_id INTEGER REFERENCES paths(id),state TEXT DEFAULT 'active',PRIMARY KEY(user_id,path_id));
    CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY,type TEXT,message TEXT,lesson_id INTEGER,date TEXT DEFAULT CURRENT_TIMESTAMP,status TEXT DEFAULT 'New');
    CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT);
    CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY,user_id INTEGER,action TEXT,date TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY,count INTEGER,until REAL);
    ''')
    if 'auth_version' not in [r['name'] for r in rows('PRAGMA table_info(users)')]:
        db().execute('ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0')
    if not rows('SELECT id FROM categories'):
        from seed import seed
        seed(db())
    db().commit()

def audit(action): run('INSERT INTO activity(user_id,action) VALUES(?,?)',(session.get('uid'),action))
def data():
    value=request.get_json(silent=True)
    if not isinstance(value,dict): abort(400,'Expected a JSON object.')
    return value

def limited(key,limit=10,window=900):
    now=time.time()
    run('DELETE FROM attempts WHERE until<?',(now,))
    run('INSERT INTO attempts(key,count,until) VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1',(key,now+window))
    if rows('SELECT count FROM attempts WHERE key=?',(key,))[0]['count']>limit: abort(429,'Too many attempts. Please try again in 15 minutes.')

@app.get('/healthz')
def health():
    db().execute('SELECT 1 FROM settings WHERE id=1').fetchone()
    return jsonify(status='ok')

@app.get('/api/session')
def me(): return jsonify(user=user(),csrf=session['csrf'])
@app.post('/api/auth/<mode>')
def auth(mode):
    d=data(); email=str(d.get('email','')).strip().lower(); password=str(d.get('password',''))
    limited('auth-ip:'+str(request.remote_addr),30)
    limited('auth-email:'+email)
    if mode=='signup':
        if '@' not in email or len(email)>254 or len(password)<12 or not str(d.get('name','')).strip(): abort(400,'Enter a name, valid email, and a password of at least 12 characters.')
        try: uid=run('INSERT INTO users(email,password,name) VALUES(?,?,?)',(email,generate_password_hash(password),str(d['name']).strip()[:80]))
        except sqlite3.IntegrityError: abort(409,'Unable to create this account. Try signing in or contact support.')
    elif mode=='login':
        u=rows('SELECT * FROM users WHERE email=?',(email,))
        if not u or not check_password_hash(u[0]['password'],password): abort(401,'Email or password is incorrect.')
        uid=u[0]['id']
    else: abort(404)
    session.clear(); session['uid']=uid; session['auth_version']=rows('SELECT auth_version FROM users WHERE id=?',(uid,))[0]['auth_version']; session['csrf']=secrets.token_hex(24)
    return jsonify(user=user(),csrf=session['csrf'])
@app.post('/api/logout')
def logout(): session.clear(); return jsonify(ok=True)
@app.route('/api/profile',methods=['PUT','DELETE'])
@require()
def profile():
    d=data(); u=rows('SELECT * FROM users WHERE id=?',(session['uid'],))[0]
    if request.method=='DELETE' or d.get('password'):
        if not check_password_hash(u['password'],str(d.get('current_password',''))): abort(403,'Current password is incorrect.')
    if request.method=='DELETE':
        if u['role']=='owner': abort(400,'Transfer ownership before deleting your owner account.')
        run('DELETE FROM users WHERE id=?',(u['id'],));session.clear();return jsonify(ok=True)
    if d.get('password'):
        if len(d['password'])<12: abort(400,'Use at least 12 characters.')
        run('UPDATE users SET password=?,auth_version=auth_version+1 WHERE id=?',(generate_password_hash(d['password']),u['id']))
        session['auth_version']=u['auth_version']+1
    run('UPDATE users SET name=?,preferences=? WHERE id=?',(str(d.get('name',u['name']))[:80],json.dumps(d.get('preferences',json.loads(u['preferences']))),u['id']))
    return jsonify(ok=True)

@app.get('/api/catalog')
def catalog():
    return jsonify(categories=rows('SELECT * FROM categories WHERE visible=1 ORDER BY position,id'),lessons=rows("SELECT l.* FROM lessons l JOIN categories c ON c.id=l.category_id WHERE l.status='published' AND c.visible=1 ORDER BY l.id"),paths=rows("SELECT * FROM paths WHERE status='published'"),recipes=rows('SELECT * FROM recipes WHERE reviewed=1'),settings=json.loads(rows('SELECT data FROM settings WHERE id=1')[0]['data']))
@app.get('/api/library')
@require()
def library():
    uid=session['uid']
    return jsonify(saved=rows('SELECT lesson_id,created FROM saved WHERE user_id=? ORDER BY created DESC',(uid,)),progress=rows('SELECT * FROM progress WHERE user_id=?',(uid,)),paths=rows('SELECT path_id,state FROM user_paths WHERE user_id=?',(uid,)))
@app.post('/api/lesson/<int:lid>/<action>')
@require()
def learn(lid,action):
    if not rows("SELECT l.id FROM lessons l JOIN categories c ON c.id=l.category_id WHERE l.id=? AND l.status='published' AND c.visible=1",(lid,)): abort(404)
    uid=session['uid']; d=data()
    if action=='save':
        if d.get('saved'): run('INSERT OR IGNORE INTO saved(user_id,lesson_id) VALUES(?,?)',(uid,lid))
        else: run('DELETE FROM saved WHERE user_id=? AND lesson_id=?',(uid,lid))
    elif action=='progress':
        run('INSERT INTO progress(user_id,lesson_id,completed) VALUES(?,?,?) ON CONFLICT(user_id,lesson_id) DO UPDATE SET completed=excluded.completed,updated=CURRENT_TIMESTAMP',(uid,lid,int(bool(d.get('completed')))))
    else: abort(404)
    return jsonify(ok=True)
@app.post('/api/path/<int:pid>')
@require()
def path_state(pid):
    if not rows("SELECT id FROM paths WHERE id=? AND status='published'",(pid,)): abort(404)
    state=data().get('state')
    if state not in ('active','paused'): abort(400)
    run('INSERT INTO user_paths(user_id,path_id,state) VALUES(?,?,?) ON CONFLICT(user_id,path_id) DO UPDATE SET state=excluded.state',(session['uid'],pid,state));return jsonify(ok=True)
@app.post('/api/feedback')
def feedback():
    limited('feedback:'+str(request.remote_addr),10)
    d=data(); msg=str(d.get('message','')).strip()
    if not 10<=len(msg)<=4000: abort(400,'Please write between 10 and 4,000 characters.')
    if d.get('type') not in ('Lesson request','Error report','Feature request','General feedback'): abort(400)
    run('INSERT INTO feedback(type,message,lesson_id) VALUES(?,?,?)',(d['type'],msg,d.get('lesson_id')));return jsonify(ok=True)

@app.get('/api/admin')
@require(admin=True)
def admin_data():
    return jsonify(recipes=rows('SELECT * FROM recipes'),lessons=rows('SELECT * FROM lessons ORDER BY updated DESC'),categories=rows('SELECT * FROM categories ORDER BY position,id'),paths=rows('SELECT * FROM paths'),feedback=rows('SELECT * FROM feedback ORDER BY date DESC'),users=rows('SELECT id,email,name,role FROM users') if user()['role']=='owner' else [],activity=rows('SELECT a.*,u.name FROM activity a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 100'),settings=json.loads(rows('SELECT data FROM settings WHERE id=1')[0]['data']))
@app.post('/api/admin/<kind>')
@require(admin=True)
def admin_save(kind):
    d=data(); ident=d.pop('id',None)
    fields={
        'lessons':['title','category_id','description','minutes','difficulty','content','example','quiz','keywords','status','review_date','sources','needs_review'],
        'categories':['name','description','icon','color','position','visible'],
        'paths':['name','description','lessons','status'],
        'feedback':['status'],
        'recipes':['name','ingredients','instructions','dietary','source','review_date','reviewed'],
    }
    if kind=='settings':
        if not all(isinstance(d.get(k),str) and len(d[k])<1000 for k in ['headline','description','primary']): abort(400,'Invalid homepage settings.')
        import re
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',d['primary']): abort(400,'Choose a valid color.')
        run('UPDATE settings SET data=? WHERE id=1',(json.dumps(d),));audit('Homepage updated');return jsonify(ok=True)
    if kind=='users':
        if user()['role']!='owner': abort(403)
        if d.get('role') not in ('user','content','owner'): abort(400)
        if ident==session['uid'] and d['role']!='owner': abort(400,'Another owner must change your role.')
        run('UPDATE users SET role=? WHERE id=?',(d['role'],ident));audit('Administrator permissions changed');return jsonify(ok=True)
    if kind not in fields: abort(404)
    if kind in ('lessons','paths') and d.get('status') not in ('draft','published','archived'): abort(400,'Choose a valid status.')
    if kind=='lessons':
        if not str(d.get('title','')).strip() or not str(d.get('content','')).strip(): abort(400,'Title and lesson content are required.')
        if d.get('difficulty') not in ('Beginner','Intermediate','Advanced'): abort(400)
        try:
            if not 1<=int(d.get('minutes',0))<=180: raise ValueError()
            quiz=json.loads(d.get('quiz','[]'))
            if not isinstance(quiz,list): raise ValueError()
            for q in quiz:
                if not isinstance(q['question'],str) or not 2<=len(q['options'])<=6 or not all(isinstance(o,str) for o in q['options']) or not isinstance(q['answer'],int) or not 0<=q['answer']<len(q['options']) or not isinstance(q['explanation'],str): raise ValueError()
        except (ValueError,TypeError,KeyError): abort(400,'Check lesson duration and quiz JSON.')
        if not rows('SELECT id FROM categories WHERE id=?',(d.get('category_id'),)): abort(400,'Choose an existing category.')
    if kind=='paths':
        try:
            ids=json.loads(d.get('lessons','[]'))
            if not isinstance(ids,list) or not ids or not all(isinstance(i,int) and rows('SELECT id FROM lessons WHERE id=?',(i,)) for i in ids): raise ValueError()
        except (ValueError,TypeError): abort(400,'Select existing lesson IDs in order.')
    if kind=='recipes':
        if not all(isinstance(d.get(k),str) and d[k].strip() for k in ('name','ingredients','instructions','source')): abort(400,'Complete the recipe name, ingredients, instructions, and reference URL.')
        if not d['source'].startswith('https://'): abort(400,'Use an HTTPS reference URL.')
        if d.get('dietary') not in ('vegetarian','vegan','no restriction'): abort(400,'Choose a dietary classification.')
        if d.get('reviewed') and not d.get('review_date'): abort(400,'A review date is required before publishing a recipe.')
    if kind=='categories':
        if not str(d.get('name','')).strip(): abort(400,'Category name required.')
        import re
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(d.get('color',''))): abort(400,'Choose a valid accent color.')
    if kind=='feedback' and d.get('status') not in ('New','Under Review','Planned','Resolved','Archived'): abort(400)
    chosen={k:d[k] for k in fields[kind] if k in d}
    if not chosen: abort(400)
    try:
        if ident:
            if not rows(f'SELECT id FROM {kind} WHERE id=?',(ident,)): abort(404)
            run(f'UPDATE {kind} SET '+','.join(k+'=?' for k in chosen)+' WHERE id=?',(*chosen.values(),ident))
        else:
            if kind=='feedback': abort(400)
            ident=run(f'INSERT INTO {kind} ('+','.join(chosen)+') VALUES('+','.join('?' for _ in chosen)+')',tuple(chosen.values()))
        if kind=='lessons': run('UPDATE lessons SET updated=CURRENT_TIMESTAMP WHERE id=?',(ident,))
    except sqlite3.IntegrityError: abort(400,'Please complete all required fields.')
    audit(f'{kind.capitalize()} #{ident} saved'+(' ('+d['status']+')' if 'status' in d else ''))
    return jsonify(ok=True,id=ident)

@app.get('/')
@app.get('/<path:path>')
def index(path=''): return render_template('index.html')

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('command',nargs='?',default='serve',choices=['serve','init','create-admin','reset-password']);p.add_argument('--role',choices=['owner','content'],default='content');p.add_argument('--port',type=int,default=3000);args=p.parse_args()
    with app.app_context():
        init()
        if args.command in ('create-admin','reset-password'):
            email=input('Email: ').strip().lower(); password=getpass.getpass('New password (12+ characters): ')
            if '@' not in email or len(password)<12: raise SystemExit('Valid email and 12+ character password required.')
            if args.command=='create-admin':
                name=input('Display name: ').strip() or 'Administrator'
                run('INSERT INTO users(email,password,name,role) VALUES(?,?,?,?)',(email,generate_password_hash(password),name,args.role))
            else:
                if not rows('SELECT id FROM users WHERE email=?',(email,)): raise SystemExit('Account not found.')
                run('UPDATE users SET password=?,auth_version=auth_version+1 WHERE email=?',(generate_password_hash(password),email))
            print('Account updated securely.')
    if args.command=='serve': app.run(host='0.0.0.0',port=args.port,debug=False)
