from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from curl_cffi import requests
import trafilatura
import yaml
import json
import tldextract
import hashlib
import os
import time
import re

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import Request

from url_cleaner import cleaner

# ==========================================
# [ SETUP & MODELS ]
# ==========================================

app = FastAPI(title="Universal HTML Parser")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = await request.body()
    print(f"--- 422 VALIDATION ERROR ---", flush=True)
    print(f"URL: {request.url}", flush=True)
    print(f"Body received: {body.decode('utf-8', errors='ignore')}", flush=True)
    print(f"Errors: {exc.errors()}", flush=True)
    print(f"----------------------------", flush=True)
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

SOCIAL_DOMAINS = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", 
    "linkedin.com", "youtube.com", "tiktok.com", "pinterest.com", 
    "snapchat.com", "reddit.com", "discord.com", "t.me", 
    "telegram.me", "whatsapp.com", "github.com", "wa.me"
}

class FetchRequest(BaseModel):
    url: str
    proxy: str | None = None
    headers: dict | None = None
    cookies: dict | None = None
    impersonate: str = "chrome"
    force_refresh: bool = False
    output_format: str = "markdown"  # "markdown", "text", "html"
    include_links: bool = False
    include_images: bool = False
    for_agent: bool = False
    show_external_links: bool | None = None
    extract_social_links: bool = False
    proxy_retries: int = 3
    boilerplate: bool = True
    clean_url: bool = True

class ClickRequest(BaseModel):
    current_url: str
    link_text: str
    proxy: str | None = None
    impersonate: str = "chrome"
    proxy_retries: int = 3
    for_agent: bool = False
    clean_url: bool = True

class ClearCacheRequest(BaseModel):
    url: str | None = None
    clean_url: bool = True


# ==========================================
# [ CACHE & UTILITIES ]
# ==========================================

def normalize_url_for_cache(url: str) -> str:
    url = url.strip()
    # Remove http:// or https://
    url = re.sub(r'^https?://', '', url)
    # Remove www.
    url = re.sub(r'^www\.', '', url)
    # Remove optional trailing slashes
    return url.rstrip('/')

def get_cache_path(url: str, suffix: str) -> str:
    normalized_url = normalize_url_for_cache(url)
    hash_name = hashlib.md5(normalized_url.encode('utf-8')).hexdigest()
    return os.path.join(CACHE_DIR, f"{hash_name}_{suffix}")


# ==========================================
# [ NETWORK OPERATIONS ]
# ==========================================

def fetch_with_curl_cffi(url: str, proxy: str=None, headers: dict=None, cookies: dict=None, impersonate: str="chrome", proxy_retries: int=3):
    kwargs = {
        "impersonate": impersonate,
        "timeout": 15
    }
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    if headers:
        kwargs["headers"] = headers
    if cookies:
        kwargs["cookies"] = cookies
        
    last_error = None
    for attempt in range(proxy_retries + 1):
        try:
            return requests.get(url, **kwargs)
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            
            # Determine if the error is specifically related to the proxy (code 56, tunnel failed, proxy etc.)
            is_proxy_error = proxy and (
                "connect tunnel failed" in error_str or 
                "proxy" in error_str or 
                "curl: (56)" in error_str or 
                "curl: (97)" in error_str
            )
            
            if is_proxy_error and attempt < proxy_retries:
                time.sleep(1)
                continue
            
            # If the error is not proxy-related or retries are exhausted, break the loop
            break
            
    raise HTTPException(status_code=500, detail=f"Failed to fetch {url}: {str(last_error)}")


# ==========================================
# [ PARSING & EXTRACTION ]
# ==========================================

def detect_required_capabilities(html: str) -> list[str]:
    capabilities = []
    html_lower = html.lower()
    
    if "enable javascript" in html_lower or \
       "checking your browser" in html_lower or \
       "just a moment..." in html_lower or \
       ("cloudflare" in html_lower and "ray id" in html_lower):
        capabilities.append("javascript")
        
    if len(html) < 1500 and "<script" in html_lower:
        if "javascript" not in capabilities:
            capabilities.append("javascript")
            
    return capabilities

