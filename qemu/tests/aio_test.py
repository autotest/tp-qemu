import contextlib
import functools
import glob
import logging
import os
import re

from avocado import TestCancel, TestFail
from avocado.utils import cpu, path, process
from virttest import data_dir, utils_misc

LOG_JOB = logging.getLogger("avocado.test")


def which(cmd):
    """Return command path if available, otherwise cancel the test."""
    LOG_JOB.debug("check if command '%s' is available", cmd)
    try:
        return path.find_command(cmd)
    except path.CmdNotFoundError as detail:
        raise TestCancel(str(detail))


def coroutine(func):
    """Start coroutine."""

    @functools.wraps(func)
    def start(*args, **kargs):
        cr = func(*args, **kargs)
        cr.send(None)
        return cr

    return start


@contextlib.contextmanager
def chcwd(path):
    """Support with statement to temporarily change cwd to path."""
    cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(cwd)


def get_qemu_version(params, target):
    """Get installed QEMU version."""
    LOG_JOB.debug("check QEMU version")
    qemu_binary = utils_misc.get_qemu_binary(params)
    cmd = "%s --version" % qemu_binary
    line = process.run(cmd).stdout_text.splitlines()[0]
    version = line.split()[-1].strip("()")
    LOG_JOB.debug("QEMU version: %s", version)
    target.send(version)


@coroutine
def brew_download_build(target):
    """Download source rpm."""
    while True:
        version = yield
        filename = "%s.src.rpm" % version
        root_dir = data_dir.get_data_dir()
        save_path = os.path.join(root_dir, filename)
        LOG_JOB.debug("download source rpm to %s", save_path)
        if not os.path.isfile(save_path):
            with chcwd(root_dir):
                cmd = "brew download-build -q --rpm {filename}".format(
                    filename=filename
                )
                process.run(cmd)
        target.send(save_path)


@coroutine
def unpack_source(target):
    """Unpack source rpm."""
    while True:
        path = yield
        LOG_JOB.debug("unpack source rpm")
        process.run("rpm -ivhf {path}".format(path=path))
        process.run("rpmbuild -bp /root/rpmbuild/SPECS/qemu-kvm.spec --nodeps")
        version = re.search(r"\d+.\d+.\d+", path).group()
        src_path = glob.glob("/root/rpmbuild/BUILD/qemu*%s" % version)[0]
        target.send(src_path)


@coroutine
def run_aio_tests(target):
    """Compile the source code then run aio tests."""
    while True:
        path = yield
        with chcwd(path):
            LOG_JOB.debug("compile source code of QEMU")
            process.run("./configure")
            cpu_count = cpu.online_count()
            aio_path = "tests/test-aio"
            make_cmd = "make {aio_path} -j{cpu_count}".format(
                aio_path=aio_path, cpu_count=cpu_count
            )
            process.run(make_cmd)
            LOG_JOB.debug("run aio tests")
            result = process.run(aio_path)
        target.send(result.stdout_text)


@coroutine
def parse_result():
    """Parse tests result."""
    while True:
        result = yield
        err = False
        for line in result.splitlines():
            if "OK" not in line:
                err = True
                LOG_JOB.error(line)
        if err:
            raise TestFail("aio test failed.")
        else:
            LOG_JOB.debug("all aio tests have passed")


def run(test, params, env):
    """
    Build and run aio tests from QEMU source.

    1. get QEMU version.
    2. download source.
    3. compile source.
    4. run aio tests.
    5. check result.
    """

    # check if command brew and rpmbuild is presented
    which("brew")
    which("rpmbuild")
    get_qemu_version(
        params, brew_download_build(unpack_source(run_aio_tests(parse_result())))
    )
