# Efficient Web Crawling Strategies with Pydoll

## Overview

This guide explains the most efficient ways to crawl websites and capture JavaScript, HTML, API endpoints, and network data using Pydoll.

---

## Strategy Comparison

| Strategy | Efficiency | Data Captured | Best For |
|----------|-----------|---------------|----------|
| **Network Interception** | ⭐⭐⭐⭐⭐ | Everything (XHR, Fetch, JS, HTML, API) | Complete data capture |
| **Network Events Only** | ⭐⭐⭐⭐⭐ | All network traffic, minimal overhead | Large-scale crawling |
| **DOM Parsing** | ⭐⭐⭐ | Only visible HTML content | Simple static sites |
| **Hybrid Approach** | ⭐⭐⭐⭐ | Network + DOM validation | Comprehensive analysis |

---

## 1. MOST EFFICIENT: Network Interception (Recommended)

### Why This is Best

**Captures EVERYTHING without DOM parsing:**
- ✅ All JavaScript files (inline + external)
- ✅ All XHR/Fetch API calls
- ✅ POST/GET requests with payloads
- ✅ GraphQL queries
- ✅ WebSocket connections
- ✅ Service Worker requests
- ✅ Dynamic content loaded via AJAX

**Advantages:**
1. **Zero overhead** - No DOM traversal needed
2. **Complete coverage** - Captures API calls DOM parsing would miss
3. **Real payloads** - Gets actual POST data and responses
4. **Asynchronous** - Doesn't block on page load
5. **Memory efficient** - No need to store full DOM

### Implementation

```python
async def efficient_network_capture(tab: Tab):
    await tab.enable_network_events()

    captured_data = {
        'javascript': [],
        'api_calls': [],
        'html_docs': []
    }

    async def on_request(event):
        params = event['params']
        request = params['request']

        url = request['url']
        method = request['method']
        resource_type = params.get('type', '')

        # Classify request
        if resource_type == 'script' or url.endswith('.js'):
            captured_data['javascript'].append({
                'url': url,
                'request_id': params['requestId']
            })

        elif resource_type in ['xhr', 'fetch']:
            captured_data['api_calls'].append({
                'method': method,
                'url': url,
                'headers': request.get('headers', {}),
                'post_data': request.get('postData'),
                'request_id': params['requestId']
            })

    async def on_response(event):
        params = event['params']
        request_id = params['requestId']
        response = params['response']

        # Get response body
        try:
            body = await tab.get_response_body(request_id)

            # Save based on type
            # (implementation in efficient_crawler.py)
        except:
            pass

    from pydoll.protocol.network.events import NetworkEvent
    await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, on_request)
    await tab.on(NetworkEvent.RESPONSE_RECEIVED, on_response)

    # Navigate and let interception work
    await tab.go_to('https://example.com')
    await asyncio.sleep(3)  # Wait for network to settle

    return captured_data
```

---

## 2. Maximum Performance: Pure Network Events

### No Request Interception Overhead

```python
async def pure_network_capture(tab: Tab):
    """
    Even more efficient - just log network events.
    No interception overhead, pure observation.
    """

    network_log = []

    async def log_request(event):
        params = event['params']
        request = params['request']

        network_log.append({
            'type': 'request',
            'url': request['url'],
            'method': request['method'],
            'resource_type': params.get('type'),
            'headers': request.get('headers'),
            'post_data': request.get('postData'),
            'timestamp': params.get('timestamp')
        })

    async def log_response(event):
        params = event['params']
        response = params['response']

        network_log.append({
            'type': 'response',
            'url': response['url'],
            'status': response['status'],
            'mime_type': response.get('mimeType'),
            'headers': response.get('headers'),
            'request_id': params['requestId']
        })

    await tab.enable_network_events()

    from pydoll.protocol.network.events import NetworkEvent
    await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, log_request)
    await tab.on(NetworkEvent.RESPONSE_RECEIVED, log_response)

    return network_log
```

**Use Case:** When you need to map the network topology but don't need actual file contents initially.

---

## 3. Hybrid: Network + Browser Fetch API

### Best for API-Heavy Sites

