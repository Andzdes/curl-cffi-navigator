# HTML Extraction Microservice API

A fast, anti-bot resistant API for downloading and parsing HTML into LLM-friendly Markdown, with semantic navigation tracking.

Base URL: `http://<server-ip>:8000`
Content-Type: `application/json`

## 1. Unified Page Extractor (`POST /api/get_page`)
Downloads a page, extracts Markdown content, and groups navigation links semantically.

### Request Body
| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `url` | string | **Required** | Target URL. |
| `for_agent` | boolean | `false` | If `true`, returns link text as array. If `false`, returns `{ "Text": "URL" }` map. |
| `show_external_links`| boolean | `true` (if agent) | Appends `(URL)` to external links if `for_agent=true`. |
| `extract_social_links`| boolean | `false` | Extracts social links into a dedicated `"socials"` array. |
| `proxy` | string | `null` | HTTP proxy (e.g., `http://user:pass@proxy.com:8000`). |
| `headers` | object | `null` | Custom HTTP headers. |
| `cookies` | object | `null` | Custom HTTP cookies. |
| `impersonate` | string | `"chrome"` | Browser signature (`"chrome"`, `"safari"`, `"edge"`). |
| `force_refresh` | boolean | `false` | Bypass cache. |
| `output_format` | string | `"markdown"` | `"markdown"`, `"text"`, or `"html"`. |
| `include_links` | boolean | `false` | Keep inline links in output. |
| `include_images` | boolean | `false` | Keep inline images in output. |
| `proxy_retries` | integer | `3` | Retries on proxy error. |
| `boilerplate` | boolean | `true` | `false` extracts only main article content. |
| `clean_url` | boolean | `true` | Automatically strip tracking parameters (ClearURLs). |

### Response (`for_agent: false`)
```json
{
  "current_url": "https://example.com/page",
  "markdown": "---\ntitle: Page Title\n---\n\nMain content...",
  "navigation": { "nav": { "About Us": "https://example.com/about" } },
  "cached": false
}
```

## 2. Navigate via Link Text (`POST /api/click_link`)
Agent endpoint to navigate using ONLY link text.

### Request Body
Accepts **ALL parameters** from `/api/get_page` to maintain session context (proxy, headers, cookies, extract_social_links, etc.), plus:
- `current_url` (string, **Required**): The URL the agent is currently on.
- `link_text` (string, **Required**): Exact text of the link to click.

### Response
Returns the exact same structure as `/api/get_page`. If `for_agent=true` and link is not found, returns `200 OK` with an `error` warning inside the markdown payload instead of a 404 crash.

## 3. Smart Router & Soft Errors
To prevent agent crashes, the API intercepts WAF blocks and unresolved JS-dependent tracking links, returning `200 OK` with bypass instructions. The system uses a unified schema (`vendor` and `block_type`) so orchestrators can handle all interventions uniformly.

**Example 1: WAF/Antibot Block**
```json
{
  "error": true,
  "requires": ["javascript", "captcha_solver"],
  "vendor": "cloudflare",
  "block_type": "captcha",
  "message": "Agent Warning: Blocked by Cloudflare"
}
```

**Example 2: JS-Dependent Tracking Link (e.g., HubSpot)**
```json
{
  "error": true,
  "requires": ["javascript"],
  "vendor": "tracking_system",
  "block_type": "js_redirect_required",
  "message": "Agent Warning: Unresolved JS-dependent redirect (HTTP 404)"
}
```

## 4. Clear Cache (`POST /api/clear_cache`)
- `url` (string, optional): Clear cache for specific URL. If omitted, clears all.
- `clean_url` (boolean, default: `true`): Strip tracking parameters before finding cache.
```json
{ "detail": "Cache cleared for URL. Deleted 3 files." }
```
