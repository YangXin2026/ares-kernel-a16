#!/usr/bin/env python3
"""ksu_hooks.py <kernel_tree_root>

给「原厂小米树」补上 ReSukiSU 手工 hook 需要的调用点。

原厂树 (xiaomi-mt6893-dev/kernel_xiaomi_mt6893) 里没有这些钩子，ReSukiSU 的
manual_hook_check.mk 会直接 error 掉编译：
    -- You lost ksu_handle_execveat hook in your kernel
    manual_hook_check.mk:70: *** You should integrate ReSukiSU in your kernel.. Stop.

需要补的（按 manual_hook_check.mk 的要求）：
    fs/exec.c        ksu_handle_execveat
    fs/open.c        ksu_handle_faccessat
    fs/stat.c        ksu_handle_stat / ksu_handle_newfstat_ret / ksu_handle_fstat64_ret
    kernel/reboot.c  ksu_handle_sys_reboot
（setuid / initrc / input 走 LSM 与 input_handler，由 CONFIG_KSU_MANUAL_HOOK_AUTO_* 自动处理）

幂等：靠 guard 片段判断是否已插过；锚点找不到会明确报错，方便下一轮修。
"""
import os
import re
import sys

MARK = 'CONFIG_KSU_MANUAL_HOOK'


def read(p):
    with open(p, 'r', encoding='utf-8', errors='surrogateescape') as f:
        return f.read()


def write(p, t):
    with open(p, 'w', encoding='utf-8', errors='surrogateescape', newline='\n') as f:
        f.write(t)


def find_line(lines, pattern, start=0):
    rx = re.compile(pattern)
    for i in range(start, len(lines)):
        if rx.match(lines[i]):
            return i
    return -1


EXTERN_EXEC = ['#ifdef ' + MARK,
               '__attribute__((hot))',
               'extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,',
               '\t\t\t\tvoid *argv, void *envp, int *flags);',
               '#endif', '']
EXTERN_OPEN = ['#ifdef ' + MARK,
               '__attribute__((hot))',
               'extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user,',
               '\t\t\t\tint *mode, int *flags);',
               '#endif', '']
EXTERN_STAT = ['#ifdef ' + MARK,
               '__attribute__((hot))',
               'extern int ksu_handle_stat(int *dfd, const char __user **filename_user,',
               '\t\t\t\tint *flags);',
               '',
               'extern void ksu_handle_newfstat_ret(unsigned int *fd, struct stat __user **statbuf_ptr);',
               '#if defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64)',
               'extern void ksu_handle_fstat64_ret(unsigned long *fd, struct stat64 __user **statbuf_ptr);',
               '#endif',
               '#endif', '']
EXTERN_REBOOT = ['#ifdef ' + MARK,
                 'extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);',
                 '#endif', '']


def call_block(call):
    return ['#ifdef ' + MARK, '\t' + call, '#endif', '']


# (文件, [(名字, 'before'|'after', 锚点正则, 插入块, guard 片段)])
PLAN = [
    ('fs/exec.c', [
        ('exec-decl', 'before', r'^static int do_execveat_common\(', EXTERN_EXEC, 'ksu_handle_execveat(int *fd'),
        ('execveat-call', 'before', r'^\treturn __do_execve_file\(fd, filename, argv, envp, flags, NULL\);$',
         call_block('ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);'), 'ksu_handle_execveat(&fd'),
    ]),
    ('fs/open.c', [
        ('faccessat-decl', 'before', r'^SYSCALL_DEFINE3\(faccessat,', EXTERN_OPEN, 'ksu_handle_faccessat(int *dfd'),
        ('faccessat-call', 'before', r'^\tif \(mode & ~S_IRWXO\)',
         call_block('ksu_handle_faccessat(&dfd, &filename, &mode, NULL);'), 'ksu_handle_faccessat(&dfd'),
    ]),
    ('fs/stat.c', [
        ('stat-decl', 'before', r'^SYSCALL_DEFINE4\(newfstatat,', EXTERN_STAT, 'ksu_handle_stat(int *dfd'),
        ('newfstatat-call', 'before', r'^\terror = vfs_fstatat\(dfd, filename, &stat, flag\);$',
         call_block('ksu_handle_stat(&dfd, &filename, &flag);'), 'ksu_handle_stat(&dfd'),
    ]),
    ('kernel/reboot.c', [
        ('reboot-decl', 'before', r'^SYSCALL_DEFINE4\(reboot,', EXTERN_REBOOT, 'ksu_handle_sys_reboot(int magic1'),
        ('sys_reboot-call', 'before', r'^\t/\* We only trust the superuser with rebooting the system\. \*/$',
         call_block('ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);'), 'ksu_handle_sys_reboot(magic1, magic2'),
    ]),
]

