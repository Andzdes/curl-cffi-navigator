import os
import sys
import json
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import get_page, FetchRequest

# Load .env
for env_path in [".env", "../.env"]:
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k.strip()] = v.strip()

TARGETS = [
    "https://cloudflare.com",  # Cloudflare
    "https://datadome.co",     # DataDome
    "https://www.imperva.com", # Imperva
    "https://www.nike.com",    # Often Akamai/PerimeterX
    "https://nowsecure.nl"     # Known test site for anti-bot
]

def run_tests():
    proxy = os.getenv("TEST_PROXY")
    print(f"Using proxy: {proxy}")
    
    for url in TARGETS:
        print(f"\n--- Testing {url} ---")
        req = FetchRequest(
            url=url,
            proxy=proxy,
            for_agent=True,
            force_refresh=True,
            proxy_retries=1
        )
        try:
            res = get_page(req)
            if res.get("requires"):
                print(f"Result: BLOCKED")
                print(f"Vendor: {res.get('vendor')}")
                print(f"Block Type: {res.get('block_type')}")
                print(f"Requires: {res.get('requires')}")
            else:
                print(f"Result: SUCCESS (No block detected)")
                print(f"Title: {res.get('markdown', '').splitlines()[0:3]}")
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(1)

if __name__ == "__main__":
    run_tests()
