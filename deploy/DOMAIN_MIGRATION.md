# Public-domain migration: scratchoffdata.com

This runbook moves the public edge from `illinoislotterytracker.com` to
`scratchoffdata.com` without renaming the repository, package, databases,
systemd units, VPS paths, environment-file locations, or application routes.
Run these commands on the production VPS only during an authorized cutover.

Authentication remains disabled during this migration. Do not edit the private
production environment or Google OAuth client as part of cutover.

## Preconditions

Before changing Nginx, confirm public DNS has propagated:

- `scratchoffdata.com` A/AAAA records resolve only to the intended VPS addresses.
- `www.scratchoffdata.com` resolves to the same VPS (A/AAAA or CNAME).
- Both names are reachable on TCP ports 80 and 443.
- The existing `illinoislotterytracker.com` certificate is valid and retained.
- The production origin still listens only on `127.0.0.1:8766`.

From an operator workstation:

```bash
dig +short A scratchoffdata.com
dig +short AAAA scratchoffdata.com
dig +short A www.scratchoffdata.com
dig +short AAAA www.scratchoffdata.com
```

## 1. Create the webroot and install the HTTP bootstrap

On the VPS, from the repository checkout:

```bash
sudo install -d -o root -g www-data -m 0755 /var/www/scratchoffdata/.well-known/acme-challenge
sudo install -o root -g root -m 0644 \
  deploy/nginx/scratchoffdata.com.bootstrap.conf \
  /etc/nginx/sites-available/scratchoffdata.com
sudo ln -s /etc/nginx/sites-available/scratchoffdata.com \
  /etc/nginx/sites-enabled/scratchoffdata.com
sudo nginx -t
sudo systemctl reload nginx
```

If the exact enabled symlink already exists, do not recreate it; verify it with
`readlink -f /etc/nginx/sites-enabled/scratchoffdata.com`.

Create a probe without putting secrets in it:

```bash
printf '%s\n' 'scratchoffdata-acme-check' | sudo tee \
  /var/www/scratchoffdata/.well-known/acme-challenge/preflight >/dev/null
curl -fsS http://scratchoffdata.com/.well-known/acme-challenge/preflight
curl -fsS http://www.scratchoffdata.com/.well-known/acme-challenge/preflight
sudo rm /var/www/scratchoffdata/.well-known/acme-challenge/preflight
```

Both responses must be exactly `scratchoffdata-acme-check` before continuing.

## 2. Request the new certificate

Use the established Certbot webroot convention and include both names:

```bash
sudo certbot certonly --webroot \
  --webroot-path /var/www/scratchoffdata \
  --cert-name scratchoffdata.com \
  -d scratchoffdata.com \
  -d www.scratchoffdata.com
sudo certbot certificates --cert-name scratchoffdata.com
```

The resulting certificate paths must be:

```text
/etc/letsencrypt/live/scratchoffdata.com/fullchain.pem
/etc/letsencrypt/live/scratchoffdata.com/privkey.pem
```

## 3. Install and verify the final new-domain vhost

```bash
sudo install -o root -g root -m 0644 \
  deploy/nginx/scratchoffdata.com.conf \
  /etc/nginx/sites-available/scratchoffdata.com
sudo nginx -t
sudo systemctl reload nginx
```

Verify redirects, certificates, direct SPA routes, public data, and disabled auth:

