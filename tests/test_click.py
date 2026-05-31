import os
import sys
import json
import traceback

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import get_page, click_link, FetchRequest, ClickRequest
# Load .env manually to avoid extra dependencies
for env_path in [".env", "../.env"]:
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k.strip()] = v.strip()

def test():
    proxy = os.getenv("TEST_PROXY")
    url = "https://hurdermillwork.com"
    
    print("1. Выполняю get_page для наполнения urlmap.json...")
    req1 = FetchRequest(
        url=url,
        proxy=proxy,
        for_agent=True,
        extract_social_links=True,
        force_refresh=True
    )
    
    try:
        res1 = get_page(req1)
        print("get_page успешно завершен!")
    except Exception as e:
        print("Ошибка в get_page:", e)
        traceback.print_exc()
        return

    link_text = "About Us"
    print(f"\n2. Выполняю click_link для ссылки '{link_text}'...")
    req2 = ClickRequest(
        current_url=url,
        link_text=link_text,
        proxy=proxy,
        for_agent=True
    )
    
    try:
        res2 = click_link(req2)
        
        if "error" in res2 and res2["error"]:
            print("\nПОЛУЧЕНА МЯГКАЯ ОШИБКА (Soft Error):")
            print(json.dumps(res2, indent=2, ensure_ascii=False))
        else:
            print("\nУСПЕШНЫЙ ПЕРЕХОД!")
            print("Первые 300 символов markdown-ответа новой страницы:")
            print(res2.get("markdown", "")[:300])
            
    except Exception as e:
        print("\nОШИБКА HTTP EXCEPTION:")
        traceback.print_exc()

if __name__ == "__main__":
    test()
