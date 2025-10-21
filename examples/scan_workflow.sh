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
SEMGREP_RESULTS_FILE="./semgrep_results.json"
SECRETS_DIR="./secrets_found"
USE_SEMGREP=false

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

# Check if semgrep is installed (optional)
check_semgrep() {
    if ! command -v semgrep &> /dev/null; then
        print_warning "Semgrep is not installed - pattern-based detection disabled"
        echo ""
        echo "Install Semgrep (optional):"
        echo "  pip install semgrep"
        echo "  Or: brew install semgrep"
        echo ""
        return 1
    fi
    return 0
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
    print_status "Step 2/4: Scanning with TruffleHog"
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

# Step 3: Scan with Semgrep (optional)
scan_with_semgrep() {
    if [ "$USE_SEMGREP" = false ]; then
        return
    fi

    print_status "Step 3/4: Scanning with Semgrep (pattern-based detection)"
    echo "--------------------------------------------------------------------------------"

    if ! check_semgrep; then
        print_warning "Skipping Semgrep scan"
        echo ""
        return
    fi

    if [ ! -d "$OUTPUT_DIR" ]; then
        print_error "Output directory not found: $OUTPUT_DIR"
        return
    fi

    # Scan beautified JS files (better detection) or all files
    JS_DIR="$OUTPUT_DIR/javascript"
    if [ -d "$JS_DIR" ]; then
        print_status "Running Semgrep on JavaScript files..."

        semgrep --config=auto \
            --json \
            --output="$SEMGREP_RESULTS_FILE" \
            "$JS_DIR" 2>&1 || true

        if [ -s "$SEMGREP_RESULTS_FILE" ]; then
            FINDINGS_COUNT=$(jq '.results | length' "$SEMGREP_RESULTS_FILE" 2>/dev/null || echo "0")
            print_success "Semgrep scan completed: $FINDINGS_COUNT findings"
        else
            print_success "Semgrep scan completed: No findings"
        fi
    else
        print_warning "JavaScript directory not found, skipping Semgrep"
    fi

    echo ""
}

# Step 4: Organize results
organize_results() {
    print_status "Step 4/4: Organizing secrets by service type"
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
        rm -f "$RESULTS_FILE" "${RESULTS_FILE}.instant_alerts" "$SEMGREP_RESULTS_FILE"
    fi

    if [ -d "$SECRETS_DIR" ]; then
        rm -rf "$SECRETS_DIR"
    fi

    # Run workflow
    crawl_target "$@"
    scan_with_trufflehog
    scan_with_semgrep
    organize_results
    print_summary

    print_success "✅ Complete workflow finished!"
}

# Help message
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "Usage: $0 [OPTIONS] [CRAWLER_OPTIONS]"
    echo ""
    echo "Complete workflow: Crawl → Scan with TruffleHog → (Optional Semgrep) → Organize"
    echo ""
    echo "Options:"
    echo "  --semgrep    Enable Semgrep scanning (pattern-based detection)"
    echo ""
    echo "Examples:"
    echo "  # Single domain"
    echo "  $0 https://example.com"
    echo ""
    echo "  # Multiple domains with speed boost"
    echo "  $0 --domains domains.txt --tabs 5"
    echo ""
    echo "  # With Semgrep for enhanced detection"
    echo "  $0 https://example.com --semgrep"
    echo ""
    echo "  # Full featured scan"
    echo "  $0 --semgrep --domains domains.txt --tabs 5 --discover-subdomains"
    echo ""
    echo "All ultimate_crawler.py options are supported."
    echo ""
    exit 0
fi

# Check if any arguments provided
if [ $# -eq 0 ]; then
    print_error "No target specified"
    echo ""
    echo "Usage: $0 [OPTIONS] [CRAWLER_OPTIONS]"
    echo "Run '$0 --help' for more information"
    echo ""
    exit 1
fi

# Parse workflow-specific options
CRAWLER_ARGS=()
for arg in "$@"; do
    case $arg in
        --semgrep)
            USE_SEMGREP=true
            print_status "Semgrep scanning enabled"
            ;;
        *)
            CRAWLER_ARGS+=("$arg")
            ;;
    esac
done

main "${CRAWLER_ARGS[@]}"
