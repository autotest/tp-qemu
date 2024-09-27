"""
This code was inspired in the autotest project,
tp-qemu/provider/storage_benchmark.py
Module for providing memory benchmark tools for testing memory.

Available function:
- generate_instance: Generate a instance by specified memory benchmark class
                     to test memory by specified benchmark tool.

Available class:
- MemoryBenchmark: Define a class provides common methods to test memory.
- MemMapping: Define a class provides methods to test different mapping
              types of memory by MemMapping benchmark.

Copyright: Red Hat Inc. 2023
Authors: Yongxue Hong <yhong@redhat.com>
         Sibo Wang <siwang@redhat.com>
         Zhenyu Zhang <zhenyzha@redhat.com>
"""

import logging
import os
import re

from functools import wraps

from operator import attrgetter

from virttest import utils_misc
from virttest import data_dir
from virttest.remote import scp_to_remote
from avocado.utils import process

from avocado import TestError

LOG_JOB = logging.getLogger('avocado.test')

TAR_UNPACK = 'tar'


class MmapBenchmark(object):

    cmds = {'linux': {'_symlinks': 'ln -s -f %s %s',
                      '_list_pid': 'pgrep -xl %s',
                      '_kill_pid': 'killall -s SIGKILL %s',
                      '_rm_file': 'rm -rf {}'}}

    tar_map = {'.tar': '-xvf', '.tar.gz': '-xzf',
               '.tar.bz2': '-xjf', '.tar.Z': '-xZf'}

    unpack_cmd = {TAR_UNPACK: '_tar_unpack_file'}

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
        if not self._session.is_alive():
            self._session.close()
            self._session = self.vm.wait_for_login(timeout=360)
        return self._session

    def __wait_procs_done(self, session, timeout=180):
        proc_name = self.name
        LOG_JOB.info('Checking the running %s processes', self.name)
        if not utils_misc.wait_for(
                lambda: not re.search(
                    proc_name.lower(), session.cmd_output(
                        self._list_pid % proc_name), re.I | re.M), timeout, step=3.0):
            raise TestError(
                'Not all %s processes done in %s sec.' % (proc_name, timeout))

    def __kill_procs(self, session):
        LOG_JOB.info('Killing all %s processes by force.', self.name)
        session.cmd_output(self.cmds[self.os_type]['_kill_pid'] % self.name)

    def scp_benckmark(self, username, password, host_path, guest_path, port='22'):
        """
        Scp a benchmark tool from the local host to the guest.

        """
        scp_to_remote(self.vm.get_address(), port, username, password, host_path, guest_path)
        self.env_files.append(guest_path)

    def _tar_unpack_file(self, src, dst, timeout=300):

        cmd = "mkdir -p {0} && tar {1} {2} -C {0}".format(
            dst, self.tar_map[re.search(r'\.tar\.?(\w+)?$', src).group()], src)
        self._session.cmd(cmd, timeout=timeout)

    def unpack_file(self, mode, src, dst, timeout=300):
        getattr(self, self.unpack_cmd[mode])(*(src, dst, timeout))
        self.env_files.append(dst)

    def __remove_env_files(self, session, timeout=300):
        LOG_JOB.info('Removing the environment files.')
        cmds = (self.cmds[self.os_type]['_rm_file'].format(f) for f in
                self.env_files)
        session.cmd(' && '.join(cmds), timeout=timeout)

    def _install_linux(self, src, dst, timeout):

        self.session.cmd('gcc mem_mapping.c -o mem_mapping', timeout=timeout)

    @staticmethod
    def _clean_env(func):
        """ Decorator that clean the env files. """

        @wraps(func)
        def __clean_env(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                self.clean()
                raise TestError(str(e))

        return __clean_env

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
        install_map = {'linux': '_install_linux'}
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


class MemMapingLinuxCfg(object):
    def __init__(self, params, session):
        mmap_pkg = params.get('mmap_pkg', 'mem_mapping.tar.gz')
        compile_pkg = params.get('compile_pgk', 'gcc mem_mapping.c -o mem_mapping')
        host_path = os.path.join(data_dir.get_deps_dir('mem_mapping'), mmap_pkg)
        self.download_path = os.path.join('/home', mmap_pkg)
        self.mmap_inst = os.path.join('/home', 'mmap_inst')
        self.mmap_path = '%s/mem_mapping' % self.mmap_inst
        self.cmd = 'cd %s && %s' % (self.mmap_path, compile_pkg)
        scp_benckmark = attrgetter('scp_benckmark')
        unpack_file = attrgetter('unpack_file')
        session_cmd = attrgetter('session.cmd')
        self.setups = {scp_benckmark: (params.get('username'), params.get('password'),
                                       host_path, self.download_path),
                       unpack_file: (TAR_UNPACK, self.download_path, self.mmap_inst),
                       session_cmd: (self.cmd, 300)}
        self.setup_orders = (scp_benckmark, unpack_file, session_cmd)


class MemMapping(MmapBenchmark):
    @MmapBenchmark._clean_env
    def __init__(self, params, vm):
        self.os_type = params['os_type']
        super(MemMapping, self).__init__(self.os_type, vm, 'mem_mapping')
        self.cfg_map = {'linux': MemMapingLinuxCfg}
        self.cfg = self.cfg_map[self.os_type](params, self.session)
        self.mmap_path = '/home/mmap_inst/mem_mapping'
        for method in self.cfg.setup_orders:
            method(self)(*self.cfg.setups[method])

    def run(self, cmd_options='-a -p -l 2048M', session=None, timeout=1800):
        cmd = 'cd %s && ./mem_mapping %s' % (self.mmap_path, cmd_options)
        if session:
            return session.cmd(cmd, timeout=timeout, ignore_all_errors=True)
        else:
            return process.system(cmd, shell=True, ignore_bg_processes=True)


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
    return {'mmap': MemMapping}[name](params, vm)
