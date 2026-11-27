"""A seccomp filter for builds under bwrap, equivalent to docker's default.

bwrap --seccomp FD loads a classic BPF program (an array of struct
sock_filter) before running the build. This one denies, with EPERM, the
syscalls docker's default profile denies to a container with docker's default
capabilities, so a build sees what it would see under docker:

- the tables below are generated from moby's profile (github.com/moby/profiles,
  seccomp/default.json at a0fa70805f74, 2026-11-20, as vendored by docker
  29.x; last change 9ee3204f0d0c) and the syscall tables of Linux 6.12
  (arch/x86/entry/syscalls/syscall_64.tbl; scripts/syscall.tbl with arm64's
  ABIs). The generator is not part of aliBuild: regenerate when either moves;
- the syscalls docker allows only for some arguments are filtered the same
  way: clone without namespace flags (which also blocks nested user
  namespaces), clone3 failing with ENOSYS (glibc then uses clone), socket and
  socketpair for docker's address families, personality for its values;
- docker allows what it lists and denies the rest; this filter denies what docker
  does not list among the syscalls Linux 6.12 has, and answers ENOSYS to
  syscalls newer than those, so programs fall back as on an older kernel;
- a syscall from another ABI (i386 or x32 on x86_64, arm32 on aarch64) kills
  the process. Docker filters those ABIs too; builds have no use for them.
"""

import hashlib
import os
import struct

X86_64_DENY = {  # denied: 69
  "syslog": 103, "uselib": 134, "ustat": 136, "sysfs": 139, "vhangup": 153, "pivot_root": 155,
  "_sysctl": 156, "acct": 163, "settimeofday": 164, "mount": 165, "umount2": 166, "swapon": 167,
  "swapoff": 168, "reboot": 169, "sethostname": 170, "setdomainname": 171, "iopl": 172,
  "ioperm": 173, "create_module": 174, "init_module": 175, "delete_module": 176,
  "get_kernel_syms": 177, "query_module": 178, "quotactl": 179, "nfsservctl": 180, "getpmsg": 181,
  "putpmsg": 182, "afs_syscall": 183, "tuxcall": 184, "security": 185, "lookup_dcookie": 212,
  "clock_settime": 227, "vserver": 236, "mbind": 237, "set_mempolicy": 238, "get_mempolicy": 239,
  "kexec_load": 246, "add_key": 248, "request_key": 249, "keyctl": 250, "migrate_pages": 256,
  "unshare": 272, "move_pages": 279, "perf_event_open": 298, "fanotify_init": 300,
  "open_by_handle_at": 304, "setns": 308, "kcmp": 312, "finit_module": 313, "kexec_file_load": 320,
  "bpf": 321, "userfaultfd": 323, "io_uring_setup": 425, "io_uring_enter": 426,
  "io_uring_register": 427, "open_tree": 428, "move_mount": 429, "fsopen": 430, "fsconfig": 431,
  "fsmount": 432, "fspick": 433, "pidfd_getfd": 438, "process_madvise": 440, "mount_setattr": 442,
  "quotactl_fd": 443, "set_mempolicy_home_node": 450, "lsm_get_self_attr": 459,
  "lsm_set_self_attr": 460, "lsm_list_modules": 461,
}
X86_64_ARGS = {"clone": 56, "clone3": 435, "socket": 41, "socketpair": 53, "personality": 135}
AARCH64_DENY = {  # denied: 54
  "lookup_dcookie": 18, "umount2": 39, "mount": 40, "pivot_root": 41, "nfsservctl": 42,
  "vhangup": 58, "quotactl": 60, "acct": 89, "unshare": 97, "kexec_load": 104, "init_module": 105,
  "delete_module": 106, "clock_settime": 112, "syslog": 116, "reboot": 142, "sethostname": 161,
  "setdomainname": 162, "settimeofday": 170, "add_key": 217, "request_key": 218, "keyctl": 219,
  "swapon": 224, "swapoff": 225, "mbind": 235, "get_mempolicy": 236, "set_mempolicy": 237,
  "migrate_pages": 238, "move_pages": 239, "perf_event_open": 241, "fanotify_init": 262,
  "open_by_handle_at": 265, "setns": 268, "kcmp": 272, "finit_module": 273, "bpf": 280,
  "userfaultfd": 282, "kexec_file_load": 294, "io_uring_setup": 425, "io_uring_enter": 426,
  "io_uring_register": 427, "open_tree": 428, "move_mount": 429, "fsopen": 430, "fsconfig": 431,
  "fsmount": 432, "fspick": 433, "pidfd_getfd": 438, "process_madvise": 440, "mount_setattr": 442,
  "quotactl_fd": 443, "set_mempolicy_home_node": 450, "lsm_get_self_attr": 459,
  "lsm_set_self_attr": 460, "lsm_list_modules": 461,
}
AARCH64_ARGS = {"clone": 220, "clone3": 435, "socket": 198, "socketpair": 199, "personality": 92}

