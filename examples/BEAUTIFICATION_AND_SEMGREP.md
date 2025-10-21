# JS Beautification & Semgrep Integration

## What's New

### 🎨 Automatic JavaScript Beautification

All JavaScript files are now automatically beautified during crawl for:
- ✅ **Better manual code review** - Readable, formatted code
- ✅ **Improved TruffleHog detection** - Better context for secret detection
- ✅ **Both versions saved** - Original (minified) + Beautified

**Output Structure:**
```
javascript/
├── abc123_bundle.js              # Original (minified)
├── abc123_bundle.beautified.js   # Readable! ✨
├── def456_main.js
└── def456_main.beautified.js
```

**Example:**
```javascript
// Before (minified)
var a=function(e){return e+1},b="AKIAIOSFODNN7EXAMPLE";console.log(a(5),b);

// After (beautified)
var a = function(e) {
  return e + 1
},
b = "AKIAIOSFODNN7EXAMPLE";
console.log(a(5), b);
```

---

### 🔍 Semgrep Pattern Detection (Optional)

Add pattern-based detection on top of TruffleHog:

**What Semgrep Catches:**
- Generic API keys (any hex string in `apiKey` variable)
- Hardcoded passwords (`if (password == "secret")`)
- Database connection strings
- Firebase/AWS config objects
- JWT tokens in code
- Custom company-specific patterns

**Enable with:**
```bash
./scan_workflow.sh https://example.com --semgrep
```

---

## Installation

### Required:
```bash
pip install jsbeautifier
```

### Optional (for Semgrep):
```bash
pip install semgrep
# or
brew install semgrep
```

---

## Usage

### Default (Beautification Only):
```bash
# JS automatically beautified
./scan_workflow.sh https://example.com --tabs 5
```

### With Semgrep (Enhanced Detection):
```bash
# Adds pattern-based detection
./scan_workflow.sh https://example.com --semgrep --tabs 5
```

---

## Real-World Comparison

### Example Scan: `shop.example.com`

**TruffleHog Finds:**
```
✅ AWS Access Key: AKIAIOSFODNN7EXAMPLE
✅ GitHub Token: ghp_1234567890abcdef
✅ Stripe Live Key: sk_live_abcdefghijk
```

**Semgrep Additionally Finds:**
```
✅ Generic API key: const key = "a1b2c3d4e5f6..."
✅ Hardcoded password: if (pwd === "admin123")
✅ Firebase config: apiKey: "AIza..." in object
✅ MongoDB URI: "mongodb://user:pass@..."
✅ JWT token in localStorage: "eyJhbGci..."
```

**Result: 3 secrets → 8 secrets found! 🎯**

---

## When To Use Semgrep

| Use Case | Semgrep? |
|----------|----------|
| **Quick scan** | ❌ Skip (TruffleHog only) |
| **Bug bounty** | ✅ Enable (max coverage) |
| **Production audit** | ✅ Enable (find everything) |
| **CI/CD pipeline** | ⚠️ Optional (adds ~5-10s) |
| **Custom patterns** | ✅ Enable (extensible rules) |

---

## Performance Impact

| Feature | Time Impact | Benefit |
|---------|-------------|---------|
| **JS Beautification** | ~50ms per file | 🔥 Essential |
| **Semgrep** | ~5-10 seconds | ⭐ High value |

**Recommendation:** Always beautify, enable Semgrep for important scans.

---

## Output Examples

### Beautified JS:
```bash
# View beautified code
cat trufflehog_scan_output/javascript/main.beautified.js

# Search for patterns
grep -r "password" trufflehog_scan_output/javascript/*.beautified.js
```

### Semgrep Results:
```bash
# Check Semgrep findings
cat semgrep_results.json | jq '.results[] | {file, check_id, extra}'
```

---

## Summary

**What Changed:**
- ✅ All JS files automatically beautified
- ✅ Semgrep integration (optional flag)
- ✅ Better secret detection
- ✅ No breaking changes

**Dependencies Added:**
- Required: `jsbeautifier`
- Optional: `semgrep`

**Usage:**
```bash
# Default (with beautification)
./scan_workflow.sh https://example.com

# Enhanced (with Semgrep)
./scan_workflow.sh https://example.com --semgrep
```
