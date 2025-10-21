# Critical Features Implementation Plan

## Overview

Adding 3 critical features to ultimate_crawler.py:
1. ✅ Authentication Support (cookies + headers)
2. ✅ SPA Waiting (network idle + configurable wait)
3. ✅ Smart File Handling (skip media, never skip JS)

---

## 1. Authentication Support 🔐

### Parameters Added (✅ Done):
```python
auth_cookies: Optional[str] = None
auth_headers: Optional[dict] = None
```

### Implementation Needed:

####  A. Cookie Injection
**Where:** In `crawl()` method after browser starts

```python
async def crawl(self, start_url: str):
    async with Chrome(options=options) as browser:
        # NEW: Inject authentication cookies
        if self.auth_cookies:
            await self._inject_cookies(browser, start_url)

        # Continue with existing code...
```

**New method to add:**
```python
async def _inject_cookies(self, browser, url: str):
    """Inject authentication cookies"""
    tab = await browser.get_tab()

    # Parse cookie string
    # Format: "session=abc123; token=xyz789"
    for cookie_str in self.auth_cookies.split(';'):
        if '=' in cookie_str:
            name, value = cookie_str.strip().split('=', 1)
            await tab.set_cookie(name=name, value=value, domain=urlparse(url).netloc)

    if self.verbose:
        print(f"[AUTH] Injected {len(self.auth_cookies.split(';'))} cookies")
```

#### B. Header Injection
**Where:** In `_crawl_page()` before navigation

```python
async def _crawl_page(self, tab, url: str, worker_id: int):
    # NEW: Set custom headers if provided
    if self.auth_headers:
        await tab.set_extra_headers(self.auth_headers)

    # Existing navigation code...
```

---

## 2. SPA Waiting ⏱️

### Parameters Added (✅ Done):
```python
wait_for_idle: bool = False
page_wait_time: int = 3
```

### Implementation Needed:

**Where:** In `_crawl_page()` after `tab.go_to()`

```python
async def _crawl_page(self, tab, url: str, worker_id: int):
    # Existing code...
    await tab.go_to(url, timeout=30)

    # NEW: Wait for dynamic content
    if self.wait_for_idle:
        await self._wait_for_network_idle(tab)

    # Additional wait time (default 3s, configurable)
    await asyncio.sleep(self.page_wait_time)

    # Continue with existing code...
```

**New method to add:**
```python
async def _wait_for_network_idle(self, tab, timeout: int = 10):
    """Wait for network to be idle (no requests for 500ms)"""
    try:
        start_time = asyncio.get_event_loop().time()
        last_request_time = start_time

        async def on_request(_):
            nonlocal last_request_time
            last_request_time = asyncio.get_event_loop().time()

        # Monitor network requests
        cb_id = await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, on_request)

        # Wait until no requests for 500ms or timeout
        while True:
            await asyncio.sleep(0.5)
            now = asyncio.get_event_loop().time()

            # Idle for 500ms?
            if (now - last_request_time) >= 0.5:
                break

            # Timeout?
            if (now - start_time) > timeout:
                if self.verbose:
                    print(f"    [WARN] Network idle timeout after {timeout}s")
                break

        await tab.off(cb_id)

    except Exception as e:
        if self.verbose:
            print(f"    [WARN] Network idle wait failed: {e}")
```

---

## 3. Smart File Handling 📦

### Parameters Added (✅ Done):
```python
skip_media: bool = True
max_media_size: int = 10 * 1024 * 1024  # 10MB
warn_large_files: bool = True
```

### Implementation Needed:

**Where:** In `on_response_received()` inside `_setup_network_capture()`

```python
async def on_response_received(event):
    try:
        params = event.get('params', {})
        response = params.get('response', {})
        request_id = params.get('requestId', '')

        if request_id not in requests_map:
            return

        req_info = requests_map[request_id]
        status = response.get('status', 0)

        if status not in [200, 201]:
            return

        # NEW: Check file size before downloading
        content_length = response.get('headers', {}).get('Content-Length', 0)
        try:
            file_size = int(content_length)
        except:
            file_size = 0

        # NEW: Smart file handling
        mime_type = response.get('mimeType', '')
        should_skip, reason = self._should_skip_file(
            req_info['url'],
            mime_type,
            file_size
        )

        if should_skip:
            if self.verbose:
                print(f"  [SKIP] {reason}: {req_info['url'][:60]}")
            return

        # Existing download code...
        body = await tab.get_response_body(request_id)
        # ...
```

**New method to add:**
```python
def _should_skip_file(self, url: str, mime_type: str, file_size: int) -> tuple[bool, str]:
    """
    Determine if file should be skipped based on type and size.
    Returns: (should_skip, reason)

    Rules:
    - NEVER skip JavaScript (regardless of size)
    - Skip large media files if skip_media enabled
    - Warn about large files if warn_large_files enabled
    """

    # NEVER skip JavaScript - these often contain secrets!
    if 'javascript' in mime_type or url.lower().endswith('.js'):
        if self.warn_large_files and file_size > 50 * 1024 * 1024:  # 50MB
            if self.verbose:
                size_mb = file_size / (1024 * 1024)
                print(f"  [WARN] Large JS file ({size_mb:.1f}MB): {url[:60]}")
        return (False, "")  # Never skip

    # Skip media files if enabled
    if self.skip_media:
        media_types = [
            'image/', 'video/', 'audio/',
            'font/', 'application/octet-stream'
        ]

        media_extensions = [
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg',
            '.mp4', '.webm', '.avi', '.mov', '.mp3', '.wav',
            '.woff', '.woff2', '.ttf', '.eot', '.otf'
        ]

        # Check MIME type
        if any(media_type in mime_type for media_type in media_types):
            if file_size > self.max_media_size:
                size_mb = file_size / (1024 * 1024)
                return (True, f"Large media file ({size_mb:.1f}MB)")

        # Check file extension
        if any(url.lower().endswith(ext) for ext in media_extensions):
            if file_size > self.max_media_size:
                size_mb = file_size / (1024 * 1024)
                return (True, f"Media file ({size_mb:.1f}MB)")

    # Warn about other large files but still download
    if self.warn_large_files and file_size > 100 * 1024 * 1024:  # 100MB
        size_mb = file_size / (1024 * 1024)
        if self.verbose:
            print(f"  [WARN] Large file ({size_mb:.1f}MB): {url[:60]}")

    return (False, "")
```