def extract_links_data(html: str, base_url: str, for_agent: bool, show_external_links: bool = False, extract_social_links: bool = False, clean_urls: bool = True):
    links_by_group = {
        "nav": {},
        "header": {},
        "footer": {},
        "main": {},
        "article": {},
        "aside": {},
        "other": {}
    }
    
    social_urls = []
    
    try:
        from lxml import html as lxml_html
        from urllib.parse import urldefrag
        
        tree = lxml_html.fromstring(html)
        tree.make_links_absolute(base_url)
        
        seen_urls = set()
        base_no_frag, _ = urldefrag(base_url)
        
        def process_a_tag(a, group_name):
            # Filter out behavioral UI elements pretending to be links
            if a.get('role', '').lower() == 'button':
                return
                
            url = a.get('href')
            if not url:
                return
                
            url_lower = url.lower()
            
            # Allow http(s), absolute paths (/), and contact links (email, phone)
            # Filter out garbage schemas like javascript:
            if not url_lower.startswith(('http', '/', 'mailto:', 'tel:')): 
                return
            
            # Filter out anchor links pointing to the current page
            url_no_frag, _ = urldefrag(url)
            if url_no_frag == base_no_frag:
                return
            
            # Clean standard web URLs only, preserve contact links as they are
            if clean_urls and url_lower.startswith(('http', '/')):
                url = cleaner.clean(url)
                
            if url in seen_urls: return
            
            if extract_social_links:
                ext = tldextract.extract(url)
                domain = f"{ext.domain}.{ext.suffix}"
                if domain in SOCIAL_DOMAINS:
                    social_urls.append(url)
                    seen_urls.add(url)
                    return
            
            text = a.text_content().strip()
            if not text: return
            
            links_by_group[group_name][text] = url
            seen_urls.add(url)

        for group in ["nav", "header", "footer", "main", "article", "aside"]:
            for a in tree.xpath(f"//{group}//a[@href]"):
                process_a_tag(a, group)
                    
        for a in tree.xpath("//a[@href]"):
            process_a_tag(a, "other")
                
    except Exception:
        pass
        
    final_links = {}
    url_map = {}
    
    base_ext = tldextract.extract(base_url)
    base_domain = f"{base_ext.domain}.{base_ext.suffix}"
    
    for group, items in links_by_group.items():
        if not items: continue
        
        if for_agent:
            # For agent: list of names (and optionally URLs for external links)
            final_list = []
            for text, url in items.items():
                if show_external_links:
                    link_ext = tldextract.extract(url)
                    link_domain = f"{link_ext.domain}.{link_ext.suffix}"
                    if link_domain and link_domain != base_domain:
                        final_list.append(f"{text} ({url})")
                    else:
                        final_list.append(text)
                else:
                    final_list.append(text)
            final_links[group] = final_list
        else:
            # For human/dev: mapping of name -> URL
            final_links[group] = items
            
        for text, url in items.items():
            url_map[text] = url
            
    if extract_social_links and social_urls:
        final_links["socials"] = social_urls
        # Adding to url_map so they are optionally reachable if needed, though they don't have text
        for url in social_urls:
            url_map[url] = url
            
    return final_links, url_map


# ==========================================
# [ API ENDPOINTS ]
# ==========================================

@app.post("/api/get_page")
def get_page(req: FetchRequest):
    if req.clean_url:
        req.url = cleaner.clean(req.url)

    suffix = "agent_page.json" if req.for_agent else "full_page.json"
    cache_path = get_cache_path(req.url, suffix)
    map_cache_path = get_cache_path(req.url, "urlmap.json")
    
    if not req.force_refresh and os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.loads(f.read())

    response = fetch_with_curl_cffi(req.url, req.proxy, req.headers, req.cookies, req.impersonate, req.proxy_retries)
    html = response.text
    
    caps = detect_required_capabilities(html)
    if caps:
        return {"requires": caps, "cached": False}
        
    if response.status_code >= 400:
        raise HTTPException(status_code=500, detail=f"Failed to fetch {req.url}: HTTP Error {response.status_code}")
    
    if req.boilerplate:
        try:
            import markdownify
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            # Remove scripts, styles, and other non-content tags
            for x in soup(["script", "style", "noscript", "svg", "iframe"]):
                x.extract()
                
            strip_tags = []
            if not req.include_links:
                strip_tags.append('a')
            if not req.include_images:
                strip_tags.append('img')
                
            extracted = markdownify.markdownify(
                str(soup), 
                heading_style="ATX", 
                strip=strip_tags if strip_tags else None
            )
            if extracted:
                extracted = extracted.strip()
        except ImportError:
            # Fallback if markdownify or bs4 are not installed
            extracted = trafilatura.extract(
                html, 
                include_tables=True, 
                include_links=req.include_links,
                include_images=req.include_images,
                output_format=req.output_format if req.output_format in ["markdown", "text"] else "markdown"
            )
    else:
        extracted = trafilatura.extract(
            html, 
            include_tables=True, 
            include_links=req.include_links,
            include_images=req.include_images,
            output_format=req.output_format if req.output_format in ["markdown", "text"] else "markdown"
        )
        
    if not extracted:
        extracted = ""
        
    metadata = trafilatura.extract_metadata(html)
    meta_dict = {}
    if metadata:
        meta_dict = {
            "title": getattr(metadata, "title", None),
            "author": getattr(metadata, "author", None),
            "url": getattr(metadata, "url", None),
            "date": getattr(metadata, "date", None),
            "hostname": getattr(metadata, "hostname", None)
        }
        meta_dict = {k: v for k, v in meta_dict.items() if v is not None}
    
    yaml_frontmatter = yaml.dump(meta_dict, default_flow_style=False, allow_unicode=True) if meta_dict else ""
    final_markdown = f"---\n{yaml_frontmatter}---\n\n{extracted}" if yaml_frontmatter else extracted
    
    actual_show_ext = req.show_external_links if req.show_external_links is not None else req.for_agent
    final_links, url_map = extract_links_data(html, req.url, req.for_agent, actual_show_ext, req.extract_social_links, req.clean_url)
    
    response_data = {
        "current_url": req.url,
        "markdown": final_markdown,
        "navigation": final_links,
        "cached": False
    }
    if req.output_format == "html":
        response_data["html"] = html
        
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({**response_data, "cached": True}, f)
        
    # Always save the url mapping for click_link capabilities
    with open(map_cache_path, "w", encoding="utf-8") as f:
        json.dump(url_map, f)
        
    return response_data

