import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_docker_files_live_under_build_directory():
    assert (PROJECT_ROOT / "build" / "Dockerfile").exists()
    assert (PROJECT_ROOT / "build" / "Dockerfile.ui").exists()
    assert (PROJECT_ROOT / "build" / "Dockerfile国内源版").exists()
    assert (PROJECT_ROOT / "build" / "docker-compose.yml").exists()
    assert (PROJECT_ROOT / "build" / ".dockerignore").exists()
    assert (PROJECT_ROOT / "build" / "nginx.conf").exists()
    assert not (PROJECT_ROOT / "build" / "backend_api.py").exists()
    assert (PROJECT_ROOT / "app" / "gateway.py").exists()

    assert not (PROJECT_ROOT / "Dockerfile").exists()
    assert not (PROJECT_ROOT / "Dockerfile国内源版").exists()
    assert not (PROJECT_ROOT / "docker-compose.yml").exists()


def test_root_dockerignore_is_compatibility_shim():
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "Docker compatibility shim" in dockerignore
    assert "build/.dockerignore" in dockerignore


def test_docker_compose_has_frontend_and_backend_services():
    compose = (PROJECT_ROOT / "build" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "frontend:" in compose
    assert "backend:" in compose
    assert "build/Dockerfile.ui" in compose
    assert "8080:80" in compose
    assert "8501:8501" in compose
    assert "8503:8503" not in compose
    assert "/api/health" in compose
    assert "_stcore/health" not in compose


def test_nginx_conf_supports_spa_fallback_and_backend_proxy():
    nginx = (PROJECT_ROOT / "build" / "nginx.conf").read_text(encoding="utf-8")
    assert "try_files $uri /index.html" in nginx
    assert "proxy_pass http://backend:8501" in nginx
    assert "proxy_pass http://backend:8503" not in nginx
    assert "/api/" in nginx


def test_backend_dockerfiles_point_to_api_server():
    dockerfile = (PROJECT_ROOT / "build" / "Dockerfile").read_text(encoding="utf-8")
    cn_dockerfile = (PROJECT_ROOT / "build" / "Dockerfile国内源版").read_text(encoding="utf-8")

    for text in [dockerfile, cn_dockerfile]:
        assert "app/gateway.py" in text
        assert "/api/health" in text
        assert "_stcore/health" not in text
        assert "streamlit run app.py" not in text.lower()


def test_backend_api_shim_exposes_health_endpoint():
    backend_api = PROJECT_ROOT / "app" / "gateway.py"
    port = _find_free_port()
    env = os.environ.copy()
    env["PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, str(backend_api)],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_health(port)
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["status"] == "ok"
        assert payload["service"] == "xuanwu-api"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1):
                return
        except Exception as exc:  # pragma: no cover - only on startup races
            last_error = exc
            time.sleep(0.2)
    raise AssertionError(f"gateway.py did not become healthy: {last_error}")