---

## 4. CLI Arguments

### Add to argparse section:

```python
# Authentication
parser.add_argument('--auth-cookie', type=str,
                   help='Authentication cookies (format: "name1=value1; name2=value2")')
parser.add_argument('--auth-header', type=str, action='append',
                   help='Authentication header (format: "Name: Value"). Can be used multiple times.')

# SPA/Dynamic content
parser.add_argument('--wait-for-idle', action='store_true',
                   help='Wait for network to be idle before capturing (for SPAs)')
parser.add_argument('--page-wait', type=int, default=3,
                   help='Wait time in seconds after page load (default: 3)')

# File handling
parser.add_argument('--no-skip-media', action='store_true',
                   help='Download all media files (default: skip large media)')
parser.add_argument('--max-media-size', type=str, default='10M',
                   help='Max size for media files (e.g., 10M, 50M). Default: 10M')
parser.add_argument('--no-warn-large', action='store_true',
                   help='Disable warnings for large files')
```

### Parse arguments:

```python
# Parse auth headers
auth_headers = {}
if args.auth_header:
    for header in args.auth_header:
        if ':' in header:
            name, value = header.split(':', 1)
            auth_headers[name.strip()] = value.strip()

# Parse max media size
max_media_size = parse_size(args.max_media_size)  # Helper function needed

crawler = UltimateCrawler(
    # ... existing args ...
    auth_cookies=args.auth_cookie,
    auth_headers=auth_headers if auth_headers else None,
    wait_for_idle=args.wait_for_idle,
    page_wait_time=args.page_wait,
    skip_media=not args.no_skip_media,
    max_media_size=max_media_size,
    warn_large_files=not args.no_warn_large,
)
```

---

## Usage Examples

### Authentication:
```bash
# Cookies only
python ultimate_crawler.py https://app.example.com \
    --auth-cookie "session=abc123; user_token=xyz789"

# Headers only
python ultimate_crawler.py https://api.example.com \
    --auth-header "Authorization: Bearer token123" \
    --auth-header "X-API-Key: key456"

# Both
python ultimate_crawler.py https://app.example.com \
    --auth-cookie "session=abc123" \
    --auth-header "Authorization: Bearer token"
```

### SPA Waiting:
```bash
# Wait for network idle (React/Vue/Angular apps)
python ultimate_crawler.py https://spa-app.com --wait-for-idle

# Fixed wait time
python ultimate_crawler.py https://slow-app.com --page-wait 5

# Both
python ultimate_crawler.py https://react-app.com --wait-for-idle --page-wait 3
```

### File Handling:
```bash
# Default (skip large media, warn on huge files)
python ultimate_crawler.py https://example.com

# Download all media (no limits)
python ultimate_crawler.py https://example.com --no-skip-media

# Custom media size limit
python ultimate_crawler.py https://example.com --max-media-size 50M

# Disable large file warnings
python ultimate_crawler.py https://example.com --no-warn-large
```

### Combined:
```bash
# Full authenticated SPA scan
./scan_workflow.sh https://app.example.com \
    --auth-cookie "session=abc123" \
    --auth-header "Authorization: Bearer token" \
    --wait-for-idle \
    --page-wait 5 \
    --tabs 3 \
    --semgrep
```

---

## Testing Checklist

- [ ] Test cookie injection (verify cookies sent in requests)
- [ ] Test header injection (verify headers sent in requests)
- [ ] Test SPA waiting (verify dynamic content captured)
- [ ] Test file size detection (verify large media skipped)
- [ ] Test that JS is NEVER skipped (even 500MB bundles)
- [ ] Test warnings for large files
- [ ] Test CLI argument parsing
- [ ] Test backward compatibility (without new flags)

---

## Implementation Status

✅ Parameters added to __init__
✅ Cookie injection - COMPLETE
✅ Header injection - COMPLETE
✅ Network idle waiting - COMPLETE
✅ Smart file handling - COMPLETE (NEVER skips JavaScript!)
✅ CLI arguments - COMPLETE
✅ Documentation - COMPLETE
✅ scan_workflow.sh updated - COMPLETE

**Implementation completed!**

## What Was Implemented

1. **`_inject_cookies()`** - Injects authentication cookies before crawling starts
2. **`_wait_for_network_idle()`** - Waits for network to be idle (500ms quiet) for SPA support
3. **`_should_skip_file()`** - Smart file handling with CRITICAL rule: NEVER skip JavaScript files
4. **Cookie injection integration** - Automatically injects cookies when `--auth-cookie` is provided
5. **Header injection integration** - Sets custom headers via `tab.set_extra_headers()` when `--auth-header` is provided
6. **SPA waiting integration** - Waits for network idle and configurable page wait time
7. **File size checking** - Checks Content-Length and MIME type before downloading, skips large media but NEVER JavaScript
8. **CLI arguments** - Added 7 new arguments for all features
9. **Documentation updates** - Updated docstrings and help examples
10. **scan_workflow.sh updates** - Updated help message with new feature examples
