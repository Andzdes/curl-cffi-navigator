from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from curl_cffi import requests
from dataclasses import dataclass, field
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
    "telegram.me", "whatsapp.com", "github.com", "wa.me", "threads.net"
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
    headers: dict | None = None
    cookies: dict | None = None
    impersonate: str = "chrome"
    proxy_retries: int = 3
    for_agent: bool = False
    clean_url: bool = True
    extract_social_links: bool = False
    show_external_links: bool | None = None
    include_links: bool = False
    include_images: bool = False
    boilerplate: bool = True

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
            response = requests.get(url, **kwargs)
            
            if response.status_code in (403, 429, 503):
                if response.status_code == 429:
                    if proxy and attempt < proxy_retries:
                        time.sleep(1)
                        continue
                else:
                    block = detect_antibot(response)
                    if block.is_blocked and block.block_type == "hard_block":
                        if proxy and attempt < proxy_retries:
                            time.sleep(1)
                            continue
            return response
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
# [ ANTI-BOT DETECTION ]
# ==========================================

def is_interaction_dependent_link(url: str) -> bool:
    url_lower = url.lower()
    
    # Common tracking/redirect domains that rely on JS or session state
    tracking_domains = [
        "hubspot.com",
        "cta-service-cms2",
        "hs-sites.com",
        "bit.ly",
        "t.co",
        "lnkd.in",
        "out.reddit.com"
    ]
    
    if any(domain in url_lower for domain in tracking_domains):
        return True
        
    # Check for opaque/encrypted payload patterns common in trackers
    if "encryptedpayload=" in url_lower or "token=" in url_lower:
        if "/track/" in url_lower or "/click" in url_lower:
            return True
            
    return False

@dataclass
class BlockResult:
    is_blocked: bool = False
    vendor: str | None = None
    block_type: str | None = None
    confidence: str = "none"
    signals: list[str] = field(default_factory=list)

    def __bool__(self):
        return self.is_blocked

def _hget(headers: dict, key: str) -> str:
    return headers.get(key, headers.get(key.lower(), headers.get(key.upper(), "")))

def _cookie_has(headers: dict, *fragments: str) -> bool:
    cookie_val = _hget(headers, "set-cookie").lower()
    return any(f.lower() in cookie_val for f in fragments)

def _detect_cloudflare(status: int, headers: dict, body: str) -> BlockResult | None:
    signals = []
    if _hget(headers, "cf-mitigated").lower() == "challenge":
        signals.append("header:cf-mitigated=challenge")
        block_type = "captcha" if "cf-turnstile" in body else "js_challenge"
        return BlockResult(True, "cloudflare", block_type, "definitive", signals)

    cf_in_path = bool(_hget(headers, "cf-ray")) or "cloudflare" in _hget(headers, "server").lower()
    if cf_in_path:
        signals.append("header:cf-ray or server:cloudflare")

    body_lower = body.lower()
    html_challenge = (
        'id="challenge-form"' in body or 'id="challenge-running"' in body
        or 'id="challenge-error-title"' in body or "__cf_chl_f_tk" in body
    )
    if html_challenge:
        signals.append("html:challenge-form/challenge-running")

    turnstile = 'class="cf-turnstile"' in body and "data-sitekey" in body
    if turnstile:
        signals.append("html:cf-turnstile widget")

    hard_block = "sorry, you have been blocked" in body_lower and "cloudflare ray id" in body_lower and status == 403
    if hard_block:
        signals.append("html:hard-block+ray-id + 403")

    if html_challenge or hard_block:
        if cf_in_path or status in (403, 503):
            block_type = "hard_block" if hard_block else ("captcha" if turnstile else "js_challenge")
            return BlockResult(True, "cloudflare", block_type, "definitive", signals)

    if turnstile:
        return BlockResult(True, "cloudflare", "captcha", "high", signals)
    return None

def _detect_datadome(status: int, headers: dict, body: str) -> BlockResult | None:
    signals = []
    if _hget(headers, "x-datadome"):
        signals.append("header:x-datadome")
        if status == 403 or "captcha-delivery.com" in body or _cookie_has(headers, "datadome"):
            signals.append("status:403 or html:captcha-delivery or cookie:datadome")
            return BlockResult(True, "datadome", "captcha", "definitive", signals)
        return BlockResult(True, "datadome", "js_challenge", "high", signals)

    if _cookie_has(headers, "datadome") and status == 403:
        signals.append("cookie:datadome + status:403")
        return BlockResult(True, "datadome", "captcha", "high", signals)
    return None

def _detect_perimeterx(status: int, headers: dict, body: str) -> BlockResult | None:
    signals = []
    if "window._pxappid" in body.lower() or "_pxJsClientSrc" in body:
        signals.append("html:window._pxAppId")
        return BlockResult(True, "perimeterx", "captcha", "definitive", signals)
    if 'id="px-captcha"' in body:
        signals.append("html:px-captcha div")
        return BlockResult(True, "perimeterx", "captcha", "definitive", signals)
    if "perimeterx.net" in body or "px-cdn.net" in body:
        signals.append("html:perimeterx.net domain")
        if status in (403, 429):
            return BlockResult(True, "perimeterx", "captcha", "high", signals)
    return None

