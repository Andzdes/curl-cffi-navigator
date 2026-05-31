import os
import sys
from curl_cffi import requests
from lxml import html

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env manually to avoid extra dependencies
for env_path in [".env", "../.env"]:
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k.strip()] = v.strip()

proxy = os.getenv("TEST_PROXY")
proxies = {"http": proxy, "https": proxy} if proxy else None
res = requests.get("https://www.salford-works.com", proxies=proxies, impersonate="chrome")
tree = html.fromstring(res.text)

print("--- Facebook/Instagram links ---")
for a in tree.xpath("//a[contains(@href, 'facebook.com') or contains(@href, 'instagram.com')]"):
    href = a.get('href')
    text = a.text_content().strip()
    title = a.get('title')
    aria_label = a.get('aria-label')
    print(f"HREF: {href}")
    print(f"TEXT: '{text}'")
    print(f"TITLE: '{title}'")
    print(f"ARIA-LABEL: '{aria_label}'")
    print("---")
