"""Utilitários comuns dos testes da Parte 2 (somente biblioteca padrão)."""
import json
import os
import math
import statistics
import time
import urllib.error
import urllib.request

AUTH = "http://localhost:8001"
MARKET = "http://localhost:8002"
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26}


def call(method, url, body=None, token=None, timeout=10):
    """Retorna (status, json, latência_ms). status 0 = falha de rede/timeout."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}"), (time.perf_counter() - t0) * 1000
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except Exception:
            payload = {}
        return e.code, payload, (time.perf_counter() - t0) * 1000
    except Exception:
        return 0, {}, (time.perf_counter() - t0) * 1000


def new_user(prefix):
    name = f"{prefix}{int(time.time() * 1000000) % 10**11}"[:20]
    call("POST", f"{AUTH}/register", {"username": name, "password": "senha123"})
    _, resp, _ = call("POST", f"{AUTH}/login", {"username": name, "password": "senha123"})
    return name, resp.get("access_token")


def mean_ci(values):
    """Média e meia-largura do IC 95% (t de Student)."""
    n = len(values)
    if n < 2:
        return (values[0] if values else 0.0), 0.0
    sd = statistics.stdev(values)
    return statistics.mean(values), T95.get(n - 1, 1.96) * sd / math.sqrt(n)


def pct(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * p / 100))]


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
os.makedirs(RES, exist_ok=True)
