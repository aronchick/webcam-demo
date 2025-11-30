#!/bin/bash
#
# Strip unnecessary services from Raspberry Pi for clean demo setup
#
# Run with: sudo ./strip-services.sh
#
# This disables services not needed for the webcam demo.
# To restore: sudo ./strip-services.sh --restore
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Services to disable (safe to remove for headless demo Pi)
DISABLE_SERVICES=(
    # Printing - not needed
    "cups.service"
    "cups-browsed.service"

    # Bluetooth - not using
    "bluetooth.service"

    # Modem/cellular - not using
    "ModemManager.service"

    # NFS - not using
    "nfs-blkmap.service"
    "rpcbind.service"

    # Desktop/GUI stuff (if running headless)
    "lightdm.service"
    "accounts-daemon.service"
    "colord.service"
    "udisks2.service"

    # mDNS - optional (disable if not using .local hostnames)
    # "avahi-daemon.service"
)

# Services that MUST stay enabled
KEEP_SERVICES=(
    "dbus.service"
    "NetworkManager.service"
    "ssh.service"
    "systemd-journald.service"
    "systemd-logind.service"
    "systemd-timesyncd.service"
    "systemd-udevd.service"
    "polkit.service"
    "wpa_supplicant.service"
    "tailscaled.service"
    "expanso-edge.service"
    "cron.service"
)

check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}This script must be run as root (use sudo)${NC}"
        exit 1
    fi
}

show_status() {
    echo -e "${YELLOW}Current service status:${NC}\n"

    echo "Services that will be DISABLED:"
    for svc in "${DISABLE_SERVICES[@]}"; do
        status=$(systemctl is-active "$svc" 2>/dev/null || echo "inactive")
        enabled=$(systemctl is-enabled "$svc" 2>/dev/null || echo "disabled")
        if [[ "$status" == "active" ]]; then
            echo -e "  ${RED}●${NC} $svc (running, $enabled)"
        else
            echo -e "  ${GREEN}○${NC} $svc ($status, $enabled)"
        fi
    done

    echo ""
    echo "Services that will STAY enabled:"
    for svc in "${KEEP_SERVICES[@]}"; do
        status=$(systemctl is-active "$svc" 2>/dev/null || echo "inactive")
        if [[ "$status" == "active" ]]; then
            echo -e "  ${GREEN}●${NC} $svc"
        else
            echo -e "  ${YELLOW}○${NC} $svc ($status)"
        fi
    done
}

disable_services() {
    echo -e "${YELLOW}Disabling unnecessary services...${NC}\n"

    for svc in "${DISABLE_SERVICES[@]}"; do
        if systemctl is-enabled "$svc" &>/dev/null || systemctl is-active "$svc" &>/dev/null; then
            echo -n "Disabling $svc... "
            systemctl stop "$svc" 2>/dev/null || true
            systemctl disable "$svc" 2>/dev/null || true
            systemctl mask "$svc" 2>/dev/null || true
            echo -e "${GREEN}done${NC}"
        else
            echo -e "Skipping $svc (already disabled)"
        fi
    done

    echo ""
    echo -e "${GREEN}Done! Services disabled.${NC}"
    echo ""
    echo "Reboot recommended: sudo reboot"
}

restore_services() {
    echo -e "${YELLOW}Restoring services...${NC}\n"

    for svc in "${DISABLE_SERVICES[@]}"; do
        echo -n "Restoring $svc... "
        systemctl unmask "$svc" 2>/dev/null || true
        systemctl enable "$svc" 2>/dev/null || true
        echo -e "${GREEN}done${NC}"
    done

    echo ""
    echo -e "${GREEN}Done! Services restored.${NC}"
    echo "Reboot to start them: sudo reboot"
}

disable_gui() {
    echo -e "${YELLOW}Disabling GUI desktop (boot to CLI)...${NC}"

    systemctl set-default multi-user.target
    systemctl stop lightdm 2>/dev/null || true

    echo -e "${GREEN}Done! Pi will boot to command line.${NC}"
    echo "To restore GUI: sudo systemctl set-default graphical.target"
}

show_help() {
    echo "Strip unnecessary services from Raspberry Pi"
    echo ""
    echo "Usage: sudo $0 [command]"
    echo ""
    echo "Commands:"
    echo "  (none)     Show current status"
    echo "  disable    Disable unnecessary services"
    echo "  restore    Restore disabled services"
    echo "  headless   Disable GUI (boot to CLI)"
    echo "  help       Show this help"
    echo ""
    echo "Safe to disable:"
    for svc in "${DISABLE_SERVICES[@]}"; do
        echo "  - $svc"
    done
}

# Main
case "${1:-}" in
    disable)
        check_root
        disable_services
        ;;
    restore)
        check_root
        restore_services
        ;;
    headless)
        check_root
        disable_gui
        ;;
    help|-h|--help)
        show_help
        ;;
    "")
        show_status
        echo ""
        echo -e "Run ${YELLOW}sudo $0 disable${NC} to disable these services"
        echo -e "Run ${YELLOW}sudo $0 headless${NC} to also disable GUI"
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        show_help
        exit 1
        ;;
esac
