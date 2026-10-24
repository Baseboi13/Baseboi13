# How2 development

Python 3.12, Flask, SQLite, and vanilla JavaScript. No external database or account provider is required for local development. The original profile README is preserved.

## Install and run

```sh
cd /workspace/Baseboi13
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python app.py init
.venv/bin/python -m gunicorn --bind 0.0.0.0:3000 --workers 2 wsgi:app
```

Initialization is idempotent. The SQLite database and generated session signing key are in ignored `instance/`. Back up both securely; never commit them. Live processes must be started again after restoring the environment. Use the existing checkout: cloud tasks are isolated, so no worktree is needed.

## Create two individual administrators

Run twice, with each administrator's own email and password. Password prompts do not echo. No default credentials exist.

```sh
.venv/bin/python app.py create-admin --role owner
.venv/bin/python app.py create-admin --role content
```

Open `/admin/login`. The owner can change account roles under Users. Content administrators can manage lessons, categories, paths, feedback, and the homepage but cannot manage users. Reset a password through the trusted operator terminal:

```sh
.venv/bin/python app.py reset-password
```

Email delivery, self-service email verification, and email password recovery are not configured. Do not claim email recovery is available. Configure and test a provider before public deployment. Google sign-in and MFA are optional and not implemented.

## Validation

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
curl --fail http://127.0.0.1:3000/api/catalog
```

Tests use temporary databases and verify draft visibility, publish/archive, dynamic categories, permission boundaries for owner/content/learner, per-user progress isolation, deletion, feedback, settings, paths, CSRF, quiz validation, login throttling, password-change session revocation, and recipe review visibility.

## Current implementation and limits

- Seven written lessons, six categories, searchable published content, optional form-authored quiz, explicit completion, saved lessons, progress, three paths, optional preferences.
- Admin lesson editor with safe headings, bold, lists, links, image URLs, and privacy-enhanced YouTube embeds, draft preview, publish/archive; category names/descriptions/icons/colors/order/visibility; lesson selection and ordering in paths; homepage text/announcement/featured lessons/color/image URL/recommended paths; feedback status and activity log.
- Budget, savings, and apartment calculators run locally in the browser, without transmitting financial entries.
- Sources and content dates are visible. Seed lessons are not expert-reviewed. Editorial review flags are shown honestly.
- Admin recipe library and meal planner support review-gated recipes, dietary preferences, meal count, and budget allowances without claiming current prices. No recipes are pre-labeled as reviewed. Administrators must supply and actually review recipes before the planner can suggest them. File uploads and a WYSIWYG editor remain future enhancements; the existing formatting toolbar and preview support safe rich content.
- No invented engagement, popularity, reviews, or testimonials.

## Public deployment prerequisites

Use HTTPS and set `HOW2_HTTPS=1` for Secure cookies. Set a stable high-entropy `HOW2_SECRET_KEY` through deployment secrets or retain the protected instance key. Optionally set `HOW2_DATABASE` to persistent storage. Terminate HTTPS at a trusted reverse proxy, configure canonical host restrictions, backups and retention, email verification/recovery, monitoring, and account-abuse controls. Review content and youth privacy/legal policies before public launch. Do not enable Flask debug mode. This is a development implementation, not a completed production launch.