# stat.c 里按「函数区域」逐个插，避免 \treturn error; 之类锚点撞车
STAT_FUNC_OPS = [
    (r'^SYSCALL_DEFINE2\(newfstat,', r'^\treturn error;$', 'ksu_handle_newfstat_ret(&fd, &statbuf);', 'newfstat'),
    (r'^SYSCALL_DEFINE2\(fstat64,', r'^\treturn error;$', 'ksu_handle_fstat64_ret(&fd, &statbuf);', 'fstat64'),
    (r'^SYSCALL_DEFINE4\(fstatat64,', r'^\terror = vfs_fstatat\(dfd, filename, &stat, flag\);$',
     'ksu_handle_stat(&dfd, &filename, &flag);', 'fstatat64'),
]


def apply_ops(root, rel, ops, search_from_zero=True):
    path = os.path.join(root, rel)
    if not os.path.exists(path):
        print(f'!! 找不到 {rel}')
        return False
    text = read(path)
    lines = text.split('\n')
    ok = True
    for name, kind, anchor, block, guard in ops:
        if guard in '\n'.join(lines):
            print(f'   跳过 {rel}:{name}（已插过）')
            continue
        idx = find_line(lines, anchor)
        if idx < 0:
            print(f'   !! {rel}:{name} 锚点没找到 -> {anchor}')
            ok = False
            continue
        if kind == 'before':
            lines = lines[:idx] + block + lines[idx:]
        else:
            lines = lines[:idx + 1] + block + lines[idx + 1:]
        print(f'   ok {rel}:{name} @ 原第 {idx + 1} 行')
    write(path, '\n'.join(lines))
    return ok


def patch_stat_funcs(root):
    path = os.path.join(root, 'fs/stat.c')
    lines = read(path).split('\n')
    changed = False
    for sig, anchor, call, tag in STAT_FUNC_OPS:
        i = find_line(lines, sig)
        if i < 0:
            print(f'   !! fs/stat.c:{tag} 函数签名没找到')
            continue
        # guard 只看「本函数区域内」，否则会和别的函数撞名（newfstatat 与 fstatat64 都调 ksu_handle_stat）
        region = '\n'.join(lines[i:i + 20])
        if call in region:
            print(f'   跳过 fs/stat.c:{tag}（本函数内已插过）')
            continue
        j = find_line(lines, anchor, i)
        if j < 0:
            print(f'   !! fs/stat.c:{tag} 锚点没找到')
            continue
        lines = lines[:j] + call_block(call) + lines[j:]
        print(f'   ok fs/stat.c:{tag} @ 第 {j + 1} 行')
        changed = True
    if changed:
        write(path, '\n'.join(lines))


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else '.'
    print(f'=== 给 {root} 补 ReSukiSU 手工 hook ===')
    allok = True
    for rel, ops in PLAN:
        allok &= apply_ops(root, rel, ops)
    patch_stat_funcs(root)

    print('=== 自检（manual_hook_check.mk 关心的符号） ===')
    checks = {
        'fs/exec.c': ['ksu_handle_execveat'],
        'fs/open.c': ['ksu_handle_faccessat'],
        'fs/stat.c': ['ksu_handle_stat', 'ksu_handle_newfstat_ret', 'ksu_handle_fstat64_ret'],
        'kernel/reboot.c': ['ksu_handle_sys_reboot'],
    }
    for rel, syms in checks.items():
        p = os.path.join(root, rel)
        txt = read(p) if os.path.exists(p) else ''
        for s in syms:
            hit = s in txt
            print(f'   {"OK  " if hit else "MISS"} {rel}: {s}')
            allok &= hit
    bad = {'fs/read_write.c': 'ksu_vfs_read_hook',
           'security/selinux/hooks.c': 'is_ksu_transition',
           'security/security.c': 'ksu_handle_rename'}
    for rel, s in bad.items():
        p = os.path.join(root, rel)
        txt = read(p) if os.path.exists(p) else ''
        if s in txt:
            print(f'   !! {rel} 含不兼容钩子 {s}')
            allok = False
    print('=== 结果:', 'ALL OK' if allok else '有问题，见上面 !!', '===')
    return 0 if allok else 1


if __name__ == '__main__':
    sys.exit(main())
