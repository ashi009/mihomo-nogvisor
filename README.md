# mihomo-nogvisor

面向 OpenWrt 的单进程 Mihomo Smart + Tailscale 原生路由服务。
使用内核 TUN，不引入 gVisor；通过 Jsonnet 生成配置，procd 管理生命周期，
Zashboard 提供运行界面。无需 ShellCrash 或独立 Tailscale/LuCI 应用。

## 安装

[Native Linux CI](../../actions/workflows/native.yml) 的构建产物包含 ARM64 裸二进制、
APK、校验和及体积报告。APK 面向使用 APK 3 的 OpenWrt/ImmortalWrt；
目前不提供 opkg/IPK 包。

先把生成的配置放到 `/etc/mihomo/config.yaml`，再安装下载的 APK：

```sh
apk add --allow-untrusted /tmp/mihomo-native-*.apk
```

当前包未签名。安装会注册、启用 procd 服务；存在配置时自动启动。
升级会重启原本运行的服务，保持主动停止的服务不启动。
包不包含私有配置、订阅或身份状态，卸载也不删除这些数据。
包定义和生命周期行为分别由 [打包脚本](scripts/package-native.sh) 和
[APK hooks](openwrt/apk-hooks.sh) 管理。

从旧服务迁移时，先停止 ShellCrash 和 Tailscale，将需要的规则、订阅、UI 缓存
移到 `/etc/mihomo`，将原 Tailscale 状态目录移到配置指定的 `state-dir`。
移除旧服务后安装 APK；已有身份不需要重新登录。

## 配置与登录

[router.jsonnet](config/router.jsonnet) 将已有 Mihomo 配置与
[透明代理策略](config/capture.libsonnet)、[Tailscale 配置](config/tailnet.libsonnet)
组合。私有 Jsonnet 可以直接导入这些模块；端口例外、DNS 和路由参数均由它们生成。

默认只指定 LAN 接口 `br-lan`。核心读取系统 hostname，并从该接口的实际 IPv4
地址推导捕获范围和 Tailscale 广播路由；同一份 YAML 可用于不同路由器。
接口不存在或没有可用 IPv4 地址时启动失败，不会扩大捕获范围。
修改 hostname 或 LAN 地址后需重启服务，重新读取主机信息。

[firewall.libsonnet](config/firewall.libsonnet) 从同一份配置生成 `firewall.uci`，
与 YAML 一起部署到 `/etc/mihomo/`。APK 在服务启动时同步它拥有的 UCI sections，
由 fw4 限制 tailnet 只向 LAN 转发，保留 masquerade 和 MSS 调整。
捕获和 DNS 重定向只处理 LAN 入站；普通路由器管理仍可访问，Mihomo 的代理、
控制器及 DNS 监听端口则禁止从 tailnet 访问。端口列表从 Jsonnet 的配置对象推导，
更改监听端口后需同时重新生成两个文件并重启服务。
包直接绑定 Tailscale 设备，不需要单独的 LuCI 网络接口。升级会迁移原有的
Tailscale UCI 配置；卸载仅删除包拥有的 sections，保留其他防火墙配置。

原生捕获策略通过 `route-exclude-address-set: [cn-ip]` 将同名 IP 规则集交给
nftables，随规则集更新同步。真实 CN-IP 目的地址直接转发，跳过 Mihomo 的规则判断；
fake-IP 仍进入 Mihomo，CN-domain 规则也保留在那里。已有端口及 UDP 例外不变。

新路由器可在本机用 OAuth 换取一次性、非临时节点的 auth key。
OAuth 客户端需要 `auth_keys` 权限及相应的 tags，见
[Tailscale OAuth 文档](https://tailscale.com/docs/features/oauth-clients)。
OAuth secret 只保存在部署机；凭据文件路径相对于生成的 `provision.json`，也可用绝对路径。

```sh
jsonnet config/provision.jsonnet \
  --tla-str clientId=YOUR_CLIENT_ID \
  --tla-str clientSecretFile=/private/path/oauth.secret \
  --tla-code 'tags=["tag:router"]' > provision.json
python3 scripts/provision-tailnet.py provision.json secrets/tailnet.key
```

该脚本在本机运行版本锁定的官方 `get-authkey`，需要 Go 和网络访问。
它只写出权限为 0600 的节点 auth key，不覆盖已有文件，也不打印密钥。
将该文件单独传到路由器 `/etc/mihomo/secrets/tailnet.key`，保持目录 0700、文件 0600，
并通过 Jsonnet 的 `authKeyFile='secrets/tailnet.key'` 引用。
路由器自行生成并保存身份状态。首次登录后若要删除已使用的 key 文件，
先从 Jsonnet 清空 `authKeyFile` 并重新生成配置。

## 开发与更新

[PATCHES.md](PATCHES.md) 索引上游版本、独立补丁、构建与 Linux 测试入口；
补丁的原因和来源保留在各自文件头。构建标签由 [native-tags](scripts/native-tags) 管理。
二进制从 overlay 直接执行，避免将完整核心解压并常驻 tmpfs。

[上游更新 workflow](.github/workflows/upstream.yml) 按需触发，生成含 changelog 的 PR，
不定时运行，也不自动合并。Native CI 验证 Linux 路由/DNS、APK 安装与升级生命周期，
并报告裸二进制、gzip 和 APK 的大小。

旧 ShellCrash 用的 [latest release](../../releases/tag/latest) 仍保留手动发布；
它与原生服务 APK 是不同产物。
