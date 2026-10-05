#!/usr/bin/env python3
"""tree_fixups.py <kernel_tree_root>

原厂小米树的「小修」集合（幂等）。每加一条都写清楚为什么。

为什么需要：MTK/小米的厂商树是配自家工具链编的，换来 clang + -Werror 之后
会暴露一些缺 include、旧 API 之类的小问题。这些不是我们的功能改动，只是让树能编过。

当前修的：
  1) kernel/usermode_driver.c: 用了 task_tgid() 但没 include <linux/sched/signal.h>
     （4.14 起 task_tgid 定义在 sched/signal.h:577），
     报错：implicit declaration of function 'task_tgid' [-Werror,-Wimplicit-function-declaration]
"""
import os
import sys


def read(p):
    with open(p, 'r', encoding='utf-8', errors='surrogateescape') as f:
        return f.read()


def write(p, t):
    with open(p, 'w', encoding='utf-8', errors='surrogateescape', newline='\n') as f:
        f.write(t)


def fix_usermode_sched_signal(root):
    rel = 'kernel/usermode_driver.c'
    p = os.path.join(root, rel)
    if not os.path.exists(p):
        return f'skip {rel} (not in tree)'
    t = read(p)
    if 'linux/sched/signal.h' in t:
        return f'ok   {rel} (already includes sched/signal.h)'
    if 'task_tgid' not in t:
        return f'skip {rel} (no task_tgid usage)'
    lines = t.split('\n')
    anchor = None
    for i, l in enumerate(lines[:80]):
        if l.startswith('#include <linux/'):
            anchor = i
    if anchor is None:
        return f'!!   {rel} include anchor not found'
    lines.insert(anchor + 1, '#include <linux/sched/signal.h> /* task_tgid() lives here since 4.11 */')
    write(p, '\n'.join(lines))
    return f'fix  {rel} (+#include <linux/sched/signal.h>)'


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else '.'
    print(f'=== tree_fixups on {root} ===')
    results = [fix_usermode_sched_signal(root)]
    for r in results:
        print('   ' + r)
    bad = [r for r in results if r.startswith('!!')]
    print('=== result:', 'ALL OK' if not bad else 'PROBLEM', '===')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