def _detect_imperva(status: int, headers: dict, body: str) -> BlockResult | None:
    signals = []
    if _hget(headers, "x-iinfo"):
        signals.append("header:x-iinfo")
    cdn_header = _hget(headers, "x-cdn").lower()
    if "incapsula" in cdn_header or "imperva" in cdn_header:
        signals.append("header:x-cdn=incapsula/imperva")
    if _cookie_has(headers, "incap_ses", "visid_incap"):
        signals.append("cookie:incap_ses or visid_incap")

    body_lower = body.lower()
    html_signals = [
        ("powered by incapsula", "html:powered-by-incapsula"),
        ("incapsula incident id", "html:incapsula-incident-id"),
        ("_incapsula_resource", "html:incapsula-resource"),
        ("subject=waf block page", "html:waf-block-page"),
    ]
    for phrase, label in html_signals:
        if phrase in body_lower:
            signals.append(label)

    if signals:
        is_hard_blocked = status in (403, 429, 503) or any(s.startswith("html:") for s in signals)
        if is_hard_blocked:
            return BlockResult(True, "imperva", "js_challenge", "definitive", signals)
        return BlockResult(False, "imperva", None, "medium", signals)
    return None

def _detect_akamai(status: int, headers: dict, body: str) -> BlockResult | None:
    signals = []
    if "window.bmak" in body or "/_bm/async_api" in body:
        signals.append("html:bmak sensor script")
    if _cookie_has(headers, "_abck"):
        signals.append("cookie:_abck")
    if "akamaighost" in _hget(headers, "server").lower():
        signals.append("header:server=AkamaiGHost")
    if signals and status in (403, 429, 503):
        return BlockResult(True, "akamai", "js_challenge", "high", signals)
    return None

def _detect_generic(status: int, headers: dict, body: str) -> BlockResult | None:
    body_lower = body.lower()
    generic_phrases = [
        "enable javascript to continue",
        "javascript is required",
        "your browser does not support javascript",
        "you have been blocked",
        "access denied",
        "bot protection",
        "ddos protection",
    ]
    matched = [p for p in generic_phrases if p in body_lower]
    if matched and status in (403, 429, 503):
        return BlockResult(True, "generic", "js_challenge", "medium", matched)
    return None

def detect_antibot(response) -> BlockResult:
    status = response.status_code
    headers = dict(response.headers)
    body = response.text[:32_768] if response.text else ""
    detectors = [
        _detect_cloudflare, _detect_datadome, _detect_perimeterx, 
        _detect_imperva, _detect_akamai, _detect_generic
    ]
    for detector in detectors:
        result = detector(status, headers, body)
        if result and result.is_blocked:
            return result
    return BlockResult(is_blocked=False)

# ==========================================
# [ HTML PARSING & LINK EXTRACTION ]
# ==========================================

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
            
            raw_text = a.text_content().strip()
            if not raw_text: return
            
            # Clean up multiline link texts by taking the longest non-empty line
            lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            if not lines: return
            
            text = max(lines, key=len)
            text = re.sub(r'\s+', ' ', text).strip()
            
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
            
    if extract_social_links:
        final_links["socials"] = social_urls
        # Adding to url_map so they are optionally reachable if needed, though they don't have text
        for url in social_urls:
            url_map[url] = url
            
    return final_links, url_map


# ==========================================
# [ API - GET PAGE ]
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
    
    block = detect_antibot(response)
    if block.is_blocked:
        requires = ["javascript"]
        if block.block_type == "captcha":
            requires.append("captcha_solver")
        elif block.block_type == "hard_block":
            requires = ["proxy_rotation"]

        return {
            "requires": requires, 
            "cached": False, 
            "vendor": block.vendor,
            "block_type": block.block_type
        }
        
    if response.status_code >= 400:
        if req.for_agent:
            requires = []
            if is_interaction_dependent_link(req.url):
                requires.append("javascript")
                return {
                    "error": True,
                    "requires": requires,
                    "vendor": "tracking_system",
                    "block_type": "js_redirect_required",
                    "message": f"Agent Warning: Unresolved JS-dependent redirect (HTTP {response.status_code})",
                    "markdown": f"**SYSTEM WARNING:** The target URL is a client-side tracking link that failed to resolve via standard HTTP ({response.status_code} Error). This is not a dead link; it requires JavaScript execution to construct the final destination. Please escalate this action to a JavaScript-enabled browser tool if available."
                }
            else:
                return {
                    "error": True,
                    "message": f"Agent Warning: HTTP Error {response.status_code}",
                    "markdown": f"**SYSTEM WARNING:** The server returned an HTTP {response.status_code} error when trying to fetch the page. This link might be broken, or it requires JavaScript/auth to redirect properly. Please go back and try another link."
                }
        raise HTTPException(status_code=500, detail=f"Failed to fetch {req.url}: HTTP Error {response.status_code}")
    
    if req.boilerplate:
        try:
            import markdownify
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            # Remove scripts, styles, and other non-content tags
            for x in soup(["script", "style", "noscript", "svg", "iframe", "nav"]):
                x.extract()
            for x in soup.find_all(attrs={"role": "navigation"}):
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
            "date": getattr(metadata, "date", None)
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

# ==========================================
# [ API - CLICK LINK ]
# ==========================================

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
        headers=req.headers,
        cookies=req.cookies,
        impersonate=req.impersonate,
        proxy_retries=req.proxy_retries,
        for_agent=req.for_agent,
        clean_url=req.clean_url,
        extract_social_links=req.extract_social_links,
        show_external_links=req.show_external_links,
        include_links=req.include_links,
        include_images=req.include_images,
        boilerplate=req.boilerplate
    )
    return get_page(fetch_req)

# ==========================================
# [ API - CACHE CLEAR ]
# ==========================================

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
