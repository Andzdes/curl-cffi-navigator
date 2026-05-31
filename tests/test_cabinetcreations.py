import os
import sys

# Add parent directory to path so we can import main
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app

def test_cabinet_creations_navigation():
    client = TestClient(app)
    proxy = os.environ.get("TEST_PROXY")

    print("\nClearing cache...")
    client.post("/api/clear_cache", json={"clean_url": True})

    # Step 1: Initial page
    print("\n--- Step 1: Get_Page https://cabinetcreations.net ---")
    res1 = client.post("/api/get_page", json={
        "url": "https://cabinetcreations.net",
        "proxy": proxy,
        "for_agent": True
    })
    
    assert res1.status_code == 200, f"FAILED Get_Page: {res1.json()}"
    print("Success: get_page https://cabinetcreations.net")

    # Step 2: Click 'About Us'
    print("\n--- Step 2: Click 'About Us' ---")
    res2 = client.post("/api/click_link", json={
        "current_url": "https://cabinetcreations.net",
        "link_text": "About Us",
        "proxy": proxy,
        "for_agent": True
    })
    
    assert res2.status_code == 200, f"FAILED click_link 'About Us': {res2.json()}"
    target_url_2 = res2.json().get('current_url')
    print(f"Success: navigated to {target_url_2}")

    # Step 3: Click 'Contact Us' from the new URL
    print("\n--- Step 3: Click 'Contact Us' ---")
    res3 = client.post("/api/click_link", json={
        "current_url": "https://cabinetcreations.net/about-cabinet-creations",
        "link_text": "Contact Us",
        "proxy": proxy,
        "for_agent": True
    })
    
    data3 = res3.json()
    if res3.status_code == 200 and data3.get("error"):
        print(f"Success: Agent received soft error for Contact Us: {data3.get('message')}")
    else:
        print(f"FAILED or UNEXPECTED: {res3.status_code} - {data3}")

if __name__ == "__main__":
    test_cabinet_creations_navigation()
