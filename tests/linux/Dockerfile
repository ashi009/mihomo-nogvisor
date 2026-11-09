FROM alpine:3.22 AS openwrt
RUN apk add --no-cache curl
RUN curl -fsSL https://downloads.openwrt.org/releases/25.12.0/targets/armsr/armv8/openwrt-25.12.0-armsr-armv8-rootfs.tar.gz -o /rootfs.tar.gz && \
    echo 'd5e42b396d7f64697c65a884912107b49e05d2b2f2c00a251f94c44f8deef507  /rootfs.tar.gz' | sha256sum -c - && \
    mkdir /rootfs && tar -xzf /rootfs.tar.gz -C /rootfs

FROM alpine:3.23@sha256:469c9ea410b9215eaee7976ba6c0639039b444be8e5d638f7abbada189971eb2
RUN apk add --no-cache iproute2 iptables nftables python3 curl json-c
COPY --from=openwrt /rootfs/sbin/uci /rootfs/sbin/fw4 /sbin/
COPY --from=openwrt /rootfs/usr/bin/ucode /usr/bin/ucode
COPY --from=openwrt /rootfs/lib/libblobmsg_json.so.* /rootfs/lib/libubox.so.* /rootfs/lib/libubus.so.* /rootfs/lib/libuci.so.* /lib/
COPY --from=openwrt /rootfs/usr/lib/libucode.so.* /usr/lib/
COPY --from=openwrt /rootfs/usr/lib/ucode/fs.so /rootfs/usr/lib/ucode/uci.so /rootfs/usr/lib/ucode/ubus.so /usr/lib/ucode/
COPY --from=openwrt /rootfs/usr/share/firewall4 /usr/share/firewall4
COPY --from=openwrt /rootfs/usr/share/ucode/fw4.uc /usr/share/ucode/fw4.uc
RUN ln -s ucode /usr/bin/utpl && mkdir -p /etc/config /etc/nftables.d /var/run /var/lock /tmp/.uci
