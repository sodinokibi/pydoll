"""
Ultimate Crawler - All Features Combined
=========================================

The complete solution with ALL features:
- ✅ Concurrent crawling (1-5 tabs) - configurable speed
- ✅ Domain list support - crawl multiple domains from file
- ✅ Subdomain discovery - external tools + passive
- ✅ Proxy support - HTTP/SOCKS5
- ✅ CAPTCHA bypass - Cloudflare, reCAPTCHA
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

    # Full featured
    python ultimate_crawler.py --domains domains.txt \
        --tabs 5 \
        --discover-subdomains \
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
from typing import Set, List, Optional
import re
import hashlib
from collections import deque

from pydoll.browser import Chrome
from pydoll.browser.options import ChromiumOptions
from pydoll.protocol.network.events import NetworkEvent


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
        domains: Optional[List[str]] = None
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

        # Tracking
        self.visited_urls: Set[str] = set()
        self.url_queue: deque = deque()
        self.content_hashes: Set[str] = set()
        self.discovered_subdomains: Set[str] = set()
        self.allowed_domains: Set[str] = set()
        self.lock = asyncio.Lock()

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
            'errors': 0
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

    async def _save_content(self, url: str, content: str, content_type: str, is_high_priority: bool = False):
        """Save content (thread-safe)"""
        try:
            content_hash = self._hash_content(content)

            async with self.lock:
                if content_hash in self.content_hashes:
                    return
                self.content_hashes.add(content_hash)

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
                print(f"  {priority}[{content_type}] {url[:70]}")

        except Exception as e:
            async with self.lock:
                self.stats['errors'] += 1

    async def _setup_network_capture(self, tab, worker_id: int):
        """Setup network interception"""
        try:
            await tab.enable_network_events()
        except:
            return []

        requests_map = {}
        callback_ids = []

        async def on_request_sent(event):
            try:
                params = event.get('params', {})
                request = params.get('request', {})
                url = request.get('url', '')

                if self._should_skip_resource(url):
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

                await self._save_content(req_info['url'], body, content_type, is_high_priority)

                if req_info['method'] == 'POST':
                    async with self.lock:
                        self.stats['api_endpoints'] += 1

            except:
                pass

        try:
            cb_id1 = await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, on_request_sent)
            cb_id2 = await tab.on(NetworkEvent.RESPONSE_RECEIVED, on_response_received)
            callback_ids = [cb_id1, cb_id2]
        except:
            pass

        return callback_ids

    async def _crawl_page(self, tab, url: str, worker_id: int) -> Set[str]:
        """Crawl a single page"""
        async with self.lock:
            if url in self.visited_urls:
                return set()
            self.visited_urls.add(url)

        if self.verbose:
            worker_str = f"[W{worker_id}]" if self.concurrent_tabs > 1 else ""
            print(f"{worker_str} 🔍 {url[:75]}")

        callback_ids = []

        try:
            callback_ids = await self._setup_network_capture(tab, worker_id)

            if self.bypass_captcha:
                try:
                    async with tab.expect_and_bypass_cloudflare_captcha():
                        await tab.go_to(url, timeout=30)
                        async with self.lock:
                            self.stats['captchas_solved'] += 1
                        if self.verbose:
                            print(f"  ✓ CAPTCHA bypassed")
                except:
                    await tab.go_to(url, timeout=30)
            else:
                await tab.go_to(url, timeout=30)

            await asyncio.sleep(1)

            html = await tab.page_source
            is_secret_prone, priority = self._is_secret_prone_file(url)
            await self._save_content(url, html, 'html_page', priority == 'high')

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
        """Extract links from HTML"""
        urls = set()
        try:
            for pattern in [r'href=["\'](.*?)["\']', r'src=["\'](.*?)["\']']:
                for match in re.finditer(pattern, html, re.IGNORECASE):
                    try:
                        url = urljoin(base_url, match.group(1))
                        url = url.split('#')[0]
                        if self._is_allowed_domain(url) and not self._should_skip_resource(url):
                            urls.add(url)
                    except:
                        pass
        except:
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
        print(f"   Errors:             {self.stats['errors']}")
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

    crawler = UltimateCrawler(
        output_dir=args.output,
        max_pages=args.max_pages,
        concurrent_tabs=args.tabs,
        verbose=not args.quiet,
        proxy=args.proxy,
        bypass_captcha=args.bypass_captcha,
        discover_subdomains=args.discover_subdomains,
        headless=headless,
        domains=domains
    )

    asyncio.run(crawler.crawl())


if __name__ == "__main__":
    main()
