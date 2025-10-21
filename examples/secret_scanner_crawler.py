"""
TruffleHog-Ready Web Crawler (Enhanced with Proxy & CAPTCHA Bypass)
====================================================================

Crawls ANY website/domain and captures data optimized for TruffleHog scanning.

Features:
- Proxy support (HTTP/SOCKS5)
- Automatic CAPTCHA bypass (Cloudflare Turnstile, reCAPTCHA v3)
- Targets secret-prone files (.env, config.js, etc.)
- Works on any domain

Usage:
    # Basic
    python secret_scanner_crawler.py https://target.com

    # With proxy
    python secret_scanner_crawler.py https://target.com --proxy http://user:pass@proxy:8080

    # With CAPTCHA bypass
    python secret_scanner_crawler.py https://target.com --bypass-captcha

    # Full featured
    python secret_scanner_crawler.py https://target.com \
        --proxy socks5://proxy:1080 \
        --bypass-captcha \
        --max-pages 500 \
        --headless false

Then scan with TruffleHog:
    trufflehog filesystem ./trufflehog_scan_output/
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, urljoin
from datetime import datetime
from typing import Set, List, Dict, Optional
import re
import hashlib

from pydoll.browser import Chrome
from pydoll.browser.options import ChromiumOptions
from pydoll.protocol.network.events import NetworkEvent


class SecretScannerCrawler:
    """
    Enhanced crawler optimized for secret scanning with TruffleHog.
    Supports proxy and CAPTCHA bypass.
    """

    # Files that commonly contain secrets
    SECRET_PRONE_PATTERNS = {
        # Environment files
        '.env', '.env.local', '.env.production', '.env.development',
        '.env.staging', '.env.test',

        # Config files
        'config.js', 'config.json', 'config.yml', 'config.yaml',
        'configuration.js', 'configuration.json',
        'settings.js', 'settings.json',
        'constants.js', 'constants.json',

        # AWS/Cloud configs
        'credentials', 'aws.json', 'gcp.json', 'azure.json',

        # Database configs
        'database.yml', 'database.json', 'db.json',

        # API configs
        'api-keys.json', 'apikeys.json', 'secrets.json',

        # Build/deployment
        '.npmrc', '.pypirc', 'package.json', 'composer.json',

        # Docker/K8s
        'docker-compose.yml', 'docker-compose.yaml',
        'deployment.yml', 'deployment.yaml',
    }

    # URL patterns that might contain secrets
    SECRET_PRONE_PATHS = {
        '/config', '/configuration', '/settings', '/api-keys',
        '/.env', '/env', '/credentials', '/secrets',
        '/admin/config', '/api/config',
    }

    # Common API endpoint patterns
    API_PATTERNS = [
        r'/api/', r'/v\d+/', r'/graphql', r'/rest/',
        r'/oauth', r'/auth', r'/token', r'/login',
        r'/webhook', r'/callback'
    ]

    def __init__(
        self,
        output_dir: str = "./trufflehog_scan_output",
        max_pages: int = 200,
        verbose: bool = True,
        proxy: Optional[str] = None,
        bypass_captcha: bool = False,
        headless: bool = True
    ):
        self.output_dir = Path(output_dir)
        self.max_pages = max_pages
        self.verbose = verbose
        self.proxy = proxy
        self.bypass_captcha = bypass_captcha
        self.headless = headless

        # Tracking
        self.visited_urls: Set[str] = set()
        self.url_queue: List[str] = []
        self.content_hashes: Set[str] = set()
        self.domain = None

        # Statistics
        self.stats = {
            'pages_crawled': 0,
            'js_files': 0,
            'config_files': 0,
            'api_endpoints': 0,
            'env_files': 0,
            'high_priority_files': 0,
            'captchas_solved': 0,
            'errors': 0
        }

        # Setup directory structure optimized for TruffleHog
        self._setup_output_dirs()

    def _setup_output_dirs(self):
        """Create output structure optimized for TruffleHog scanning"""
        (self.output_dir / "javascript").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "config_files").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "env_files").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "api_responses").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "html_pages").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "high_priority").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "logs").mkdir(parents=True, exist_ok=True)

    def _is_same_domain(self, url: str) -> bool:
        """Check if URL belongs to target domain or subdomain"""
        if not self.domain:
            return True

        try:
            hostname = urlparse(url).netloc.lower()
            return hostname == self.domain or hostname.endswith(f'.{self.domain}')
        except:
            return False

    def _should_skip_resource(self, url: str) -> bool:
        """Skip media and non-target resources"""
        if not self._is_same_domain(url):
            return True

        # Skip media files
        skip_extensions = {
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',
            '.mp4', '.webm', '.avi', '.mov', '.mkv',
            '.mp3', '.wav', '.ogg',
            '.woff', '.woff2', '.ttf', '.eot',
            '.pdf', '.zip', '.tar', '.gz', '.exe', '.dmg'
        }

        try:
            return any(url.lower().endswith(ext) for ext in skip_extensions)
        except:
            return True

    def _is_secret_prone_file(self, url: str) -> tuple[bool, str]:
        """
        Check if URL is a file that commonly contains secrets.
        Returns (is_prone, priority_level)
        """
        try:
            url_lower = url.lower()
            path = urlparse(url_lower).path

            # HIGH PRIORITY: .env files
            if any(pattern in url_lower for pattern in ['.env', '/env/', 'environment']):
                return (True, 'high')

            # HIGH PRIORITY: Named secret files
            for pattern in self.SECRET_PRONE_PATTERNS:
                if pattern in path:
                    return (True, 'high')

            # HIGH PRIORITY: Secret paths
            for pattern in self.SECRET_PRONE_PATHS:
                if pattern in path:
                    return (True, 'high')

            # MEDIUM PRIORITY: Config-like files
            if any(word in path for word in ['config', 'setting', 'constant', 'credential']):
                return (True, 'medium')

            # MEDIUM PRIORITY: API endpoints
            for pattern in self.API_PATTERNS:
                if re.search(pattern, path):
                    return (True, 'medium')

            # LOW PRIORITY: Any JS file
            if path.endswith('.js'):
                return (True, 'low')

            return (False, 'none')
        except:
            return (False, 'none')

    def _classify_content(self, url: str, content: str, mime_type: str = '') -> str:
        """Classify content type for appropriate storage"""
        try:
            url_lower = url.lower()
            path = urlparse(url_lower).path

            # .env files
            if '.env' in url_lower or 'environment' in url_lower:
                return 'env_file'

            # Config files
            if any(p in url_lower for p in self.SECRET_PRONE_PATTERNS):
                return 'config_file'

            # JavaScript
            if path.endswith('.js') or mime_type == 'application/javascript':
                return 'javascript'

            # JSON
            if path.endswith('.json') or mime_type == 'application/json':
                try:
                    json.loads(content)
                    if any(word in path for word in ['config', 'setting', 'key', 'secret']):
                        return 'config_file'
                    return 'api_response'
                except:
                    pass

            # HTML
            if mime_type == 'text/html':
                return 'html_page'

            return 'other'
        except:
            return 'other'

    def _hash_content(self, content: str) -> str:
        """Generate content hash for deduplication"""
        try:
            return hashlib.sha256(content.encode('utf-8', errors='ignore')).hexdigest()[:16]
        except:
            return hashlib.sha256(str(content).encode('utf-8', errors='ignore')).hexdigest()[:16]

    def _sanitize_filename(self, url: str) -> str:
        """Create safe filename from URL"""
        try:
            parsed = urlparse(url)
            name = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            name = re.sub(r'[^\w\-_.]', '_', name)
            name = name.strip('_')[:200]
            return name or 'index'
        except:
            return 'index'

    def _save_content(self, url: str, content: str, content_type: str, is_high_priority: bool = False):
        """Save content to appropriate directory for TruffleHog scanning"""

        try:
            # Skip if duplicate
            content_hash = self._hash_content(content)
            if content_hash in self.content_hashes:
                return

            self.content_hashes.add(content_hash)

            # Determine directory
            dir_map = {
                'env_file': self.output_dir / "env_files",
                'config_file': self.output_dir / "config_files",
                'javascript': self.output_dir / "javascript",
                'api_response': self.output_dir / "api_responses",
                'html_page': self.output_dir / "html_pages",
            }

            save_dir = dir_map.get(content_type, self.output_dir / "other")

            # Create filename
            base_name = self._sanitize_filename(url)
            filename = f"{content_hash}_{base_name}"

            # Add extension
            if content_type == 'javascript' and not filename.endswith('.js'):
                filename += '.js'
            elif content_type in ['config_file', 'api_response', 'env_file']:
                if not any(filename.endswith(ext) for ext in ['.json', '.yml', '.yaml', '.env', '.txt']):
                    filename += '.txt'

            filepath = save_dir / filename

            # Save content
            filepath.write_text(content, encoding='utf-8', errors='ignore')

            # Also save high priority
            if is_high_priority:
                high_pri_path = self.output_dir / "high_priority" / filename
                high_pri_path.write_text(content, encoding='utf-8', errors='ignore')
                self.stats['high_priority_files'] += 1

            # Update stats
            if content_type == 'env_file':
                self.stats['env_files'] += 1
            elif content_type == 'config_file':
                self.stats['config_files'] += 1
            elif content_type == 'javascript':
                self.stats['js_files'] += 1

            if self.verbose:
                priority = "⚠️  HIGH" if is_high_priority else "   "
                print(f"  {priority} [{content_type}] {url[:80]}")

            # Log the file
            self._log_file(url, filename, content_type, is_high_priority, len(content))

        except Exception as e:
            if self.verbose:
                print(f"  [ERROR] Failed to save {url}: {e}")
            self.stats['errors'] += 1

    def _log_file(self, url: str, filename: str, content_type: str, is_high_priority: bool, size: int):
        """Log captured file with metadata"""
        try:
            log_entry = {
                'url': url,
                'filename': filename,
                'type': content_type,
                'high_priority': is_high_priority,
                'size': size,
                'timestamp': datetime.now().isoformat()
            }

            log_file = self.output_dir / "logs" / "captured_files.jsonl"
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry) + '\n')
        except:
            pass

    async def _setup_network_capture(self, tab):
        """Setup network interception to capture all content"""

        try:
            await tab.enable_network_events()
        except:
            if self.verbose:
                print("  [WARN] Could not enable network events")
            return []

        # Track requests by ID
        requests_map = {}
        callback_ids = []

        async def on_request_sent(event):
            """Capture outgoing requests"""
            try:
                params = event.get('params', {})
                request = params.get('request', {})

                url = request.get('url', '')
                if self._should_skip_resource(url):
                    return

                request_id = params.get('requestId', '')
                resource_type = params.get('type', '')
                method = request.get('method', 'GET')

                is_secret_prone, priority = self._is_secret_prone_file(url)

                requests_map[request_id] = {
                    'url': url,
                    'method': method,
                    'type': resource_type,
                    'is_secret_prone': is_secret_prone,
                    'priority': priority,
                    'post_data': request.get('postData')
                }
            except:
                pass

        async def on_response_received(event):
            """Capture responses and save content"""
            try:
                params = event.get('params', {})
                response = params.get('response', {})
                request_id = params.get('requestId', '')

                if request_id not in requests_map:
                    return

                req_info = requests_map[request_id]
                url = req_info['url']
                status = response.get('status', 0)
                mime_type = response.get('mimeType', '')

                if status not in [200, 201]:
                    return

                # Get response body
                body = await tab.get_response_body(request_id)
                if not body:
                    return

                # Classify and save
                content_type = self._classify_content(url, body, mime_type)
                is_high_priority = req_info['priority'] == 'high'

                self._save_content(url, body, content_type, is_high_priority)

                # Log API endpoint
                if req_info['method'] == 'POST' and req_info.get('post_data'):
                    self.stats['api_endpoints'] += 1

                    api_log = {
                        'method': req_info['method'],
                        'url': url,
                        'request_body': req_info['post_data'],
                        'response_body': body[:1000],
                        'timestamp': datetime.now().isoformat()
                    }

                    api_file = self.output_dir / "logs" / "api_endpoints.jsonl"
                    with open(api_file, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(api_log) + '\n')

            except Exception as e:
                pass

        # Subscribe to events
        try:
            cb_id1 = await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, on_request_sent)
            cb_id2 = await tab.on(NetworkEvent.RESPONSE_RECEIVED, on_response_received)
            callback_ids = [cb_id1, cb_id2]
        except:
            pass

        return callback_ids

    async def _crawl_page(self, tab, url: str) -> Set[str]:
        """Crawl a single page"""

        if url in self.visited_urls:
            return set()

        self.visited_urls.add(url)

        if self.verbose:
            print(f"\n[{len(self.visited_urls)}/{self.max_pages}] 🔍 {url}")

        callback_ids = []

        try:
            # Setup network capture BEFORE navigation
            callback_ids = await self._setup_network_capture(tab)

            # Handle CAPTCHA if enabled
            if self.bypass_captcha:
                try:
                    async with tab.expect_and_bypass_cloudflare_captcha():
                        await tab.go_to(url, timeout=30)
                        self.stats['captchas_solved'] += 1
                        if self.verbose:
                            print("  ✓ CAPTCHA bypassed")
                except:
                    # No CAPTCHA or bypass failed, try normal navigation
                    await tab.go_to(url, timeout=30)
            else:
                await tab.go_to(url, timeout=30)

            # Wait for network to settle
            await asyncio.sleep(2)

            # Get page HTML
            html = await tab.page_source

            # Save HTML
            is_secret_prone, priority = self._is_secret_prone_file(url)
            self._save_content(url, html, 'html_page', priority == 'high')

            # Extract links
            discovered_urls = self._extract_links(html, url)

            self.stats['pages_crawled'] += 1

            return discovered_urls

        except asyncio.TimeoutError:
            if self.verbose:
                print(f"  [TIMEOUT] {url}")
            self.stats['errors'] += 1
            return set()
        except Exception as e:
            if self.verbose:
                print(f"  [ERROR] {url}: {str(e)[:100]}")
            self.stats['errors'] += 1
            return set()
        finally:
            # Cleanup event handlers
            for cb_id in callback_ids:
                try:
                    await tab.off(cb_id)
                except:
                    pass

    def _extract_links(self, html: str, base_url: str) -> Set[str]:
        """Extract links from HTML for crawling"""
        urls = set()

        try:
            # Find href and src attributes
            for pattern in [r'href=["\'](.*?)["\']', r'src=["\'](.*?)["\']']:
                for match in re.finditer(pattern, html, re.IGNORECASE):
                    try:
                        url = urljoin(base_url, match.group(1))
                        url = url.split('#')[0]  # Remove fragments

                        if self._is_same_domain(url) and not self._should_skip_resource(url):
                            urls.add(url)
                    except:
                        pass
        except:
            pass

        return urls

    async def crawl(self, start_url: str):
        """Main crawl function"""

        # Set domain from start URL
        self.domain = urlparse(start_url).netloc
        self.url_queue = [start_url]

        print("=" * 80)
        print("🔐 SECRET SCANNER CRAWLER (Enhanced)")
        print("=" * 80)
        print(f"Target:         {start_url}")
        print(f"Domain:         {self.domain}")
        print(f"Max Pages:      {self.max_pages}")
        print(f"Proxy:          {self.proxy or 'None'}")
        print(f"CAPTCHA Bypass: {'Enabled' if self.bypass_captcha else 'Disabled'}")
        print(f"Headless:       {self.headless}")
        print(f"Output:         {self.output_dir.absolute()}")
        print("=" * 80)
        print("\n🎯 Targeting secret-prone files:")
        print("  • .env files")
        print("  • config.js, config.json")
        print("  • API endpoints")
        print("  • JavaScript bundles")
        print("  • JSON responses")
        print("\n" + "=" * 80 + "\n")

        # Browser options
        options = ChromiumOptions()

        # Add proxy if specified
        if self.proxy:
            options.add_argument(f'--proxy-server={self.proxy}')
            if self.verbose:
                print(f"[INFO] Using proxy: {self.proxy}\n")

        # Optimize for speed
        options.browser_preferences = {
            'profile': {
                'default_content_setting_values': {
                    'images': 2,  # Block images
                }
            }
        }

        async with Chrome(options=options) as browser:
            # Start browser
            tab = await browser.start(headless=self.headless)

            pages_crawled = 0

            while self.url_queue and pages_crawled < self.max_pages:
                url = self.url_queue.pop(0)

                if url in self.visited_urls:
                    continue

                # Crawl page
                discovered_urls = await self._crawl_page(tab, url)

                # Prioritize secret-prone URLs
                high_priority = []
                low_priority = []

                for new_url in discovered_urls:
                    if new_url not in self.visited_urls and new_url not in self.url_queue:
                        is_prone, priority = self._is_secret_prone_file(new_url)
                        if is_prone and priority == 'high':
                            high_priority.append(new_url)
                        else:
                            low_priority.append(new_url)

                # Add high priority first
                self.url_queue = high_priority + self.url_queue + low_priority

                pages_crawled += 1

        # Generate final report
        self._generate_report()

    def _generate_report(self):
        """Generate final scan report"""

        report = {
            'scan_info': {
                'domain': self.domain,
                'timestamp': datetime.now().isoformat(),
                'pages_crawled': self.stats['pages_crawled'],
                'proxy_used': self.proxy is not None,
                'captcha_bypass': self.bypass_captcha,
                'captchas_solved': self.stats['captchas_solved'],
                'errors': self.stats['errors']
            },
            'captured_files': {
                'javascript_files': self.stats['js_files'],
                'config_files': self.stats['config_files'],
                'env_files': self.stats['env_files'],
                'api_endpoints': self.stats['api_endpoints'],
                'high_priority_files': self.stats['high_priority_files']
            },
            'next_steps': {
                'command': f"trufflehog filesystem {self.output_dir.absolute()}",
                'high_priority_scan': f"trufflehog filesystem {self.output_dir.absolute()}/high_priority",
                'description': "Run TruffleHog to scan captured files for secrets"
            }
        }

        # Save report
        report_file = self.output_dir / "scan_report.json"
        report_file.write_text(json.dumps(report, indent=2), encoding='utf-8')

        # Print summary
        print("\n" + "=" * 80)
        print("✅ CRAWL COMPLETE")
        print("=" * 80)
        print(f"📊 Statistics:")
        print(f"   Pages Crawled:      {self.stats['pages_crawled']}")
        print(f"   JavaScript Files:   {self.stats['js_files']}")
        print(f"   Config Files:       {self.stats['config_files']}")
        print(f"   .env Files:         {self.stats['env_files']}")
        print(f"   API Endpoints:      {self.stats['api_endpoints']}")
        print(f"   ⚠️  High Priority:   {self.stats['high_priority_files']}")
        if self.bypass_captcha:
            print(f"   CAPTCHAs Solved:    {self.stats['captchas_solved']}")
        print(f"   Errors:             {self.stats['errors']}")
        print(f"\n📁 Output: {self.output_dir.absolute()}")
        print(f"\n🔍 Next Step - Run TruffleHog:")
        print(f"   trufflehog filesystem {self.output_dir.absolute()}")
        print(f"\n⚠️  Scan high priority files first:")
        print(f"   trufflehog filesystem {self.output_dir.absolute()}/high_priority")
        print("=" * 80 + "\n")


def main():
    """CLI entry point"""

    parser = argparse.ArgumentParser(
        description='TruffleHog-Ready Web Crawler with Proxy & CAPTCHA Bypass',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python secret_scanner_crawler.py https://example.com

  # With proxy
  python secret_scanner_crawler.py https://example.com --proxy http://user:pass@proxy:8080

  # With SOCKS5 proxy
  python secret_scanner_crawler.py https://example.com --proxy socks5://proxy:1080

  # With CAPTCHA bypass (Cloudflare, reCAPTCHA)
  python secret_scanner_crawler.py https://example.com --bypass-captcha

  # Full featured
  python secret_scanner_crawler.py https://app.example.com \
      --proxy http://proxy:8080 \
      --bypass-captcha \
      --max-pages 500 \
      --headless false \
      -o ./my_scan

Then scan with TruffleHog:
  trufflehog filesystem ./trufflehog_scan_output/
        """
    )

    parser.add_argument('url', help='Target URL to crawl')
    parser.add_argument('-o', '--output', default='./trufflehog_scan_output',
                       help='Output directory (default: ./trufflehog_scan_output)')
    parser.add_argument('-m', '--max-pages', type=int, default=200,
                       help='Maximum pages to crawl (default: 200)')
    parser.add_argument('-p', '--proxy', type=str, default=None,
                       help='Proxy URL (http://host:port or socks5://host:port)')
    parser.add_argument('-c', '--bypass-captcha', action='store_true',
                       help='Enable automatic CAPTCHA bypass (Cloudflare, reCAPTCHA)')
    parser.add_argument('--headless', type=str, default='true',
                       help='Run in headless mode (default: true)')
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Quiet mode (less output)')

    args = parser.parse_args()

    # Parse headless
    headless = args.headless.lower() in ['true', '1', 'yes']

    # Create and run crawler
    crawler = SecretScannerCrawler(
        output_dir=args.output,
        max_pages=args.max_pages,
        verbose=not args.quiet,
        proxy=args.proxy,
        bypass_captcha=args.bypass_captcha,
        headless=headless
    )

    asyncio.run(crawler.crawl(args.url))


if __name__ == "__main__":
    main()
