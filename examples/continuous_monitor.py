#!/usr/bin/env python3
"""
Continuous Secret Scanner Monitor
==================================

24/7 monitoring wrapper for ultimate_crawler.py with:
- Automatic cleanup of old results
- Health monitoring and auto-restart
- Configurable scan intervals
- Graceful shutdown handling
- Error recovery and logging

Usage:
    # Run with defaults (scan every hour)
    python3 continuous_monitor.py --domains scope.txt

    # Custom interval and retention
    python3 continuous_monitor.py --domains scope.txt \
        --interval 3600 \
        --retention-days 7 \
        --max-memory-gb 1.5

    # As systemd service
    sudo systemctl start pydoll-monitor
"""

import asyncio
import argparse
import json
import shutil
import signal
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import time

# Import the crawler
from ultimate_crawler import UltimateCrawler


class ContinuousMonitor:
    """
    24/7 continuous monitoring system with automatic cleanup and health checks.
    """

    def __init__(
        self,
        domains: list,
        scan_interval: int = 3600,
        retention_days: int = 7,
        base_output_dir: str = "./scans",
        max_memory_gb: float = 1.5,
        max_consecutive_failures: int = 3,
        **crawler_kwargs
    ):
        self.domains = domains
        self.scan_interval = scan_interval
        self.retention_days = retention_days
        self.base_output_dir = Path(base_output_dir)
        self.max_memory_gb = max_memory_gb
        self.max_consecutive_failures = max_consecutive_failures
        self.crawler_kwargs = crawler_kwargs

        # State
        self.shutdown_requested = False
        self.scan_count = 0
        self.consecutive_failures = 0
        self.total_secrets_found = 0

        # Setup
        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        self._setup_signal_handlers()

        print("=" * 80)
        print("🔄 CONTINUOUS SECRET SCANNER - 24/7 MODE")
        print("=" * 80)
        print(f"Domains:            {len(domains)}")
        print(f"Scan interval:      {scan_interval}s ({scan_interval//60} minutes)")
        print(f"Retention:          {retention_days} days")
        print(f"Memory limit:       {max_memory_gb} GB")
        print(f"Output directory:   {self.base_output_dir.absolute()}")
        print("=" * 80 + "\n")

    def _setup_signal_handlers(self):
        """Setup graceful shutdown handlers"""
        def signal_handler(signum, frame):
            print(f"\n[SIGNAL] Received signal {signum}, initiating graceful shutdown...")
            self.shutdown_requested = True

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def _cleanup_old_scans(self):
        """Delete scan results older than retention_days"""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        deleted_count = 0

        for scan_dir in self.base_output_dir.glob("scan_*"):
            try:
                # Parse timestamp from directory name (scan_20231215_143025)
                timestamp_str = scan_dir.name.replace("scan_", "")
                timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")

                if timestamp < cutoff:
                    print(f"[CLEANUP] Removing old scan: {scan_dir.name}")
                    shutil.rmtree(scan_dir)
                    deleted_count += 1
            except (ValueError, OSError) as e:
                print(f"[WARN] Failed to cleanup {scan_dir.name}: {e}")

        if deleted_count > 0:
            print(f"[CLEANUP] Removed {deleted_count} old scan(s)\n")

    def _get_disk_usage(self) -> dict:
        """Get disk usage statistics"""
        try:
            total_size = 0
            file_count = 0

            for scan_dir in self.base_output_dir.glob("scan_*"):
                for file in scan_dir.rglob("*"):
                    if file.is_file():
                        total_size += file.stat().st_size
                        file_count += 1

            return {
                'total_size_mb': total_size / (1024 * 1024),
                'total_size_gb': total_size / (1024 * 1024 * 1024),
                'file_count': file_count
            }
        except Exception as e:
            return {'error': str(e)}

    def _write_health_status(self, status: dict):
        """Write health status for external monitoring"""
        health_file = self.base_output_dir / "health.json"
        try:
            health_file.write_text(json.dumps(status, indent=2))
        except Exception as e:
            print(f"[WARN] Failed to write health status: {e}")

    async def _run_single_scan(self) -> bool:
        """Run a single scan, return True if successful"""
        scan_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = self.base_output_dir / f"scan_{scan_id}"

        print(f"\n{'='*80}")
        print(f"🔍 SCAN #{self.scan_count + 1} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")

        try:
            # Create crawler instance
            crawler = UltimateCrawler(
                output_dir=str(output_dir),
                domains=self.domains,
                memory_limit_mb=self.max_memory_gb * 1024,
                **self.crawler_kwargs
            )

            # Run scan
            await crawler.crawl()

            # Check if secrets were found
            secrets_file = output_dir / "instant_alerts"
            if secrets_file.exists() and list(secrets_file.iterdir()):
                secrets_count = len(list(secrets_file.iterdir()))
                self.total_secrets_found += secrets_count
                print(f"\n🚨 ALERT: {secrets_count} secrets found in this scan!")
                print(f"🚨 Total secrets found: {self.total_secrets_found}\n")

            # Success
            self.consecutive_failures = 0
            self.scan_count += 1

            return True

        except KeyboardInterrupt:
            raise  # Re-raise to trigger shutdown
        except Exception as e:
            print(f"\n[ERROR] Scan failed: {e}")
            self.consecutive_failures += 1
            return False

    async def run_forever(self):
        """Main loop - runs scans continuously"""
        start_time = datetime.now()

        print(f"[START] Continuous monitoring started at {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"[INFO] Press Ctrl+C to stop gracefully\n")

        while not self.shutdown_requested:
            # Check for too many consecutive failures
            if self.consecutive_failures >= self.max_consecutive_failures:
                print(f"[FATAL] {self.consecutive_failures} consecutive failures, stopping...")
                break

            # Run scan
            success = await self._run_single_scan()

            # Cleanup old scans
            self._cleanup_old_scans()

            # Get disk usage
            disk_usage = self._get_disk_usage()
            if 'total_size_gb' in disk_usage:
                print(f"[INFO] Disk usage: {disk_usage['total_size_gb']:.2f} GB ({disk_usage['file_count']} files)")

            # Write health status
            health_status = {
                'healthy': success and self.consecutive_failures == 0,
                'timestamp': datetime.now().isoformat(),
                'uptime_seconds': (datetime.now() - start_time).total_seconds(),
                'scan_count': self.scan_count,
                'consecutive_failures': self.consecutive_failures,
                'total_secrets_found': self.total_secrets_found,
                'disk_usage_gb': disk_usage.get('total_size_gb', 0)
            }
            self._write_health_status(health_status)

            # Wait for next scan
            if not self.shutdown_requested:
                print(f"\n[WAIT] Next scan in {self.scan_interval//60} minutes...")
                print(f"[INFO] Total scans completed: {self.scan_count}")
                print(f"[INFO] Uptime: {health_status['uptime_seconds']/3600:.1f} hours\n")

                # Sleep in small increments to allow graceful shutdown
                sleep_start = time.time()
                while time.time() - sleep_start < self.scan_interval:
                    if self.shutdown_requested:
                        break
                    await asyncio.sleep(5)

        # Shutdown
        end_time = datetime.now()
        uptime = end_time - start_time
        print(f"\n{'='*80}")
        print("🛑 SHUTTING DOWN")
        print(f"{'='*80}")
        print(f"Total scans:        {self.scan_count}")
        print(f"Total secrets:      {self.total_secrets_found}")
        print(f"Uptime:             {uptime}")
        print(f"{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Continuous Secret Scanner - 24/7 Monitoring',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic monitoring (scan every hour)
  python3 continuous_monitor.py --domains scope.txt

  # Custom interval and retention
  python3 continuous_monitor.py --domains scope.txt \\
      --interval 1800 \\
      --retention-days 14

  # Production setup with rate limiting
  python3 continuous_monitor.py --domains scope.txt \\
      --interval 3600 \\
      --tabs 3 \\
      --rate-limit 8 \\
      --max-pages 500

  # High-frequency monitoring
  python3 continuous_monitor.py --domains scope.txt \\
      --interval 300 \\
      --tabs 5 \\
      --max-pages 200
        """
    )

    # Monitoring configuration
    parser.add_argument('--domains', type=str, required=True,
                       help='File with list of domains to monitor')
    parser.add_argument('--interval', type=int, default=3600,
                       help='Scan interval in seconds (default: 3600 = 1 hour)')
    parser.add_argument('--retention-days', type=int, default=7,
                       help='Keep scan results for N days (default: 7)')
    parser.add_argument('--output-dir', type=str, default='./scans',
                       help='Base output directory for scans')
    parser.add_argument('--max-memory-gb', type=float, default=1.5,
                       help='Memory limit in GB (default: 1.5)')

    # Crawler options
    parser.add_argument('--tabs', type=int, default=3,
                       help='Concurrent tabs (default: 3)')
    parser.add_argument('--max-pages', type=int, default=500,
                       help='Max pages per scan (default: 500)')
    parser.add_argument('--rate-limit', type=float, default=10.0,
                       help='Requests per second per domain (default: 10)')
    parser.add_argument('--wait-for-idle', action='store_true',
                       help='Wait for network idle (for SPAs)')
    parser.add_argument('--auth-cookie', type=str,
                       help='Authentication cookies')
    parser.add_argument('--proxy', type=str,
                       help='Proxy URL')

    args = parser.parse_args()

    # Load domains
    try:
        with open(args.domains, 'r') as f:
            domains = [
                line.strip() for line in f
                if line.strip() and not line.startswith('#')
            ]

        if not domains:
            print(f"[ERROR] No domains found in {args.domains}")
            sys.exit(1)

        print(f"[INFO] Loaded {len(domains)} domains from {args.domains}\n")

    except FileNotFoundError:
        print(f"[ERROR] Domains file not found: {args.domains}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Failed to load domains: {e}")
        sys.exit(1)

    # Create monitor
    monitor = ContinuousMonitor(
        domains=domains,
        scan_interval=args.interval,
        retention_days=args.retention_days,
        base_output_dir=args.output_dir,
        max_memory_gb=args.max_memory_gb,
        # Crawler options
        concurrent_tabs=args.tabs,
        max_pages=args.max_pages,
        rate_limit=args.rate_limit,
        wait_for_idle=args.wait_for_idle,
        auth_cookies=args.auth_cookie,
        proxy=args.proxy,
        verbose=True
    )

    # Run forever
    try:
        asyncio.run(monitor.run_forever())
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
    except Exception as e:
        print(f"\n[FATAL] Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
