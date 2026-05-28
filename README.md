# HTML Extraction Microservice API Specification

Base URL: `http://<server-ip>:8000`
Content-Type: `application/json`

## 1. Unified Page Extractor (`POST /api/get_page`)

Downloads a page, extracts the main readable text (Markdown), and extracts all navigation links grouped by semantic blocks (`nav`, `header`, `footer`, etc.).

### Request Body
Only `url` is required. All other parameters are optional.

| Parameter | Type | Default | Description / Available Values |
| --- | --- | --- | --- |
| `url` | string | **Required** | The target website URL. |
| `for_agent` | boolean | `false` | If `true`, returns only the text titles of links (to save tokens). If `false`, returns key-value mapping of `{ "Link Text": "URL" }`. |
| `show_external_links` | boolean | `true` (if `for_agent=true`) | If `true` (and `for_agent` is `true`), displays external links in the format `"Text (URL)"`. Internal links remain just text. |
| `extract_social_links` | boolean | `false` | If `true`, extracts social media links (based on domain) into a dedicated `"socials"` array containing just their URLs, and excludes them from regular navigation groups. |
| `proxy` | string | `null` | Proxy URL (e.g., `http://user:pass@proxy.com:8000`). |
| `headers` | object | `null` | Custom HTTP headers dictionary. |
| `cookies` | object | `null` | Custom cookies dictionary. |
| `impersonate` | string | `"chrome"` | Browser TLS signature to mimic. Available: `"chrome"`, `"safari"`, `"edge"`. |
| `force_refresh` | boolean | `false` | If `true`, ignores local cache and forces a new download. |
| `output_format` | string | `"markdown"` | Format of extracted content. Available: `"markdown"`, `"text"`, `"html"`. |
| `include_links` | boolean | `false` | If `true`, keeps inline links in the Markdown/Text output. |
| `include_images` | boolean | `false` | If `true`, keeps inline images in the Markdown/Text output. |
| `proxy_retries` | integer | `3` | Number of retry attempts upon proxy errors. |
| `boilerplate` | boolean | `true` | If `true`, returns full unfiltered webpage content (including headers/footers). If `false`, applies heuristic to extract only the main article content. |
| `clean_url` | boolean | `true` | If `true`, automatically removes tracking and garbage parameters (like `utm_*`, `gclid`) from the requested URL and all extracted links using ClearURLs rules. |

### Response (`for_agent: false`)
```json
{
  "current_url": "https://example.com/page",
  "markdown": "---\ntitle: Page Title\n---\n\nMain content...",
  "navigation": {
    "nav": {
      "About Us": "https://example.com/about",
      "Contact": "https://example.com/contact"
    }
  },
  "cached": false
}
```

### Response (`for_agent: true`)
Optimized for LLM context windows.
```json
{
  "current_url": "https://example.com/page",
  "markdown": "---\ntitle: Page Title\n---\n\nMain content...",
  "navigation": {
    "nav": ["About Us", "Contact"]
  },
  "cached": false
}
```

*Note: If `show_external_links: true` is provided, external links will be appended with their URLs. Example:*
```json
  "navigation": {
    "nav": ["About Us", "Our GitHub (https://github.com/example)"]
  }
```

*Note: If `extract_social_links: true` is provided, social links are grouped into a dedicated array:*
```json
  "navigation": {
    "nav": ["About Us", "Contact"],
    "socials": [
      "https://facebook.com/example",
      "https://instagram.com/example"
    ]
  }
```

## 2. Navigate via Link Text (`POST /api/click_link`)

Used by the LLM agent to navigate to a new page using ONLY the text of the link (relies on server-side caching mapping).

### Request Body

**Required Parameters:**
- `current_url` (string): The URL of the page the agent is currently on.
- `link_text` (string): The exact text of the link the agent wants to click (e.g., "About Us" or "Contact").

**Optional Parameters:**
- `proxy` (string): HTTP/HTTPS proxy URL.
- `impersonate` (string): Browser to impersonate (default: "chrome").
- `proxy_retries` (integer): Number of times to retry on proxy failure (default: 3).
- `for_agent` (boolean): If `true`, enables agent-friendly responses (soft errors on 404) and formats the output for the LLM (default: `false`).
- `clean_url` (boolean): If `true`, strips tracking parameters from `current_url` before looking up link mappings (default: `true`).

```json
{
  "current_url": "https://example.com",
  "link_text": "Contact",
  "proxy": null,
  "impersonate": "chrome",
  "proxy_retries": 3
}
```

### Response
Returns the exact same structure as `/api/get_page` for the new target page (depends on `for_agent` value).

**Soft Error (If `for_agent=true` and link or cache is not found):**
Returns a 200 OK with `error: true` and a warning message in the `markdown` field to notify the LLM without crashing the workflow.

## Smart Router (JS / Headless Browser Requirement)
If the server detects that the page requires JavaScript rendering (e.g. Cloudflare stub or empty React body), it will still return a **200 OK**, but with a special `requires` array instructing the client that additional capabilities are needed.
```json
{
  "requires": ["javascript"],
  "cached": false
}
```

## 3. Clear Cache (`POST /api/clear_cache`)

Clears the cache either entirely or for a specific URL.

### Request Body

**Optional Parameters:**
- `url` (string): If provided, only the cache for this specific URL is cleared. If omitted, the entire cache is cleared.
- `clean_url` (boolean): If `true`, strips tracking parameters from `url` before clearing its cache (default: `true`).

```json
{
  "url": "https://example.com"
}
```

### Response
```json
{
  "detail": "Cache cleared for URL. Deleted 3 files."
}
```
