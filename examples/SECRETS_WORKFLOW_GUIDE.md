# Complete Secret Scanning Workflow Guide

**End-to-end automated secret scanning with metadata enrichment and bulk organization.**

## Overview

This workflow combines three powerful tools:

1. **`ultimate_crawler.py`** - Crawls websites with metadata capture + instant alerts
2. **TruffleHog** - Scans for 900+ secret types with verification
3. **`secrets_organizer.py`** - Enriches results with metadata + organizes by service

## Quick Start

### One Command (Automated)

```bash
# Single domain
./scan_workflow.sh https://example.com

# Multiple domains with speed
./scan_workflow.sh --domains domains.txt --tabs 5

# Full featured
./scan_workflow.sh --domains domains.txt \
    --tabs 5 \
    --discover-subdomains \
    --proxy http://proxy:8080 \
    --max-pages 1000
```

### Manual Steps

```bash
# Step 1: Crawl with metadata capture
python ultimate_crawler.py https://example.com --tabs 3

# Step 2: Scan with TruffleHog
trufflehog filesystem trufflehog_scan_output/ --json > results.json

# Step 3: Organize by service
python secrets_organizer.py results.json
```

---

## What's New

### 1. **Metadata Capture** ✅

Every file now has a metadata JSON with full HTTP context:

```json
{
  "url": "https://example.com/config.js",
  "content_type": "javascript",
  "timestamp": "2025-10-21T18:45:32",
  "response_data": {
    "status": 200,
    "mime_type": "application/javascript",
    "headers": {...},
    "method": "GET"
  },
  "quick_secrets_found": [...]
}
```

**Location:** `trufflehog_scan_output/metadata/`

### 2. **Instant Alerts** 🚨

Detects OBVIOUS secrets during crawl (high precision only):

- AWS Access Keys (`AKIA...`)
- GitHub Tokens (`ghp_...`, `gho_...`)
- Private Keys (`-----BEGIN PRIVATE KEY-----`)
- Stripe Keys (`sk_live_...`)
- Slack Tokens (`xoxb-...`)
- Google API Keys (`AIza...`)
- OpenAI Keys (`sk-proj-...`)
- JWT Tokens (`eyJ...`)

**Alert Example:**
```
================================================================================
🚨 INSTANT ALERT - OBVIOUS SECRETS DETECTED!
================================================================================
URL: https://example.com/config.js
File: trufflehog_scan_output/javascript/abc123_config.js
  • AWS Access Key: AKIAIOSFODNN7EXAMPLE
  • GitHub Personal Access Token: ghp_1234567890abcdef1234567890abcdef123456
================================================================================
```

**Location:** `trufflehog_scan_output/instant_alerts/`

### 3. **Bulk Organization by Service** 📦

TruffleHog results organized by service type with bulk export:

```
secrets_found/
├── aws/
│   ├── keys.txt              # AKIATEST:secretkeyhere (one per line)
│   ├── details.json          # Full metadata for each key
│   └── urls.txt              # Where each key was found
├── github/
│   ├── tokens.txt            # ghp_... (one per line)
│   ├── details.json
│   └── urls.txt
├── stripe/
├── slack/
├── google/
├── private_keys/
└── summary.json
```

**Bulk Format (`aws/keys.txt`):**
```
[VERIFIED] AKIAIOSFODNN7EXAMPLE:wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
[UNVERIFIED] AKIA6ODU4Q3RSOMEKEY:anotherSecretKeyHere123456789
[VERIFIED] AKIATESTTESTTEST1234:moreSecretsHere/K7MDENG/zzzzzz
```

---

## Output Structure

After running the workflow:

```
./
├── trufflehog_scan_output/          # Crawler output
│   ├── javascript/                  # All JS files
│   ├── config_files/                # Config files
│   ├── env_files/                   # .env files
│   ├── api_responses/               # API JSON responses
│   ├── high_priority/               # High-value files
│   ├── instant_alerts/              # Files with obvious secrets
│   └── metadata/                    # JSON metadata per file
│       ├── abc123.json
│       ├── def456.json
│       └── ...
│
├── trufflehog_results.json          # Raw TruffleHog output
│
└── secrets_found/                   # Organized by service
    ├── aws/
    │   ├── keys.txt                 # Bulk: access_key:secret_key
    │   ├── details.json             # Full metadata
    │   └── urls.txt                 # Source URLs
    ├── github/
    │   ├── tokens.txt
    │   ├── details.json
    │   └── urls.txt
    ├── stripe/
    ├── slack/
    ├── private_keys/
    └── summary.json                 # Overview report
```

---

## Use Cases

### Bug Bounty - Scan All In-Scope Domains

```bash
# Create domains.txt
cat > domains.txt <<EOF
example.com
api.example.com
admin.example.com
staging.example.com
EOF

# Run automated workflow
./scan_workflow.sh --domains domains.txt --tabs 5 --discover-subdomains

# Check results
cat secrets_found/summary.json
cat secrets_found/aws/keys.txt
```

### Test AWS Keys in Bulk

```bash
# After workflow completes
cat secrets_found/aws/keys.txt

# Output:
# [VERIFIED] AKIAIOSFODNN7EXAMPLE:wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
# [VERIFIED] AKIA6ODU4Q3RSOMEKEY:anotherSecretKey123456789012345678

# Test with AWS CLI
while read line; do
  if [[ $line == "[VERIFIED]"* ]]; then
    key=$(echo $line | cut -d' ' -f2 | cut -d':' -f1)
    secret=$(echo $line | cut -d' ' -f2 | cut -d':' -f2)

    AWS_ACCESS_KEY_ID=$key AWS_SECRET_ACCESS_KEY=$secret \
      aws sts get-caller-identity
  fi
done < secrets_found/aws/keys.txt
```

