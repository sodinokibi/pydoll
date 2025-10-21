# Pydoll Crawler Examples

This directory contains efficient web crawler implementations using Pydoll.

## Files

### 1. `simple_production_crawler.py` ⭐ START HERE

**The simplest, production-ready crawler.**

```bash
# Basic usage
python simple_production_crawler.py https://example.com

# Custom output directory
python simple_production_crawler.py https://example.com ./my_crawl
```

**What it captures:**
- ✅ All JavaScript files (deduplicated)
- ✅ All HTML pages
- ✅ All API endpoints (XHR/Fetch)
- ✅ Request/response data

**Output structure:**
```
crawl_output/
├── js/                    # JavaScript files
│   ├── abc123_bundle.js
│   └── def456_app.js
├── html/                  # HTML pages
│   ├── index.html
│   └── about.html
├── api/                   # API calls
│   ├── api_1.json
│   └── api_2.json
└── summary.json          # Crawl summary
```

**Features:**
- Network-based capture (most efficient)
- Automatic content deduplication
- Progress tracking
- Clean JSON output
- Blocks images for speed

---

### 2. `efficient_crawler.py`

**Advanced crawler with full configurability.**

```python
from efficient_crawler import EfficientWebCrawler

crawler = EfficientWebCrawler(
    output_dir="./results",
    max_depth=3,           # How deep to crawl
    max_pages=1000,        # Maximum pages
    concurrent_tabs=5,     # Parallel processing
    target_domain=None     # Auto-detect or specify
)

await crawler.crawl("https://example.com")
```

**Additional features:**
- Concurrent crawling with multiple tabs
- Subdomain discovery
- Advanced network logging
- Configurable depth limits
- Statistics tracking

---

### 3. `crawler_strategies.md`

**Complete guide to efficient crawling strategies.**

Covers:
- Network interception vs DOM parsing
- Performance optimization techniques
- Hybrid approaches (API discovery)
- Resource filtering
- Deduplication strategies
- Database storage patterns
- Concurrent architecture

**Read this to understand:**
- Why network interception is most efficient
- How to capture API calls without parsing
- Performance tuning tips
- Advanced patterns

---

## Quick Start

### Install Pydoll

```bash
pip install pydoll-python
```

### Run Simple Crawler

```bash
cd examples
python simple_production_crawler.py https://example.com
```

### Check Results

```bash
# View summary
cat crawl_output/summary.json

# Count files
ls crawl_output/js/ | wc -l     # JavaScript files
ls crawl_output/html/ | wc -l   # HTML pages
ls crawl_output/api/ | wc -l    # API calls
```

---

## How It Works

### Network Interception (Most Efficient)

```
1. Enable network events BEFORE page load
2. Browser makes all requests (JS, XHR, Fetch, etc.)
3. Capture requests/responses via CDP
4. Extract content from responses
5. Save to disk with deduplication
```

**Why this is best:**
- ✅ Captures EVERYTHING (including dynamic API calls)
- ✅ No DOM parsing overhead
- ✅ Gets actual POST data and responses
- ✅ Works with SPAs and dynamic sites
- ✅ Minimal memory usage

**vs DOM Parsing:**
- ❌ Misses XHR/Fetch calls
- ❌ Misses dynamically loaded scripts
- ❌ High memory usage
- ❌ Slower

---

## Use Cases

### 1. Security Analysis
```bash
# Crawl target domain
python simple_production_crawler.py https://target.com

# Analyze JavaScript
grep -r "eval" crawl_output/js/
grep -r "innerHTML" crawl_output/js/

# Check API endpoints
jq '.endpoint' crawl_output/api/*.json
```

### 2. API Discovery
```python
crawler = EfficientWebCrawler(max_pages=50)
await crawler.crawl("https://app.example.com")

# Check discovered APIs
with open("crawl_output/crawl_report.json") as f:
    report = json.load(f)
    print(report['unique_endpoints'])
```

### 3. JavaScript Analysis
```bash
# Find all JavaScript files
find crawl_output/js -name "*.js"

# Search for specific patterns
grep -r "fetch(" crawl_output/js/
grep -r "XMLHttpRequest" crawl_output/js/
```

### 4. Subdomain Discovery
```python
# Crawl main domain
crawler = EfficientWebCrawler(target_domain="example.com")
await crawler.crawl("https://example.com")

# Check discovered subdomains
print(crawler.stats['subdomains'])
```

---

## Advanced Configuration

### Block Resources for Speed

