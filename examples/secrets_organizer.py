#!/usr/bin/env python3
"""
Secrets Organizer - TruffleHog Results Enrichment
=================================================

Enriches TruffleHog JSON output with crawler metadata and organizes
secrets by service type for easy bulk usage.

Usage:
    python secrets_organizer.py trufflehog_results.json

Output Structure:
    secrets_found/
    ├── aws/
    │   ├── keys.txt              # Bulk format: access_key:secret_key
    │   ├── details.json          # Full metadata per key
    │   └── urls.txt              # Source URLs
    ├── github/
    │   ├── tokens.txt
    │   ├── details.json
    │   └── urls.txt
    ├── stripe/
    ├── slack/
    ├── google/
    ├── openai/
    ├── private_keys/
    └── summary.json
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set
from datetime import datetime


class SecretsOrganizer:
    """Organize TruffleHog results by service type with metadata enrichment"""

    # Map TruffleHog detector names to friendly service names
    DETECTOR_MAP = {
        'AWS': 'aws',
        'GitHub': 'github',
        'Stripe': 'stripe',
        'Slack': 'slack',
        'Google': 'google',
        'OpenAI': 'openai',
        'Twilio': 'twilio',
        'SendGrid': 'sendgrid',
        'Mailgun': 'mailgun',
        'JWT': 'jwt',
        'PrivateKey': 'private_keys',
        'RSAPrivateKey': 'private_keys',
        'SSHPrivateKey': 'private_keys',
    }

    def __init__(self, trufflehog_results_file: str, metadata_dir: str = None, output_dir: str = "./secrets_found"):
        self.trufflehog_file = Path(trufflehog_results_file)
        self.metadata_dir = Path(metadata_dir) if metadata_dir else Path("trufflehog_scan_output/metadata")
        self.output_dir = Path(output_dir)

        # Load metadata cache
        self.metadata_cache = self._load_metadata_cache()

        # Results by service
        self.secrets_by_service = defaultdict(list)
        self.stats = {
            'total_secrets': 0,
            'verified_secrets': 0,
            'unverified_secrets': 0,
            'by_service': defaultdict(lambda: {'count': 0, 'verified': 0})
        }

    def _load_metadata_cache(self) -> Dict:
        """Load all metadata files for quick lookup"""
        cache = {}

        if not self.metadata_dir.exists():
            print(f"[WARNING] Metadata directory not found: {self.metadata_dir}")
            print("[INFO] Results will not include crawler metadata")
            return cache

        for meta_file in self.metadata_dir.glob("*.json"):
            try:
                with open(meta_file, 'r') as f:
                    metadata = json.load(f)
                    # Index by file path for quick lookup
                    file_path = metadata.get('file_path', '')
                    if file_path:
                        cache[file_path] = metadata
            except:
                pass

        print(f"[INFO] Loaded {len(cache)} metadata files")
        return cache

    def _get_metadata_for_file(self, file_path: str) -> Dict:
        """Get crawler metadata for a file"""
        # Try exact match
        if file_path in self.metadata_cache:
            return self.metadata_cache[file_path]

        # Try filename match (in case paths differ)
        file_path_obj = Path(file_path)
        filename = file_path_obj.name

        for cached_path, metadata in self.metadata_cache.items():
            if Path(cached_path).name == filename:
                return metadata

        return {}

    def _get_service_name(self, detector_type: str) -> str:
        """Map detector type to service name"""
        # Direct mapping
        if detector_type in self.DETECTOR_MAP:
            return self.DETECTOR_MAP[detector_type]

        # Partial matches
        detector_lower = detector_type.lower()
        if 'aws' in detector_lower:
            return 'aws'
        if 'github' in detector_lower:
            return 'github'
        if 'stripe' in detector_lower:
            return 'stripe'
        if 'slack' in detector_lower:
            return 'slack'
        if 'google' in detector_lower:
            return 'google'
        if 'key' in detector_lower and 'private' in detector_lower:
            return 'private_keys'

        # Default to detector name (lowercase, no spaces)
        return detector_type.lower().replace(' ', '_')

    def process_trufflehog_results(self):
        """Process TruffleHog JSON output"""
        print(f"[INFO] Processing TruffleHog results from {self.trufflehog_file}")

        try:
            with open(self.trufflehog_file, 'r') as f:
                # TruffleHog outputs one JSON object per line
                for line in f:
                    if not line.strip():
                        continue

                    try:
                        result = json.loads(line)
                        self._process_secret(result)
                    except json.JSONDecodeError:
                        continue

        except FileNotFoundError:
            print(f"[ERROR] TruffleHog results file not found: {self.trufflehog_file}")
            return

        print(f"[INFO] Processed {self.stats['total_secrets']} secrets")
        print(f"[INFO]   Verified: {self.stats['verified_secrets']}")
        print(f"[INFO]   Unverified: {self.stats['unverified_secrets']}")

    def _process_secret(self, result: Dict):
        """Process a single secret finding"""
        detector_type = result.get('DetectorType', result.get('DetectorName', 'Unknown'))
        service = self._get_service_name(str(detector_type))

        # Extract key information
        raw_secret = result.get('Raw', '')
        redacted = result.get('Redacted', raw_secret)
        verified = result.get('Verified', False)

        # Source information
        source_metadata = result.get('SourceMetadata', {})
        source_data = source_metadata.get('Data', {})

        # Try to get file info from different possible locations
        file_path = ''
        if 'Git' in source_data:
            file_path = source_data['Git'].get('file', '')
        elif 'Filesystem' in source_data:
            file_path = source_data['Filesystem'].get('file', '')
        else:
            # Generic fallback
            for key, value in source_data.items():
                if isinstance(value, dict) and 'file' in value:
                    file_path = value['file']
                    break

        # Get crawler metadata
        crawler_metadata = self._get_metadata_for_file(file_path)

        # Build secret record
        secret_record = {
            'detector_type': detector_type,
            'service': service,
            'raw': raw_secret,
            'redacted': redacted,
            'verified': verified,
            'file_path': file_path,
            'extra_data': result.get('ExtraData', {}),
            'source_metadata': source_metadata,
            'crawler_metadata': crawler_metadata,
            'timestamp': datetime.now().isoformat()
        }

        # Add to service collection
        self.secrets_by_service[service].append(secret_record)

        # Update stats
        self.stats['total_secrets'] += 1
        if verified:
            self.stats['verified_secrets'] += 1
        else:
            self.stats['unverified_secrets'] += 1

        self.stats['by_service'][service]['count'] += 1
        if verified:
            self.stats['by_service'][service]['verified'] += 1

    def organize_and_export(self):
        """Organize secrets by service and export in bulk format"""
        print(f"\n[INFO] Organizing secrets by service type...")

        self.output_dir.mkdir(parents=True, exist_ok=True)

        for service, secrets in self.secrets_by_service.items():
            service_dir = self.output_dir / service
            service_dir.mkdir(exist_ok=True)

            self._export_service_secrets(service, secrets, service_dir)

        # Generate summary
        self._generate_summary()

        print(f"\n[SUCCESS] Secrets organized in: {self.output_dir}")
        print(f"[INFO] Found secrets in {len(self.secrets_by_service)} services")

    def _export_service_secrets(self, service: str, secrets: List[Dict], service_dir: Path):
        """Export secrets for a specific service"""
        print(f"  📁 {service}: {len(secrets)} secrets")

        # Bulk format files
        keys_file = service_dir / "keys.txt"
        urls_file = service_dir / "urls.txt"
        details_file = service_dir / "details.json"

        keys_list = []
        urls_set = set()
        details = {}

        for secret in secrets:
            raw = secret['raw']
            verified_indicator = "[VERIFIED]" if secret['verified'] else "[UNVERIFIED]"

            # Add to bulk keys file
            keys_list.append(f"{verified_indicator} {raw}")

            # Extract URL from crawler metadata
            url = secret['crawler_metadata'].get('url', 'unknown')
            if url != 'unknown':
                urls_set.add(url)

            # Build detailed record
            details[raw[:50]] = {  # Use first 50 chars as key to avoid huge keys
                'full_secret': raw,
                'verified': secret['verified'],
                'detector_type': secret['detector_type'],
                'url': url,
                'file_path': secret['file_path'],
                'extra_data': secret['extra_data'],
                'crawler_context': {
                    'response_code': secret['crawler_metadata'].get('response_data', {}).get('status'),
                    'content_type': secret['crawler_metadata'].get('content_type'),
                    'timestamp': secret['crawler_metadata'].get('timestamp'),
                    'mime_type': secret['crawler_metadata'].get('response_data', {}).get('mime_type'),
                }
            }

        # Write bulk keys
        with open(keys_file, 'w') as f:
            f.write('\n'.join(keys_list))

        # Write URLs
        with open(urls_file, 'w') as f:
            f.write('\n'.join(sorted(urls_set)))

        # Write detailed JSON
        with open(details_file, 'w') as f:
            json.dump(details, f, indent=2)

        print(f"      ✓ {keys_file.name} ({len(keys_list)} keys)")
        print(f"      ✓ {urls_file.name} ({len(urls_set)} unique URLs)")
        print(f"      ✓ {details_file.name}")

    def _generate_summary(self):
        """Generate summary report"""
        summary = {
            'scan_date': datetime.now().isoformat(),
            'total_secrets_found': self.stats['total_secrets'],
            'verified_secrets': self.stats['verified_secrets'],
            'unverified_secrets': self.stats['unverified_secrets'],
            'by_service': {},
            'high_priority_alerts': []
        }

        # Service breakdown
        for service, stats in self.stats['by_service'].items():
            service_dir = self.output_dir / service
            summary['by_service'][service] = {
                'count': stats['count'],
                'verified': stats['verified'],
                'files': [
                    str(service_dir / "keys.txt"),
                    str(service_dir / "details.json")
                ]
            }

            # High priority alerts (verified secrets)
            if stats['verified'] > 0:
                secrets = self.secrets_by_service[service]
                for secret in secrets:
                    if secret['verified']:
                        url = secret['crawler_metadata'].get('url', 'unknown')
                        summary['high_priority_alerts'].append(
                            f"{service.upper()} verified secret found at {url}"
                        )

        # Write summary
        summary_file = self.output_dir / "summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        print(f"\n  📊 Summary: {summary_file}")

        # Print high priority alerts
        if summary['high_priority_alerts']:
            print(f"\n{'='*80}")
            print("🚨 HIGH PRIORITY VERIFIED SECRETS:")
            print('='*80)
            for alert in summary['high_priority_alerts'][:10]:  # Show first 10
                print(f"  • {alert}")
            if len(summary['high_priority_alerts']) > 10:
                print(f"  ... and {len(summary['high_priority_alerts']) - 10} more")
            print('='*80)


def main():
    parser = argparse.ArgumentParser(
        description='Organize TruffleHog results by service type with metadata enrichment',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python secrets_organizer.py trufflehog_results.json

  # Specify custom metadata directory
  python secrets_organizer.py trufflehog_results.json --metadata-dir ./my_crawl/metadata

  # Custom output directory
  python secrets_organizer.py trufflehog_results.json -o ./organized_secrets

Output:
  Creates organized directory structure with bulk export files per service
        """
    )

    parser.add_argument('trufflehog_json', help='TruffleHog JSON results file')
    parser.add_argument('--metadata-dir', '-m',
                       help='Crawler metadata directory (default: trufflehog_scan_output/metadata)')
    parser.add_argument('--output-dir', '-o', default='./secrets_found',
                       help='Output directory for organized secrets (default: ./secrets_found)')

    args = parser.parse_args()

    print("="*80)
    print("Secrets Organizer - TruffleHog Results Enrichment")
    print("="*80)

    organizer = SecretsOrganizer(
        args.trufflehog_json,
        args.metadata_dir,
        args.output_dir
    )

    organizer.process_trufflehog_results()
    organizer.organize_and_export()

    print("\n✅ Done!")


if __name__ == '__main__':
    main()
