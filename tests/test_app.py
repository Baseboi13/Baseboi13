import unittest, tempfile, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import app, init, run
from werkzeug.security import generate_password_hash

class How2Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        app.config.update(TESTING=True,DATABASE=str(Path(self.temp.name)/'test.sqlite'))
        self.client=app.test_client()
        with app.app_context():
            init()
            run('INSERT INTO users(email,password,name,role) VALUES(?,?,?,?)',('owner@example.com',generate_password_hash('unique-owner-password'),'Owner','owner'))
            run('INSERT INTO users(email,password,name,role) VALUES(?,?,?,?)',('partner@example.com',generate_password_hash('unique-partner-password'),'Partner','content'))
        self.token=self.client.get('/api/session').json['csrf']
    def tearDown(self): self.temp.cleanup()
    def post(self,url,body,method='POST'):
        return self.client.open('/api/'+url,method=method,json=body,headers={'X-CSRF-Token':self.token})
    def login(self,email='owner@example.com',password='unique-owner-password'):
        r=self.post('auth/login',dict(email=email,password=password))
        self.assertEqual(r.status_code,200)
        self.token=r.json['csrf']
    def lesson(self,status='draft'):
        return dict(title='Test lesson',category_id=1,description='A real test',minutes=5,difficulty='Beginner',content='## Explanation\n\nTest content',example='',quiz='[]',keywords='testing',status=status,review_date='2026-10-24',sources='',needs_review=1)
    def test_public_catalog_and_csrf(self):
        d=self.client.get('/api/catalog').json
        self.assertEqual(len(d['lessons']),7);self.assertEqual(len(d['categories']),6)
        self.assertEqual(self.client.get('/api/admin').status_code,401)
        self.assertEqual(self.client.post('/api/feedback',json={}).status_code,400)
    def test_draft_publish_archive_and_dynamic_categories(self):
        self.login()
        r=self.post('admin/lessons',self.lesson());self.assertEqual(r.status_code,200);lid=r.json['id']
        self.assertNotIn(lid,[l['id'] for l in self.client.get('/api/catalog').json['lessons']])
        self.post('admin/lessons',dict(self.lesson('published'),id=lid))
        self.assertIn(lid,[l['id'] for l in self.client.get('/api/catalog').json['lessons']])
        self.post('admin/lessons',dict(self.lesson('archived'),id=lid))
        self.assertNotIn(lid,[l['id'] for l in self.client.get('/api/catalog').json['lessons']])
        self.assertGreaterEqual(len(self.client.get('/api/admin').json['activity']),3)
        r=self.post('admin/categories',dict(name='New category',description='New skills',color='#eeeeee',icon='learn',position=8,visible=1))
        self.assertEqual(r.status_code,200)
        self.assertIn('New category',[c['name'] for c in self.client.get('/api/catalog').json['categories']])
    def test_partner_permission_and_owner_permissions(self):
        self.login('partner@example.com','unique-partner-password')
        self.assertEqual(self.post('admin/lessons',self.lesson()).status_code,200)
        self.assertEqual(self.post('admin/users',dict(id=1,role='user')).status_code,403)
        self.assertEqual(self.client.get('/api/admin').json['users'],[])
    def test_user_isolation_and_deletion(self):
        r=self.post('auth/signup',dict(email='student@example.com',password='student-password-long',name='Student'));self.assertEqual(r.status_code,200);self.token=r.json['csrf']
        self.assertEqual(self.client.get('/api/admin').status_code,403)
        self.assertEqual(self.post('admin/lessons',self.lesson()).status_code,403)
        self.assertEqual(self.post('lesson/1/save',dict(saved=True)).status_code,200)
        self.post('lesson/1/progress',dict(completed=True))
        self.assertEqual(self.client.get('/api/library').json['saved'][0]['lesson_id'],1)
        self.post('logout',{});self.token=self.client.get('/api/session').json['csrf'];self.login()
        self.assertEqual(self.client.get('/api/library').json['saved'],[])
        self.post('logout',{});self.token=self.client.get('/api/session').json['csrf'];self.login('student@example.com','student-password-long')
        self.assertEqual(self.client.get('/api/library').json['progress'][0]['completed'],1)
        self.assertEqual(self.post('profile',dict(current_password='wrong'),method='DELETE').status_code,403)
        self.assertEqual(self.post('profile',dict(current_password='student-password-long'),method='DELETE').status_code,200)
        self.assertIsNone(self.client.get('/api/session').json['user'])
    def test_homepage_feedback_and_path(self):
        self.post('feedback',dict(type='Lesson request',message='Please add a moving checklist.'))
        self.login();self.assertEqual(len(self.client.get('/api/admin').json['feedback']),1)
        settings=self.client.get('/api/catalog').json['settings'];settings['headline']='A changed headline'
        self.assertEqual(self.post('admin/settings',settings).status_code,200)
        self.assertEqual(self.client.get('/api/catalog').json['settings']['headline'],'A changed headline')
        self.assertEqual(self.post('path/1',dict(state='paused')).status_code,200)
        self.assertEqual(self.client.get('/api/library').json['paths'][0]['state'],'paused')
    def test_recipe_review_visibility(self):
        self.login()
        recipe=dict(name='Test recipe',ingredients='Ingredients and allergy notes',instructions='Follow safe cooking instructions.',dietary='vegetarian',source='https://www.myplate.gov/recipes',review_date='',reviewed=0)
        r=self.post('admin/recipes',recipe);self.assertEqual(r.status_code,200);rid=r.json['id']
        self.assertEqual(self.client.get('/api/catalog').json['recipes'],[])
        recipe.update(id=rid,reviewed=1)
        self.assertEqual(self.post('admin/recipes',recipe).status_code,400)
        recipe['review_date']='2026-10-24'
        self.assertEqual(self.post('admin/recipes',recipe).status_code,200)
        self.assertEqual(self.client.get('/api/catalog').json['recipes'][0]['id'],rid)

    def test_password_change_revokes_other_sessions(self):
        self.login()
        other=app.test_client()
        token=other.get('/api/session').json['csrf']
        logged=other.post('/api/auth/login',json=dict(email='owner@example.com',password='unique-owner-password'),headers={'X-CSRF-Token':token})
        self.assertEqual(logged.status_code,200)
        changed=self.post('profile',dict(current_password='unique-owner-password',password='changed-owner-password'),method='PUT')
        self.assertEqual(changed.status_code,200)
        self.assertEqual(other.get('/api/admin').status_code,401)
        self.assertEqual(self.client.get('/api/admin').status_code,200)

    def test_bad_quiz_rejected_and_login_limited(self):
        self.login();d=self.lesson();d['quiz']='[{"question":"Bad"}]'
        self.assertEqual(self.post('admin/lessons',d).status_code,400)
        for _ in range(10):self.post('auth/login',dict(email='no@example.com',password='wrong'))
        self.assertEqual(self.post('auth/login',dict(email='no@example.com',password='wrong')).status_code,429)

if __name__=='__main__':unittest.main()
