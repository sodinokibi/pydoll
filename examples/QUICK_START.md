# Quick Start Guide - Secret Scanner Crawler

**Find leaked API keys and secrets in ANY website**

---

## ⚡ Quick Commands

### Basic Scan
```bash
python secret_scanner_crawler.py https://example.com
trufflehog filesystem ./trufflehog_scan_output/
```

### With Proxy
```bash
# HTTP proxy
python secret_scanner_crawler.py https://example.com \
    --proxy http://user:pass@proxy:8080

# SOCKS5 proxy
python secret_scanner_crawler.py https://example.com \
    --proxy socks5://proxy:1080
```

### With CAPTCHA Bypass
```bash
# Bypass Cloudflare Turnstile & reCAPTCHA v3
python secret_scanner_crawler.py https://example.com \
    --bypass-captcha
```

### Full Featured
```bash
python secret_scanner_crawler.py https://example.com \
    --proxy http://proxy:8080 \
    --bypass-captcha \
    --max-pages 500 \
    --headless false \
    -o ./my_scan
```

### One-Command Automation
```bash
./scan_for_secrets.sh https://example.com
```

### Ultimate Crawler (Multi-Domain + Speed)
```bash
# Single domain
python ultimate_crawler.py https://example.com

# Multiple domains from file
python ultimate_crawler.py --domains domains.txt

# Multi-domain with 5 concurrent tabs (5x faster)
python ultimate_crawler.py --domains domains.txt --tabs 5

# Full featured
python ultimate_crawler.py --domains domains.txt \
    --tabs 5 \
    --discover-subdomains \
    --max-pages 1000 \
    --proxy http://proxy:8080 \
    --bypass-captcha
```

---

## 📝 Domain List Format

Create a `domains.txt` file for multi-domain scans:

```
# Lines starting with # are comments
# Domains can be with or without https://

# E-commerce sites
example.com
shop.example.com
https://api.example.com

# SaaS platforms
app.mycompany.com
staging.mycompany.com

# Corporate sites
company.io
www.company.io
```

Then use it:
```bash
python ultimate_crawler.py --domains domains.txt --tabs 5
```

---

## 🎯 What Gets Captured

### High Priority (Scanned First)
- `.env`, `.env.production`, `.env.local`
- `config.json`, `settings.json`, `constants.js`
- `credentials`, `api-keys.json`, `secrets.json`
- `aws.json`, `azure.json`, `database.yml`

### Also Captured
- All JavaScript files (may have hardcoded keys)
- All API endpoints (POST/GET with payloads)
- JSON responses (may leak credentials)
- HTML pages (may contain embedded secrets)

---

## 📁 Output Structure

```
trufflehog_scan_output/
├── high_priority/      ⭐ SCAN THIS FIRST
├── env_files/
├── config_files/
├── javascript/
├── api_responses/
├── html_pages/
└── logs/
    ├── captured_files.jsonl
    └── api_endpoints.jsonl
```

---

## 🔍 Scanning with TruffleHog

### Quick Scan (High Priority Only)
```bash
trufflehog filesystem ./trufflehog_scan_output/high_priority/
```

### Full Scan
```bash
trufflehog filesystem ./trufflehog_scan_output/
```

### Verified Secrets Only
```bash
trufflehog filesystem ./trufflehog_scan_output/ --only-verified
```

### JSON Output
```bash
trufflehog filesystem ./trufflehog_scan_output/ --json > findings.json
```

### Analyze Results
```bash
# Count by type
cat findings.json | jq -r '.DetectorName' | sort | uniq -c

# Show all AWS keys
cat findings.json | jq 'select(.DetectorName == "AWS")'

# Only verified
cat findings.json | jq 'select(.Verified == true)'
```

---

## 🌐 Proxy Support

### Supported Proxy Types
- ✅ HTTP/HTTPS: `http://proxy:8080`
- ✅ SOCKS5: `socks5://proxy:1080`
- ✅ With authentication: `http://user:pass@proxy:8080`

### Examples
```bash
# Simple HTTP proxy
python secret_scanner_crawler.py https://example.com \
    --proxy http://10.0.0.1:8080

# With credentials
python secret_scanner_crawler.py https://example.com \
    --proxy http://admin:secret@proxy.com:8080

# SOCKS5 (Tor, etc.)
python secret_scanner_crawler.py https://example.com \
    --proxy socks5://127.0.0.1:9050
```

---

## 🔐 CAPTCHA Bypass

### Supported CAPTCHAs
- ✅ Cloudflare Turnstile
- ✅ reCAPTCHA v3
- ✅ Custom implementations

### How It Works
Pydoll uses **human-like behavior** to bypass CAPTCHAs:
- Realistic mouse movements
- Natural timing between actions
- Behavioral patterns that fool detection

### Enable CAPTCHA Bypass
```bash
python secret_scanner_crawler.py https://protected-site.com \
    --bypass-captcha
```

### Important Notes
- ⚠️ Requires good IP reputation (not blocked)
- ⚠️ Works best with residential/clean IPs
- ⚠️ May not work with extremely aggressive protection
- ✅ Use with proxies for better success rate

---

## 🛠️ All Options

