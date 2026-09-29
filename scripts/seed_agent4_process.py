#!/usr/bin/env python3
"""Seed an Agent 4 ready sample process into the local development store."""

import os
import sys
from pathlib import Path

# Add services/api to sys.path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "services" / "api"))

from app.database.memory import get_memory_store
from app.database.seed_demo import DEFAULT_ORG_ID, DEFAULT_USER_ID, seed_agent4_demo_process, AGENT4_PROCESS_NAME
from app.repositories.memory_repos import ProcessRepository

def main():
    print(f"[*] Seeding Agent 4 Ready process for Org {DEFAULT_ORG_ID}...")
    store = get_memory_store()
    seed_agent4_demo_process(store, organization_id=DEFAULT_ORG_ID, user_id=DEFAULT_USER_ID)
    
    repo = ProcessRepository(DEFAULT_ORG_ID, store)
    proc = next((p for p in repo.list_all() if p.name == AGENT4_PROCESS_NAME), None)
    if proc:
        print(f"[✓] Successfully seeded: '{proc.name}' (ID: {proc.id})")
        print("    Status: Confirmed plan with approved snapshot.")
        print("    Open the UI at http://localhost:5173/plans or http://localhost:5173/runs to launch Agent 4 Execution Hub!")
    else:
        print("[!] Process was already present or could not be found.")

if __name__ == "__main__":
    main()
