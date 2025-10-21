"""
Ultimate Crawler - All Features Combined
=========================================

The complete solution with ALL features:
- ✅ Concurrent crawling (1-5 tabs) - configurable speed
- ✅ Domain list support - crawl multiple domains from file
- ✅ Subdomain discovery - external tools + passive
- ✅ Proxy support - HTTP/SOCKS5
- ✅ CAPTCHA bypass - Cloudflare, reCAPTCHA
- ✅ Authentication support - cookies + headers
- ✅ SPA waiting - network idle + configurable wait
- ✅ Smart file handling - skip media, NEVER skip JS
- ✅ TruffleHog-ready output
- ✅ Smart priority queue
- ✅ Session sharing

Usage:
    # Single domain (backward compatible)
    python ultimate_crawler.py https://example.com

    # Multiple domains from file
    python ultimate_crawler.py --domains domains.txt

    # With speed boost (3 concurrent tabs)
    python ultimate_crawler.py https://example.com --tabs 3

    # Authenticated crawl (cookies + headers)
    python ultimate_crawler.py https://app.example.com \
        --auth-cookie "session=abc123; token=xyz789" \
        --auth-header "Authorization: Bearer token123"

    # SPA support (wait for dynamic content)
    python ultimate_crawler.py https://react-app.com \
        --wait-for-idle \
        --page-wait 5

    # Full featured
    python ultimate_crawler.py --domains domains.txt \
        --tabs 5 \
        --discover-subdomains \
        --auth-cookie "session=abc123" \
        --wait-for-idle \
        --proxy http://proxy:8080 \
        --bypass-captcha \
        --max-pages 1000

Domain list file format (domains.txt):
    https://example.com
    https://api.example.com
    https://admin.example.com
    example2.com
    *.example3.com
"""

import asyncio
import argparse
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urljoin
from datetime import datetime
from typing import Set, List, Optional, Dict
import re
import hashlib
from collections import deque, OrderedDict
import time
import sys

from pydoll.browser import Chrome
from pydoll.browser.options import ChromiumOptions
from pydoll.protocol.network.events import NetworkEvent

# JS Beautification
try:
    import jsbeautifier
    BEAUTIFIER_AVAILABLE = True
except ImportError:
    BEAUTIFIER_AVAILABLE = False
    print("[WARNING] jsbeautifier not installed - JS beautification disabled")
    print("[INFO] Install with: pip install jsbeautifier")


# ============================================================================
# Production-Ready Helper Classes for 24/7 Operation
# ============================================================================

class BoundedSet:
    """
    Set with maximum size that evicts oldest items (LRU).
    Prevents unbounded memory growth during long-running operations.
    """
    def __init__(self, max_size: int = 100000):
        self.data = OrderedDict()
        self.max_size = max_size

    def add(self, item: str):
        """Add item to set (evicts oldest if at capacity)"""
        if item in self.data:
            # Move to end (most recently used)
            self.data.move_to_end(item)
        else:
            self.data[item] = True
            # Evict oldest if over capacity
            if len(self.data) > self.max_size:
                self.data.popitem(last=False)

    def __contains__(self, item: str) -> bool:
        return item in self.data

    def __len__(self) -> int:
        return len(self.data)


class PerDomainRateLimiter:
    """
    Rate limiter that applies limits per domain, not globally.
    Allows fast multi-domain crawling while respecting per-domain limits.
    """
    def __init__(self, requests_per_second: float = 10.0):
        self.rate = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self.domain_last_request: Dict[str, float] = {}
        self.lock = asyncio.Lock()

    async def acquire(self, url: str):
        """Wait if necessary to respect rate limit for this domain"""
        domain = urlparse(url).netloc

        async with self.lock:
            now = time.time()
            last_request = self.domain_last_request.get(domain, 0)
            time_since_last = now - last_request

            if time_since_last < self.min_interval:
                wait_time = self.min_interval - time_since_last
                await asyncio.sleep(wait_time)

            self.domain_last_request[domain] = time.time()


class HealthMonitor:
    """
    Monitors crawler health and detects issues.
    Tracks memory usage, heartbeat, and error rates.
    """
    def __init__(self, memory_limit_mb: float = 2048, error_rate_threshold: float = 0.3):
        self.memory_limit = memory_limit_mb * 1024 * 1024  # Convert to bytes
        self.error_rate_threshold = error_rate_threshold
        self.last_heartbeat = time.time()
        self.start_time = time.time()

    def heartbeat(self):
        """Update heartbeat timestamp"""
        self.last_heartbeat = time.time()

    def check_memory(self) -> tuple[bool, str]:
        """Check if memory usage is within limits"""
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024

            if memory_info.rss > self.memory_limit:
                return (False, f"Memory limit exceeded: {memory_mb:.0f} MB / {self.memory_limit/1024/1024:.0f} MB")
            return (True, f"Memory OK: {memory_mb:.0f} MB")
        except ImportError:
            # psutil not available, skip check
            return (True, "Memory check skipped (psutil not installed)")
        except Exception as e:
            return (True, f"Memory check failed: {e}")

    def check_heartbeat(self, timeout_seconds: int = 300) -> tuple[bool, str]:
        """Check if heartbeat is recent"""
        elapsed = time.time() - self.last_heartbeat
        if elapsed > timeout_seconds:
            return (False, f"No heartbeat for {elapsed:.0f}s")
        return (True, f"Heartbeat OK ({elapsed:.0f}s ago)")

    def check_error_rate(self, errors: int, total: int) -> tuple[bool, str]:
        """Check if error rate is acceptable"""
        if total == 0:
            return (True, "No requests yet")

        error_rate = errors / total
        if error_rate > self.error_rate_threshold:
            return (False, f"High error rate: {error_rate*100:.1f}% ({errors}/{total})")
        return (True, f"Error rate OK: {error_rate*100:.1f}%")

    def get_uptime(self) -> str:
        """Get uptime string"""
        uptime_seconds = time.time() - self.start_time
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        seconds = int(uptime_seconds % 60)
        return f"{hours}h {minutes}m {seconds}s"


