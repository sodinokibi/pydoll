# TruffleHog Secret Scanning Guide

Complete guide for using the crawler with TruffleHog to find leaked API keys and secrets.

---

## Quick Start

### 1. Crawl Target Website

```bash
# Crawl any domain - fully automatic
python secret_scanner_crawler.py https://example.com

# With custom settings
python secret_scanner_crawler.py https://api.example.com \
    --max-pages 500 \
    --output ./my_scan
```

### 2. Scan with TruffleHog

```bash
# Install TruffleHog (if not installed)
brew install trufflesecurity/trufflehog/trufflehog
# or: go install github.com/trufflesecurity/trufflehog/v3@latest

# Scan all captured files
trufflehog filesystem ./trufflehog_scan_output/

# Scan high priority files first (faster)
trufflehog filesystem ./trufflehog_scan_output/high_priority/
```

---

## What Does This Crawler Do?

### ✅ Works on ANY Domain

The crawler is designed to work on **any website** you give it:

- ✅ Single Page Applications (React, Vue, Angular)
- ✅ Traditional multi-page websites
- ✅ API documentation sites
- ✅ Admin panels
- ✅ Subdomains (api.example.com, admin.example.com)
- ✅ Protected sites (after authentication)
- ✅ JavaScript-heavy applications

### 🎯 Targets Secret-Prone Files

The crawler **specifically targets** files that commonly contain secrets:

#### High Priority (scanned first):
- `.env`, `.env.local`, `.env.production`
- `config.js`, `config.json`, `settings.json`
- `credentials`, `api-keys.json`, `secrets.json`
- `database.yml`, `aws.json`, `azure.json`
- Files in `/config`, `/settings`, `/.env` paths

#### Medium Priority:
- All JavaScript files (may have hardcoded keys)
- API endpoints (JSON responses may leak keys)
- Configuration-like files

#### Also Captures:
- HTML pages (may contain embedded secrets)
- JSON API responses
- POST request bodies (may contain keys)

---

## Output Format (TruffleHog Ready)

### Directory Structure

```
trufflehog_scan_output/
├── high_priority/          ⭐ SCAN THIS FIRST
│   ├── abc123_.env
│   ├── def456_config.json
│   └── ghi789_api-keys.json
│
├── env_files/              .env and environment files
├── config_files/           config.js, config.json, etc.
├── javascript/             All JS files
├── api_responses/          JSON API responses
├── html_pages/             HTML pages
│
├── logs/
│   ├── captured_files.jsonl    # All captured files
│   └── api_endpoints.jsonl     # All API endpoints
│
└── scan_report.json        # Summary report
```

### Why This Format?

1. **TruffleHog can scan directly** - All files are saved as plain text
2. **Organized by risk** - High priority files in separate directory
3. **Deduplicated** - No duplicate content (hash-based)
4. **Metadata preserved** - Logs track original URLs and context

---

## File Formats Saved

### 1. JavaScript Files → `.js`

```javascript
// Saved as: abc123_bundle.js
const API_KEY = "sk-1234567890abcdef";  // ← TruffleHog will find this
const config = {
    apiUrl: "https://api.example.com",
    token: "ghp_xxxxxxxxxxxx"           // ← And this
};
```

### 2. Config Files → `.json`, `.yml`, `.txt`

```json
{
  "aws": {
    "accessKeyId": "AKIAIOSFODNN7EXAMPLE",
    "secretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
  }
}
```

### 3. .env Files → `.env`, `.txt`

```bash
# Saved as: def456_.env
DATABASE_URL=postgresql://user:password@localhost/db
API_KEY=sk-1234567890abcdef
AWS_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
```

### 4. API Responses → `.json`, `.txt`

```json
{
  "user": "admin",
  "debug": true,
  "internal_api_key": "secret_key_12345"
}
```

### 5. HTML Pages → `.html`

