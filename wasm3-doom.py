#!/usr/bin/env python3

import os, sys, struct, time, io, inspect
import wasm3
import numpy

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "true"

import pygame

scriptpath = os.path.dirname(os.path.realpath(__file__))
wasm_fn = os.path.join(scriptpath, "./wasidoom.wasm")

WAD = "./doom1.wad"

# Prepare Wasm3 engine

env = wasm3.Environment()
rt = env.new_runtime(32*1024)
with open(wasm_fn, "rb") as f:
    mod = env.parse_module(f.read())
    rt.load(mod)

# Prepare PyGame

img_size = (320, 200)
(img_w, img_h) = img_size
scr_size = (img_w*2, img_h*2)
pygame.init()
surface = pygame.display.set_mode(scr_size)
pygame.display.set_caption("Wasm3 DOOM")
clock = pygame.time.Clock()

# WASI emulation

class FileType:
    DIR = 3
    REG = 4

class WasiErrno:
    SUCCESS = 0
    BADF    = 8
    INVAL   = 28
    NOENT   = 44

def errToStr(err):
    strings = {
        0:  "ESUCCESS",
        8:  "EBADF",
        28: "EINVAL",
        44: "ENOENT",
    }
    return strings.get(err, f"<unknown:{err}>")

def whenceToStr(err):
    strings = {
        0:  "SET",
        1:  "CUR",
        2:  "END",
    }
    return strings.get(err, f"<unknown:{err}>")

f_doom = open(WAD, "rb")
f_scr = io.BytesIO()
f_pal = io.BytesIO()

def stdout_write(data):
    print(data.decode(), end='')

def update_screen():
    for event in pygame.event.get():
        if (event.type == pygame.QUIT or
            (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE)):
            pygame.quit()
            sys.exit()

    if len(f_pal.getbuffer()) != 3*256 or len(f_scr.getbuffer()) != 320*200:
        return

    scr = numpy.frombuffer(f_scr.getbuffer(), dtype=numpy.uint8)
    pal = numpy.frombuffer(f_pal.getbuffer(), dtype=numpy.uint8).reshape((256, 3))

    # Convert indexed color to RGB
    arr = pal[scr]

    data = arr.astype(numpy.uint8).tobytes()

    img = pygame.image.frombuffer(data, img_size, "RGB")

    img_scaled = pygame.transform.scale(img, scr_size)
    surface.blit(img_scaled, (0, 0))
    pygame.display.flip()

    clock.tick(60)


vfs = {
    "<stdin>":  { "fd" : 0, "type": FileType.REG, },
    "<stdout>": { "fd" : 1, "type": FileType.REG, "write": stdout_write },
    "<stderr>": { "fd" : 2, "type": FileType.REG, "write": stdout_write },
    "/":        { "fd" : 3, "type": FileType.DIR, "dirname" : b"/\x00"  },
    "./doom1.wad":   { "fd": 5, "type": FileType.REG, "file": f_doom, "exists": True  },
    "./screen.data": { "fd": 6, "type": FileType.REG, "file": f_scr,  "exists": False },
    "./palette.raw": { "fd": 7, "type": FileType.REG, "file": f_pal,  "exists": False },
}
vfs_fds = { v["fd"] : v for (k,v) in vfs.items() }

def wasi_generic_api(func):
    for modname in ["wasi_unstable", "wasi_snapshot_preview1"]:
        mod.link_function(modname, func.__name__, func)
    return func

def trace(*args, **kwargs):
    #print(inspect.stack()[1].function, *args, file=sys.stderr, **kwargs)
    return

@wasi_generic_api
def args_sizes_get(argc, buf_sz):
    mem = rt.get_memory(0)
    struct.pack_into("<I", mem, argc,   3)
    struct.pack_into("<I", mem, buf_sz, 32)
    return WasiErrno.SUCCESS

@wasi_generic_api
def args_get(argv, buf):
    mem = rt.get_memory(0)
    struct.pack_into("<I", mem, argv, buf)
    struct.pack_into("5s", mem, buf, b"doom\0")
    return WasiErrno.SUCCESS

@wasi_generic_api
def environ_sizes_get(envc, buf_sz):
    mem = rt.get_memory(0)
    struct.pack_into("<I", mem, envc,   1)
    struct.pack_into("<I", mem, buf_sz, 32)
    return WasiErrno.SUCCESS

@wasi_generic_api
def environ_get(envs, buf):
    mem = rt.get_memory(0)
    struct.pack_into("<I", mem, envs, buf)
    struct.pack_into("7s", mem, buf, b"HOME=/\0")
    return WasiErrno.SUCCESS

@wasi_generic_api
def fd_prestat_get(fd, result):
    mem = rt.get_memory(0)
    if fd != 3:
        trace(f"fd:{fd} => EBADF")
        return WasiErrno.BADF

    name_len = len(vfs_fds[fd]["dirname"])
    struct.pack_into("<II", mem, result, 0, name_len)
    trace(f"fd:{fd} | type:0, name_len:{name_len} => ESUCCESS")
    return WasiErrno.SUCCESS

@wasi_generic_api
def fd_fdstat_get(fd, result):
    mem = rt.get_memory(0)
    if fd not in vfs_fds:
        trace(f"fd:{fd} => BADF")
        return WasiErrno.BADF

    all1 = numpy.iinfo(numpy.uint64).max
    f = vfs_fds[fd]
    struct.pack_into("<BxHxxxxQQ", mem, result, f["type"], 0, all1, all1)
    trace(f"fd:{fd} => ESUCCESS")
    return WasiErrno.SUCCESS

