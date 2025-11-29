#!/usr/bin/env bash
#
# Local Debug Script for Webcam Pipeline Demo
#
# Use this script to test the pipeline locally WITHOUT Expanso Cloud.
# For actual demos, use ./demo.sh and deploy pipelines via cloud.expanso.io
#
# Usage:
#   ./debug.sh              # Interactive menu
#   ./debug.sh dashboard    # Start dashboard only
#   ./debug.sh capture      # Start capture only
#   ./debug.sh detect       # Start detection only
#   ./debug.sh full         # Run full pipeline (capture + detect)
#   ./debug.sh stage N      # Set stage to N (0-4)

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
NC='\033[0m'
BOLD='\033[1m'

# PIDs for cleanup
DASHBOARD_PID=""
CAPTURE_PID=""
DETECT_PID=""

cleanup() {
    echo -e "\n${YELLOW}Cleaning up...${NC}"
    [[ -n "$DASHBOARD_PID" ]] && kill $DASHBOARD_PID 2>/dev/null || true
    [[ -n "$CAPTURE_PID" ]] && kill $CAPTURE_PID 2>/dev/null || true
    [[ -n "$DETECT_PID" ]] && kill $DETECT_PID 2>/dev/null || true
    pkill -f "dashboard.py" 2>/dev/null || true
    pkill -f "capture_video.py" 2>/dev/null || true
    pkill -f "process_chunks.py" 2>/dev/null || true
    echo -e "${GREEN}Done.${NC}"
}

trap cleanup EXIT

banner() {
    echo -e "${PURPLE}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${PURPLE}║  ${YELLOW}LOCAL DEBUG MODE${PURPLE}                                            ║${NC}"
    echo -e "${PURPLE}║  ${NC}For demos, use ./demo.sh + cloud.expanso.io${PURPLE}                 ║${NC}"
    echo -e "${PURPLE}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

get_ip() {
    hostname -I 2>/dev/null | awk '{print $1}' || hostname
}

# Tailscale configuration
TAILSCALE_URL="https://fepi.tail8e9db.ts.net"

get_tailscale_dns() {
    if command -v tailscale &> /dev/null && tailscale status &>/dev/null; then
        echo "fepi.tail8e9db.ts.net"
    fi
}

clear_data() {
    echo -e "${YELLOW}Clearing data...${NC}"
    # Kill any processes that might be holding the database
    pkill -f "dashboard.py" 2>/dev/null || true
    pkill -f "capture_video.py" 2>/dev/null || true
    pkill -f "process_chunks.py" 2>/dev/null || true
    sleep 0.5
    # Remove all data files
    rm -rf chunks processed 2>/dev/null || true
    rm -f pipeline.db pipeline.db-shm pipeline.db-wal 2>/dev/null || true
    # Recreate directories
    mkdir -p chunks processed/thumbnails
    for cat in left_hand_raised right_hand_raised both_hands_raised no_detection; do
        mkdir -p "processed/$cat"
    done
    echo -e "${GREEN}Data cleared.${NC}"
}

start_dashboard() {
    local ip=$(get_ip)
    local ts_dns=$(get_tailscale_dns)
    echo -e "${CYAN}[DASHBOARD]${NC} Starting on port 8181..."
    uv run -s dashboard.py &
    DASHBOARD_PID=$!
    sleep 2
    if kill -0 $DASHBOARD_PID 2>/dev/null; then
        echo -e "${GREEN}[DASHBOARD]${NC} Running at:"
        echo -e "  Local:  ${BOLD}http://${ip}:8181${NC}"
        if [[ -n "$ts_dns" ]]; then
            echo -e "  Public: ${BOLD}https://${ts_dns}${NC}"
        fi
    else
        echo -e "${RED}[DASHBOARD]${NC} Failed to start"
        exit 1
    fi
}

start_capture() {
    echo -e "${CYAN}[CAPTURE]${NC} Starting video capture..."
    uv run -s capture_video.py &
    CAPTURE_PID=$!
    sleep 2
    if kill -0 $CAPTURE_PID 2>/dev/null; then
        echo -e "${GREEN}[CAPTURE]${NC} Running (Stage 1)"
    else
        echo -e "${RED}[CAPTURE]${NC} Failed to start"
    fi
}

start_detection() {
    echo -e "${CYAN}[DETECTION]${NC} Starting pose detection..."
    uv run -s process_chunks.py &
    DETECT_PID=$!
    sleep 2
    if kill -0 $DETECT_PID 2>/dev/null; then
        echo -e "${GREEN}[DETECTION]${NC} Running (Stage 2)"
    else
        echo -e "${RED}[DETECTION]${NC} Failed to start"
    fi
}

set_stage() {
    local stage=$1
    echo -e "${CYAN}Setting stage to ${stage}...${NC}"
    curl -s -X POST "http://localhost:8181/api/stage/${stage}" | cat
    echo ""
}

show_menu() {
    echo -e "\n${BOLD}Debug Commands:${NC}"
    echo -e "  ${GREEN}1${NC}) Start dashboard only"
    echo -e "  ${GREEN}2${NC}) Start capture (Stage 1)"
    echo -e "  ${GREEN}3${NC}) Start detection (Stage 2)"
    echo -e "  ${GREEN}4${NC}) Set stage manually (0-4)"
    echo -e "  ${GREEN}5${NC}) Clear all data"
    echo -e "  ${GREEN}6${NC}) Run full pipeline"
    echo -e "  ${GREEN}q${NC}) Quit"
    echo ""
}

interactive_mode() {
    banner
    clear_data
    start_dashboard

    while true; do
        show_menu
        read -p "Enter choice: " choice
        case $choice in
            1)
                if ! kill -0 $DASHBOARD_PID 2>/dev/null; then
                    start_dashboard
                else
                    echo -e "${YELLOW}Dashboard already running${NC}"
                fi
                ;;
            2)
                start_capture
                ;;
            3)
                start_detection
                ;;
            4)
                read -p "Enter stage (0-4): " stage
                set_stage $stage
                ;;
            5)
                clear_data
                echo -e "${GREEN}Data cleared${NC}"
                ;;
            6)
                clear_data
                start_capture
                sleep 2
                start_detection
                echo -e "\n${GREEN}Full pipeline running!${NC}"
                echo -e "Press Enter to return to menu..."
                read
                ;;
            q|Q)
                exit 0
                ;;
            *)
                echo -e "${RED}Invalid choice${NC}"
                ;;
        esac
    done
}

