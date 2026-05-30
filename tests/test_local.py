import os
import json
from main import get_page, FetchRequest

# Load .env manually to avoid extra dependencies
for env_path in [".env", "../.env"]:
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k.strip()] = v.strip()

def test():
    req = FetchRequest(
        url="https://www.salford-works.com",
        proxy=os.getenv("TEST_PROXY"),
        for_agent=True,
        show_external_links=True
    )
    
    try:
        res = get_page(req)
        print("--- Navigation Links ---")
        print(json.dumps(res.get("navigation", {}), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test()
