"""Build pinned, native macOS shader CLI tools in a user-owned cache."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import subprocess
import tarfile
import tempfile


SOURCE_ARCHIVES = (
    (
        'https://archive.ubuntu.com/ubuntu/pool/universe/v/vkd3d/vkd3d_1.2.orig.tar.xz',
        'e688ecfbcf4dd552b44761c2a45f4f944cd0618dc44bc4213c190ce783d641bf',
        'vkd3d-1.2',
    ),
    (
        'https://archive.ubuntu.com/ubuntu/pool/universe/s/spirv-cross/spirv-cross_2021.01.15+1.4.335.0.orig.tar.gz',
        'c3e935cb19e2dda8e2e03fcfcbe451131595fec2cfbc73ab79a6f4c4cd43eb16',
        'SPIRV-Cross-vulkan-sdk-1.4.335.0',
    ),
    (
        'https://codeload.github.com/KhronosGroup/SPIRV-Headers/tar.gz/refs/tags/vulkan-sdk-1.4.335.0',
        '1c47ca6342ebe86f57b46b8dbeb266fa655a1ca8e10d07e45370ff2d9c36312e',
        'SPIRV-Headers-vulkan-sdk-1.4.335.0',
    ),
)

VKD3D_FILES = (
    'libs/vkd3d-common/debug.c', 'libs/vkd3d-common/memory.c', 'libs/vkd3d-common/utf8.c',
    'libs/vkd3d-shader/checksum.c', 'libs/vkd3d-shader/dxbc.c', 'libs/vkd3d-shader/spirv.c',
    'libs/vkd3d-shader/trace.c', 'libs/vkd3d-shader/vkd3d_shader_main.c',
    'programs/vkd3d-compiler/main.c',
)

SPIRV_CROSS_FILES = (
    'spirv_cross.cpp', 'spirv_parser.cpp', 'spirv_cross_parsed_ir.cpp', 'spirv_cfg.cpp',
    'spirv_glsl.cpp', 'spirv_cpp.cpp', 'spirv_msl.cpp', 'spirv_hlsl.cpp', 'spirv_reflect.cpp',
    'spirv_cross_util.cpp', 'main.cpp',
)

VKD3D_CONFIG = '''\
#define HAVE_BUILTIN_CLZ 1
#define HAVE_BUILTIN_POPCOUNT 1
#define HAVE_SYNC_ADD_AND_FETCH 1
#define HAVE_SYNC_SUB_AND_FETCH 1
#define HAVE_SPIRV_UNIFIED1_SPIRV_H 1
#define HAVE_SPIRV_UNIFIED1_GLSL_STD_450_H 1
#define HAVE_DECL_PROGRAM_INVOCATION_NAME 0
#define PACKAGE_VERSION "1.2"
'''


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def checked_run(command, *, timeout=120):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f'{Path(command[0]).name} exited with code {result.returncode}\n{detail}')
    return (result.stdout or result.stderr).strip()


def fetch_source(stage, spec):
    url, digest, root = spec
    archive = stage / (root + '.archive')
    checked_run(['/usr/bin/curl', '--fail', '--silent', '--show-error', '--location',
                 '--proto', '=https', '--proto-redir', '=https', '--retry', '2',
                 '--connect-timeout', '15', '--max-time', '75', '--output', str(archive), url])
    if file_hash(archive) != digest:
        raise RuntimeError(f'SHA-256 mismatch for {root}')
    with tarfile.open(archive) as compressed:
        members = compressed.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if (not path.parts or path.parts[0] != root or '..' in path.parts
                    or not (member.isfile() or member.isdir())):
                raise RuntimeError(f'Unexpected file in source archive {root}')
        compressed.extractall(stage, members=members)
    return stage / root


def compile_spirv_cross(clang, architecture, source, stage, output):
    config = stage / 'spirv-config'
    config.mkdir()
    (config / 'gitversion.h').write_text('#define SPIRV_CROSS_GIT_REVISION "vulkan-sdk-1.4.335.0"\n', 'utf-8')
    flags = ['-O2', '-DNDEBUG', '-std=c++11', '-arch', architecture, '-mmacosx-version-min=11.0',
             '-DHAVE_SPIRV_CROSS_GIT_VERSION', '-I', str(config)]

    def compile_file(name):
        obj = config / (name + '.o')
        checked_run([clang, *flags, '-c', str(source / name), '-o', str(obj)])
        return str(obj)

    with ThreadPoolExecutor(max_workers=2) as workers:
        objects = list(workers.map(compile_file, SPIRV_CROSS_FILES))
    checked_run([clang, '-arch', architecture, '-mmacosx-version-min=11.0', *objects, '-o', str(output)])
    if checked_run([str(output), '--revision']) != 'vulkan-sdk-1.4.335.0':
        raise RuntimeError('Unexpected SPIRV-Cross revision')


def compile_vkd3d(clang, architecture, source, headers, stage, output):
    config = stage / 'vkd3d-config'
    config.mkdir()
    (config / 'config.h').write_text(VKD3D_CONFIG, 'utf-8')
    (config / 'vkd3d_version.h').write_text('#define VKD3D_VCS_ID " (from vkd3d 1.2-15build1 source)"\n', 'utf-8')
    include_paths = [config, source / 'include', source / 'include/private', headers / 'include']
    includes = [arg for directory in include_paths for arg in ('-I', str(directory))]
    flags = ['-O2', '-std=c99', '-D_DARWIN_C_SOURCE', '-arch', architecture, '-mmacosx-version-min=11.0']
    checked_run([clang, *flags, *includes, *(str(source / name) for name in VKD3D_FILES), '-o', str(output)])
    if not checked_run([str(output), '--version']).startswith('vkd3d shader compiler version 1.2 '):
        raise RuntimeError('Unexpected vkd3d-compiler version')


def cached_tools_valid(manifest, paths):
    if not all(path.is_file() and os.access(path, os.X_OK) for path in paths):
        return False
    try:
        expected = json.loads(manifest.read_text('utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(expected, dict) and all(expected.get(path.name) == file_hash(path) for path in paths)


def prepare_tools(cache):
    """Return absolute paths to (vkd3d-compiler, spirv-cross), building once per architecture."""
    architecture = platform.machine()
    if platform.system() != 'Darwin' or architecture not in ('arm64', 'x86_64'):
        raise RuntimeError('Native shader tools require macOS on Apple Silicon or Intel')
    import fcntl

    destination = Path(cache).expanduser().resolve() / f'shader-tools-v1-{architecture}'
    destination.mkdir(parents=True, exist_ok=True)
    tools = (destination / 'vkd3d-compiler', destination / 'spirv-cross')
    manifest = destination / 'checksums.json'
    with (destination / '.build.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if cached_tools_valid(manifest, tools):
            return tools
        try:
            clang = checked_run(['/usr/bin/xcrun', '--find', 'clang'])
            clangxx = checked_run(['/usr/bin/xcrun', '--find', 'clang++'])
        except RuntimeError as error:
            raise RuntimeError('Install the Xcode Command Line Tools to build the shader converters') from error
        with tempfile.TemporaryDirectory(prefix='.build-', dir=destination) as scratch:
            stage = Path(scratch)
            with ThreadPoolExecutor(max_workers=3) as downloads:
                vkd3d_source, spirv_source, headers = downloads.map(lambda spec: fetch_source(stage, spec), SOURCE_ARCHIVES)
            vkd3d_exe, spirv_exe = (stage / tool.name for tool in tools)
            compile_vkd3d(clang, architecture, vkd3d_source, headers, stage, vkd3d_exe)
            compile_spirv_cross(clangxx, architecture, spirv_source, stage, spirv_exe)
            for source in (vkd3d_source, spirv_source, headers):
                license_file = destination / (source.name + '.LICENSE')
                (stage / license_file.name).write_bytes((source / 'LICENSE').read_bytes())
                (stage / license_file.name).replace(license_file)
            for built, tool in zip((vkd3d_exe, spirv_exe), tools):
                built.replace(tool)
            stamp = stage / manifest.name
            stamp.write_text(json.dumps({tool.name: file_hash(tool) for tool in tools}, indent=2) + '\n', 'utf-8')
            stamp.replace(manifest)
    return tools


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    args = parser.parse_args()
    for executable in prepare_tools(args.cache):
        print(executable)