# Address families docker allows for socket(): < 3 (AF_UNSPEC, AF_UNIX, AF_INET) or these.
SOCKET_FAMILIES = (7, 8, 9, 10, 13, 14, 15, 16, 17, 18, 21, 22, 24, 26, 27, 28, 29, 30, 31, 32, 33,
                   35, 36, 39, 41, 42, 43, 44, 45)
SOCKETPAIR_FAMILIES = (1, 30)
PERSONALITIES = (0, 8, 0x20000, 0x20008, 0xffffffff)
# CLONE_NEWNS | CLONE_NEWCGROUP | CLONE_NEWUTS | CLONE_NEWIPC | CLONE_NEWUSER | CLONE_NEWPID | CLONE_NEWNET
CLONE_NAMESPACES = 0x7e020000

ARCHES = {  # uname -m: (AUDIT_ARCH_*, denied, filtered on arguments)
  "x86_64": (0xc000003e, X86_64_DENY, X86_64_ARGS),
  "aarch64": (0xc00000b7, AARCH64_DENY, AARCH64_ARGS),
}
X32_SYSCALL_BIT = 0x40000000
MAX_NR = 462   # the last syscall of Linux 6.12 (mseal), on both

EPERM, ENOSYS = 1, 38
RET_KILL_PROCESS, RET_ERRNO, RET_ALLOW = 0x80000000, 0x00050000, 0x7fff0000
LD_W_ABS, JEQ_K, JGE_K, JSET_K, RET_K = 0x20, 0x15, 0x35, 0x45, 0x06
NR, ARCH, ARG0 = 0, 4, 16   # offsetof(struct seccomp_data, ...); ARG0 is its low word (little endian)


def _ins(code, k=0, jt=0, jf=0):
  return (code, jt, jf, k)


def program(machine):
  """Return the filter for MACHINE (uname -m) as a list of (code, jt, jf, k)."""
  audit_arch, deny, args = ARCHES[machine]
  ret = lambda action: _ins(RET_K, action)
  prog = [_ins(LD_W_ABS, ARCH), _ins(JEQ_K, audit_arch, 1, 0), ret(RET_KILL_PROCESS),
          _ins(LD_W_ABS, NR)]
  if machine == "x86_64":
    prog += [_ins(JGE_K, X32_SYSCALL_BIT, 0, 1), ret(RET_KILL_PROCESS)]
  # Each test is followed by its own return, so no jump is longer than one
  # instruction: classic BPF jumps reach at most 255 ahead.
  for nr in sorted(deny.values()):
    prog += [_ins(JEQ_K, nr, 0, 1), ret(RET_ERRNO | EPERM)]
  prog += [_ins(JEQ_K, args["clone3"], 0, 1), ret(RET_ERRNO | ENOSYS)]
  prog += [_ins(JGE_K, MAX_NR + 1, 0, 1), ret(RET_ERRNO | ENOSYS)]

  def allow_if(name, tests):
    # if nr == name: load arg0; allow if any test passes, else EPERM
    body = [_ins(LD_W_ABS, ARG0)]
    for code, k in tests:
      body += [_ins(code, k, 0, 1), ret(RET_ALLOW)]
    body += [ret(RET_ERRNO | EPERM)]
    return [_ins(JEQ_K, args[name], 0, len(body))] + body
  prog += allow_if("socket", [(JEQ_K, f) for f in (0, 1, 2) + SOCKET_FAMILIES])
  prog += allow_if("socketpair", [(JEQ_K, f) for f in SOCKETPAIR_FAMILIES])
  prog += allow_if("personality", [(JEQ_K, p) for p in PERSONALITIES])
  # clone: EPERM with any namespace flag
  prog += [_ins(JEQ_K, args["clone"], 0, 3), _ins(LD_W_ABS, ARG0),
           _ins(JSET_K, CLONE_NAMESPACES, 0, 1), ret(RET_ERRNO | EPERM)]
  prog += [ret(RET_ALLOW)]
  return prog


def encode(prog):
  """The program as bwrap --seccomp reads it: struct sock_filter, native endian."""
  return b"".join(struct.pack("=HBBI", *ins) for ins in prog)


def filter_file(directory, machine=None):
  """Write the filter for MACHINE (default: this one) under DIRECTORY, once,
  and return its path; None if there is no filter for this machine."""
  machine = machine or os.uname().machine
  if machine not in ARCHES:
    return None
  data = encode(program(machine))
  path = os.path.join(directory, "seccomp-%s-%s.bpf" % (machine, hashlib.sha256(data).hexdigest()[:12]))
  if not os.path.exists(path):
    os.makedirs(directory, exist_ok=True)
    with open(path + ".tmp%d" % os.getpid(), "wb") as f:
      f.write(data)
    os.replace(path + ".tmp%d" % os.getpid(), path)
  return path