### Check Where Secrets Were Found

```bash
# See all URLs where AWS keys were found
cat secrets_found/aws/urls.txt

# Full details with HTTP context
jq '.' secrets_found/aws/details.json
```

### Instant Response to Live Secrets

```bash
# During crawl, instant alerts appear:
🚨 INSTANT ALERT - OBVIOUS SECRETS DETECTED!
URL: https://example.com/config.js

# Immediately scan just instant_alerts for verification
trufflehog filesystem trufflehog_scan_output/instant_alerts/ \
  --json --results=verified > critical.json

# Organize just the critical findings
python secrets_organizer.py critical.json -o critical_secrets/
```

---

## Advanced Features

### Metadata Enrichment

`secrets_organizer.py` enriches TruffleHog findings with crawler metadata:

```json
{
  "AKIAIOSFODNN7EXAMPLE": {
    "full_secret": "AKIAIOSFODNN7EXAMPLE:wJalrXUtnFEMI/K7MDENG/...",
    "verified": true,
    "url": "https://example.com/admin/config.js",
    "file_path": "trufflehog_scan_output/javascript/abc123.js",
    "crawler_context": {
      "response_code": 200,
      "content_type": "javascript",
      "timestamp": "2025-10-21T18:45:32",
      "mime_type": "application/javascript"
    },
    "extra_data": {
      "account": "595918472158",
      "arn": "arn:aws:iam::595918472158:user/...",
      "user_id": "AIDAYVP4CIPPJ5M54LRCY"
    }
  }
}
```

**Benefits:**
- Know exactly WHERE secret was found (URL, not just file path)
- See HTTP response code (200 = publicly accessible)
- Understand context (was it in a config file? API response?)

### Instant Alerts vs Full Scan

**Instant Alerts** (during crawl):
- High precision patterns only
- Alerts appear immediately
- Files saved to `instant_alerts/`
- For critical triage

**TruffleHog Full Scan** (after crawl):
- 900+ detectors
- Scans EVERYTHING
- Finds obfuscated/encoded secrets
- Comprehensive coverage

**Both run** - no secrets missed!

---

## Workflow Diagram

```
                     🎯 Target Domain
                            ↓
         ╔══════════════════════════════════════╗
         ║   ultimate_crawler.py                ║
         ║   • Crawls with concurrent tabs      ║
         ║   • Saves metadata per file          ║
         ║   • Quick secret detection           ║
         ║   • Instant alerts                   ║
         ╚══════════════════════════════════════╝
                            ↓
              trufflehog_scan_output/
              ├── javascript/
              ├── config_files/
              ├── instant_alerts/     ⚠️
              └── metadata/           ✅
                            ↓
         ╔══════════════════════════════════════╗
         ║   TruffleHog                         ║
         ║   • Scans all files                  ║
         ║   • 900+ detectors                   ║
         ║   • Verifies secrets                 ║
         ╚══════════════════════════════════════╝
                            ↓
              trufflehog_results.json
                            ↓
         ╔══════════════════════════════════════╗
         ║   secrets_organizer.py               ║
         ║   • Enriches with metadata           ║
         ║   • Groups by service                ║
         ║   • Bulk export format               ║
         ╚══════════════════════════════════════╝
                            ↓
              secrets_found/
              ├── aws/keys.txt        ✅ Use these!
              ├── github/tokens.txt   ✅ Use these!
              ├── stripe/keys.txt     ✅ Use these!
              └── summary.json        📊 Overview
```

---

## Troubleshooting

### No secrets found but instant alert showed

**Cause:** Instant alerts detect high-precision patterns. TruffleHog may mark them as unverified if verification failed.

**Solution:**
```bash
# Check unverified results too
trufflehog filesystem trufflehog_scan_output/ \
  --json --results=verified,unverified,unknown > all_results.json

python secrets_organizer.py all_results.json
```

### Metadata not found

**Cause:** Old crawl output without metadata support.

**Solution:** Re-run crawler with updated `ultimate_crawler.py`.

### Can't find jq command

**Install:**
```bash
# macOS
brew install jq

# Linux
sudo apt-get install jq
```

---

## Performance

| Operation | Time (500 pages) |
|-----------|------------------|
| Crawl (1 tab) | ~30 minutes |
| Crawl (5 tabs) | ~8 minutes ⚡ |
| TruffleHog scan | ~2 minutes |
| Organization | ~5 seconds |
| **Total (5 tabs)** | **~10 minutes** |

---

## Security Best Practices

1. **Instant triage** - Scan `instant_alerts/` first
2. **Verify findings** - TruffleHog verification confirms if secret works
3. **Check metadata** - See if secret is publicly accessible (status 200)
4. **Test safely** - Use bulk exports to test credentials programmatically
5. **Document** - `urls.txt` shows exactly where secrets were found

---

## Summary

**What you get:**

✅ **Metadata capture** - Full HTTP context for every file
✅ **Instant alerts** - Real-time detection of obvious secrets
✅ **Zero missed secrets** - TruffleHog scans everything
✅ **Bulk organization** - Secrets grouped by service (AWS, GitHub, etc.)
✅ **Easy testing** - `keys.txt` format ready for bulk validation
✅ **Full context** - Know WHERE and HOW secrets were exposed

**One command, complete results:**
```bash
./scan_workflow.sh https://example.com --tabs 5
```