```python
async def api_discovery_crawler(tab: Tab):
    """
    Use tab.request to replay API calls discovered via network monitoring.
    Gets fresh data without browser overhead.
    """

    # Step 1: Monitor network to discover API endpoints
    await tab.enable_network_events()

    discovered_apis = []

    async def discover_api(event):
        params = event['params']
        request = params['request']

        if params.get('type') in ['xhr', 'fetch']:
            discovered_apis.append({
                'url': request['url'],
                'method': request['method'],
                'headers': request.get('headers', {}),
                'post_data': request.get('postData')
            })

    from pydoll.protocol.network.events import NetworkEvent
    await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, discover_api)

    # Step 2: Load page to discover APIs
    await tab.go_to('https://api-heavy-site.com')
    await asyncio.sleep(3)

    # Step 3: Replay API calls using browser context
    # This inherits cookies, auth, CORS - super powerful!
    api_responses = []

    for api in discovered_apis:
        try:
            if api['method'] == 'GET':
                response = await tab.request.get(api['url'])
            elif api['method'] == 'POST':
                # Parse post data
                post_data = json.loads(api['post_data']) if api['post_data'] else {}
                response = await tab.request.post(api['url'], json=post_data)

            api_responses.append({
                'endpoint': api['url'],
                'method': api['method'],
                'response': response.json() if response.ok else response.text,
                'status': response.status
            })
        except Exception as e:
            print(f"Error replaying {api['url']}: {e}")

    return api_responses
```

**Advantages:**
- Gets authenticated API responses (inherits browser session)
- No CORS issues
- Can replay/test APIs easily
- Bypasses rate limiting (uses browser identity)

---

## 4. Smart Resource Filtering

### Skip Unnecessary Content

```python
def should_skip_resource(url: str, resource_type: str) -> bool:
    """Efficient resource filtering"""

    # Media files (SKIP)
    media_extensions = {
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',
        '.mp4', '.webm', '.avi', '.mov',
        '.mp3', '.wav', '.ogg',
        '.woff', '.woff2', '.ttf', '.eot',
        '.pdf', '.zip'
    }

    if any(url.endswith(ext) for ext in media_extensions):
        return True

    # Resource type filtering
    if resource_type in ['image', 'media', 'font']:
        return True

    # Analytics/tracking (optional)
    tracking_domains = ['google-analytics.com', 'googletagmanager.com', 'facebook.net']
    if any(domain in url for domain in tracking_domains):
        return True

    return False


async def filtered_crawl(tab: Tab):
    """Crawl with smart filtering"""

    await tab.enable_network_events()

    valuable_requests = []

    async def filter_request(event):
        params = event['params']
        request = params['request']

        url = request['url']
        resource_type = params.get('type', '')

        # Skip unwanted resources
        if should_skip_resource(url, resource_type):
            return

        # Only process valuable resources
        if resource_type in ['script', 'xhr', 'fetch', 'document']:
            valuable_requests.append({
                'url': url,
                'type': resource_type,
                'method': request['method']
            })

    from pydoll.protocol.network.events import NetworkEvent
    await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, filter_request)

    await tab.go_to('https://example.com')

    return valuable_requests
```

---

## 5. Concurrent Crawling Architecture

### Maximum Throughput

```python
async def concurrent_subdomain_crawler(subdomains: List[str], max_concurrent: int = 5):
    """
    Crawl multiple subdomains concurrently.
    Each gets its own tab for parallel processing.
    """

    async def crawl_subdomain(browser: Browser, subdomain: str):
        tab = await browser.new_tab()

        # Setup network capture
        await tab.enable_network_events()

        results = {
            'subdomain': subdomain,
            'javascript': [],
            'apis': [],
            'pages': []
        }

        # Crawl logic here...
        await tab.go_to(f'https://{subdomain}')

        await tab.close()
        return results

    async with Chrome() as browser:
        await browser.start(headless=True)

        # Process in batches to respect max_concurrent limit
        all_results = []
        for i in range(0, len(subdomains), max_concurrent):
            batch = subdomains[i:i+max_concurrent]

            tasks = [crawl_subdomain(browser, sd) for sd in batch]
            batch_results = await asyncio.gather(*tasks)

            all_results.extend(batch_results)

        return all_results
```

---

## 6. Deduplication Strategies

