#!/usr/bin/env bash
#
# Webcam Pipeline Demo Script
# Starts Expanso Edge agent and dashboard for demo presentations
#
# Pipeline deployment is done via Expanso Cloud web UI (cloud.expanso.io)
#
# Usage:
#   ./demo.sh          # Start demo (clears data, starts services)
#   ./demo.sh status   # Check if services are running

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m'
BOLD='\033[1m'

# PIDs
DASHBOARD_PID=""
EDGE_PID=""

# Get local IP address
get_ip() {
    hostname -I 2>/dev/null | awk '{print $1}' || hostname
}

# Print banner
banner() {
    echo -e "${PURPLE}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                                                               ║"
    echo "║   ${WHITE}EXPANSO${PURPLE}  ${CYAN}WEBCAM PIPELINE DEMO${PURPLE}                            ║"
    echo "║                                                               ║"
    echo "║   Deploy pipelines via ${WHITE}cloud.expanso.io${PURPLE}                       ║"
    echo "║                                                               ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Clear all data directories
clear_data() {
    echo -e "${YELLOW}Clearing data directories...${NC}"
    rm -rf chunks/* processed/* 2>/dev/null || true
    mkdir -p chunks processed/thumbnails
    for cat in left_hand_raised right_hand_raised both_hands_raised no_detection high_motion medium_motion low_motion no_motion; do
        mkdir -p "processed/$cat"
    done
    echo -e "${GREEN}Data cleared.${NC}"
}

# Cleanup function - runs on exit
cleanup() {
    echo -e "\n${YELLOW}Shutting down demo...${NC}"

    # Kill dashboard
    if [[ -n "$DASHBOARD_PID" ]] && kill -0 "$DASHBOARD_PID" 2>/dev/null; then
        echo -e "${PURPLE}[DASHBOARD]${NC} Stopping..."
        kill "$DASHBOARD_PID" 2>/dev/null || true
        wait "$DASHBOARD_PID" 2>/dev/null || true
    fi

    # Note: We don't kill expanso-edge - it should keep running
    # User can stop it manually with: expanso-edge stop

    # Clear data on exit
    echo -e "${YELLOW}Cleaning up data...${NC}"
    clear_data

    echo -e "${GREEN}Demo ended. Data cleared.${NC}"
    echo -e "${CYAN}Expanso edge agent may still be running.${NC}"
    echo -e "Stop it with: ${WHITE}expanso-edge stop${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# Check if expanso-edge is installed
check_expanso() {
    if ! command -v expanso-edge &> /dev/null; then
        echo -e "${RED}expanso-edge not found!${NC}"
        echo ""
        echo "Install it with:"
        echo -e "  ${WHITE}curl -fsSL https://get.expanso.io/edge/install.sh | sh${NC}"
        echo ""
        echo "Then bootstrap with your token from cloud.expanso.io:"
        echo -e "  ${WHITE}expanso-edge bootstrap --token YOUR_TOKEN${NC}"
        echo ""
        return 1
    fi
    return 0
}

# Start expanso-edge agent
start_edge() {
    echo -e "${BLUE}[EXPANSO]${NC} Checking edge agent..."

    # Check if already running
    if expanso-edge status &>/dev/null; then
        echo -e "${GREEN}[EXPANSO]${NC} Edge agent already running"
    else
        echo -e "${BLUE}[EXPANSO]${NC} Starting edge agent..."
        expanso-edge start &
        EDGE_PID=$!
        sleep 2

        if expanso-edge status &>/dev/null; then
            echo -e "${GREEN}[EXPANSO]${NC} Edge agent started"
        else
            echo -e "${YELLOW}[EXPANSO]${NC} Edge agent may need bootstrapping"
            echo "Run: expanso-edge bootstrap --token YOUR_TOKEN"
        fi
    fi
}

# Start dashboard
start_dashboard() {
    local ip=$(get_ip)
    echo -e "${PURPLE}[DASHBOARD]${NC} Starting on port 8181..."
    uv run -s dashboard.py &
    DASHBOARD_PID=$!
    sleep 2

    if kill -0 "$DASHBOARD_PID" 2>/dev/null; then
        echo -e "${GREEN}[DASHBOARD]${NC} Running at http://${ip}:8181"
    else
        echo -e "${RED}[DASHBOARD]${NC} Failed to start!"
        exit 1
    fi
}

# Show status
show_status() {
    banner
    echo -e "${BOLD}Service Status:${NC}\n"

    # Check expanso-edge
    echo -n "Expanso Edge Agent: "
    if command -v expanso-edge &> /dev/null; then
        if expanso-edge status &>/dev/null; then
            echo -e "${GREEN}Running${NC}"
            expanso-edge status 2>/dev/null | head -5 | sed 's/^/  /'
        else
            echo -e "${YELLOW}Not running${NC}"
        fi
    else
        echo -e "${RED}Not installed${NC}"
    fi
    echo ""

    # Check dashboard
    local ip=$(get_ip)
    echo -n "Dashboard: "
    if curl -s "http://${ip}:8181" >/dev/null 2>&1; then
        echo -e "${GREEN}Running${NC} at http://${ip}:8181"
    else
        echo -e "${YELLOW}Not running${NC}"
    fi
    echo ""

    # Check data directories
    echo -e "${BOLD}Data Status:${NC}"
    if [[ -d chunks ]]; then
        local chunk_count=$(find chunks -name "*.mp4" 2>/dev/null | wc -l)
        echo "  Pending chunks: $chunk_count"
    fi

    if [[ -d processed ]]; then
        local total=0
        for cat in left_hand_raised right_hand_raised both_hands_raised no_detection; do
            if [[ -d "processed/$cat" ]]; then
                local count=$(find "processed/$cat" -name "*.mp4" 2>/dev/null | wc -l)
                if [[ $count -gt 0 ]]; then
                    echo "  $cat: $count"
                    total=$((total + count))
                fi
            fi
        done
        echo "  Total processed: $total"
    fi
}

# Main run
run_demo() {
    banner

    # Check prerequisites
    if ! check_expanso; then
        exit 1
    fi

    # Clear data before starting
    clear_data

    # Start services
    echo -e "\n${BOLD}Starting services...${NC}\n"
    start_edge
    start_dashboard

    local ip=$(get_ip)
    echo -e "\n${BOLD}${GREEN}Demo ready!${NC}\n"
    echo -e "Dashboard:      ${WHITE}http://${ip}:8181${NC}"
    echo -e "Expanso Cloud:  ${WHITE}https://cloud.expanso.io${NC}"
    echo ""
    echo -e "Deploy pipelines from Expanso Cloud to see them in action!"
    echo ""
    echo -e "Press ${BOLD}Ctrl+C${NC} to stop demo and clear data.\n"

    # Wait forever (cleanup happens on signal)
    while true; do
        sleep 1

        # Check if dashboard died
        if ! kill -0 "$DASHBOARD_PID" 2>/dev/null; then
            echo -e "${RED}Dashboard crashed! Restarting...${NC}"
            start_dashboard
        fi
    done
}

# Help
show_help() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  (none)    Start demo - clears data, starts services"
    echo "  status    Show current service status"
    echo "  help      Show this help"
    echo ""
    echo "Pipeline deployment is done via Expanso Cloud:"
    echo "  https://cloud.expanso.io"
    echo ""
    echo "The demo script handles:"
    echo "  - Clearing data directories before start"
    echo "  - Starting expanso-edge agent (if not running)"
    echo "  - Starting the web dashboard"
    echo "  - Clearing data on exit (Ctrl+C)"
}

# Main
case "${1:-}" in
    status)
        show_status
        ;;
    help|-h|--help)
        show_help
        ;;
    "")
        run_demo
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        show_help
        exit 1
        ;;
esac