@app.post("/api/click_link")
def click_link(req: ClickRequest):
    if req.clean_url:
        req.current_url = cleaner.clean(req.current_url)
        
    map_cache_path = get_cache_path(req.current_url, "urlmap.json")
    if not os.path.exists(map_cache_path):
        if req.for_agent:
            return {
                "error": True,
                "message": f"Agent Warning: Source URL link map not found.",
                "markdown": "**SYSTEM WARNING:** The `current_url` you provided was not found in the cache. Are you sure you passed the correct `current_url`? Please check the `current_url` field from the previous page output and use it exactly."
            }
        raise HTTPException(status_code=400, detail="Source URL link map not found in cache. Please call /api/get_page first.")
        
    with open(map_cache_path, "r", encoding="utf-8") as f:
        url_map = json.loads(f.read())
        
    # Smart search for link_text
    target_url = url_map.get(req.link_text)
    
    if not target_url:
        req_clean = req.link_text.strip().lower()
        for k, v in url_map.items():
            if k.strip().lower() == req_clean:
                target_url = v
                break
                
    if not target_url:
        req_clean = req.link_text.strip().lower()
        for k, v in url_map.items():
            k_clean = k.strip().lower()
            if req_clean in k_clean or k_clean in req_clean:
                target_url = v
                break

    if not target_url:
        if req.for_agent:
            return {
                "error": True,
                "message": f"Agent Warning: Link text '{req.link_text}' not found.",
                "markdown": f"**SYSTEM WARNING:** The link '{req.link_text}' does not exist on this page. You must ONLY use the exact link texts that were explicitly listed in the previous page's navigation blocks."
            }
        else:
            raise HTTPException(status_code=404, detail=f"Link text '{req.link_text}' not found on {req.current_url}.")
        
    # Simulate get_page for the new target url
    fetch_req = FetchRequest(
        url=target_url,
        proxy=req.proxy,
        impersonate=req.impersonate,
        for_agent=req.for_agent,
        proxy_retries=req.proxy_retries,
        clean_url=req.clean_url
    )
    return get_page(fetch_req)

@app.post("/api/clear_cache")
def clear_cache(req: ClearCacheRequest):
    import shutil
    
    deleted_files = 0
    if req.url:
        if req.clean_url:
            req.url = cleaner.clean(req.url)
            
        normalized_url = normalize_url_for_cache(req.url)
        hash_name = hashlib.md5(normalized_url.encode('utf-8')).hexdigest()
        
        for filename in os.listdir(CACHE_DIR):
            if filename.startswith(hash_name):
                file_path = os.path.join(CACHE_DIR, filename)
                try:
                    os.remove(file_path)
                    deleted_files += 1
                except Exception:
                    pass
        return {"detail": f"Cache cleared for URL. Deleted {deleted_files} files."}
    else:
        for filename in os.listdir(CACHE_DIR):
            file_path = os.path.join(CACHE_DIR, filename)
            try:
                os.remove(file_path)
                deleted_files += 1
            except Exception:
                pass
        return {"detail": f"Entire cache cleared. Deleted {deleted_files} files."}