### Avoid Redundant Data

```python
import hashlib

class ContentDeduplicator:
    """Efficient content deduplication"""

    def __init__(self):
        self.seen_hashes = set()
        self.url_to_hash = {}

    def is_duplicate(self, content: bytes, url: str = None) -> bool:
        """Check if content is duplicate using hash"""
        content_hash = hashlib.sha256(content).hexdigest()

        if content_hash in self.seen_hashes:
            return True

        self.seen_hashes.add(content_hash)

        if url:
            self.url_to_hash[url] = content_hash

        return False

    def get_unique_content_count(self) -> int:
        return len(self.seen_hashes)


# Usage in crawler
deduplicator = ContentDeduplicator()

async def save_if_unique(url: str, content: bytes):
    if not deduplicator.is_duplicate(content, url):
        # Save to disk
        save_to_file(content)
        return True
    return False
```

---

## 7. Data Storage Strategies

### Efficient Storage

```python
import sqlite3
import json
from pathlib import Path

class CrawlDatabase:
    """Efficient SQLite storage for crawl data"""

    def __init__(self, db_path: str = "crawl.db"):
        self.conn = sqlite3.connect(db_path)
        self._setup_schema()

    def _setup_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS javascript_files (
                id INTEGER PRIMARY KEY,
                url TEXT UNIQUE,
                content TEXT,
                content_hash TEXT,
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS api_endpoints (
                id INTEGER PRIMARY KEY,
                method TEXT,
                endpoint TEXT,
                full_url TEXT,
                request_headers TEXT,
                request_body TEXT,
                response_status INTEGER,
                response_body TEXT,
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS html_pages (
                id INTEGER PRIMARY KEY,
                url TEXT UNIQUE,
                content TEXT,
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_js_hash ON javascript_files(content_hash);
            CREATE INDEX IF NOT EXISTS idx_api_endpoint ON api_endpoints(method, endpoint);
        """)
        self.conn.commit()

    def save_javascript(self, url: str, content: str, content_hash: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO javascript_files (url, content, content_hash) VALUES (?, ?, ?)",
            (url, content, content_hash)
        )
        self.conn.commit()

    def save_api_call(self, method: str, endpoint: str, full_url: str,
                      req_headers: dict, req_body: str,
                      resp_status: int, resp_body: str):
        self.conn.execute(
            """INSERT INTO api_endpoints
               (method, endpoint, full_url, request_headers, request_body, response_status, response_body)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (method, endpoint, full_url, json.dumps(req_headers), req_body, resp_status, resp_body)
        )
        self.conn.commit()

    def get_unique_endpoints(self):
        cursor = self.conn.execute(
            "SELECT DISTINCT method, endpoint FROM api_endpoints"
        )
        return cursor.fetchall()
```

---

## 8. Complete Efficient Crawler Pattern

### Recommended Architecture

