"""Tests for IoT simulator URL validation and security controls."""
import importlib.util
from pathlib import Path

import pytest

sim_path = Path(__file__).resolve().parents[2] / "iot-simulator" / "simulator.py"
spec = importlib.util.spec_from_file_location("simulator", sim_path)
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)


@pytest.mark.parametrize("url", [
    "http://localhost:8000",
    "http://localhost",
    "http://127.0.0.1:8000",
    "http://127.0.0.1",
    "http://[::1]:8000",
    "http://subdomain.localhost:8000",
    "https://api.example.com",
    "https://logistics.onrender.com",
    "https://192.168.1.100:8443",
])
def test_validate_api_url_allowed(url):
    assert sim.validate_api_url(url) == url


@pytest.mark.parametrize("url", [
    "http://api.example.com",
    "http://example.com/api",
    "http://192.168.1.100:8000",
    "http://10.0.0.1:8000",
    "http://remote-host:8000",
])
def test_validate_api_url_rejects_insecure_remote_http(url):
    with pytest.raises(ValueError, match="plain HTTP is only allowed for loopback"):
        sim.validate_api_url(url)


@pytest.mark.parametrize("url", [
    "ftp://localhost",
    "file:///etc/passwd",
    "gopher://localhost",
    "ws://localhost:8000",
])
def test_validate_api_url_rejects_unsupported_schemes(url):
    with pytest.raises(ValueError, match="Invalid API URL scheme"):
        sim.validate_api_url(url)


def test_post_and_login_validate_url_before_dispatch():
    # Ensure invalid URL raises ValueError before any network requests or auth
    with pytest.raises(ValueError, match="plain HTTP is only allowed for loopback"):
        sim.post("http://insecure-remote.example.com", {"test": 1})

    with pytest.raises(ValueError, match="plain HTTP is only allowed for loopback"):
        sim._login("http://insecure-remote.example.com")