```bash
curl -fsSI 'http://scratchoffdata.com/test/path?strategy=value_full'
curl -fsSI 'http://www.scratchoffdata.com/test/path?strategy=value_full'
curl -fsSI 'https://www.scratchoffdata.com/test/path?strategy=value_full'
curl -fsS https://scratchoffdata.com/ >/dev/null
curl -fsS https://scratchoffdata.com/tickets >/dev/null
curl -fsS https://scratchoffdata.com/api/v1/rankings >/dev/null
curl -fsS https://scratchoffdata.com/api/v1/auth/session
GAME_ID="$(curl -fsS https://scratchoffdata.com/api/v1/rankings | jq -r '.rankings[0].gameId')"
test -n "$GAME_ID" && test "$GAME_ID" != null
curl -fsS "https://scratchoffdata.com/games/$GAME_ID" >/dev/null
openssl s_client -connect scratchoffdata.com:443 -servername scratchoffdata.com \
  </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

Each redirect must use status 301 and retain the complete path and query string.
The auth response must report authentication unavailable
and unauthenticated. Confirm Uvicorn remains loopback-only with `ss -ltnp`.

Deploy the reviewed Scratch-Off Data application release through the existing
release procedure, then repeat every check above before touching the old vhost.

## 4. Activate old-domain redirects only after new-domain verification

The repository's `illinoislotterytracker.com.conf` becomes redirect-only but keeps
the old certificate and old ACME webroot. Install it only after the new HTTPS
application and release have passed all checks:

```bash
sudo cp -a /etc/nginx/sites-available/illinoislotterytracker.com \
  /etc/nginx/sites-available/illinoislotterytracker.com.pre-scratchoffdata
sudo install -o root -g root -m 0644 \
  deploy/nginx/illinoislotterytracker.com.conf \
  /etc/nginx/sites-available/illinoislotterytracker.com
sudo nginx -t
sudo systemctl reload nginx
```

Verify all four old-origin cases with a path and query string:

```bash
curl -fsSI 'http://illinoislotterytracker.com/games/1?strategy=value_full'
curl -fsSI 'https://illinoislotterytracker.com/games/1?strategy=value_full'
curl -fsSI 'http://www.illinoislotterytracker.com/games/1?strategy=value_full'
curl -fsSI 'https://www.illinoislotterytracker.com/games/1?strategy=value_full'
```

Every response must be 301 with `Location:
https://scratchoffdata.com/games/1?strategy=value_full`.

## 5. Renewal verification

Keep both certificates and both ACME webroots. Verify each lineage and then the
normal renewal command:

```bash
sudo certbot certificates --cert-name scratchoffdata.com
sudo certbot certificates --cert-name illinoislotterytracker.com
sudo certbot renew --cert-name scratchoffdata.com --dry-run --no-random-sleep-on-renew
sudo certbot renew --cert-name illinoislotterytracker.com --dry-run --no-random-sleep-on-renew
sudo nginx -t
systemctl status certbot.timer
```

The installed deploy hook must remain `deploy/certbot/reload-nginx`: it validates
Nginx before reloading after renewal.

## Authentication follow-up (not part of this cutover)

Before authentication is publicly enabled, separately update the protected
production configuration and Google OAuth client to exactly:

```text
PUBLIC_BASE_URL=https://scratchoffdata.com
Google authorized JavaScript origin: https://scratchoffdata.com
Google authorized redirect URI: https://scratchoffdata.com/api/v1/auth/google/callback
```

The callback is the application's existing `PUBLIC_BASE_URL +
/api/v1/auth/google/callback` route. Keep the existing host-only `__Host-` cookies;
do not add a cookie `Domain` attribute. Authentication must remain disabled until
its separate release gate passes.

The `scratchoffdata.siteNotice` localStorage record is origin-scoped. Do not copy
it from the old origin; the new origin correctly presents the notice once.

## Immediate rollback

If the new vhost fails before old-domain redirect activation, restore the saved
new-domain bootstrap:

```bash
sudo install -o root -g root -m 0644 \
  deploy/nginx/scratchoffdata.com.bootstrap.conf \
  /etc/nginx/sites-available/scratchoffdata.com
sudo nginx -t
sudo systemctl reload nginx
```

If failure occurs after old-domain redirect activation, restore the old serving
vhost first, then leave or restore the new bootstrap as appropriate:

```bash
sudo install -o root -g root -m 0644 \
  /etc/nginx/sites-available/illinoislotterytracker.com.pre-scratchoffdata \
  /etc/nginx/sites-available/illinoislotterytracker.com
sudo nginx -t
sudo systemctl reload nginx
curl -fsS https://illinoislotterytracker.com/api/v1/rankings >/dev/null
```

Do not delete either certificate, disable either renewal lineage, edit private
environment files, alter DNS, or change the loopback production service during
this rollback.
