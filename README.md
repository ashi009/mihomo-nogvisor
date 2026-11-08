# mihomo-nogvisor

自动构建 [vernesong/mihomo](https://github.com/vernesong/mihomo) 的 **Alpha (smart)** 分支，
去掉 `with_gvisor` build tag，产出裸 `linux/arm64` 二进制，供 ShellCrash 在
内存受限的 OpenWrt 路由器上使用。

## 为什么

原生路由器版本已在 20.1 通过 procd 常驻：内嵌 Tailscale 原生 TUN 后端，
通过 Jsonnet 配置透明代理拦截，替换 ShellCrash 和独立 Tailscale。
独立上游补丁队列、构建、测试和部署记录见
[PATCHES.md](PATCHES.md)。原生版本按需通过 PR 跟踪上游，附变更摘要及完整
changelog，Linux 检查通过后转为待审。旧 ShellCrash `latest` 发布改为手动触发。

两件事叠加，专治小内存设备：

1. **去掉 `with_gvisor`** —— 该 tag 引入 tailscale 内建栈 + gvisor 用户态网络栈
   （291 个额外包，其中 195 个是 tailscale）。用真 tailscaled 做子网路由、
   且 tun `stack: system` 的场景用不到它。二进制从约 43MB 降到约 31MB。

2. **让核心从 rom 原地执行，而非解压到内存** —— OpenWrt 上 `$TMPDIR` 是 tmpfs（RAM），
   把核心解压到那里会把整份二进制钉在不可回收的 `Shmem` 里。改为把裸二进制存于
   `$BINDIR`（overlay/ubifs，透明压缩约 2.2:1，闪存只占约 14MB）、`$TMPDIR` 软链过去，
   运行时代码段就是 file-backed、可回收，省下约 44MB 常驻内存。
   参见 [juewuy/ShellCrash#1304](https://github.com/juewuy/ShellCrash/issues/1304)、
   [#1305](https://github.com/juewuy/ShellCrash/pull/1305)。

   真 upx 压缩反而更费内存：它的 stub 在 exec 时 `memfd_create` 把整个程序解压回 RAM。

## 产物

`latest` release 发布 `mihomo-linux-arm64.gz`（gzip 封装的裸二进制，下载约 11MB）。
需 ShellCrash [#1305](https://github.com/juewuy/ShellCrash/pull/1305) 及以后版本 ——
它在 tmpfs + 压缩 rom 设备上会把解出的裸二进制存于 rom 并软链，运行时 `RssShmem` 归零。

## 用法

在 ShellCrash 里把自定义内核链接（`custcorelink`）设为：

```
https://github.com/ashi009/mihomo-nogvisor/releases/latest/download/mihomo-linux-arm64.gz
```

菜单：`crash` → 内核管理 → 自定义内核链接，粘贴上面的 URL。ShellCrash 会持久化
`zip_type` 与 `custcorelink`，之后每次更新内核都会自动重建这套布置，无需手工干预。

## 版本

版本号沿用 vernesong 的命名 `alpha-smart-<短 commit>`，通过 ldflags 打进
`constant.Version`。rolling 的 `latest` tag 始终指向最新 commit 的构建。

## 更新

- 原生版本按需检查上游并创建更新 PR，没有定时任务；可在 Actions 页或通过 Dot 触发。
- 旧版 `build` workflow 仅保留手动发布，不再自动跳过 PR 更新上游。
- ShellCrash 的定时任务 111（自动更新内核）比对的是 ShellCrash 官方 `bin/version`，
  不会因本仓库更新而触发。要更新到最新，手动重新拉取自定义内核即可
  （`custcorelink` 的 URL 恒指向 `latest`）。

## 构建配方

与 vernesong 官方一致，仅去掉 `-tags with_gvisor`，产物再 gzip：

```
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 GOARM64=v8.0 \
  go build -trimpath \
    -ldflags '-X "github.com/metacubex/mihomo/constant.Version=alpha-smart-<hash>" -w -s -buildid=' \
    -o mihomo-linux-arm64 .
gzip -c -9 mihomo-linux-arm64 > mihomo-linux-arm64.gz
```