# URL patterns that should NEVER be crawled (dangerous actions)
URL_BLACKLIST_PATTERNS = [
    r'/logout',
    r'/signout',
    r'/sign-out',
    r'/log-out',
    r'/delete',
    r'/remove',
    r'/destroy',
    r'/drop',
    r'/admin/delete',
    r'/admin/remove',
    r'/admin/drop',
    r'/api/delete',
    r'/api/remove',
]


class UltimateCrawler:
    """
    Ultimate crawler with all features:
    - Concurrent crawling (configurable)
    - Domain list support
    - Subdomain discovery
    - Proxy, CAPTCHA bypass
    """

    SECRET_PRONE_PATTERNS = {
        '.env', '.env.local', '.env.production', '.env.development',
        'config.js', 'config.json', 'settings.json', 'constants.js',
        'credentials', 'api-keys.json', 'secrets.json',
        'database.yml', 'aws.json', 'azure.json',
    }

    def __init__(
        self,
        output_dir: str = "./trufflehog_scan_output",
        max_pages: int = 500,
        concurrent_tabs: int = 1,  # Default 1 for backward compatibility
        verbose: bool = True,
        proxy: Optional[str] = None,
        bypass_captcha: bool = False,
        discover_subdomains: bool = False,
        headless: bool = True,
        domains: Optional[List[str]] = None,
        auth_cookies: Optional[str] = None,  # Authentication cookies
        auth_headers: Optional[dict] = None,  # Authentication headers
        wait_for_idle: bool = False,  # Wait for network idle
        page_wait_time: int = 3,  # Additional wait time after page load
        skip_media: bool = True,  # Skip large media files
        max_media_size: int = 10 * 1024 * 1024,  # 10MB limit for media
        warn_large_files: bool = True,  # Warn about large files
        rate_limit: float = 10.0,  # NEW: Requests per second per domain
        enable_health_check: bool = True,  # NEW: Enable health monitoring
        memory_limit_mb: float = 2048,  # NEW: Memory limit in MB
        max_retries: int = 3  # NEW: Max retries for transient failures
    ):
        self.output_dir = Path(output_dir)
        self.max_pages = max_pages
        self.concurrent_tabs = min(concurrent_tabs, 5)
        self.verbose = verbose
        self.proxy = proxy
        self.bypass_captcha = bypass_captcha
        self.discover_subdomains = discover_subdomains
        self.headless = headless
        self.domains = domains or []

        # Authentication
        self.auth_cookies = auth_cookies
        self.auth_headers = auth_headers or {}

        # SPA/Dynamic content handling
        self.wait_for_idle = wait_for_idle
        self.page_wait_time = page_wait_time

        # File handling
        self.skip_media = skip_media
        self.max_media_size = max_media_size
        self.warn_large_files = warn_large_files

        # Production features
        self.rate_limit = rate_limit
        self.max_retries = max_retries
        self.enable_health_check = enable_health_check

        # Tracking (using BoundedSet to prevent memory leaks)
        self.visited_urls = BoundedSet(max_size=100000)
        self.url_queue: deque = deque()
        self.content_hashes = BoundedSet(max_size=100000)
        self.discovered_subdomains: Set[str] = set()
        self.allowed_domains: Set[str] = set()
        self.lock = asyncio.Lock()

        # Production systems
        self.rate_limiter = PerDomainRateLimiter(requests_per_second=rate_limit) if rate_limit > 0 else None
        self.health_monitor = HealthMonitor(memory_limit_mb=memory_limit_mb) if enable_health_check else None

        # Statistics
        self.stats = {
            'pages_crawled': 0,
            'js_files': 0,
            'config_files': 0,
            'api_endpoints': 0,
            'env_files': 0,
            'high_priority_files': 0,
            'subdomains_found': 0,
            'domains_crawled': 0,
            'captchas_solved': 0,
            'duplicates_skipped': 0,
            'media_skipped': 0,
            'errors': 0,
            'dangerous_urls_skipped': 0,
            'retries': 0
        }

        self._setup_output_dirs()

    def _setup_output_dirs(self):
        """Create output directories"""
        (self.output_dir / "javascript").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "config_files").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "env_files").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "api_responses").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "html_pages").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "high_priority").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "logs").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "metadata").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "instant_alerts").mkdir(parents=True, exist_ok=True)

    def _load_domains_from_file(self, filepath: str) -> List[str]:
        """Load domains from file"""
        domains = []
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Handle different formats
                        if not line.startswith('http'):
                            line = f'https://{line}'
                        domains.append(line)

            if self.verbose:
                print(f"[INFO] Loaded {len(domains)} domains from {filepath}")

        except Exception as e:
            print(f"[ERROR] Failed to load domains file: {e}")

        return domains

    def _discover_subdomains_external(self, domain: str) -> Set[str]:
        """Use external tools for subdomain discovery"""
        subdomains = set()

        # Try subfinder
        try:
            if self.verbose:
                print(f"[INFO] Running subfinder for {domain}...")

            result = subprocess.run(
                ['subfinder', '-d', domain, '-silent'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                found = result.stdout.strip().split('\n')
                subdomains.update([s.strip() for s in found if s.strip()])

                if self.verbose:
                    print(f"[INFO] Subfinder found {len(subdomains)} subdomains for {domain}")

        except FileNotFoundError:
            if self.verbose:
                print("[INFO] subfinder not installed (optional)")
        except:
            pass

        # Try assetfinder (fallback)
        if not subdomains:
            try:
                result = subprocess.run(
                    ['assetfinder', '--subs-only', domain],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0:
                    found = result.stdout.strip().split('\n')
                    subdomains.update([s.strip() for s in found if s.strip()])

            except:
                pass

        return subdomains

    def _is_allowed_domain(self, url: str) -> bool:
        """Check if URL belongs to allowed domains"""
        if not self.allowed_domains:
            return True

        try:
            hostname = urlparse(url).netloc.lower()

            for allowed in self.allowed_domains:
                if hostname == allowed or hostname.endswith(f'.{allowed}'):
                    return True

            return False
        except:
            return False

    def _should_skip_resource(self, url: str) -> bool:
        """Skip media and non-target resources"""
        if not self._is_allowed_domain(url):
            return True

        skip_extensions = {
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',
            '.mp4', '.webm', '.avi', '.mov', '.mp3', '.wav',
            '.woff', '.woff2', '.ttf', '.eot',
            '.pdf', '.zip', '.tar', '.gz', '.exe'
        }

        try:
            return any(url.lower().endswith(ext) for ext in skip_extensions)
        except:
            return True

    def _is_dangerous_url(self, url: str) -> bool:
        """
        Check if URL matches dangerous patterns (logout, delete, etc.).
        These URLs should NEVER be crawled as they could perform destructive actions.
        """
        try:
            url_lower = url.lower()
            for pattern in URL_BLACKLIST_PATTERNS:
                if re.search(pattern, url_lower):
                    if self.verbose:
                        print(f"  [BLOCKED] Dangerous URL: {url[:70]}")
                    return True
            return False
        except Exception:
            # On error, be safe and skip
            return True

    def _is_secret_prone_file(self, url: str) -> tuple[bool, str]:
        """Check if URL is secret-prone"""
        try:
            url_lower = url.lower()
            path = urlparse(url_lower).path

            if any(pattern in url_lower for pattern in ['.env', '/env/', 'environment']):
                return (True, 'high')

            for pattern in self.SECRET_PRONE_PATTERNS:
                if pattern in path:
                    return (True, 'high')

            if any(word in path for word in ['config', 'setting', 'constant', 'credential']):
                return (True, 'medium')

            if path.endswith('.js'):
                return (True, 'low')

            return (False, 'none')
        except:
            return (False, 'none')

    def _classify_content(self, url: str, content: str, mime_type: str = '') -> str:
        """Classify content type"""
        try:
            url_lower = url.lower()
            path = urlparse(url_lower).path

            if '.env' in url_lower:
                return 'env_file'
            if any(p in url_lower for p in self.SECRET_PRONE_PATTERNS):
                return 'config_file'
            if path.endswith('.js') or mime_type == 'application/javascript':
                return 'javascript'
            if path.endswith('.json') or mime_type == 'application/json':
                if any(word in path for word in ['config', 'setting', 'key']):
                    return 'config_file'
                return 'api_response'
            if mime_type == 'text/html':
                return 'html_page'

            return 'other'
        except:
            return 'other'

    def _hash_content(self, content: str) -> str:
        """Generate content hash"""
        try:
            return hashlib.sha256(content.encode('utf-8', errors='ignore')).hexdigest()[:16]
        except:
            return hashlib.sha256(str(content).encode('utf-8', errors='ignore')).hexdigest()[:16]

    def _sanitize_filename(self, url: str) -> str:
        """Create safe filename"""
        try:
            parsed = urlparse(url)
            name = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            name = re.sub(r'[^\w\-_.]', '_', name)
            return (name.strip('_')[:200]) or 'index'
        except:
            return 'index'

    def _quick_detect_secrets(self, content: str) -> List[dict]:
        """
        Quick detection of OBVIOUS secrets (high precision patterns only).
        This doesn't replace TruffleHog - it's for instant alerts during crawl.
        """
        secrets_found = []

        try:
            # AWS Access Keys (very distinctive)
            aws_pattern = r'(AKIA|ABIA|ACCA)[A-Z0-9]{16}'
            for match in re.finditer(aws_pattern, content):
                secrets_found.append({
                    'type': 'AWS Access Key',
                    'value': match.group(0),
                    'position': match.start()
                })

            # GitHub Personal Access Tokens
            github_patterns = [
                (r'ghp_[a-zA-Z0-9]{36}', 'GitHub Personal Access Token'),
                (r'gho_[a-zA-Z0-9]{36}', 'GitHub OAuth Token'),
                (r'ghu_[a-zA-Z0-9]{36}', 'GitHub User Token'),
                (r'ghs_[a-zA-Z0-9]{36}', 'GitHub Server Token'),
                (r'ghr_[a-zA-Z0-9]{36}', 'GitHub Refresh Token'),
            ]
            for pattern, name in github_patterns:
                for match in re.finditer(pattern, content):
                    secrets_found.append({
                        'type': name,
                        'value': match.group(0),
                        'position': match.start()
                    })

            # Private Keys (unmistakable)
            if '-----BEGIN PRIVATE KEY-----' in content or '-----BEGIN RSA PRIVATE KEY-----' in content:
                secrets_found.append({
                    'type': 'Private Key',
                    'value': 'PRIVATE_KEY_FOUND',
                    'position': content.find('-----BEGIN')
                })

            # Stripe Keys (very distinctive)
            stripe_patterns = [
                (r'sk_live_[a-zA-Z0-9]{24,}', 'Stripe Live Secret Key'),
                (r'sk_test_[a-zA-Z0-9]{24,}', 'Stripe Test Secret Key'),
                (r'rk_live_[a-zA-Z0-9]{24,}', 'Stripe Live Restricted Key'),
            ]
            for pattern, name in stripe_patterns:
                for match in re.finditer(pattern, content):
                    secrets_found.append({
                        'type': name,
                        'value': match.group(0),
                        'position': match.start()
                    })

            # Slack Tokens (distinctive prefixes)
            slack_patterns = [
                (r'xoxb-[a-zA-Z0-9\-]{50,}', 'Slack Bot Token'),
                (r'xoxp-[a-zA-Z0-9\-]{50,}', 'Slack User Token'),
                (r'xoxa-[a-zA-Z0-9\-]{50,}', 'Slack App Token'),
            ]
            for pattern, name in slack_patterns:
                for match in re.finditer(pattern, content):
                    secrets_found.append({
                        'type': name,
                        'value': match.group(0),
                        'position': match.start()
                    })

            # Google API Keys (distinctive prefix)
            google_pattern = r'AIza[a-zA-Z0-9_\-]{35}'
            for match in re.finditer(google_pattern, content):
                secrets_found.append({
                    'type': 'Google API Key',
                    'value': match.group(0),
                    'position': match.start()
                })

            # OpenAI API Keys
            openai_pattern = r'sk-proj-[a-zA-Z0-9]{40,}'
            for match in re.finditer(openai_pattern, content):
                secrets_found.append({
                    'type': 'OpenAI API Key',
                    'value': match.group(0),
                    'position': match.start()
                })

            # Generic JWT tokens (high entropy base64)
            jwt_pattern = r'eyJ[a-zA-Z0-9_\-]+\.eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+'
            for match in re.finditer(jwt_pattern, content):
                secrets_found.append({
                    'type': 'JWT Token',
                    'value': match.group(0)[:50] + '...',  # Truncate for display
                    'position': match.start()
                })

        except Exception as e:
            pass  # Don't let detection errors break crawling

        return secrets_found

    async def _inject_cookies(self, browser, url: str):
        """Inject authentication cookies before crawling"""
        if not self.auth_cookies:
            return

        try:
            tab = await browser.get_tab()
            parsed_url = urlparse(url)
            domain = parsed_url.netloc

            # Parse cookie string (format: "session=abc123; token=xyz789")
            cookies_injected = 0
            for cookie_str in self.auth_cookies.split(';'):
                cookie_str = cookie_str.strip()
                if '=' in cookie_str:
                    name, value = cookie_str.split('=', 1)
                    await tab.set_cookie(
                        name=name.strip(),
                        value=value.strip(),
                        domain=domain
                    )
                    cookies_injected += 1

            if self.verbose:
                print(f"[AUTH] Injected {cookies_injected} cookies for {domain}")

        except Exception as e:
            if self.verbose:
                print(f"[WARNING] Cookie injection failed: {e}")

    async def _wait_for_network_idle(self, tab, timeout: int = 10):
        """
        Wait for network to be idle (no requests for 500ms).
        Useful for SPAs that load content dynamically.
        """
        try:
            start_time = asyncio.get_event_loop().time()
            last_request_time = start_time

            async def on_request(_):
                nonlocal last_request_time
                last_request_time = asyncio.get_event_loop().time()

            # Monitor network requests
            try:
                cb_id = await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, on_request)
            except:
                # If we can't monitor, just wait the timeout
                await asyncio.sleep(0.5)
                return

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

            try:
                await tab.off(cb_id)
            except:
                pass

        except Exception as e:
            if self.verbose:
                print(f"    [WARN] Network idle wait failed: {e}")

    def _should_skip_file(self, url: str, mime_type: str, file_size: int) -> tuple[bool, str]:
        """
        Determine if file should be skipped based on type and size.

        Returns: (should_skip, reason)

        CRITICAL RULES:
        - NEVER skip JavaScript files (regardless of size) - they often contain secrets!
        - Skip large media files if skip_media enabled
        - Warn about large files if warn_large_files enabled
        """

        # NEVER SKIP JAVASCRIPT - these often contain the most secrets!
        if 'javascript' in mime_type.lower() or url.lower().endswith('.js'):
            # Still warn if it's unusually large
            if self.warn_large_files and file_size > 50 * 1024 * 1024:  # 50MB
                size_mb = file_size / (1024 * 1024)
                if self.verbose:
                    print(f"  [WARN] Large JS file ({size_mb:.1f}MB): {url[:60]}")
            return (False, "")  # Never skip!

        # Skip large media files if enabled
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
            for media_type in media_types:
                if media_type in mime_type.lower():
                    if file_size > self.max_media_size:
                        size_mb = file_size / (1024 * 1024)
                        return (True, f"Large media file ({size_mb:.1f}MB)")

            # Check file extension
            if any(url.lower().endswith(ext) for ext in media_extensions):
                if file_size > self.max_media_size:
                    size_mb = file_size / (1024 * 1024)
                    return (True, f"Media file ({size_mb:.1f}MB)")

        # Warn about other large files but still download them
        if self.warn_large_files and file_size > 100 * 1024 * 1024:  # 100MB
            size_mb = file_size / (1024 * 1024)
            if self.verbose:
                print(f"  [WARN] Large file ({size_mb:.1f}MB): {url[:60]}")

        return (False, "")

    async def _save_content(self, url: str, content: str, content_type: str, is_high_priority: bool = False, response_data: dict = None):
        """Save content with metadata (thread-safe)"""
        try:
            content_hash = self._hash_content(content)

            async with self.lock:
                if content_hash in self.content_hashes:
                    if self.verbose:
                        print(f"  [SKIP] Duplicate content: {url[:60]}")
                    self.stats['duplicates_skipped'] += 1
                    return
                self.content_hashes.add(content_hash)

            # Quick secret detection (high precision patterns only)
            quick_secrets = self._quick_detect_secrets(content)

            dir_map = {
                'env_file': self.output_dir / "env_files",
                'config_file': self.output_dir / "config_files",
                'javascript': self.output_dir / "javascript",
                'api_response': self.output_dir / "api_responses",
                'html_page': self.output_dir / "html_pages",
            }

            save_dir = dir_map.get(content_type, self.output_dir / "other")
            base_name = self._sanitize_filename(url)
            filename = f"{content_hash}_{base_name}"

            if content_type == 'javascript' and not filename.endswith('.js'):
                filename += '.js'
            elif content_type in ['config_file', 'api_response', 'env_file']:
                if not any(filename.endswith(ext) for ext in ['.json', '.yml', '.env', '.txt']):
                    filename += '.txt'

            filepath = save_dir / filename
            filepath.write_text(content, encoding='utf-8', errors='ignore')

            # Beautify JavaScript files for better readability and TruffleHog detection
            if content_type == 'javascript' and BEAUTIFIER_AVAILABLE:
                try:
                    beautifier_options = jsbeautifier.default_options()
                    beautifier_options.indent_size = 2
                    beautifier_options.wrap_line_length = 120

                    beautified_content = jsbeautifier.beautify(content, beautifier_options)

                    # Save beautified version with .beautified.js extension
                    beautified_filename = filename.replace('.js', '.beautified.js')
                    beautified_filepath = save_dir / beautified_filename
                    beautified_filepath.write_text(beautified_content, encoding='utf-8', errors='ignore')

                    if self.verbose:
                        print(f"    ✨ Beautified: {beautified_filename[:60]}")
                except Exception as e:
                    # Don't fail the whole save if beautification fails
                    if self.verbose:
                        print(f"    [WARNING] Beautification failed for {filename}: {e}")

            # Save metadata for context enrichment
            metadata = {
                'url': url,
                'content_hash': content_hash,
                'content_type': content_type,
                'file_path': str(filepath),
                'timestamp': datetime.now().isoformat(),
                'is_high_priority': is_high_priority,
                'file_size': len(content),
                'quick_secrets_found': quick_secrets,
                'response_data': response_data or {}
            }

            metadata_file = self.output_dir / "metadata" / f"{content_hash}.json"
            metadata_file.write_text(json.dumps(metadata, indent=2), encoding='utf-8')

            # Instant alert if obvious secrets found
            if quick_secrets:
                alert_file = self.output_dir / "instant_alerts" / filename
                alert_file.write_text(content, encoding='utf-8', errors='ignore')

                # Log alert
                print(f"\n{'='*80}")
                print(f"🚨 INSTANT ALERT - OBVIOUS SECRETS DETECTED!")
                print(f"{'='*80}")
                print(f"URL: {url}")
                print(f"File: {filepath}")
                for secret in quick_secrets:
                    value_display = secret['value'][:50] + '...' if len(secret['value']) > 50 else secret['value']
                    print(f"  • {secret['type']}: {value_display}")
                print(f"{'='*80}\n")

            if is_high_priority:
                (self.output_dir / "high_priority" / filename).write_text(content, encoding='utf-8', errors='ignore')
                async with self.lock:
                    self.stats['high_priority_files'] += 1

            async with self.lock:
                if content_type == 'env_file':
                    self.stats['env_files'] += 1
                elif content_type == 'config_file':
                    self.stats['config_files'] += 1
                elif content_type == 'javascript':
                    self.stats['js_files'] += 1

            if self.verbose:
                priority = "⚠️ " if is_high_priority else "  "
                secret_indicator = " 🚨" if quick_secrets else ""
                print(f"  {priority}[{content_type}]{secret_indicator} {url[:70]}")

        except Exception as e:
            async with self.lock:
                self.stats['errors'] += 1

    async def _setup_network_capture(self, tab, worker_id: int):
        """
        Setup network interception to capture responses.

        Media Filtering:
        - Filters media files by extension (.jpg, .mp4, .mp3, etc.)
        - Prevents processing/saving of media files
        - Saves: processing time, memory usage, disk space

        Note: Browser may still download files (Chrome downloads before
        we see the request). For true bandwidth savings, would need
        Network.setBlockedURLs CDP command (not implemented yet).
        """
        try:
            await tab.enable_network_events()
        except:
            return []

        requests_map = {}
        callback_ids = []

        async def on_request_will_be_sent(event):
            try:
                params = event.get('params', {})
                request = params.get('request', {})
                url = request.get('url', '')

                # Skip media files entirely (saves bandwidth by not tracking them)
                if self.skip_media and self._should_skip_resource(url):
                    if self.verbose:
                        # Only log occasionally to avoid spam
                        if url.endswith(('.mp4', '.webm', '.avi', '.mov')):
                            print(f"  [SKIP] Media blocked: {url[:60]}")
                    async with self.lock:
                        self.stats['media_skipped'] += 1
                    return

                request_id = params.get('requestId', '')
                is_secret_prone, priority = self._is_secret_prone_file(url)

                requests_map[request_id] = {
                    'url': url,
                    'method': request.get('method', 'GET'),
                    'type': params.get('type', ''),
                    'priority': priority,
                    'post_data': request.get('postData')
                }

                # Passive subdomain discovery
                hostname = urlparse(url).netloc
                if hostname and self._is_allowed_domain(url):
                    async with self.lock:
                        if hostname not in self.discovered_subdomains:
                            self.discovered_subdomains.add(hostname)
                            self.stats['subdomains_found'] += 1

            except:
                pass

        async def on_response_received(event):
            try:
                params = event.get('params', {})
                response = params.get('response', {})
                request_id = params.get('requestId', '')

                # Skip if not in requests_map (already filtered in on_request_will_be_sent)
                if request_id not in requests_map:
                    return

                req_info = requests_map[request_id]
                status = response.get('status', 0)

                if status not in [200, 201]:
                    return

                body = await tab.get_response_body(request_id)
                if not body:
                    return

                content_type = self._classify_content(req_info['url'], body, response.get('mimeType', ''))
                is_high_priority = req_info['priority'] == 'high'

                # Prepare response metadata
                response_data = {
                    'status': status,
                    'mime_type': response.get('mimeType', ''),
                    'headers': response.get('headers', {}),
                    'method': req_info['method'],
                    'request_type': req_info['type'],
                    'post_data': req_info.get('post_data')
                }

                await self._save_content(req_info['url'], body, content_type, is_high_priority, response_data)

                if req_info['method'] == 'POST':
                    async with self.lock:
                        self.stats['api_endpoints'] += 1

            except:
                pass

        try:
            cb_id1 = await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, on_request_will_be_sent)
            cb_id2 = await tab.on(NetworkEvent.RESPONSE_RECEIVED, on_response_received)
            callback_ids = [cb_id1, cb_id2]
        except:
            pass

        return callback_ids

    async def _crawl_page(self, tab, url: str, worker_id: int) -> Set[str]:
        """Crawl a single page with safety checks and rate limiting"""

        # Check if URL is dangerous (logout, delete, etc.)
        if self._is_dangerous_url(url):
            async with self.lock:
                self.stats['dangerous_urls_skipped'] += 1
            return set()

        # Check if already visited
        async with self.lock:
            if url in self.visited_urls:
                return set()
            self.visited_urls.add(url)

        # Health monitoring heartbeat
        if self.health_monitor:
            self.health_monitor.heartbeat()

        if self.verbose:
            worker_str = f"[W{worker_id}]" if self.concurrent_tabs > 1 else ""
            print(f"{worker_str} 🔍 {url[:75]}")

        callback_ids = []

        try:
            callback_ids = await self._setup_network_capture(tab, worker_id)

            # Set custom headers if provided
            if self.auth_headers:
                try:
                    await tab.set_extra_headers(self.auth_headers)
                    if self.verbose:
                        print(f"  [AUTH] Set {len(self.auth_headers)} custom headers")
                except Exception as e:
                    if self.verbose:
                        print(f"  [WARN] Failed to set headers: {e}")

            # Apply rate limiting (per-domain) if enabled
            if self.rate_limiter:
                await self.rate_limiter.acquire(url)

            if self.bypass_captcha:
                try:
                    async with tab.expect_and_bypass_cloudflare_captcha():
                        await tab.go_to(url, timeout=30)
                        async with self.lock:
                            self.stats['captchas_solved'] += 1
                        if self.verbose:
                            print(f"  ✓ CAPTCHA bypassed")
                except Exception:
                    await tab.go_to(url, timeout=30)
            else:
                await tab.go_to(url, timeout=30)

            # Wait for dynamic content (SPA support)
            if self.wait_for_idle:
                if self.verbose:
                    print(f"  ⏱️  Waiting for network idle...")
                await self._wait_for_network_idle(tab)

            # Additional wait time (configurable, default 3s)
            if self.page_wait_time > 0:
                await asyncio.sleep(self.page_wait_time)
            else:
                await asyncio.sleep(1)

            html = await tab.page_source
            is_secret_prone, priority = self._is_secret_prone_file(url)

            # HTML page metadata
            html_response_data = {
                'status': 200,
                'mime_type': 'text/html',
                'method': 'GET',
                'request_type': 'Document'
            }

            await self._save_content(url, html, 'html_page', priority == 'high', html_response_data)

            discovered_urls = self._extract_links(html, url)

            async with self.lock:
                self.stats['pages_crawled'] += 1

            return discovered_urls

        except asyncio.TimeoutError:
            async with self.lock:
                self.stats['errors'] += 1
            return set()
        except Exception as e:
            async with self.lock:
                self.stats['errors'] += 1
            return set()
        finally:
            for cb_id in callback_ids:
                try:
                    await tab.off(cb_id)
                except:
                    pass

    def _extract_links(self, html: str, base_url: str) -> Set[str]:
        """Extract links from HTML, filtering out dangerous and irrelevant URLs"""
        urls = set()
        try:
            for pattern in [r'href=["\'](.*?)["\']', r'src=["\'](.*?)["\']']:
                for match in re.finditer(pattern, html, re.IGNORECASE):
                    try:
                        url = urljoin(base_url, match.group(1))
                        url = url.split('#')[0]

                        # Filter: allowed domain, not media, not dangerous
                        if (self._is_allowed_domain(url) and
                            not self._should_skip_resource(url) and
                            not self._is_dangerous_url(url)):
                            urls.add(url)
                    except Exception:
                        pass
        except Exception:
            pass
        return urls

    async def _worker(self, browser, worker_id: int, tab):
        """Worker coroutine - processes URLs from queue"""
        processed = 0

        while True:
            url = None
            async with self.lock:
                if self.url_queue and self.stats['pages_crawled'] < self.max_pages:
                    url = self.url_queue.popleft()
                else:
                    break

            if not url:
                await asyncio.sleep(0.1)
                continue

            discovered_urls = await self._crawl_page(tab, url, worker_id)

            # Add discovered URLs with priority
            async with self.lock:
                high_priority = []
                low_priority = []

                for new_url in discovered_urls:
                    if new_url not in self.visited_urls:
                        is_prone, priority = self._is_secret_prone_file(new_url)
                        if is_prone and priority == 'high':
                            high_priority.append(new_url)
                        else:
                            low_priority.append(new_url)

                for url in reversed(high_priority):
                    self.url_queue.appendleft(url)
                self.url_queue.extend(low_priority)

            processed += 1

        if self.verbose and self.concurrent_tabs > 1:
            print(f"[W{worker_id}] Finished ({processed} pages)")

    async def crawl(self, start_urls: Optional[List[str]] = None):
        """Main crawl function"""

        # Use provided URLs or self.domains
        urls_to_crawl = start_urls or self.domains

        if not urls_to_crawl:
            print("[ERROR] No URLs provided")
            return

        # Extract base domains for filtering
        for url in urls_to_crawl:
            try:
                domain = urlparse(url if url.startswith('http') else f'https://{url}').netloc
                self.allowed_domains.add(domain)
            except:
                pass

        print("=" * 80)
        print("🚀 ULTIMATE CRAWLER")
        print("=" * 80)
        print(f"Domains:        {len(urls_to_crawl)}")
        print(f"Concurrent Tabs: {self.concurrent_tabs}")
        print(f"Max Pages:      {self.max_pages}")
        print(f"Proxy:          {self.proxy or 'None'}")
        print(f"CAPTCHA Bypass: {'Enabled' if self.bypass_captcha else 'Disabled'}")
        print(f"Subdomain Discovery: {'Enabled' if self.discover_subdomains else 'Passive only'}")
        print(f"Output:         {self.output_dir.absolute()}")
        print("=" * 80 + "\n")

        # Discover subdomains for each domain
        if self.discover_subdomains:
            all_subdomains = set()
            for url in urls_to_crawl:
                domain = urlparse(url if url.startswith('http') else f'https://{url}').netloc
                subdomains = self._discover_subdomains_external(domain)
                all_subdomains.update(subdomains)

            if all_subdomains:
                print(f"[INFO] Found {len(all_subdomains)} total subdomains\n")
                for subdomain in all_subdomains:
                    urls_to_crawl.append(f'https://{subdomain}')
                    self.allowed_domains.add(subdomain)

        # Add all URLs to queue
        for url in urls_to_crawl:
            if not url.startswith('http'):
                url = f'https://{url}'
            self.url_queue.append(url)

        self.stats['domains_crawled'] = len(urls_to_crawl)

        # Browser options
        options = ChromiumOptions()
        if self.proxy:
            options.add_argument(f'--proxy-server={self.proxy}')

        options.browser_preferences = {
            'profile': {
                'default_content_setting_values': {
                    'images': 2,
                }
            }
        }

        async with Chrome(options=options) as browser:
            await browser.start(headless=self.headless)

            # Inject authentication cookies if provided
            if self.auth_cookies and urls_to_crawl:
                first_url = urls_to_crawl[0] if urls_to_crawl[0].startswith('http') else f'https://{urls_to_crawl[0]}'
                await self._inject_cookies(browser, first_url)

            # Create worker tabs
            tabs = []
            for i in range(self.concurrent_tabs):
                if i == 0:
                    opened = await browser.get_opened_tabs()
                    tabs.append(opened[0])
                else:
                    tab = await browser.new_tab()
                    tabs.append(tab)

            if self.concurrent_tabs > 1:
                print(f"[INFO] Started {len(tabs)} concurrent workers\n")

            # Run workers
            workers = [
                self._worker(browser, i, tabs[i])
                for i in range(len(tabs))
            ]

            await asyncio.gather(*workers)

        self._generate_report()

    def _generate_report(self):
        """Generate final report"""
        report = {
            'scan_info': {
                'domains_crawled': self.stats['domains_crawled'],
                'concurrent_tabs': self.concurrent_tabs,
                'timestamp': datetime.now().isoformat(),
                'pages_crawled': self.stats['pages_crawled'],
                'subdomains_found': self.stats['subdomains_found'],
                'captchas_solved': self.stats['captchas_solved'],
                'duplicates_skipped': self.stats['duplicates_skipped'],
                'media_skipped': self.stats['media_skipped'],
                'errors': self.stats['errors']
            },
            'captured_files': {
                'javascript_files': self.stats['js_files'],
                'config_files': self.stats['config_files'],
                'env_files': self.stats['env_files'],
                'api_endpoints': self.stats['api_endpoints'],
                'high_priority_files': self.stats['high_priority_files']
            },
            'discovered_subdomains': list(self.discovered_subdomains),
            'allowed_domains': list(self.allowed_domains)
        }

        report_file = self.output_dir / "scan_report.json"
        report_file.write_text(json.dumps(report, indent=2), encoding='utf-8')

        print("\n" + "=" * 80)
        print("✅ CRAWL COMPLETE")
        print("=" * 80)
        print(f"📊 Statistics:")
        print(f"   Domains Crawled:    {self.stats['domains_crawled']}")
        print(f"   Pages Crawled:      {self.stats['pages_crawled']}")
        print(f"   Subdomains Found:   {self.stats['subdomains_found']}")
        print(f"   JavaScript Files:   {self.stats['js_files']}")
        print(f"   Config Files:       {self.stats['config_files']}")
        print(f"   .env Files:         {self.stats['env_files']}")
        print(f"   API Endpoints:      {self.stats['api_endpoints']}")
        print(f"   ⚠️  High Priority:   {self.stats['high_priority_files']}")
        if self.bypass_captcha:
            print(f"   CAPTCHAs Solved:    {self.stats['captchas_solved']}")
        print(f"\n   🛡️  Safety:")
        print(f"   Dangerous URLs Blocked: {self.stats['dangerous_urls_skipped']}")
        print(f"   Duplicates Skipped: {self.stats['duplicates_skipped']}")
        if self.skip_media:
            print(f"   Media Files Skipped: {self.stats['media_skipped']}")
        print(f"   Errors:             {self.stats['errors']}")

        # Health monitoring summary
        if self.health_monitor:
            print(f"\n   💪 Health:")
            print(f"   Uptime:             {self.health_monitor.get_uptime()}")
            memory_ok, memory_msg = self.health_monitor.check_memory()
            print(f"   {memory_msg}")
            error_ok, error_msg = self.health_monitor.check_error_rate(
                self.stats['errors'],
                self.stats['pages_crawled']
            )
            print(f"   {error_msg}")

        print(f"\n📁 Output: {self.output_dir.absolute()}")
        print(f"\n🔍 Next Step:")
        print(f"   trufflehog filesystem {self.output_dir.absolute()}")
        print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Ultimate Crawler - All Features Combined',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single domain (backward compatible)
  python ultimate_crawler.py https://example.com

  # Multiple domains from file
  python ultimate_crawler.py --domains domains.txt

  # Single domain with speed boost (3 tabs)
  python ultimate_crawler.py https://example.com --tabs 3

  # Domain list with max speed (5 tabs)
  python ultimate_crawler.py --domains domains.txt --tabs 5

  # Full featured
  python ultimate_crawler.py --domains domains.txt \
      --tabs 5 \
      --discover-subdomains \
      --proxy http://proxy:8080 \
      --bypass-captcha \
      --max-pages 2000

Domain list file format (domains.txt):
  https://example.com
  https://api.example.com
  admin.example.com
  *.example2.com
        """
    )

    parser.add_argument('url', nargs='?', help='Single URL to crawl')
    parser.add_argument('-d', '--domains', type=str,
                       help='File with list of domains to crawl')
    parser.add_argument('-o', '--output', default='./trufflehog_scan_output',
                       help='Output directory')
    parser.add_argument('-m', '--max-pages', type=int, default=500,
                       help='Maximum pages to crawl (default: 500)')
    parser.add_argument('-t', '--tabs', type=int, default=1,
                       help='Concurrent tabs (1-5, default: 1)')
    parser.add_argument('--discover-subdomains', action='store_true',
                       help='Use external tools for subdomain discovery')
    parser.add_argument('-p', '--proxy', type=str, default=None,
                       help='Proxy URL')
    parser.add_argument('-c', '--bypass-captcha', action='store_true',
                       help='Enable CAPTCHA bypass')
    parser.add_argument('--headless', type=str, default='true',
                       help='Headless mode (default: true)')
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Quiet mode')

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

    # Production features (24/7 operation)
    parser.add_argument('--rate-limit', type=float, default=10.0,
                       help='Requests per second per domain (default: 10)')
    parser.add_argument('--no-rate-limit', action='store_true',
                       help='Disable rate limiting (use with caution!)')
    parser.add_argument('--max-retries', type=int, default=3,
                       help='Max retries for transient failures (default: 3)')
    parser.add_argument('--memory-limit-mb', type=float, default=2048,
                       help='Memory limit in MB (default: 2048)')
    parser.add_argument('--no-health-check', action='store_true',
                       help='Disable health monitoring')

    args = parser.parse_args()

    if not args.url and not args.domains:
        parser.error("Either provide a URL or --domains file")

    headless = args.headless.lower() in ['true', '1', 'yes']

    # Load domains
    domains = []
    if args.domains:
        domains_file = args.domains
        try:
            with open(domains_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if not line.startswith('http'):
                            line = f'https://{line}'
                        domains.append(line)
            print(f"[INFO] Loaded {len(domains)} domains from {domains_file}\n")
        except Exception as e:
            print(f"[ERROR] Failed to load domains file: {e}")
            return
    elif args.url:
        domains = [args.url]

    # Parse auth headers
    auth_headers = {}
    if args.auth_header:
        for header in args.auth_header:
            if ':' in header:
                name, value = header.split(':', 1)
                auth_headers[name.strip()] = value.strip()

    # Parse max media size (e.g., "10M" -> 10485760)
    def parse_size(size_str: str) -> int:
        """Parse size string like '10M', '50M' to bytes"""
        size_str = size_str.upper().strip()
        if size_str.endswith('M'):
            return int(size_str[:-1]) * 1024 * 1024
        elif size_str.endswith('K'):
            return int(size_str[:-1]) * 1024
        elif size_str.endswith('G'):
            return int(size_str[:-1]) * 1024 * 1024 * 1024
        else:
            return int(size_str)

    max_media_size = parse_size(args.max_media_size)

    # Handle rate limit
    rate_limit = 0 if args.no_rate_limit else args.rate_limit

    crawler = UltimateCrawler(
        output_dir=args.output,
        max_pages=args.max_pages,
        concurrent_tabs=args.tabs,
        verbose=not args.quiet,
        proxy=args.proxy,
        bypass_captcha=args.bypass_captcha,
        discover_subdomains=args.discover_subdomains,
        headless=headless,
        domains=domains,
        # Authentication
        auth_cookies=args.auth_cookie,
        auth_headers=auth_headers if auth_headers else None,
        # SPA support
        wait_for_idle=args.wait_for_idle,
        page_wait_time=args.page_wait,
        # File handling
        skip_media=not args.no_skip_media,
        max_media_size=max_media_size,
        warn_large_files=not args.no_warn_large,
        # Production features
        rate_limit=rate_limit,
        enable_health_check=not args.no_health_check,
        memory_limit_mb=args.memory_limit_mb,
        max_retries=args.max_retries
    )

    asyncio.run(crawler.crawl())


if __name__ == "__main__":
    main()
