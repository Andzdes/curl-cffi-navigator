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
| `proxy` | string | `null` | Proxy URL (e.g., `http://user:pass@proxy.com:8000`). |
| `headers` | object | `null` | Custom HTTP headers dictionary. |
| `cookies` | object | `null` | Custom cookies dictionary. |
| `impersonate` | string | `"chrome"` | Browser TLS signature to mimic. Available: `"chrome"`, `"safari"`, `"edge"`. |
| `force_refresh` | boolean | `false` | If `true`, ignores local cache and forces a new download. |
| `output_format` | string | `"markdown"` | Format of extracted content. Available: `"markdown"`, `"text"`, `"html"`. |
| `include_links` | boolean | `false` | If `true`, keeps inline links in the Markdown/Text output. |
| `include_images` | boolean | `false` | If `true`, keeps inline images in the Markdown/Text output. |
| `proxy_retries` | integer | `3` | Number of retry attempts upon proxy errors. |

### Response (`for_agent: false`)
```json
{
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
  "markdown": "---\ntitle: Page Title\n---\n\nMain content...",
  "navigation": {
    "nav": ["About Us", "Contact"]
  },
  "cached": false
}
```

## 2. Navigate via Link Text (`POST /api/click_link`)

Used by the LLM agent to navigate to a new page using ONLY the text of the link (relies on server-side caching mapping).

### Request Body
```json
{
  "source_url": "https://example.com",
  "link_text": "Contact",
  "proxy": null,
  "impersonate": "chrome",
  "proxy_retries": 3
}
```

### Response
Returns the exact same structure as `/api/get_page` with `for_agent: true` for the new target page.

## Smart Router (JS / Headless Browser Requirement)
If the server detects that the page requires JavaScript rendering (e.g. Cloudflare stub or empty React body), it will still return a **200 OK**, but with a special `requires` array instructing the client that additional capabilities are needed.
```json
{
  "requires": ["javascript"],
  "cached": false
}
```
