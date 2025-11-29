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

# Tailscale configuration
TAILSCALE_URL="https://fepi.tail8e9db.ts.net"

# Get Tailscale DNS name (verify it's actually available)
get_tailscale_dns() {
    if command -v tailscale &> /dev/null && tailscale status &>/dev/null; then
        echo "fepi.tail8e9db.ts.net"
    fi
}

# Print banner
banner() {
    echo -e "${PURPLE}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${PURPLE}║                                                               ║${NC}"
    echo -e "${PURPLE}║   ${WHITE}EXPANSO${NC}${PURPLE}  ${CYAN}WEBCAM PIPELINE DEMO${NC}${PURPLE}                            ║${NC}"
    echo -e "${PURPLE}║                                                               ║${NC}"
    echo -e "${PURPLE}║   Deploy pipelines via ${WHITE}cloud.expanso.io${NC}${PURPLE}                      ║${NC}"
    echo -e "${PURPLE}║                                                               ║${NC}"
    echo -e "${PURPLE}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Clear all data directories and state
clear_data() {
    echo -e "${YELLOW}Clearing all data and state...${NC}"

    # Remove all video chunks and processed files
    rm -rf chunks 2>/dev/null || true
    rm -rf processed 2>/dev/null || true

    # Remove any state files
    rm -f .demo_state 2>/dev/null || true

    # Reset database (keep schema, clear data)
    rm -f pipeline.db 2>/dev/null || true

    # Recreate empty directories
    mkdir -p chunks
    mkdir -p processed/thumbnails
    for cat in left_hand_raised right_hand_raised both_hands_raised no_detection high_motion medium_motion low_motion no_motion; do
        mkdir -p "processed/$cat"
    done

    echo -e "${GREEN}All data and counts cleared.${NC}"
}

# Cleanup function - runs on exit
CLEANUP_DONE=false
cleanup() {
    # Prevent running twice
    if $CLEANUP_DONE; then
        return
    fi
    CLEANUP_DONE=true

    echo -e "\n${YELLOW}Shutting down demo...${NC}"

    # Kill dashboard
    if [[ -n "$DASHBOARD_PID" ]] && kill -0 "$DASHBOARD_PID" 2>/dev/null; then
        echo -e "${PURPLE}[DASHBOARD]${NC} Stopping..."
        kill "$DASHBOARD_PID" 2>/dev/null || true
        wait "$DASHBOARD_PID" 2>/dev/null || true
    fi

    # Kill any lingering Python processes from this demo
    pkill -f "dashboard.py" 2>/dev/null || true
    pkill -f "capture_video.py" 2>/dev/null || true
    pkill -f "process_chunks.py" 2>/dev/null || true
    pkill -f "process_motion.py" 2>/dev/null || true

    # Note: We don't stop expanso-edge - it runs via systemd
    # Clear ALL data on exit - videos, thumbnails, processed files, state
    echo -e "${YELLOW}Cleaning up all data...${NC}"
    clear_data

    echo -e "${GREEN}Demo ended. All data cleared.${NC}"
    echo -e "${CYAN}Expanso edge agent still running (systemd).${NC}"
    echo -e "Stop it with: ${WHITE}sudo systemctl stop expanso-edge${NC}"
}

trap cleanup SIGINT SIGTERM EXIT

# Check if expanso-edge is installed (optional - demo works without it)
check_expanso() {
    if ! command -v expanso-edge &> /dev/null; then
        echo -e "${YELLOW}[EXPANSO]${NC} expanso-edge not installed (optional)"
        echo ""
        echo "To install later:"
        echo -e "  ${WHITE}curl -fsSL https://get.expanso.io/edge/install.sh | bash${NC}"
        echo ""
        return 1
    fi
    return 0
}

# Check if expanso-edge systemd service is running
check_edge_running() {
    systemctl is-active --quiet expanso-edge 2>/dev/null
}

# Start expanso-edge agent via systemd
start_edge() {
    # Check if already running
    if check_edge_running; then
        echo -e "${GREEN}[EXPANSO]${NC} Edge agent already running (systemd)"
        return 0
    fi

    echo -e "${BLUE}[EXPANSO]${NC} Starting edge agent via systemd..."

    if sudo systemctl start expanso-edge 2>/dev/null; then
        sleep 2
        if check_edge_running; then
            echo -e "${GREEN}[EXPANSO]${NC} Edge agent running (systemd)"
        else
            echo -e "${YELLOW}[EXPANSO]${NC} Edge agent failed to start"
            echo -e "Check logs: ${WHITE}sudo journalctl -u expanso-edge -f${NC}"
        fi
    else
        echo -e "${YELLOW}[EXPANSO]${NC} Could not start edge agent"
        echo -e "Run: ${WHITE}sudo systemctl status expanso-edge${NC}"
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

        # Set up Tailscale Funnel if available
        if command -v tailscale &> /dev/null; then
            echo -e "${CYAN}[TAILSCALE]${NC} Setting up Funnel..."
            sudo tailscale funnel --https=443 off 2>/dev/null
            if sudo tailscale funnel --bg 8181 2>/dev/null; then
                echo -e "${GREEN}[TAILSCALE]${NC} Funnel enabled"
            else
                echo -e "${YELLOW}[TAILSCALE]${NC} Funnel setup failed (may need admin approval)"
            fi
        fi
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

    # Check if expanso-edge is available (optional)
    local has_expanso=false
    if check_expanso; then
        has_expanso=true
    fi

    # Clear data before starting
    clear_data

    # Start services
    echo -e "\n${BOLD}Starting services...${NC}\n"

    # Only start edge if available
    if $has_expanso; then
        start_edge
    fi

    start_dashboard

    local ip=$(get_ip)
    local ts_dns=$(get_tailscale_dns)
    echo -e "\n${BOLD}${GREEN}Demo ready!${NC}\n"
    echo -e "Dashboard:"
    echo -e "  Local:        ${WHITE}http://${ip}:8181${NC}"
    if [[ -n "$ts_dns" ]]; then
        echo -e "  Public:       ${WHITE}https://${ts_dns}${NC}"
    fi
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
