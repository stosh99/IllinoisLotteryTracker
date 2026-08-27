import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NGINX = ROOT / "deploy" / "nginx"
NEW_ORIGIN = "http://127.0.0.1:8766"


def _read(name: str) -> str:
    return (NGINX / name).read_text(encoding="utf-8")


def test_new_domain_bootstrap_exposes_acme_and_only_proxies_loopback() -> None:
    document = _read("scratchoffdata.com.bootstrap.conf")

    assert "server_name scratchoffdata.com www.scratchoffdata.com;" in document
    assert "root /var/www/scratchoffdata;" in document
    assert f"proxy_pass {NEW_ORIGIN};" in document
    assert "proxy_connect_timeout 5s;" in document
    assert "proxy_read_timeout 30s;" in document
    assert "proxy_send_timeout 30s;" in document
    assert "0.0.0.0:8766" not in document


def test_new_domain_https_serves_apex_and_redirects_http_and_www() -> None:
    document = _read("scratchoffdata.com.conf")

    assert document.count("return 301 https://scratchoffdata.com$request_uri;") == 2
    assert "server_name www.scratchoffdata.com;" in document
    assert "server_name scratchoffdata.com;" in document
    assert "ssl_certificate /etc/letsencrypt/live/scratchoffdata.com/fullchain.pem;" in document
    assert "ssl_certificate_key /etc/letsencrypt/live/scratchoffdata.com/privkey.pem;" in document
    # Several locations now proxy, but every one of them must target loopback.
    proxy_targets = re.findall(r"proxy_pass\s+(\S+);", document)
    assert proxy_targets
    assert set(proxy_targets) == {NEW_ORIGIN}
    assert "root /var/www/scratchoffdata;" in document


def test_new_domain_applies_the_blueprint_source_limits() -> None:
    document = _read("scratchoffdata.com.conf")

    # 10/10min, 30/10min, 120/10min, and 60/10min expressed per minute.
    assert "zone=sod_login_start:1m rate=1r/m;" in document
    assert "zone=sod_callback:1m    rate=3r/m;" in document
    assert "zone=sod_auth_read:1m   rate=12r/m;" in document
    assert "zone=sod_auth_write:1m  rate=6r/m;" in document
    assert "zone=sod_destructive:1m rate=1r/m;" in document
    assert "limit_req zone=sod_login_start burst=3 nodelay;" in document
    assert "limit_req zone=sod_callback burst=10 nodelay;" in document

    # A throttled callback returns a clean local redirect, never an error page
    # that could retain the authorization code or state.
    assert "error_page 429 = @sod_callback_limited;" in document
    assert "return 303 https://scratchoffdata.com/?authResult=failed;" in document
    # Everything else refuses with 429 and tells the caller when to retry.
    assert "add_header Retry-After 60 always;" in document


def test_new_domain_never_logs_query_strings_or_cookies() -> None:
    document = _read("scratchoffdata.com.conf")

    # $uri is the path alone; $request would carry the callback's code=/state=.
    assert '"$request_method $uri $server_protocol"' in document
    assert "$request " not in document
    assert "$query_string" not in document
    assert "$args" not in document
    assert "$http_cookie" not in document
    assert "$sent_http_set_cookie" not in document
    assert "access_log /var/log/nginx/scratchoffdata.access.log sod_safe;" in document


def test_old_domain_is_redirect_only_and_keeps_old_tls_and_acme() -> None:
    document = _read("illinoislotterytracker.com.conf")

    assert "server_name illinoislotterytracker.com www.illinoislotterytracker.com;" in document
    assert document.count("return 301 https://scratchoffdata.com$request_uri;") == 3
    assert "proxy_pass" not in document
    assert "root /var/www/illinoislotterytracker;" in document
    assert (
        "ssl_certificate /etc/letsencrypt/live/illinoislotterytracker.com/fullchain.pem;"
        in document
    )
    assert (
        "ssl_certificate_key "
        "/etc/letsencrypt/live/illinoislotterytracker.com/privkey.pem;"
        in document
    )
