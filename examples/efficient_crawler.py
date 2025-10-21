"""
Efficient Website Crawler using Pydoll
========================================

This crawler efficiently captures:
- All JavaScript files
- All HTML pages
- API endpoints and responses (POST/GET)
- Network requests/responses
- Subdomains

Optimizations:
- Network interception (most efficient - captures everything)
- Concurrent crawling
- Smart deduplication
- Resource filtering (skip media)
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Set, Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs
from collections import defaultdict
import hashlib

from pydoll.browser import Chrome
from pydoll.browser.chromium.base import Browser
from pydoll.browser.tab import Tab


class EfficientWebCrawler:
    """
    Most efficient crawler strategy using network interception.
    Captures ALL data including XHR/Fetch API calls without parsing DOM.
    """

    def __init__(
        self,
        output_dir: str = "./crawl_output",
        max_depth: int = 3,
        max_pages: int = 1000,
        concurrent_tabs: int = 5,
        target_domain: Optional[str] = None
    ):
        self.output_dir = Path(output_dir)
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.concurrent_tabs = concurrent_tabs
        self.target_domain = target_domain

        # Data structures
        self.visited_urls: Set[str] = set()
        self.url_queue: List[tuple[str, int]] = []  # (url, depth)
        self.discovered_subdomains: Set[str] = set()

        # Captured data
        self.javascript_files: Dict[str, bytes] = {}
        self.html_pages: Dict[str, str] = {}
        self.api_endpoints: List[Dict] = []
        self.network_log: List[Dict] = []

        # Content deduplication
        self.content_hashes: Set[str] = set()

        # Statistics
        self.stats = {
            'pages_crawled': 0,
            'js_files': 0,
            'api_calls': 0,
            'unique_endpoints': set(),
            'subdomains': set()
        }

        self._setup_output_dirs()

    def _setup_output_dirs(self):
        """Create output directory structure"""
        (self.output_dir / "javascript").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "html").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "api_data").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "network_logs").mkdir(parents=True, exist_ok=True)

    def _get_content_hash(self, content: bytes) -> str:
        """Generate hash for content deduplication"""
        return hashlib.sha256(content).hexdigest()

    def _is_same_domain(self, url: str) -> bool:
        """Check if URL belongs to target domain or subdomain"""
        if not self.target_domain:
            return True

        parsed = urlparse(url)
        hostname = parsed.netloc.lower()

        # Check if it's the same domain or subdomain
        return hostname == self.target_domain or hostname.endswith(f'.{self.target_domain}')

    def _is_media_file(self, url: str) -> bool:
        """Check if URL is a media file we want to skip"""
        media_extensions = {
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',  # Images
            '.mp4', '.webm', '.avi', '.mov', '.mkv',  # Videos
            '.mp3', '.wav', '.ogg', '.m4a',  # Audio
            '.woff', '.woff2', '.ttf', '.eot',  # Fonts
            '.pdf', '.zip', '.tar', '.gz'  # Documents/Archives
        }

        parsed = urlparse(url)
        path = parsed.path.lower()

        return any(path.endswith(ext) for ext in media_extensions)

    def _extract_urls_from_html(self, html: str, base_url: str) -> Set[str]:
        """Extract URLs from HTML content"""
        urls = set()

        # Find href attributes
        href_pattern = r'href=["\'](.*?)["\']'
        for match in re.finditer(href_pattern, html):
            url = urljoin(base_url, match.group(1))
            if self._is_same_domain(url) and not self._is_media_file(url):
                urls.add(url.split('#')[0])  # Remove fragment

        # Find src attributes (for scripts, iframes)
        src_pattern = r'src=["\'](.*?)["\']'
        for match in re.finditer(src_pattern, html):
            url = urljoin(base_url, match.group(1))
            if url.endswith('.js'):
                urls.add(url)

        return urls

    def _classify_request_type(self, url: str, resource_type: str, method: str) -> str:
        """Classify request as API, JS, HTML, or other"""
        parsed = urlparse(url)
        path = parsed.path.lower()

        # API detection
        if resource_type in ['xhr', 'fetch']:
            return 'api'
        if '/api/' in path or '/graphql' in path or path.endswith('.json'):
            return 'api'

        # JavaScript
        if path.endswith('.js') or resource_type == 'script':
            return 'javascript'

        # HTML
        if resource_type == 'document' or path.endswith('.html'):
            return 'html'

        return 'other'

    async def _save_javascript(self, url: str, content: bytes):
        """Save JavaScript file with deduplication"""
        content_hash = self._get_content_hash(content)

        if content_hash in self.content_hashes:
            return  # Already saved

        self.content_hashes.add(content_hash)

        # Create filename from URL
        parsed = urlparse(url)
        filename = parsed.path.replace('/', '_').strip('_') or 'index.js'
        if not filename.endswith('.js'):
            filename += '.js'

        # Add hash to prevent duplicates with same name
        filename = f"{content_hash[:8]}_{filename}"

        filepath = self.output_dir / "javascript" / filename
        filepath.write_bytes(content)

        self.javascript_files[url] = content
        self.stats['js_files'] += 1

    async def _save_html(self, url: str, content: str):
        """Save HTML page"""
        parsed = urlparse(url)
        filename = parsed.path.replace('/', '_').strip('_') or 'index.html'
        if not filename.endswith('.html'):
            filename += '.html'

        filepath = self.output_dir / "html" / filename
        filepath.write_text(content, encoding='utf-8')

        self.html_pages[url] = content

    async def _save_api_response(self, request_data: Dict):
        """Save API request/response data"""
        self.api_endpoints.append(request_data)
        self.stats['api_calls'] += 1

        endpoint = request_data['endpoint']
        self.stats['unique_endpoints'].add(endpoint)

        # Save to file
        timestamp = asyncio.get_event_loop().time()
        filename = f"api_{int(timestamp)}_{len(self.api_endpoints)}.json"
        filepath = self.output_dir / "api_data" / filename

        filepath.write_text(json.dumps(request_data, indent=2), encoding='utf-8')

    async def _setup_network_interception(self, tab: Tab, page_url: str):
        """
        MOST EFFICIENT: Capture all network traffic via interception.
        This captures everything including XHR, Fetch, WebSockets without DOM parsing.
        """

        # Enable network events to capture all requests
        await tab.enable_network_events()

        # Storage for this page's network activity
        page_network_log = []

        async def on_request_will_be_sent(event):
            """Capture all outgoing requests"""
            params = event.get('params', {})
            request = params.get('request', {})

            url = request.get('url', '')
            method = request.get('method', 'GET')
            resource_type = params.get('type', 'other')
            request_id = params.get('requestId', '')

            # Skip media files
            if self._is_media_file(url):
                return

            # Log the request
            request_log = {
                'request_id': request_id,
                'url': url,
                'method': method,
                'resource_type': resource_type,
                'headers': request.get('headers', {}),
                'post_data': request.get('postData', None),
                'timestamp': params.get('timestamp', 0)
            }

            page_network_log.append(request_log)

            # Classify and handle based on type
            req_type = self._classify_request_type(url, resource_type, method)

            if req_type == 'javascript':
                # Will be captured in response
                pass
            elif req_type == 'api':
                # Track API endpoint
                parsed = urlparse(url)
                endpoint = f"{method} {parsed.path}"

                # Parse query parameters
                query_params = parse_qs(parsed.query)

                api_data = {
                    'endpoint': endpoint,
                    'full_url': url,
                    'method': method,
                    'query_params': query_params,
                    'headers': request.get('headers', {}),
                    'post_data': request.get('postData', None),
                    'page_url': page_url,
                    'timestamp': params.get('timestamp', 0)
                }

                # Will add response when available
                request_log['api_data'] = api_data

            # Discover new subdomains
            if self._is_same_domain(url):
                hostname = urlparse(url).netloc
                if hostname not in self.discovered_subdomains:
                    self.discovered_subdomains.add(hostname)
                    self.stats['subdomains'].add(hostname)

        async def on_response_received(event):
            """Capture responses to extract content"""
            params = event.get('params', {})
            response = params.get('response', {})
            request_id = params.get('requestId', '')

            url = response.get('url', '')
            status = response.get('status', 0)
            mime_type = response.get('mimeType', '')

            # Skip non-200 and media
            if status != 200 or self._is_media_file(url):
                return

            # Find matching request
            matching_request = None
            for req in page_network_log:
                if req.get('request_id') == request_id:
                    matching_request = req
                    break

            if not matching_request:
                return

            resource_type = matching_request.get('resource_type', '')
            req_type = self._classify_request_type(url, resource_type, matching_request['method'])

            try:
                # Get response body
                response_body = await tab.get_response_body(request_id)

                if req_type == 'javascript' and response_body:
                    # Save JavaScript file
                    if isinstance(response_body, str):
                        response_body = response_body.encode('utf-8')
                    await self._save_javascript(url, response_body)

                elif req_type == 'api':
                    # Save API response
                    if 'api_data' in matching_request:
                        api_data = matching_request['api_data']
                        api_data['response'] = {
                            'status': status,
                            'headers': response.get('headers', {}),
                            'body': response_body,
                            'mime_type': mime_type
                        }
                        await self._save_api_response(api_data)

            except Exception as e:
                # Some responses might not be available
                pass

        # Subscribe to network events
        from pydoll.protocol.network.events import NetworkEvent
        await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT, on_request_will_be_sent)
        await tab.on(NetworkEvent.RESPONSE_RECEIVED, on_response_received)

        return page_network_log

    async def _crawl_page(self, browser: Browser, url: str, depth: int) -> Set[str]:
        """Crawl a single page and return discovered URLs"""

        if url in self.visited_urls or depth > self.max_depth:
            return set()

        self.visited_urls.add(url)
        print(f"[Depth {depth}] Crawling: {url}")

        try:
            # Create new tab for this page
            tab = await browser.new_tab()

            # Setup network interception BEFORE loading page
            network_log = await self._setup_network_interception(tab, url)

            # Navigate to page
            await tab.go_to(url, timeout=30)

            # Wait for network to settle
            await asyncio.sleep(2)

            # Get page source (HTML)
            html = await tab.page_source
            await self._save_html(url, html)

            # Extract URLs from HTML for further crawling
            discovered_urls = self._extract_urls_from_html(html, url)

            # Save network log for this page
            log_file = self.output_dir / "network_logs" / f"{urlparse(url).path.replace('/', '_')}.json"
            log_file.write_text(json.dumps(network_log, indent=2), encoding='utf-8')

            self.stats['pages_crawled'] += 1

            # Close tab to free resources
            await tab.close()

            return discovered_urls

        except Exception as e:
            print(f"Error crawling {url}: {e}")
            return set()

    async def _worker(self, browser: Browser, worker_id: int):
        """Worker for concurrent crawling"""
        while self.url_queue and self.stats['pages_crawled'] < self.max_pages:
            try:
                url, depth = self.url_queue.pop(0)
            except IndexError:
                break

            if url in self.visited_urls:
                continue

            print(f"[Worker {worker_id}] Processing: {url}")

            discovered_urls = await self._crawl_page(browser, url, depth)

            # Add newly discovered URLs to queue
            for new_url in discovered_urls:
                if new_url not in self.visited_urls:
                    self.url_queue.append((new_url, depth + 1))

    async def crawl(self, start_url: str):
        """Main crawl function with concurrent processing"""

        print(f"\n{'='*60}")
        print(f"Starting Efficient Web Crawler")
        print(f"{'='*60}")
        print(f"Target: {start_url}")
        print(f"Max Depth: {self.max_depth}")
        print(f"Max Pages: {self.max_pages}")
        print(f"Concurrent Tabs: {self.concurrent_tabs}")
        print(f"Output: {self.output_dir}")
        print(f"{'='*60}\n")

        # Set target domain from start URL
        if not self.target_domain:
            self.target_domain = urlparse(start_url).netloc

        # Initialize queue
        self.url_queue.append((start_url, 0))

        async with Chrome() as browser:
            # Start browser
            await browser.start(headless=True)

            # Create concurrent workers
            workers = [
                self._worker(browser, i)
                for i in range(self.concurrent_tabs)
            ]

            # Run all workers concurrently
            await asyncio.gather(*workers)

        # Generate summary report
        self._generate_report()

    def _generate_report(self):
        """Generate crawl summary report"""
        report = {
            'summary': {
                'pages_crawled': self.stats['pages_crawled'],
                'javascript_files': self.stats['js_files'],
                'api_calls': self.stats['api_calls'],
                'unique_endpoints': len(self.stats['unique_endpoints']),
                'subdomains_discovered': len(self.stats['subdomains'])
            },
            'subdomains': list(self.stats['subdomains']),
            'unique_endpoints': list(self.stats['unique_endpoints']),
            'visited_urls': list(self.visited_urls)
        }

        report_file = self.output_dir / "crawl_report.json"
        report_file.write_text(json.dumps(report, indent=2), encoding='utf-8')

        print(f"\n{'='*60}")
        print(f"Crawl Complete!")
        print(f"{'='*60}")
        print(f"Pages Crawled: {report['summary']['pages_crawled']}")
        print(f"JavaScript Files: {report['summary']['javascript_files']}")
        print(f"API Calls Captured: {report['summary']['api_calls']}")
        print(f"Unique Endpoints: {report['summary']['unique_endpoints']}")
        print(f"Subdomains Found: {report['summary']['subdomains_discovered']}")
        print(f"\nOutput directory: {self.output_dir}")
        print(f"{'='*60}\n")


# Example usage
async def main():
    """Example: Crawl a website efficiently"""

    crawler = EfficientWebCrawler(
        output_dir="./crawl_results",
        max_depth=3,
        max_pages=100,
        concurrent_tabs=3,  # 3 tabs crawling simultaneously
        target_domain=None  # Auto-detect from start URL
    )

    await crawler.crawl("https://example.com")


if __name__ == "__main__":
    asyncio.run(main())
