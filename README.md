# ares-kernel-a16

Redmi K40 游戏增强版 / POCO F3 GT (ares, MT6893) 的自建内核。

- 源码: `seriaTvT/kernel_mt6893@chopin_kvm` (Linux 4.14.357-openela, 自带 ares_defconfig)
- 工具链: Mandi-Sa clang llvm23 (amd64-kernel-arm_static-23)
- 可选: KernelSU (ReSukiSU 手工 hook) / Baseband-guard
- 产物: Image.gz + dtb + System.map + config，直接发 Release（方便走镜像下载）

跑法: Actions -> Build ares kernel -> Run workflow
