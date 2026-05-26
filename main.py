from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from curl_cffi import requests
import trafilatura
import yaml
import json
import hashlib
import os
import time
import re

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import Request

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
    proxy_retries: int = 3
    boilerplate: bool = True

class ClickRequest(BaseModel):
    source_url: str
    link_text: str
    proxy: str | None = None
    impersonate: str = "chrome"
    proxy_retries: int = 3

def normalize_url_for_cache(url: str) -> str:
    url = url.strip()
    # Remove http:// or https://
    url = re.sub(r'^https?://', '', url)
    # Remove www.
    if url.startswith('www.'):
        url = url[4:]
    # Remove optional trailing slashes
    return url.rstrip('/')

def get_cache_path(url: str, suffix: str) -> str:
    normalized_url = normalize_url_for_cache(url)
    hash_name = hashlib.md5(normalized_url.encode('utf-8')).hexdigest()
    return os.path.join(CACHE_DIR, f"{hash_name}_{suffix}")

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

def extract_links_data(html: str, base_url: str, for_agent: bool):
    links_by_group = {
        "nav": {},
        "header": {},
        "footer": {},
        "main": {},
        "article": {},
        "aside": {},
        "other": {}
    }
    
    try:
        from lxml import html as lxml_html
        tree = lxml_html.fromstring(html)
        tree.make_links_absolute(base_url)
        
        seen_urls = set()
        
        for group in ["nav", "header", "footer", "main", "article", "aside"]:
            for a in tree.xpath(f"//{group}//a[@href]"):
                url = a.get('href')
                text = a.text_content().strip()
                if not text: continue
                if (url.startswith('http') or url.startswith('/')) and url not in seen_urls:
                    links_by_group[group][text] = url
                    seen_urls.add(url)
                    
        for a in tree.xpath("//a[@href]"):
            url = a.get('href')
            text = a.text_content().strip()
            if not text: continue
            if (url.startswith('http') or url.startswith('/')) and url not in seen_urls:
                links_by_group["other"][text] = url
                seen_urls.add(url)
                
    except Exception:
        pass
        
    final_links = {}
    url_map = {}
    
    for group, items in links_by_group.items():
        if not items: continue
        
        if for_agent:
            # For agent: list of names
            final_links[group] = list(items.keys())
        else:
            # For human/dev: mapping of name -> URL
            final_links[group] = items
            
        for text, url in items.items():
            url_map[text] = url
            
    return final_links, url_map

@app.post("/api/get_page")
def get_page(req: FetchRequest):
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
    
    final_links, url_map = extract_links_data(html, req.url, req.for_agent)
    
    response_data = {
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
    map_cache_path = get_cache_path(req.source_url, "urlmap.json")
    if not os.path.exists(map_cache_path):
        raise HTTPException(status_code=400, detail="Source URL link map not found in cache. Please call /api/get_page first.")
        
    with open(map_cache_path, "r", encoding="utf-8") as f:
        url_map = json.loads(f.read())
        
    target_url = url_map.get(req.link_text)
    if not target_url:
        raise HTTPException(status_code=404, detail=f"Link text '{req.link_text}' not found on {req.source_url}.")
        
    # Simulate get_page for the new target url automatically as an agent
    fetch_req = FetchRequest(
        url=target_url,
        proxy=req.proxy,
        impersonate=req.impersonate,
        for_agent=True,
        proxy_retries=req.proxy_retries
    )
    return get_page(fetch_req)
