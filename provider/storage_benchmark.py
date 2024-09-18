"""
Module for providing storage benchmark tools for testing block device.

Available function:
- generate_instance: Generate a instance by specified storage benchmark class
                     to test block io by specified benchmark tool.

Available class:
- StorageBenchmark: Define a class provides common methods to test block io.
- Iozone: Define a class provides methods to test file I/O performance by
          iozone benchmark.
- Fio: Define a class provides methods to test block I/O performance by
       fio benchmark.
"""

import logging
import os
import re
from functools import wraps
from operator import attrgetter
from platform import machine

from avocado import TestError
from virttest import data_dir, utils_misc
from virttest.remote import scp_to_remote

LOG_JOB = logging.getLogger("avocado.test")

GIT_DOWNLOAD = "git"
CURL_DOWNLOAD = "curl"

TAR_UNPACK = "tar"


class StorageBenchmark(object):
    """
    Create a Benchmark class which provides common interface(method) for
    using Benchmark tool to run test.

    """

    cmds = {
        "linux": {
            "_symlinks": "ln -s -f %s %s",
            "_list_pid": "pgrep -xl %s",
            "_kill_pid": "killall -s SIGKILL %s",
            "_rm_file": "rm -rf {}",
        },
        "windows": {
            "_symlinks": "mklink %s %s",
            "_list_pid": 'TASKLIST /FI "IMAGENAME eq %s',
            "_kill_pid": "TASKKILL /F /IM %s /T",
            "_rm_file": 'RD /S /Q "{}"',
        },
    }
    tar_map = {".tar": "-xvf", ".tar.gz": "-xzf", ".tar.bz2": "-xjf", ".tar.Z": "-xZf"}
    download_cmds = {
        GIT_DOWNLOAD: "rm -rf {0} && git clone {1} {0}",
        CURL_DOWNLOAD: "curl -o {0} {1}",
    }
    unpack_cmds = {TAR_UNPACK: "_tar_unpack_file"}

    def __init__(self, os_type, vm, name):
        """
        :param vm: vm object
        :type vm: qemu_vm.VM object
        :param name: the name of benchmark
        :type name: str
        """
        self.vm = vm
        self.name = name
        self.os_type = os_type
        self.env_files = []
        self._session = self.vm.wait_for_login(timeout=360)

    def __getattr__(self, item):
        try:
            return self.cmds[self.os_type][item]
        except KeyError as e:
            raise AttributeError(str(e))

    @property
    def session(self):
        """
        Refresh the session, if session is not alive will new one.
        """
        if not self._session.is_alive():
            self._session.close()
            self._session = self.vm.wait_for_login(timeout=360)
        return self._session

    def make_symlinks(self, src, dst):
        """
        Make symlinks between source file and destination file by force.

        :param src: source file
        :type src: str
        :param dst: destination file
        :type dst: str
        """
        self.session.cmd(self._symlinks % (src, dst))
        self.env_files.append(dst)

    def __wait_procs_done(self, session, timeout=1800):
        """
        Wait all the processes are done.

        :param session: vm session
        :type session: aexpect.client.ShellSession
        :param timeout: timeout for waiting
        :type timeout: float
        """
        proc_name = (
            self.name if self.os_type == "linux" else (self.name.upper() + ".EXE")
        )
        LOG_JOB.info("Checking the running %s processes.", self.name)
        if not utils_misc.wait_for(
            lambda: not re.search(
                proc_name.lower(),
                session.cmd_output(self._list_pid % proc_name),
                re.I | re.M,
            ),
            timeout,
            step=3.0,
        ):
            raise TestError(
                "Not all %s processes done in %s sec." % (proc_name, timeout)
            )

    def __kill_procs(self, session):
        """
        Kill the specified processors by force.

        :param session: vm session
        :type session: aexpect.client.ShellSession
        """
        LOG_JOB.info("Killing all %s processes by force.", self.name)
        session.cmd_output(self._kill_pid % self.name, timeout=120)

    def __remove_env_files(self, session, timeout=300):
        """
        Remove the environment files includes downloaded files, installation
        files and others related to benchmark.

        :param session: vm session
        :type session: aexpect.client.ShellSession
        :param timeout: timeout for removing
        :type timeout: float
        """
        LOG_JOB.info("Removing the environment files.")
        cmds = (self._rm_file.format(f) for f in self.env_files)
        session.cmd(" && ".join(cmds), timeout=timeout)

    def download_benchmark(self, mode, url, dst, timeout=300):
        """
        Download a benchmark tool to destination file.

        :param mode: the mode of downloading, e.g, git, curl
        :type mode: str
        :param url: the url downloaded
        :type url: str
        :param dst: download the file to destination file
        :param timeout: timeout for downloading
        :type timeout: float
        """
        self.session.cmd(self.download_cmds[mode].format(dst, url), timeout)
        self.env_files.append(dst)

    def scp_benckmark(self, username, password, host_path, guest_path, port="22"):
        """
        Scp a benchmark tool from the local host to the guest.

        """
        scp_to_remote(
            self.vm.get_address(), port, username, password, host_path, guest_path
        )
        self.env_files.append(guest_path)

    def _tar_unpack_file(self, src, dst, timeout=300):
        """Unpack file by tar."""
        cmd = "mkdir -p {0} && tar {1} {2} -C {0}".format(
            dst, self.tar_map[re.search(r"\.tar\.?(\w+)?$", src).group()], src
        )
        self.session.cmd(cmd, timeout=timeout)

    def unpack_file(self, mode, src, dst, timeout=300):
        """
        Unpack file from source file to destination directory.

        :param mode: the mode of unpacking, e.g, tar, unzip
        :type mode: str
        :param src: source file
        :type src: str
        :param dst: destination directory
        :type dst: str
        :param timeout: timeout for unpacking
        :type timeout: float
        """
        getattr(self, self.unpack_cmds[mode])(*(src, dst, timeout))
        self.env_files.append(dst)

    def _install_linux(self, src, dst, timeout):
        """
        Install a package from source file to destination directory in linux.
        """
        self.session.cmd(
            "cd %s && ./configure --prefix=%s && make && make install" % (src, dst),
            timeout=timeout,
        )

    def _install_win(self, src, dst, timeout):
        """
        Install a package from source file to destination directory in windows.
        """

        def _find_exe_file():
            """
            Find the path of the given executable file in windows.
            """
            cmd_dir = r'DIR /S /B "%s" | find "%s.exe"' % (dst, self.name)
            s, o = self.session.cmd_status_output(cmd_dir, timeout=timeout)
            if not s:
                return '"{}"'.format(o.splitlines()[0])
            return None

        cmd = utils_misc.set_winutils_letter(
            self.session, r'msiexec /a "%s" /qn TARGETDIR="%s"' % (src, dst)
        )
        self.session.cmd_output(cmd, timeout=timeout)
        if not utils_misc.wait_for(lambda: _find_exe_file(), timeout, step=3.0):
            raise TestError("Failed to install fio under %.2f." % timeout)

    def install(self, src, dst, timeout=300):
        """
        Install a package from source file to destination directory.

        :param src: source file
        :type src: str
        :param dst: destination directory
        :type dst: str
        :param timeout: timeout for installing
        :type timeout: float
        """
        install_map = {"linux": "_install_linux", "windows": "_install_win"}
        getattr(self, install_map[self.os_type])(src, dst, timeout)
        self.env_files.append(dst)

    def run(self, cmd, timeout=600):
        """
        Execute the benchmark command.

        :param cmd: executed command
        :type cmd: str
        :param timeout: timeout for executing command
        :type timeout: float
        :return: output of running command
        :rtype: str
        """
        return self.session.cmd(cmd, timeout=timeout)

    def clean(self, timeout=1800, force=False):
        """
        Clean benchmark tool packages and processes after testing inside guest.

        :param timeout: timeout for cleaning
        :type timeout: float
        :param force: if is True, kill the running processes
                      by force, otherwise wait they are done
        :type force: bool
        """
        # In order to the output of the previous session object does not
        # disturb the current session object to get the shell prompt, so
        # new a session.
        session = self.vm.wait_for_login(timeout=360)
        if force:
            self.__kill_procs(session)
        else:
            self.__wait_procs_done(session, timeout)
        if self.env_files:
            self.__remove_env_files(session)
        session.close()

    @staticmethod
    def _clean_env(func):
        """Decorator that clean the env files."""

        @wraps(func)
        def __clean_env(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                self.clean()
                raise TestError(str(e))

        return __clean_env


class IozoneLinuxCfg(object):
    def __init__(self, params, session):
        iozone_pkg = params.get("iozone_pkg", "iozone3_490.tar.bz2")
        host_path = os.path.join(data_dir.get_deps_dir(), "iozone", iozone_pkg)
        self.download_path = os.path.join("/home", iozone_pkg)
        self.iozone_inst = os.path.join("/home", "iozone_inst")
        if "ppc64" in machine():
            self.arch = "linux-powerpc64"
        elif "aarch64" in machine():
            self.arch = "linux-arm"
        elif "s390" in machine():
            self.arch = "linux-S390X"
        else:
            self.arch = "linux-AMD64"
        self.cmd = "cd %s/src/current && make clean && make %s" % (
            self.iozone_inst,
            self.arch,
        )
        self.iozone_path = "%s/src/current/iozone" % self.iozone_inst
        scp_benckmark = attrgetter("scp_benckmark")
        unpack_file = attrgetter("unpack_file")
        session_cmd = attrgetter("session.cmd")
        self.setups = {
            scp_benckmark: (
                params.get("username"),
                params.get("password"),
                host_path,
                self.download_path,
            ),
            unpack_file: (TAR_UNPACK, self.download_path, self.iozone_inst),
            session_cmd: (self.cmd, 300),
        }
        self.setup_orders = (scp_benckmark, unpack_file, session_cmd)


class IozoneWinCfg(object):
    def __init__(self, params, session):
        label = params.get("win_utils_label", "WIN_UTILS")
        drive_letter = utils_misc.get_winutils_vol(session, label)
        self.cmd = "set nodosfilewarning=1 && set CYGWIN=nodosfilewarning"
        self.iozone_path = drive_letter + r":\Iozone\iozone.exe"
        session_cmd = attrgetter("session.cmd")
        self.setups = {session_cmd: (self.cmd, 300)}
        self.setup_orders = (session_cmd,)


class Iozone(StorageBenchmark):
    @StorageBenchmark._clean_env
    def __init__(self, params, vm):
        self.os_type = params["os_type"]
        super(Iozone, self).__init__(self.os_type, vm, "iozone")
        self.cfg_map = {"linux": IozoneLinuxCfg, "windows": IozoneWinCfg}
        self.cfg = self.cfg_map[self.os_type](params, self.session)
        for method in self.cfg.setup_orders:
            method(self)(*self.cfg.setups[method])

    def run(self, cmd_options="-a", timeout=1800):
        """
        Run iozone test inside guest.

        :param cmd_options: iozone command options, e.g: -azR -r 64k -n 1G -g
                            1G -M -f /home/test
        :type cmd_options: str
        """
        cmd = " ".join((self.cfg.iozone_path, cmd_options))
        return super(Iozone, self).run(cmd, timeout)


class FioLinuxCfg(object):
    def __init__(self, params, session):
        # fio_resource accept 'distro' or one specified fio package.
        #'distro' means use the fio binary provides by os, and the specified
        # package means use the specified package in deps.
        fio_resource = params.get("fio_resource", "fio-3.13-48-ga819.tar.bz2")
        if fio_resource == "distro":
            status, output = session.cmd_status_output("which fio")
            if status == 0:
                self.fio_path = output.strip()
                self.setup_orders = ()
            else:
                raise TestError("No available fio in the distro")
        else:
            host_path = os.path.join(data_dir.get_deps_dir(), "fio", fio_resource)
            self.download_path = os.path.join("/home", fio_resource)
            self.fio_inst = os.path.join("/home", "fio_inst")
            self.fio_path = "%s/bin/fio" % self.fio_inst
            scp_benckmark = attrgetter("scp_benckmark")
            unpack_file = attrgetter("unpack_file")
            install_timeout = params.get_numeric("fio_install_timeout", 300)
            install = attrgetter("install")
            self.setups = {
                scp_benckmark: (
                    params.get("username"),
                    params.get("password"),
                    host_path,
                    self.download_path,
                ),
                unpack_file: (TAR_UNPACK, self.download_path, self.fio_inst),
                install: (self.fio_inst, self.fio_inst, install_timeout),
            }
            self.setup_orders = (scp_benckmark, unpack_file, install)


class FioWinCfg(object):
    def __init__(self, params, session):
        label = params.get("win_utils_label", "WIN_UTILS")
        utils_letter = utils_misc.get_winutils_vol(session, label)
        arch = params.get("vm_arch_name", "x84_64")
        fio_ver = params.get("fio_ver", "fio-latest")
        self.fio_inst = {
            "x86_64": r"C:\Program Files (x86)\fio",
            "i686": r"C:\Program Files\fio",
        }
        self.fio_msi = {
            "x86_64": r"%s:\%s-x64.msi" % (utils_letter, fio_ver),
            "i686": r"%s:\%s-x86.msi" % (utils_letter, fio_ver),
        }
        self.fio_path = r'"%s\fio\fio.exe"' % self.fio_inst[arch]
        install = attrgetter("install")
        self.setups = {install: (self.fio_msi[arch], self.fio_inst[arch], 300)}
        self.setup_orders = (install,)


class Fio(StorageBenchmark):
    @StorageBenchmark._clean_env
    def __init__(self, params, vm):
        self.os_type = params["os_type"]
        super(Fio, self).__init__(self.os_type, vm, "fio")
        self.cfg_map = {"linux": FioLinuxCfg, "windows": FioWinCfg}
        self.cfg = self.cfg_map[self.os_type](params, self.session)
        for method in self.cfg.setup_orders:
            method(self)(*self.cfg.setups[method])

    def run(self, cmd_options, timeout=1800):
        """
        Run fio test inside guest.

        :param cmd_options: fio command options, e.g, --filename=/home/test
                            --direct=1 --rw=read --bs=64K --size=1000M
                            --name=test
        :type cmd_options: str
        """
        cmd = " ".join((self.cfg.fio_path, cmd_options))
        return super(Fio, self).run(cmd, timeout)


def generate_instance(params, vm, name):
    """
    Generate a instance with the given name class.

    :param params: dictionary with the test parameters
    :param vm: vm object
    :param name: benchmark name
    :type name: str
    :return: instance with the given name class
    :rtype: StorageBenchmark object
    """
    return {"fio": Fio, "iozone": Iozone}[name](params, vm)