```html
<!-- Might contain embedded secrets in <script> tags -->
<script>
  window.CONFIG = {
    apiKey: "AIzaSyD-xxxxxxxxxxxxxxxxxxxxx"
  };
</script>
```

---

## Complete Workflow

### Step 1: Crawl Target

```bash
# Crawl your target domain
python secret_scanner_crawler.py https://app.example.com

# Output shows progress:
# [1/200] 🔍 https://app.example.com
#   ⚠️  HIGH [env_file] https://app.example.com/.env
#         [javascript] https://app.example.com/bundle.js
#         [config_file] https://app.example.com/config.json
#         [api_response] https://app.example.com/api/users
```

### Step 2: Quick Scan (High Priority Only)

```bash
# Scan high priority files first (fastest)
trufflehog filesystem ./trufflehog_scan_output/high_priority/

# Output:
# Found verified result
# Detector Type: AWS
# Raw result: AKIAIOSFODNN7EXAMPLE
# File: ./trufflehog_scan_output/high_priority/abc123_config.json
```

### Step 3: Full Scan (All Files)

```bash
# Scan everything
trufflehog filesystem ./trufflehog_scan_output/ --json > findings.json

# With specific detectors
trufflehog filesystem ./trufflehog_scan_output/ \
    --only-verified \
    --json > verified_findings.json
```

### Step 4: Analyze Results

```bash
# Count findings by type
cat findings.json | jq -r '.DetectorName' | sort | uniq -c

# Example output:
#   5 AWS
#   3 GitHub
#   2 Stripe
#   1 OpenAI
```

---

## Advanced Usage

### Scan Specific Subdomains

```bash
# API subdomain
python secret_scanner_crawler.py https://api.example.com \
    --max-pages 1000

# Admin panel
python secret_scanner_crawler.py https://admin.example.com \
    --output ./admin_scan

# Multiple subdomains (parallel)
parallel python secret_scanner_crawler.py {} ::: \
    https://www.example.com \
    https://api.example.com \
    https://admin.example.com
```

### Scan After Authentication

```python
# Modify crawler to login first
async def crawl_authenticated():
    crawler = SecretScannerCrawler()

    async with Chrome() as browser:
        tab = await browser.start()

        # Login first
        await tab.go_to('https://example.com/login')
        await (await tab.find(id='username')).type_text('admin')
        await (await tab.find(id='password')).type_text('password')
        await (await tab.find(tag_name='button', text='Login')).click()

        await asyncio.sleep(2)

        # Now crawl with authenticated session
        await crawler.crawl('https://example.com/dashboard')
```

### Target Specific File Types

```python
# Modify SECRET_PRONE_PATTERNS to add your own
SECRET_PRONE_PATTERNS = {
    '.env', 'config.js', 'config.json',
    # Add custom patterns
    'secrets.yaml', 'credentials.txt',
    'application.properties', 'appsettings.json',
}
```

---

## TruffleHog Command Reference

### Basic Scanning

```bash
# Scan filesystem
trufflehog filesystem /path/to/files

# Scan with JSON output
trufflehog filesystem /path/to/files --json

# Only verified secrets
trufflehog filesystem /path/to/files --only-verified

# Scan with specific detectors
trufflehog filesystem /path/to/files \
    --detectors="aws,github,slack,stripe"
```

### Advanced Options

```bash
# Exclude files
trufflehog filesystem /path/to/files \
    --exclude-paths=exclude.txt

# Custom regex
trufflehog filesystem /path/to/files \
    --regex \
    --rules=/path/to/rules.yaml

# Concurrency
trufflehog filesystem /path/to/files \
    --concurrency=10

# No verification (faster, more false positives)
trufflehog filesystem /path/to/files \
    --no-verification
```

### Output Formats

```bash
# JSON (machine readable)
trufflehog filesystem /path --json > results.json

# Plain text
trufflehog filesystem /path > results.txt

# Filter results
trufflehog filesystem /path --json | \
    jq 'select(.Verified == true)'
```

---

## Common Secrets Detected

TruffleHog detects 700+ secret types including:

