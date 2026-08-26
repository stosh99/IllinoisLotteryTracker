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
    assert document.count(f"proxy_pass {NEW_ORIGIN};") == 1
    assert "root /var/www/scratchoffdata;" in document


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
