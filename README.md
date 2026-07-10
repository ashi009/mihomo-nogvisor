# mihomo-nogvisor

自动构建 [vernesong/mihomo](https://github.com/vernesong/mihomo) 的 **Alpha (smart)** 分支，
去掉 `with_gvisor` build tag，产出裸 `linux/arm64` 二进制，供 ShellCrash 在
内存受限的 OpenWrt 路由器上使用。

## 为什么

两个改动叠加，专治小内存设备：

1. **去掉 `with_gvisor`** —— 该 tag 引入 tailscale 内建栈 + gvisor 用户态网络栈
   （291 个额外包，其中 195 个是 tailscale）。用真 tailscaled 做子网路由、
   且 tun `stack: system` 的场景用不到它。二进制从约 43MB 降到约 31MB。

2. **产物命名 `.upx`（但不是 upx 压缩）** —— ShellCrash 见 `.upx` 后缀只软链、
   不解压，核心便从 overlay/ubifs 执行。ubifs 透明压缩（约 2.2:1）让它在闪存上
   只占约 14MB，运行时代码段是 file-backed、可回收，省下约 44MB 常驻内存
   （对比：解压到 tmpfs 会把整份二进制钉在 RAM 里，计入不可回收的 `Shmem`）。
   参见 [juewuy/ShellCrash#1304](https://github.com/juewuy/ShellCrash/issues/1304)。

真 upx 压缩反而更费内存：它的 stub 在 exec 时 `memfd_create` 把整个程序解压回 RAM。

## 用法

在 ShellCrash 里把自定义内核链接（`custcorelink`）设为本仓库 release 的裸二进制：

```
https://github.com/ashi009/mihomo-nogvisor/releases/latest/download/mihomo-linux-arm64.upx
```

菜单：`crash` → 内核管理 → 自定义内核链接，粘贴上面的 URL。ShellCrash 会据 `.upx`
后缀自动走「只软链」路径，并持久化 `zip_type=upx` 与 `custcorelink`。之后每次更新
内核都会自动重建这套 overlay 布置，无需手工干预。

## 版本

版本号沿用 vernesong 的命名 `alpha-smart-<短 commit>`，通过 ldflags 打进
`constant.Version`。rolling 的 `latest` tag 始终指向最新 commit 的构建。

## 更新

- workflow 每日 04:00 UTC 追一次上游，也可在 Actions 页手动触发。
- ShellCrash 的定时任务 111（自动更新内核）比对的是 ShellCrash 官方 `bin/version`，
  不会因本仓库更新而触发。要更新到最新，手动重新拉取自定义内核即可
  （`custcorelink` 的 URL 恒指向 `latest`）。

## 构建配方

与 vernesong 官方一致，仅去掉 `-tags with_gvisor`：

```
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 GOARM64=v8.0 \
  go build -trimpath \
    -ldflags '-X "github.com/metacubex/mihomo/constant.Version=alpha-smart-<hash>" -w -s -buildid=' \
    -o mihomo-linux-arm64.upx .
```