### Cloud Providers
- **AWS**: Access Keys, Secret Keys
- **Azure**: Storage Keys, Service Principal
- **GCP**: Service Account Keys, API Keys

### APIs
- **OpenAI**: API Keys
- **Stripe**: Secret Keys, Publishable Keys
- **Twilio**: Account SID, Auth Token
- **SendGrid**: API Keys

### Version Control
- **GitHub**: Personal Access Tokens, OAuth Tokens
- **GitLab**: Personal Access Tokens
- **Bitbucket**: App Passwords

### Databases
- **PostgreSQL**: Connection Strings
- **MongoDB**: Connection Strings
- **MySQL**: Credentials

### Generic Patterns
- **Private Keys**: RSA, SSH, GPG
- **JWT Tokens**
- **API Keys**: Generic patterns
- **Bearer Tokens**

---

## Real-World Examples

### Example 1: E-Commerce Site

```bash
# Crawl
python secret_scanner_crawler.py https://shop.example.com

# Found:
# - Stripe API keys in checkout.js
# - AWS credentials in config.json
# - Database URL in .env file

# Scan
trufflehog filesystem ./trufflehog_scan_output/

# Results:
# ✓ Stripe Secret Key (verified)
# ✓ AWS Access Key (verified)
# ✓ PostgreSQL Connection String
```

### Example 2: API Documentation

```bash
# Crawl API docs
python secret_scanner_crawler.py https://docs.api.example.com

# Found:
# - Example API keys in documentation
# - Test credentials in code samples
# - Internal endpoints in API responses

# Scan
trufflehog filesystem ./trufflehog_scan_output/ --only-verified

# Results:
# ✓ GitHub Personal Access Token (in example)
# ⚠️  Production API key (should be redacted!)
```

### Example 3: Admin Panel

```bash
# Crawl after auth
python secret_scanner_crawler.py https://admin.example.com

# Found:
# - Database credentials in settings page
# - Internal API tokens
# - AWS keys in backup scripts

# Scan
trufflehog filesystem ./trufflehog_scan_output/high_priority/

# Results:
# ✓ AWS Secret Key (production!)
# ✓ Database Password
# ✓ Internal API Token
```

---

## Output Analysis

### Examine Captured Files

```bash
# List all captured files
cat trufflehog_scan_output/logs/captured_files.jsonl | jq -r '.filename'

# High priority files only
cat trufflehog_scan_output/logs/captured_files.jsonl | \
    jq -r 'select(.high_priority == true) | .filename'

# Files by type
cat trufflehog_scan_output/logs/captured_files.jsonl | \
    jq -r '.type' | sort | uniq -c
```

### Examine API Endpoints

```bash
# List all API endpoints
cat trufflehog_scan_output/logs/api_endpoints.jsonl | \
    jq -r '.method + " " + .url'

# POST endpoints (may contain sensitive data)
cat trufflehog_scan_output/logs/api_endpoints.jsonl | \
    jq 'select(.method == "POST")'
```

### Check Scan Report

```bash
# View summary
cat trufflehog_scan_output/scan_report.json | jq

# Example output:
{
  "scan_info": {
    "domain": "example.com",
    "pages_crawled": 150
  },
  "captured_files": {
    "javascript_files": 45,
    "config_files": 12,
    "env_files": 3,
    "api_endpoints": 67,
    "high_priority_files": 15
  }
}
```

---

## Troubleshooting

### No .env Files Found

```bash
# .env files might be:
# 1. Not accessible (403 Forbidden)
# 2. Not linked from any page
# 3. Protected by web server config

# Solution: Try direct URL
python -c "
from pydoll.browser import Chrome
import asyncio

async def check():
    async with Chrome() as browser:
        tab = await browser.start()
        await tab.go_to('https://example.com/.env')
        print(await tab.page_source)

asyncio.run(check())
"
```

### TruffleHog Not Finding Secrets

