import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

BASE = Path.home() / "PyForge"
DASHBOARD = BASE / "dashboard_v2"
API = "http://127.0.0.1:8001"
WEB = "http://127.0.0.1:8002"

passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed

    if condition:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}")

    if detail:
        print(f"       {detail}")


def request(url, method="GET"):
    req = urllib.request.Request(url, method=method)

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read().decode(
                "utf-8", errors="replace"
            )
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(
            "utf-8", errors="replace"
        )
    except Exception as error:
        return 0, str(error)


print("\n===================================")
print(" PYFORGE STARTUP MANAGER TEST SUITE")
print("===================================\n")

# 1. Files
backend = BASE / "runtime/startup_manager.py"
js = DASHBOARD / "startup-dashboard.js"
html = DASHBOARD / "index.html"

test("Startup Manager backend exists", backend.is_file())
test("Dashboard JavaScript exists", js.is_file())
test("Dashboard HTML exists", html.is_file())

# 2. Python compilation
try:
    compile(backend.read_text(), str(backend), "exec")
    test("Backend Python syntax", True)
except Exception as error:
    test("Backend Python syntax", False, str(error))

# 3. Dashboard connection
if html.exists():
    content = html.read_text(encoding="utf-8")
    connected = '<script src="./startup-dashboard.js"></script>' in content
    test("Dashboard script connected", connected)

if js.exists():
    js_content = js.read_text(encoding="utf-8")
    for feature in (
        "/api/startup/status",
        "/api/startup/restart/api",
        "/api/startup/restart/dashboard",
        "/api/startup/wake-lock",
        "setInterval"
    ):
        test(f"Dashboard feature: {feature}", feature in js_content)

# 4. API health
status, body = request(API + "/api/health")
test("API responds HTTP 200", status == 200, body[:250])

# 5. Startup Manager status
status, body = request(API + "/api/startup/status")
test("Startup Manager status endpoint", status == 200, body[:400])

if status == 200:
    try:
        data = json.loads(body)
        services = data.get("services", {})

        for key in (
            "api",
            "dashboard",
            "supervisor",
            "backup_guardian"
        ):
            test(
                f"Service status included: {key}",
                key in services
            )
    except Exception as error:
        test("Status response is valid JSON", False, str(error))

# 6. Dashboard HTTP
status, body = request(WEB + "/")
test("Dashboard responds HTTP 200", status == 200)

# 7. Security protection
status, body = request(API + "/api/projects")
test(
    "Unauthenticated API access is protected",
    status == 401,
    f"HTTP {status}"
)

# 8. Final report
print("\n===================================")
print(" TEST RESULTS")
print("===================================")
print(f"PASSED: {passed}")
print(f"FAILED: {failed}")
print(f"TOTAL:  {passed + failed}")

if failed == 0:
    print("\nALL TESTS PASSED.")
else:
    print("\nSOME TESTS NEED ATTENTION.")

print("===================================\n")

sys.exit(0 if failed == 0 else 1)