# Command line mode
case "${1:-}" in
    dashboard)
        banner
        clear_data
        start_dashboard
        echo -e "\n${YELLOW}Press Ctrl+C to stop${NC}"
        wait $DASHBOARD_PID
        ;;
    capture)
        banner
        clear_data
        start_dashboard
        sleep 1
        start_capture
        echo -e "\n${YELLOW}Press Ctrl+C to stop${NC}"
        wait
        ;;
    detect)
        banner
        start_detection
        echo -e "\n${YELLOW}Press Ctrl+C to stop${NC}"
        wait $DETECT_PID
        ;;
    full)
        banner
        clear_data
        start_dashboard
        sleep 1
        start_capture
        sleep 2
        start_detection
        echo -e "\n${GREEN}Full pipeline running!${NC}"
        echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
        wait
        ;;
    stage)
        if [[ -z "${2:-}" ]]; then
            echo "Usage: $0 stage N"
            exit 1
        fi
        set_stage $2
        ;;
    help|-h|--help)
        echo "Local Debug Script for Webcam Pipeline"
        echo ""
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  (none)      Interactive menu"
        echo "  dashboard   Start dashboard only"
        echo "  capture     Start dashboard + capture"
        echo "  detect      Start detection processor"
        echo "  full        Run full pipeline locally"
        echo "  stage N     Set stage to N (0-4)"
        echo "  help        Show this help"
        echo ""
        echo "For actual demos, use ./demo.sh and deploy via cloud.expanso.io"
        ;;
    "")
        interactive_mode
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo "Run '$0 help' for usage"
        exit 1
        ;;
esac
