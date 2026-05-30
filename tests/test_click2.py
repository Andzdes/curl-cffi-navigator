import sys
from main import normalize_url_for_cache, get_cache_path

def test():
    url1 = "https://hurdermillwork.com/"
    url2 = "https://hurdermillwork.com"
    
    norm1 = normalize_url_for_cache(url1)
    norm2 = normalize_url_for_cache(url2)
    
    print(f"URL 1: {url1} -> Normalized: {norm1}")
    print(f"URL 2: {url2} -> Normalized: {norm2}")
    
    path1 = get_cache_path(url1, "urlmap.json")
    path2 = get_cache_path(url2, "urlmap.json")
    
    print(f"\nCache Path 1: {path1}")
    print(f"Cache Path 2: {path2}")
    
    if path1 == path2:
        print("\nИТОГ: Пути к кэшу АБСОЛЮТНО ИДЕНТИЧНЫ! Косая черта не влияет на кэш.")
    else:
        print("\nИТОГ: Пути к кэшу ОТЛИЧАЮТСЯ!")

if __name__ == "__main__":
    test()