```bash
python secret_scanner_crawler.py <URL> [OPTIONS]

Required:
  URL                      Target website to crawl

Options:
  -o, --output DIR         Output directory (default: ./trufflehog_scan_output)
  -m, --max-pages N        Maximum pages to crawl (default: 200)
  -p, --proxy URL          Proxy (http://host:port or socks5://host:port)
  -c, --bypass-captcha     Enable CAPTCHA bypass
  --headless true|false    Headless mode (default: true)
  -q, --quiet              Quiet mode (less output)
  -h, --help               Show help
```

---

## 📊 Real Example

```bash
# 1. Crawl target with proxy and CAPTCHA bypass
$ python secret_scanner_crawler.py https://app.example.com \
    --proxy http://proxy:8080 \
    --bypass-captcha \
    --max-pages 300

🔐 SECRET SCANNER CRAWLER (Enhanced)
Target:         https://app.example.com
Proxy:          http://proxy:8080
CAPTCHA Bypass: Enabled
Max Pages:      300

[1/300] 🔍 https://app.example.com
  ⚠️  HIGH [env_file] https://app.example.com/.env
  ⚠️  HIGH [config_file] https://app.example.com/config.json
        [javascript] https://app.example.com/bundle.js
        [api_response] https://app.example.com/api/users
  ✓ CAPTCHA bypassed

[2/300] 🔍 https://app.example.com/admin
  ⚠️  HIGH [config_file] https://app.example.com/admin/settings.json

✅ CRAWL COMPLETE
Pages Crawled:      150
JavaScript Files:   45
Config Files:       12
.env Files:         3
High Priority:      15
CAPTCHAs Solved:    1

# 2. Scan for secrets
$ trufflehog filesystem ./trufflehog_scan_output/high_priority/

Found verified result
Detector Type: AWS
Raw result: AKIAIOSFODNN7EXAMPLE
File: ./trufflehog_scan_output/high_priority/abc123_config.json

Found verified result
Detector Type: GitHub
Raw result: ghp_xxxxxxxxxxxxxxxxxxxx
File: ./trufflehog_scan_output/high_priority/def456_.env
```

---

## 🚨 Common Issues & Solutions

### Issue: "Browser not found"
```bash
# Solution: Specify browser path
export CHROME_PATH=/usr/bin/google-chrome
# or install Chrome/Chromium
```

### Issue: "Proxy connection failed"
```bash
# Solution: Test proxy separately
curl --proxy http://proxy:8080 https://example.com

# Try different proxy format
--proxy socks5://proxy:1080
```

### Issue: "CAPTCHA not bypassed"
```bash
# Solutions:
1. Use residential proxy (better IP reputation)
2. Try without headless mode (--headless false)
3. Increase timeout
4. Check if site uses different CAPTCHA type
```

### Issue: "Too many errors"
```bash
# Solution: Reduce concurrency
--max-pages 50  # Start small
```

### Issue: "Memory usage high"
```bash
# Solution: Restart browser periodically
# (The crawler automatically cleans up)
```

---

## ✅ Errors Fixed in Enhanced Version

### Fixed Issues
- ✅ Event handler cleanup (prevents memory leaks)
- ✅ Better error handling (try/except everywhere)
- ✅ Proxy authentication support
- ✅ CAPTCHA bypass integration
- ✅ Headless mode option
- ✅ Content encoding errors (ignore errors)
- ✅ URL parsing errors (safe fallbacks)
- ✅ Network timeout handling
- ✅ Callback cleanup after each page

### Improvements
- ✅ More robust error messages
- ✅ Progress tracking
- ✅ Statistics in output
- ✅ CAPTCHA bypass counter
- ✅ Proxy usage indicator

---

## 🔄 Workflow Integration

### Daily Automated Scan
```bash
#!/bin/bash
# daily_scan.sh

DATE=$(date +%Y%m%d)
OUTPUT="./scans/scan_$DATE"

python secret_scanner_crawler.py https://yoursite.com \
    --output "$OUTPUT" \
    --max-pages 500

if [ -d "$OUTPUT/high_priority" ]; then
    trufflehog filesystem "$OUTPUT/high_priority" \
        --json > "findings_$DATE.json"

    # Alert if findings
    if [ -s "findings_$DATE.json" ]; then
        echo "⚠️  Secrets found on $DATE!" | mail -s "Security Alert" security@yourcompany.com
    fi
fi
```

### CI/CD Integration
```yaml
# .github/workflows/secret-scan.yml
name: Secret Scan
on:
  schedule:
    - cron: '0 2 * * *'  # 2 AM daily

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run crawler
        run: |
          pip install pydoll-python
          python examples/secret_scanner_crawler.py https://yoursite.com

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

## 📚 More Information

- **Complete Guide**: See [TRUFFLEHOG_GUIDE.md](./TRUFFLEHOG_GUIDE.md)
- **Strategies**: See [crawler_strategies.md](./crawler_strategies.md)
- **Examples**: See [README.md](./README.md)
- **Pydoll Docs**: https://autoscrape-labs.github.io/pydoll/

---

## 💡 Pro Tips

1. **Start small** - Use `--max-pages 50` for first run
2. **Use proxies** - Better for avoiding rate limits
3. **Enable CAPTCHA bypass** - For protected sites
4. **Scan high priority first** - Fastest way to find secrets
5. **Automate daily** - Catch new leaks quickly
6. **Use verified only** - `--only-verified` reduces false positives
7. **Check API endpoints** - Look at `logs/api_endpoints.jsonl`
8. **Monitor errors** - High error count means adjust settings

---

**Happy hunting! 🔐**