```python
async def ultimate_efficient_crawler(start_url: str, output_dir: str):
    """
    Ultimate efficient crawler combining all best practices.
    """

    from collections import deque

    # Setup
    db = CrawlDatabase(f"{output_dir}/crawl.db")
    dedup = ContentDeduplicator()

    visited = set()
    queue = deque([(start_url, 0)])  # (url, depth)

    max_depth = 3
    max_pages = 1000

    async with Chrome() as browser:
        await browser.start(headless=True)

        # Use 3-5 tabs for concurrent crawling
        active_tabs = []
        for _ in range(3):
            active_tabs.append(await browser.new_tab())

        tab_index = 0
        pages_crawled = 0

        while queue and pages_crawled < max_pages:
            url, depth = queue.popleft()

            if url in visited or depth > max_depth:
                continue

            visited.add(url)

            # Get next available tab (round-robin)
            tab = active_tabs[tab_index % len(active_tabs)]
            tab_index += 1

            print(f"[{pages_crawled}/{max_pages}] Crawling: {url}")

            # EFFICIENT NETWORK CAPTURE
            captured = {
                'js': [],
                'apis': [],
                'links': []
            }

            async def capture_request(event):
                params = event['params']
                request = params['request']
                req_url = request['url']
                resource_type = params.get('type', '')

                # Filter media
                if should_skip_resource(req_url, resource_type):
                    return

                # Capture by type
                if resource_type == 'script':
                    captured['js'].append({
                        'url': req_url,
                        'id': params['requestId']
                    })
                elif resource_type in ['xhr', 'fetch']:
                    captured['apis'].append({
                        'method': request['method'],
                        'url': req_url,
                        'headers': request.get('headers'),
                        'body': request.get('postData'),
                        'id': params['requestId']
                    })

            async def capture_response(event):
                params = event['params']
                request_id = params['requestId']
                response = params['response']

                if response['status'] != 200:
                    return

                try:
                    body = await tab.get_response_body(request_id)

                    # Check which type this is
                    for js in captured['js']:
                        if js['id'] == request_id:
                            if not dedup.is_duplicate(body.encode()):
                                content_hash = hashlib.sha256(body.encode()).hexdigest()
                                db.save_javascript(js['url'], body, content_hash)

                    for api in captured['apis']:
                        if api['id'] == request_id:
                            # Parse endpoint
                            parsed = urlparse(api['url'])
                            endpoint = f"{api['method']} {parsed.path}"

                            db.save_api_call(
                                api['method'], endpoint, api['url'],
                                api['headers'], api.get('body', ''),
                                response['status'], body
                            )
                except:
                    pass

            # Setup and navigate
            await tab.enable_network_events()

            from pydoll.protocol.network.events import NetworkEvent
            await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, capture_request)
            await tab.on(NetworkEvent.RESPONSE_RECEIVED, capture_response)

            try:
                await tab.go_to(url, timeout=30)
                await asyncio.sleep(2)  # Let network settle

                # Get HTML
                html = await tab.page_source
                db.save_html(url, html)

                # Extract links for crawling
                # (Use regex or parser to find more URLs)

                pages_crawled += 1

            except Exception as e:
                print(f"Error: {e}")

        # Cleanup
        for tab in active_tabs:
            await tab.close()

    print(f"\nCrawl complete!")
    print(f"Pages: {pages_crawled}")
    print(f"Unique JS files: {dedup.get_unique_content_count()}")
    print(f"API endpoints: {len(db.get_unique_endpoints())}")
```

---

## Performance Tips

### 1. **Headless Mode** (30% faster)
```python
await browser.start(headless=True)
```

### 2. **Disable Images** (50% faster, less bandwidth)
```python
options = ChromiumOptions()
options.browser_preferences = {
    'profile': {
        'default_content_setting_values': {
            'images': 2  # Block images
        }
    }
}
```

### 3. **Resource Blocking**
```python
# Block ads, analytics, fonts
BLOCK_PATTERNS = [
    '*google-analytics.com*',
    '*googletagmanager.com*',
    '*facebook.com*',
    '*.woff*',
    '*.ttf*'
]
```

### 4. **Page Load Optimization**
```python
options.page_load_state = PageLoadState.INTERACTIVE  # Don't wait for full load
```

### 5. **Memory Management**
```python
# Close tabs after crawling
await tab.close()

# Periodic browser restart for long crawls
if pages_crawled % 100 == 0:
    await browser.stop()
    await browser.start(headless=True)
```

---

## Comparison: Why Network Interception Wins

| Method | JS Files | API Calls | Speed | Memory |
|--------|----------|-----------|-------|--------|
| DOM Parsing | ❌ Only `<script src>` | ❌ None | Slow | High |
| Network Events | ✅ All | ✅ All | Fast | Low |
| Request Interception | ✅ All + modify | ✅ All + modify | Fast | Low |

**Winner: Network Events + Response Body Capture** (implemented in `efficient_crawler.py`)

---

## Conclusion

For maximum efficiency crawling websites to capture JavaScript, HTML, and API data:

1. ✅ **Use Network Events** - Captures everything
2. ✅ **Filter Resources** - Skip media files
3. ✅ **Concurrent Tabs** - 3-5 tabs for parallel processing
4. ✅ **Deduplicate** - Hash-based content deduplication
5. ✅ **Database Storage** - SQLite for efficient storage
6. ✅ **Headless Mode** - Faster execution
7. ✅ **Smart Queuing** - BFS with depth limits

The `efficient_crawler.py` example implements all these best practices!