```bash
# Make sure files are saved correctly
ls -lh trufflehog_scan_output/high_priority/

# Check file content
head trufflehog_scan_output/high_priority/*

# Try scanning with --no-verification (more sensitive)
trufflehog filesystem ./trufflehog_scan_output/ --no-verification
```

### Crawler Timing Out

```python
# Increase timeout
await tab.go_to(url, timeout=60)

# Or skip problematic URLs
if 'slow-site' in url:
    continue
```

---

## Security Best Practices

### ⚠️ Important Notes

1. **Only scan domains you own or have permission to test**
2. **Leaked secrets found should be rotated immediately**
3. **Don't commit scan results to version control**
4. **Store results securely**
5. **Report findings to security team**

### Remediation Steps

When secrets are found:

1. ✅ **Rotate the secret immediately**
2. ✅ **Remove from source code**
3. ✅ **Use environment variables**
4. ✅ **Implement secret management** (AWS Secrets Manager, HashiCorp Vault)
5. ✅ **Set up pre-commit hooks** (prevent future leaks)
6. ✅ **Review git history** (check if committed)

---

## Performance Tips

### Speed Up Crawling

```bash
# Increase concurrent tabs
python secret_scanner_crawler.py https://example.com --tabs 5

# Limit max pages for quick scan
python secret_scanner_crawler.py https://example.com --max-pages 50
```

### Speed Up Scanning

```bash
# Scan high priority only
trufflehog filesystem ./trufflehog_scan_output/high_priority/

# Use specific detectors (faster than all 700+)
trufflehog filesystem /path --detectors="aws,github,stripe"

# Increase concurrency
trufflehog filesystem /path --concurrency=20
```

---

## Automation

### Scheduled Scans

```bash
#!/bin/bash
# daily_scan.sh

# Crawl
python secret_scanner_crawler.py https://app.example.com \
    --output ./scan_$(date +%Y%m%d)

# Scan
trufflehog filesystem ./scan_$(date +%Y%m%d) \
    --json > findings_$(date +%Y%m%d).json

# Alert if findings
if [ -s findings_$(date +%Y%m%d).json ]; then
    echo "Secrets found! Check findings_$(date +%Y%m%d).json"
    # Send alert (email, Slack, etc.)
fi
```

### CI/CD Integration

```yaml
# .github/workflows/secret-scan.yml
name: Secret Scan

on:
  schedule:
    - cron: '0 0 * * *'  # Daily

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          pip install pydoll-python

      - name: Crawl website
        run: |
          python examples/secret_scanner_crawler.py https://example.com

      - name: Scan with TruffleHog
        run: |
          docker run --rm -v "$PWD:/scan" \
            trufflesecurity/trufflehog:latest \
            filesystem /scan/trufflehog_scan_output \
            --json > findings.json

      - name: Upload findings
        uses: actions/upload-artifact@v2
        with:
          name: secret-findings
          path: findings.json
```

---

## Summary

### Complete Command Reference

```bash
# 1. Crawl any domain
python secret_scanner_crawler.py https://example.com

# 2. Quick scan (high priority)
trufflehog filesystem ./trufflehog_scan_output/high_priority/

# 3. Full scan (all files)
trufflehog filesystem ./trufflehog_scan_output/ --json > findings.json

# 4. Analyze results
cat findings.json | jq -r '.DetectorName' | sort | uniq -c
```

### What You Get

- ✅ **Works on ANY domain** - No configuration needed
- ✅ **TruffleHog-ready output** - Scan immediately
- ✅ **Prioritized by risk** - High priority files separated
- ✅ **All file types** - JS, JSON, HTML, env, config
- ✅ **API endpoints captured** - POST/GET with payloads
- ✅ **Deduplicated** - No duplicate content
- ✅ **Detailed logs** - Track what was captured

### Next Steps

1. Run the crawler on your target
2. Scan with TruffleHog
3. Review findings
4. Rotate any leaked secrets
5. Implement preventive measures

---

**Happy hunting! 🔐**
