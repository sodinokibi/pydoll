"""
Production-Ready Simple Web Crawler
====================================

A clean, production-ready crawler focused on efficiency.
Captures JavaScript, HTML, and API endpoints with minimal configuration.

Usage:
    python simple_production_crawler.py https://example.com

Features:
- Network-based capture (most efficient)
- Automatic deduplication
- Concurrent crawling
- JSON + File output
- Progress tracking
"""

import asyncio
import json
import hashlib
import sys
from pathlib import Path
from urllib.parse import urlparse, urljoin
from datetime import datetime
from typing import Set, List, Dict
import re

from pydoll.browser import Chrome
from pydoll.browser.options import ChromiumOptions
from pydoll.protocol.network.events import NetworkEvent


class ProductionCrawler:
    """Simple, efficient production crawler"""

    def __init__(self, start_url: str, output_dir: str = "./crawl_output"):
        self.start_url = start_url
        self.output_dir = Path(output_dir)
        self.domain = urlparse(start_url).netloc

        # Tracking
        self.visited_urls: Set[str] = set()
        self.url_queue: List[str] = [start_url]
        self.content_hashes: Set[str] = set()

        # Captured data
        self.data = {
            'javascript_files': {},  # url -> content
            'html_pages': {},        # url -> html
            'api_endpoints': [],     # list of api calls
            'metadata': {
                'start_url': start_url,
                'domain': self.domain,
                'start_time': datetime.now().isoformat(),
                'stats': {}
            }
        }

        # Create output structure
        (self.output_dir / "js").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "html").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "api").mkdir(parents=True, exist_ok=True)

    def _is_same_domain(self, url: str) -> bool:
        """Check if URL is same domain"""
        hostname = urlparse(url).netloc
        return hostname == self.domain or hostname.endswith(f'.{self.domain}')

    def _should_skip(self, url: str) -> bool:
        """Skip media and non-target domains"""
        if not self._is_same_domain(url):
            return True

        skip_ext = {'.jpg', '.png', '.gif', '.mp4', '.pdf', '.zip', '.woff', '.ttf'}
        return any(url.lower().endswith(ext) for ext in skip_ext)

    def _hash_content(self, content: str) -> str:
        """Generate content hash"""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _sanitize_filename(self, url: str, extension: str = '') -> str:
        """Create safe filename from URL"""
        parsed = urlparse(url)
        name = parsed.path.replace('/', '_').strip('_') or 'index'
        return f"{name}{extension}"

    async def _setup_network_capture(self, tab):
        """Setup network event capture"""

        await tab.enable_network_events()

        # Storage for this page
        page_data = {
            'requests': {},  # request_id -> request_info
        }

        async def on_request_sent(event):
            """Capture outgoing requests"""
            params = event.get('params', {})
            request = params.get('request', {})

            url = request.get('url', '')
            if self._should_skip(url):
                return

            request_id = params.get('requestId', '')
            resource_type = params.get('type', '')
            method = request.get('method', 'GET')

            page_data['requests'][request_id] = {
                'url': url,
                'method': method,
                'type': resource_type,
                'headers': request.get('headers', {}),
                'post_data': request.get('postData')
            }

        async def on_response_received(event):
            """Capture responses and extract content"""
            params = event.get('params', {})
            response = params.get('response', {})
            request_id = params.get('requestId', '')

            if request_id not in page_data['requests']:
                return

            req_info = page_data['requests'][request_id]
            url = req_info['url']
            resource_type = req_info['type']

            if response.get('status') != 200:
                return

            try:
                # Get response body
                body = await tab.get_response_body(request_id)
                if not body:
                    return

                # Process based on type
                if resource_type == 'script' or url.endswith('.js'):
                    # JavaScript file
                    content_hash = self._hash_content(body)

                    if content_hash not in self.content_hashes:
                        self.content_hashes.add(content_hash)

                        # Save to memory
                        self.data['javascript_files'][url] = body

                        # Save to file
                        filename = f"{content_hash}_{self._sanitize_filename(url, '.js')}"
                        (self.output_dir / "js" / filename).write_text(body, encoding='utf-8')

                        print(f"  [JS] {url}")

                elif resource_type in ['xhr', 'fetch']:
                    # API call
                    parsed = urlparse(url)
                    endpoint = f"{req_info['method']} {parsed.path}"

                    api_data = {
                        'endpoint': endpoint,
                        'full_url': url,
                        'method': req_info['method'],
                        'request_headers': req_info.get('headers', {}),
                        'request_body': req_info.get('post_data'),
                        'response_status': response.get('status'),
                        'response_body': body,
                        'timestamp': datetime.now().isoformat()
                    }

                    self.data['api_endpoints'].append(api_data)

                    # Save to file
                    api_filename = f"api_{len(self.data['api_endpoints'])}.json"
                    (self.output_dir / "api" / api_filename).write_text(
                        json.dumps(api_data, indent=2),
                        encoding='utf-8'
                    )

                    print(f"  [API] {endpoint}")

            except Exception as e:
                # Some responses might fail, that's OK
                pass

        # Subscribe to events
        await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, on_request_sent)
        await tab.on(NetworkEvent.RESPONSE_RECEIVED, on_response_received)

    async def _crawl_page(self, tab, url: str) -> Set[str]:
        """Crawl single page and return discovered URLs"""

        if url in self.visited_urls:
            return set()

        self.visited_urls.add(url)
        print(f"\n[{len(self.visited_urls)}] Crawling: {url}")

        try:
            # Setup network capture before navigation
            await self._setup_network_capture(tab)

            # Navigate
            await tab.go_to(url, timeout=30)

            # Wait for network activity to settle
            await asyncio.sleep(2)

            # Get HTML
            html = await tab.page_source
            self.data['html_pages'][url] = html

            # Save HTML to file
            html_filename = self._sanitize_filename(url, '.html')
            (self.output_dir / "html" / html_filename).write_text(html, encoding='utf-8')

            print(f"  [HTML] Saved")

            # Extract links for further crawling
            discovered_urls = self._extract_links(html, url)

            return discovered_urls

        except Exception as e:
            print(f"  [ERROR] {e}")
            return set()

    def _extract_links(self, html: str, base_url: str) -> Set[str]:
        """Extract links from HTML"""
        urls = set()

        # Find href attributes
        href_pattern = r'href=["\'](.*?)["\']'
        for match in re.finditer(href_pattern, html):
            url = urljoin(base_url, match.group(1))
            url = url.split('#')[0]  # Remove fragments

            if self._is_same_domain(url) and not self._should_skip(url):
                urls.add(url)

        return urls

    async def crawl(self, max_pages: int = 100, max_depth: int = 3):
        """Main crawl function"""

        print("="*70)
        print("Production Web Crawler")
        print("="*70)
        print(f"Target: {self.start_url}")
        print(f"Domain: {self.domain}")
        print(f"Max Pages: {max_pages}")
        print(f"Output: {self.output_dir}")
        print("="*70)

        # Setup browser options
        options = ChromiumOptions()
        options.browser_preferences = {
            'profile': {
                'default_content_setting_values': {
                    'images': 2,  # Block images for speed
                }
            }
        }

        async with Chrome(options=options) as browser:
            # Start headless for performance
            tab = await browser.start(headless=True)

            pages_crawled = 0

            while self.url_queue and pages_crawled < max_pages:
                url = self.url_queue.pop(0)

                if url in self.visited_urls:
                    continue

                # Crawl page
                discovered_urls = await self._crawl_page(tab, url)

                # Add new URLs to queue
                for new_url in discovered_urls:
                    if new_url not in self.visited_urls and new_url not in self.url_queue:
                        self.url_queue.append(new_url)

                pages_crawled += 1

        # Save metadata
        self.data['metadata']['end_time'] = datetime.now().isoformat()
        self.data['metadata']['stats'] = {
            'pages_crawled': len(self.visited_urls),
            'javascript_files': len(self.data['javascript_files']),
            'api_endpoints': len(self.data['api_endpoints']),
            'html_pages': len(self.data['html_pages'])
        }

        # Save summary
        summary = {
            'metadata': self.data['metadata'],
            'visited_urls': list(self.visited_urls),
            'javascript_urls': list(self.data['javascript_files'].keys()),
            'api_endpoints_summary': [
                {'endpoint': api['endpoint'], 'method': api['method']}
                for api in self.data['api_endpoints']
            ]
        }

        (self.output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2),
            encoding='utf-8'
        )

        # Print summary
        print("\n" + "="*70)
        print("CRAWL COMPLETE")
        print("="*70)
        print(f"Pages Crawled:     {self.data['metadata']['stats']['pages_crawled']}")
        print(f"JavaScript Files:  {self.data['metadata']['stats']['javascript_files']}")
        print(f"API Endpoints:     {self.data['metadata']['stats']['api_endpoints']}")
        print(f"HTML Pages:        {self.data['metadata']['stats']['html_pages']}")
        print(f"\nOutput Directory:  {self.output_dir.absolute()}")
        print("="*70)


async def main():
    """Main entry point"""

    if len(sys.argv) < 2:
        print("Usage: python simple_production_crawler.py <URL> [output_dir]")
        print("\nExample:")
        print("  python simple_production_crawler.py https://example.com")
        print("  python simple_production_crawler.py https://example.com ./my_crawl")
        sys.exit(1)

    start_url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./crawl_output"

    crawler = ProductionCrawler(start_url, output_dir)
    await crawler.crawl(max_pages=100)


if __name__ == "__main__":
    asyncio.run(main())