@wasi_generic_api
def fd_prestat_dir_name(fd, name, name_len):
    mem = rt.get_memory(0)
    path = vfs_fds[fd]["dirname"]
    struct.pack_into("3s", mem, name, path)
    trace(f"fd:{fd}, len:{name_len} | path:{path.decode()} => ESUCCESS")
    return WasiErrno.SUCCESS

@wasi_generic_api
def path_filestat_get(fd, flags, path, path_len, buff):
    mem = rt.get_memory(0)
    path = mem[path:path+path_len].tobytes().decode()

    if path not in vfs or not vfs[path]["exists"]:
        trace(f"fd:{fd}, flags:{hex(flags)}, path:{path} => ENOENT")
        return WasiErrno.NOENT

    f = vfs[path]
    if "size" in f:
        size = f["size"]
    elif "file" in f:
        fh = f["file"]
        cur = fh.tell()
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(cur, 0)

    struct.pack_into("<QQBxxxxxxxQQQQQ", mem, buff, 1, 1, f["type"], 1, size, 0, 0 , 0)
    trace(f"fd:{fd}, flags:{hex(flags)}, path:{path} | fs.size:{size} => ESUCCESS")
    return WasiErrno.SUCCESS

@wasi_generic_api
def path_open(dirfd, dirflags, path, path_len, oflags, fs_rights_base, fs_rights_inheriting, fs_flags, fd):
    mem = rt.get_memory(0)
    path = mem[path:path+path_len].tobytes().decode()

    if path not in vfs:
        fd_val = 0
        ret = WasiErrno.NOENT
    else:
        f = vfs[path]
        f["exists"] = True
        fd_val = f["fd"]
        struct.pack_into("<I", mem, fd, fd_val)
        ret = WasiErrno.SUCCESS

    trace(f"dirfd:{dirfd}, dirflags:{hex(dirflags)}, path:{path}, oflags:{hex(oflags)}, fs_flags:{hex(fs_flags)} | fd:{fd_val} => {errToStr(ret)}")
    return ret

@wasi_generic_api
def fd_seek(fd, offset, whence, result):
    mem = rt.get_memory(0)

    if fd not in vfs_fds:
        trace(f"=> EBADF")
        return WasiErrno.BADF

    if "file" not in vfs_fds[fd]:
        trace(f"=> EINVAL")
        return WasiErrno.INVAL

    f = vfs_fds[fd]["file"]
    f.seek(offset, whence)
    res = f.tell()
    struct.pack_into("<Q", mem, result, res)
    trace(f"fd:{fd}, offset:{offset}, whence:{whenceToStr(whence)} | result:{res} => ESUCCESS")
    return WasiErrno.SUCCESS

@wasi_generic_api
def fd_close(fd):
    trace(f"fd:{fd} => ESUCCESS")
    return WasiErrno.SUCCESS

@wasi_generic_api
def fd_read(fd, iovs, iovs_len, nread):
    mem = rt.get_memory(0)

    data_sz = 0
    for i in range(iovs_len):
        iov = iovs+8*i
        (off, size) = struct.unpack("<II", mem[iov:iov+8])
        data_sz += size

    data = None
    if fd in vfs_fds:
        if "read" in vfs_fds[fd]:
            data = vfs_fds[fd]["read"](data_sz)
        elif "file" in vfs_fds[fd]:
            data = vfs_fds[fd]["file"].read(data_sz)

    if not data:
        trace(f"fd:{fd} => EBADF")
        return WasiErrno.BADF

    data_off = 0
    for i in range(iovs_len):
        iov = iovs+8*i
        (off, size) = struct.unpack("<II", mem[iov:iov+8])
        d = data[data_off:data_off+size]
        mem[off:off+len(d)] = d
        data_off += len(d)

    struct.pack_into("<I", mem, nread, data_off)
    trace(f"fd:{fd} | nread:{data_off} => ESUCCESS")
    return WasiErrno.SUCCESS

@wasi_generic_api
def fd_write(fd, iovs, iovs_len, nwritten):
    mem = rt.get_memory(0)
    # get data
    data = b''
    for i in range(iovs_len):
        iov = iovs+8*i
        (off, size) = struct.unpack("<II", mem[iov:iov+8])
        data += mem[off:off+size].tobytes()

    if fd not in vfs_fds:
        trace(f"fd:{fd} => BADF")
        return WasiErrno.BADF

    if "write" in vfs_fds[fd]:
        vfs_fds[fd]["write"](data)
    elif "file" in vfs_fds[fd]:
        vfs_fds[fd]["file"].write(data)
        update_screen()

    struct.pack_into("<I", mem, nwritten, len(data))
    trace(f"fd:{fd} | nwritten:{len(data)} => ESUCCESS")
    return WasiErrno.SUCCESS

@wasi_generic_api
def clock_time_get(clk_id, precision, result):
    mem = rt.get_memory(0)
    struct.pack_into("<Q", mem, result, time.time_ns())
    #trace(f"clk_id:{clk_id} => ESUCCESS")
    return WasiErrno.SUCCESS

@wasi_generic_api
def proc_exit(code):
    sys.exit(code)


wasm_start = rt.find_function("_start")
try:
    wasm_start()
except (KeyboardInterrupt, SystemExit):
    pass

