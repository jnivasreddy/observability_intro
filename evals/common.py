"""Shared paths and credentials. No servers or paid calls on import."""
import json
import os
from pathlib import Path
import sys
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))
load_dotenv(PROJECT / ".env")


def read_json(path):
    return json.loads(Path(path).read_text())


def smith_client():
    from langsmith import Client
    if not os.getenv("LANGSMITH_API_KEY"):
        raise ValueError("Set LANGSMITH_API_KEY in session_1_monitoring/.env")
    return Client(timeout_ms=15000)


def golden():
    return read_json(HERE / "golden.json")
