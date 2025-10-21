#!/bin/bash
#
# Secret Scanner - Crawl & Scan Automation Script
#
# Usage:
#   ./scan_for_secrets.sh https://example.com
#   ./scan_for_secrets.sh https://example.com 500
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check arguments
if [ $# -lt 1 ]; then
    echo -e "${RED}Error: Missing target URL${NC}"
    echo "Usage: $0 <URL> [max_pages]"
    echo ""
    echo "Examples:"
    echo "  $0 https://example.com"
    echo "  $0 https://api.example.com 500"
    exit 1
fi

TARGET_URL="$1"
MAX_PAGES="${2:-200}"
OUTPUT_DIR="./trufflehog_scan_output"

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}🔐 Secret Scanner - Automated Workflow${NC}"
echo -e "${BLUE}============================================${NC}"
echo -e "Target:     ${GREEN}$TARGET_URL${NC}"
echo -e "Max Pages:  ${GREEN}$MAX_PAGES${NC}"
echo -e "Output:     ${GREEN}$OUTPUT_DIR${NC}"
echo -e "${BLUE}============================================${NC}\n"

# Step 1: Crawl
echo -e "${YELLOW}[1/3]${NC} 🕷️  Crawling website..."
python3 secret_scanner_crawler.py "$TARGET_URL" \
    --max-pages "$MAX_PAGES" \
    --output "$OUTPUT_DIR"

if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Crawl failed${NC}"
    exit 1
fi

echo -e "\n${GREEN}✓${NC} Crawl complete\n"

# Step 2: Check if TruffleHog is installed
echo -e "${YELLOW}[2/3]${NC} 🔍 Checking TruffleHog installation..."

if ! command -v trufflehog &> /dev/null; then
    echo -e "${YELLOW}TruffleHog not found. Installing...${NC}"

    # Try to install based on OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if command -v brew &> /dev/null; then
            brew install trufflesecurity/trufflehog/trufflehog
        else
            echo -e "${RED}Error: Homebrew not found. Please install TruffleHog manually:${NC}"
            echo "  brew install trufflesecurity/trufflehog/trufflehog"
            exit 1
        fi
    else
        # Linux - use Docker as fallback
        echo -e "${YELLOW}Using TruffleHog via Docker${NC}"
        TRUFFLEHOG_CMD="docker run --rm -v \"$PWD:/scan\" trufflesecurity/trufflehog:latest"
    fi
else
    echo -e "${GREEN}✓${NC} TruffleHog is installed\n"
    TRUFFLEHOG_CMD="trufflehog"
fi

# Step 3: Scan with TruffleHog
echo -e "${YELLOW}[3/3]${NC} 🔐 Scanning for secrets..."

FINDINGS_FILE="secret_findings_$(date +%Y%m%d_%H%M%S).json"

echo -e "${BLUE}Scanning high priority files first...${NC}"
if [ -z "$TRUFFLEHOG_CMD" ]; then
    TRUFFLEHOG_CMD="trufflehog"
fi

# Scan high priority
eval "$TRUFFLEHOG_CMD filesystem \"$OUTPUT_DIR/high_priority\" --json" > "$FINDINGS_FILE" 2>&1 || true

# Count findings
FINDING_COUNT=$(cat "$FINDINGS_FILE" | grep -c "DetectorName" || echo "0")

echo -e "\n${BLUE}============================================${NC}"
echo -e "${BLUE}📊 Scan Results${NC}"
echo -e "${BLUE}============================================${NC}"

if [ "$FINDING_COUNT" -gt 0 ]; then
    echo -e "${RED}⚠️  Found $FINDING_COUNT potential secret(s)!${NC}\n"

    # Show summary
    echo -e "${YELLOW}Detected secret types:${NC}"
    cat "$FINDINGS_FILE" | grep "DetectorName" | jq -r '.DetectorName' | sort | uniq -c 2>/dev/null || true

    echo -e "\n${YELLOW}Findings saved to: $FINDINGS_FILE${NC}"
    echo -e "${RED}⚠️  ACTION REQUIRED: Review and rotate exposed secrets!${NC}\n"

    # Show first finding as example
    echo -e "${YELLOW}Example finding:${NC}"
    cat "$FINDINGS_FILE" | head -1 | jq '.' 2>/dev/null || cat "$FINDINGS_FILE" | head -1

else
    echo -e "${GREEN}✓ No secrets found in high priority files${NC}\n"
    echo -e "${BLUE}Scanning all files (this may take longer)...${NC}"

    eval "$TRUFFLEHOG_CMD filesystem \"$OUTPUT_DIR\" --json" > "$FINDINGS_FILE" 2>&1 || true
    FINDING_COUNT=$(cat "$FINDINGS_FILE" | grep -c "DetectorName" || echo "0")

    if [ "$FINDING_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}Found $FINDING_COUNT potential secret(s) in all files${NC}"
        cat "$FINDINGS_FILE" | grep "DetectorName" | jq -r '.DetectorName' | sort | uniq -c 2>/dev/null || true
    else
        echo -e "${GREEN}✓ No secrets found${NC}"
    fi
fi

echo -e "\n${BLUE}============================================${NC}"
echo -e "${GREEN}✓ Scan Complete${NC}"
echo -e "${BLUE}============================================${NC}"
echo -e "Output Directory: ${GREEN}$OUTPUT_DIR${NC}"
echo -e "Findings:         ${GREEN}$FINDINGS_FILE${NC}"
echo -e "\n${YELLOW}Review findings manually:${NC}"
echo -e "  cat $FINDINGS_FILE | jq '.'"
echo -e "\n${YELLOW}Scan specific directory:${NC}"
echo -e "  trufflehog filesystem $OUTPUT_DIR/config_files/"
echo -e "${BLUE}============================================${NC}\n"
