#!/bin/bash
#
# Complete Secret Scanning Workflow
# ==================================
# Automated workflow: Crawl → Scan → Organize
#
# Usage:
#   ./scan_workflow.sh https://example.com
#   ./scan_workflow.sh --domains domains.txt --tabs 5
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
OUTPUT_DIR="./trufflehog_scan_output"
RESULTS_FILE="./trufflehog_results.json"
SECRETS_DIR="./secrets_found"

# Print header
echo "================================================================================"
echo "                    🔍 Complete Secret Scanning Workflow"
echo "================================================================================"
echo ""

# Function to print status
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if trufflehog is installed
check_trufflehog() {
    if ! command -v trufflehog &> /dev/null; then
        print_error "TruffleHog is not installed"
        echo ""
        echo "Install TruffleHog:"
        echo "  macOS:   brew install trufflehog"
        echo "  Linux:   curl -sSfL https://raw.githubusercontent.com/trufflesecurity/trufflehog/main/scripts/install.sh | sh -s -- -b /usr/local/bin"
        echo "  Docker:  docker pull trufflesecurity/trufflehog:latest"
        echo ""
        exit 1
    fi
}

# Step 1: Crawl the target
crawl_target() {
    print_status "Step 1/3: Crawling target with ultimate_crawler.py"
    echo "--------------------------------------------------------------------------------"

    # Pass all arguments to the crawler
    python3 ultimate_crawler.py "$@"

    if [ $? -eq 0 ]; then
        print_success "Crawling completed"
    else
        print_error "Crawling failed"
        exit 1
    fi

    echo ""
}

# Step 2: Scan with TruffleHog
scan_with_trufflehog() {
    print_status "Step 2/3: Scanning with TruffleHog"
    echo "--------------------------------------------------------------------------------"

    if [ ! -d "$OUTPUT_DIR" ]; then
        print_error "Output directory not found: $OUTPUT_DIR"
        exit 1
    fi

    # Check if instant_alerts exists and has files
    if [ -d "$OUTPUT_DIR/instant_alerts" ] && [ "$(ls -A $OUTPUT_DIR/instant_alerts)" ]; then
        print_warning "Instant alerts found! Scanning high-priority files first..."
        trufflehog filesystem "$OUTPUT_DIR/instant_alerts" \
            --json \
            --results=verified,unknown \
            > "${RESULTS_FILE}.instant_alerts" 2>&1 || true

        if [ -s "${RESULTS_FILE}.instant_alerts" ]; then
            print_warning "⚠️  VERIFIED SECRETS in instant alerts!"
        fi
    fi

    # Full scan
    print_status "Running full TruffleHog scan..."
    trufflehog filesystem "$OUTPUT_DIR" \
        --json \
        --results=verified,unknown \
        > "$RESULTS_FILE" 2>&1 || true

    if [ -s "$RESULTS_FILE" ]; then
        SECRETS_COUNT=$(wc -l < "$RESULTS_FILE")
        print_success "TruffleHog scan completed: $SECRETS_COUNT potential secrets found"
    else
        print_success "TruffleHog scan completed: No secrets found"
    fi

    echo ""
}

# Step 3: Organize results
organize_results() {
    print_status "Step 3/3: Organizing secrets by service type"
    echo "--------------------------------------------------------------------------------"

    if [ ! -f "$RESULTS_FILE" ] || [ ! -s "$RESULTS_FILE" ]; then
        print_warning "No TruffleHog results to organize"
        return
    fi

    python3 secrets_organizer.py "$RESULTS_FILE" \
        --metadata-dir "$OUTPUT_DIR/metadata" \
        --output-dir "$SECRETS_DIR"

    if [ $? -eq 0 ]; then
        print_success "Secrets organized in: $SECRETS_DIR"
    else
        print_error "Organization failed"
        exit 1
    fi

    echo ""
}

# Print summary
print_summary() {
    echo "================================================================================"
    echo "                              📊 Scan Summary"
    echo "================================================================================"

    if [ -f "$SECRETS_DIR/summary.json" ]; then
        # Extract key stats from summary
        TOTAL=$(jq -r '.total_secrets_found // 0' "$SECRETS_DIR/summary.json" 2>/dev/null || echo "0")
        VERIFIED=$(jq -r '.verified_secrets // 0' "$SECRETS_DIR/summary.json" 2>/dev/null || echo "0")

        echo ""
        echo "  Total secrets found:     $TOTAL"
        echo "  Verified secrets:        $VERIFIED"
        echo ""

        if [ "$VERIFIED" -gt 0 ]; then
            echo -e "${RED}⚠️  VERIFIED SECRETS FOUND!${NC}"
            echo ""
            echo "  Check organized results:"
            echo "    • AWS keys:      $SECRETS_DIR/aws/keys.txt"
            echo "    • GitHub tokens: $SECRETS_DIR/github/tokens.txt"
            echo "    • All services:  $SECRETS_DIR/"
            echo ""
        fi
    fi

    echo "  Output locations:"
    echo "    • Crawled data:      $OUTPUT_DIR/"
    echo "    • TruffleHog results: $RESULTS_FILE"
    echo "    • Organized secrets:  $SECRETS_DIR/"
    echo "    • Summary report:     $SECRETS_DIR/summary.json"
    echo ""
    echo "================================================================================"
}

# Main execution
main() {
    check_trufflehog

    # Clean previous results
    if [ -f "$RESULTS_FILE" ]; then
        print_status "Removing previous results..."
        rm -f "$RESULTS_FILE" "${RESULTS_FILE}.instant_alerts"
    fi

    if [ -d "$SECRETS_DIR" ]; then
        rm -rf "$SECRETS_DIR"
    fi

    # Run workflow
    crawl_target "$@"
    scan_with_trufflehog
    organize_results
    print_summary

    print_success "✅ Complete workflow finished!"
}

# Help message
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "Usage: $0 [CRAWLER_OPTIONS]"
    echo ""
    echo "Complete workflow: Crawl → Scan with TruffleHog → Organize by service"
    echo ""
    echo "Examples:"
    echo "  # Single domain"
    echo "  $0 https://example.com"
    echo ""
    echo "  # Multiple domains with speed boost"
    echo "  $0 --domains domains.txt --tabs 5"
    echo ""
    echo "  # With proxy and subdomain discovery"
    echo "  $0 https://example.com --tabs 3 --proxy http://proxy:8080 --discover-subdomains"
    echo ""
    echo "All ultimate_crawler.py options are supported."
    echo ""
    exit 0
fi

# Check if any arguments provided
if [ $# -eq 0 ]; then
    print_error "No target specified"
    echo ""
    echo "Usage: $0 [CRAWLER_OPTIONS]"
    echo "Run '$0 --help' for more information"
    echo ""
    exit 1
fi

main "$@"
