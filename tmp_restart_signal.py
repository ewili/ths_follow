"""Force kill all python on port 8000 and verify restart."""
import subprocess
import time
import os
import signal

# Find and kill ALL python processes on port 8000
result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
pids = set()
for line in result.stdout.splitlines():
    if ":8000" in line and "LISTEN" in line:
        parts = line.split()
        pid = int(parts[-1])
        pids.add(pid)

if pids:
    for pid in pids:
        print(f"Killing PID {pid}...")
        try:
            os.kill(pid, signal.SIGTERM)
        except:
            os.system(f"taskkill /PID {pid} /F")
    time.sleep(2)
    # Verify killed
    result2 = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
    for line in result2.stdout.splitlines():
        if ":8000" in line and "LISTEN" in line:
            parts = line.split()
            pid = int(parts[-1])
            print(f"Force killing PID {pid}...")
            os.system(f"taskkill /PID {pid} /F /T")
    time.sleep(1)
else:
    print("No process on port 8000")

print("Starting signal-server...")
proc = subprocess.Popen(
    [
        r"d:\ewili\fileDoc\code\ths_follow\signal-server\python311\python.exe",
        "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", "8000",
    ],
    cwd=r"d:\ewili\fileDoc\code\ths_follow\signal-server",
    env={**os.environ, "PYTHONPATH": r"d:\ewili\fileDoc\code\ths_follow\signal-server"},
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)
print(f"Started with PID {proc.pid}")

# Wait and verify
time.sleep(4)
result3 = subprocess.run(
    ["curl", "-s", "http://127.0.0.1:8000/api/signal/status"],
    capture_output=True, text=True
)
print(f"Signal status: {result3.stdout}")
