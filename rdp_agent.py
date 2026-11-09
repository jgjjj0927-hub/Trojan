# language: Python, file: rdp_agent.py
import os, sys
import rdp_agent_lib

HOST = os.getenv("RAT_HOST", "127.0.0.1")
PORT = int(os.getenv("RAT_PORT", "5555"))
SAFE = os.getenv("RAT_SAFE", "1") == "1"

if __name__ == "__main__":
    if SAFE:
        print("[rdp_agent] SAFE_MODE: не подключаюсь.")
        sys.exit(0)
    rdp_agent_lib.run(HOST, PORT)
