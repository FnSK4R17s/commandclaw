"""E2e test configuration — load .env.test for host-side keys."""

from pathlib import Path

from dotenv import load_dotenv

env_test = Path(__file__).resolve().parents[2] / ".env.test"
load_dotenv(env_test)
