# Put How2 on the web

How2 is a dynamic website. Its accounts, lessons, and progress need a Python server and persistent database storage. GitHub Pages cannot run this backend.

## Recommended first host: Render

No domain purchase is needed. Render supplies an HTTPS `onrender.com` address after deployment. The included `render.yaml` defines the website, a persistent disk for SQLite, Secure cookies, and a generated session key. This configuration uses a **paid Starter service and a paid disk**. Check the prices Render displays before confirming. No service has been created or purchased by Codex.

1. Create an account at https://render.com and connect GitHub.
2. Commit and push the How2 application files from this checkout to a GitHub repository you want to host. Your existing repository is a GitHub profile repository; a dedicated How2 repository is also an option. Do not upload `instance/`, `.venv/`, or any credentials.
3. In Render, choose **New → Blueprint**, select that repository, and review the included `render.yaml`. Confirm only after reviewing the cost.
4. Once deployment succeeds, visit the HTTPS address shown by Render. Check `/healthz`, open a lesson, and test signup and saved progress.
5. In the service's Shell, run these commands separately, entering each person's own details:

   ```sh
   python app.py create-admin --role owner
   python app.py create-admin --role content
   ```

   Password prompts are hidden. Never put passwords in Git or chat. Each person can then sign in at `/admin/login`.

The first deployment starts with seven lessons and no user accounts. Local development data is not uploaded. Later deployments retain data on `/var/data`; never remove the disk without a verified backup. Keep this as one service instance while using SQLite. Automatic deploys are disabled in the Blueprint so future source changes are not published unexpectedly.

## Optional custom domain

After the default site works, add a domain in Render's service settings and follow its DNS instructions. A custom domain is optional; buy one only if you want it.

## Other Python hosts

- Install Python 3.12 and `pip install -r requirements.lock`.
- Mount durable storage and set `HOW2_STATE_DIR` to an absolute path on it. Both the database and fallback session key live there.
- Run `bash scripts/start.sh`. It uses the host's `PORT` variable (default 3000), preloads initialization once, and starts Gunicorn.
- Terminate HTTPS at the host and set `HOW2_HTTPS=1`. Keep a stable secret key or the generated state-directory key.
- Set `HOW2_PROXY_HOPS` only if the application is reachable exclusively through that many trusted reverse proxies. Leave it unset for a direct connection. This setting affects client IP addresses used for rate limits.
- Use `/healthz` for a database-aware health check. Back up SQLite with its backup API, not by copying a live database file blindly.

## Before inviting the public

Email verification/recovery is not implemented; password resets currently require the trusted operator CLI. Review the seed lessons, privacy policy, terms, backups, and operational requirements in DEVELOPMENT.md. Hosting files do not complete these remaining launch tasks. Provider deployment and a public address have not been verified until an actual hosting deployment succeeds.