```python
from pydoll.browser.options import ChromiumOptions

options = ChromiumOptions()
options.browser_preferences = {
    'profile': {
        'default_content_setting_values': {
            'images': 2,        # Block images
            'plugins': 2,       # Block plugins
            'popups': 2,        # Block popups
        }
    }
}

# Use with crawler
async with Chrome(options=options) as browser:
    ...
```

### Custom Resource Filtering

```python
def should_skip_resource(url: str) -> bool:
    # Skip analytics
    if 'google-analytics' in url:
        return True

    # Skip social media
    if any(domain in url for domain in ['facebook.com', 'twitter.com']):
        return True

    # Skip ads
    if '/ads/' in url or '/tracking/' in url:
        return True

    return False
```

### Concurrent Subdomain Crawling

```python
subdomains = ['www.example.com', 'api.example.com', 'admin.example.com']

async def crawl_all():
    tasks = [
        EfficientWebCrawler().crawl(f"https://{sd}")
        for sd in subdomains
    ]
    await asyncio.gather(*tasks)
```

---

## Performance Tips

1. **Use Headless Mode** (30% faster)
   ```python
   await browser.start(headless=True)
   ```

2. **Block Images** (50% faster)
   ```python
   options.browser_preferences = {
       'profile': {'default_content_setting_values': {'images': 2}}
   }
   ```

3. **Concurrent Tabs** (5x throughput)
   ```python
   crawler = EfficientWebCrawler(concurrent_tabs=5)
   ```

4. **Resource Filtering** (avoid waste)
   ```python
   # Skip .jpg, .png, .mp4, .pdf, .zip, .woff, etc.
   ```

5. **Content Deduplication** (save space)
   ```python
   # Hash-based deduplication built-in
   ```

---

## Output Format

### summary.json
```json
{
  "metadata": {
    "start_url": "https://example.com",
    "domain": "example.com",
    "start_time": "2025-10-21T10:30:00",
    "end_time": "2025-10-21T10:35:00",
    "stats": {
      "pages_crawled": 50,
      "javascript_files": 25,
      "api_endpoints": 15,
      "html_pages": 50
    }
  },
  "visited_urls": [...],
  "javascript_urls": [...],
  "api_endpoints_summary": [...]
}
```

### API Call Format (api_1.json)
```json
{
  "endpoint": "POST /api/users",
  "full_url": "https://example.com/api/users",
  "method": "POST",
  "request_headers": {...},
  "request_body": "{\"name\":\"test\"}",
  "response_status": 200,
  "response_body": "{\"id\":123}",
  "timestamp": "2025-10-21T10:31:00"
}
```

---

## Troubleshooting

### "No module named 'pydoll'"
```bash
pip install pydoll-python
```

### "Browser not found"
```python
# Specify browser path
options = ChromiumOptions()
options.binary_location = '/usr/bin/google-chrome'
```

### Memory Issues
```python
# Reduce concurrent tabs
crawler = EfficientWebCrawler(concurrent_tabs=2)

# Lower max pages
crawler = EfficientWebCrawler(max_pages=100)
```

### Network Timeout
```python
# Increase timeout
await tab.go_to(url, timeout=60)
```

---

## Best Practices

1. ✅ **Start with simple_production_crawler.py**
2. ✅ **Use headless mode for production**
3. ✅ **Block images/media for speed**
4. ✅ **Set reasonable limits (max_pages, max_depth)**
5. ✅ **Use deduplication to save space**
6. ✅ **Handle exceptions gracefully**
7. ✅ **Respect robots.txt (optional)**
8. ✅ **Add delays if needed (rate limiting)**

---

## Comparison with Other Tools

| Feature | Pydoll Crawler | Scrapy | Selenium |
|---------|---------------|--------|----------|
| JavaScript Support | ✅ Full | ⚠️ Limited | ✅ Full |
| API Call Capture | ✅ Yes | ❌ No | ⚠️ Manual |
| Setup | ⚡ Easy | 🔧 Complex | ⚡ Easy |
| Speed | ⚡ Fast | ⚡⚡ Fastest | 🐌 Slow |
| Memory | 💚 Low | 💚 Low | 🔴 High |
| Concurrency | ✅ Built-in | ✅ Built-in | ⚠️ Manual |

**Pydoll Advantage:**
- Captures API calls automatically
- No WebDriver setup needed
- Human-like behavior (CAPTCHA bypass)
- Built-in request/response interception

---

## Further Reading

- [`crawler_strategies.md`](./crawler_strategies.md) - Deep dive into strategies
- [Pydoll Documentation](https://autoscrape-labs.github.io/pydoll/)
- [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/)

---

## License

These examples are part of the Pydoll project (MIT License).
