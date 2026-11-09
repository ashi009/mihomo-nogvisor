[ -z "${IPKG_INSTROOT:-}" ] && [ "${IPKG_NO_SCRIPT:-0}" != 1 ] || exit 0
[ -f /etc/rc.common ] || exit 0
restart=/tmp/mihomo-package.restart
case "$1" in
    pre-install|pre-upgrade)
        rm -f "$restart"
        if [ -x /etc/init.d/mihomo ] && /etc/init.d/mihomo running; then
            touch "$restart"
            /etc/init.d/mihomo stop
        fi
        ;;
    post-install)
        mkdir -p -m 700 /etc/mihomo
        /etc/init.d/mihomo enable
        rm -f "$restart"
        if [ -s /etc/mihomo/config.yaml ]; then
            /etc/init.d/mihomo start
        fi
        ;;
    post-upgrade)
        if [ -f "$restart" ]; then
            rm -f "$restart"
            /etc/init.d/mihomo start
        fi
        ;;
    pre-deinstall)
        /etc/init.d/mihomo stop
        /etc/init.d/mihomo disable
        /usr/libexec/mihomo-firewall remove
        rm -f "$restart"
        ;;
esac
