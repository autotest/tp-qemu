import logging
import time
import os
import re
import base64
import random
import string
import json

import aexpect

from avocado.utils import genio
from avocado.utils import path as avo_path
from avocado.utils import process
from avocado.core import exceptions
from aexpect.exceptions import ShellTimeoutError

from virttest import error_context
from virttest import guest_agent
from virttest import utils_misc
from virttest import utils_disk
from virttest import env_process
from virttest import utils_net
from virttest import data_dir
from virttest import storage
from virttest import qemu_migration
from virttest.utils_version import VersionInterval

from virttest.utils_windows import virtio_win
from provider.win_driver_installer_test import (uninstall_gagent,
                                                run_installer_with_interaction)

LOG_JOB = logging.getLogger('avocado.test')


class BaseVirtTest(object):

    def __init__(self, test, params, env):
        self.test = test
        self.params = params
        self.env = env

    def initialize(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env
        start_vm = self.params["start_vm"]
        self.start_vm = start_vm
        if self.start_vm == "yes":
            vm = self.env.get_vm(params["main_vm"])
            vm.verify_alive()
            self.vm = vm

    def setup(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env

    def run_once(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env

    def before_run_once(self, test, params, env):
        pass

    def after_run_once(self, test, params, env):
        pass

    def cleanup(self, test, params, env):
        pass

    def execute(self, test, params, env):
        self.initialize(test, params, env)
        self.setup(test, params, env)
        try:
            self.before_run_once(test, params, env)
            self.run_once(test, params, env)
            self.after_run_once(test, params, env)
        finally:
            self.cleanup(test, params, env)


class WinDebugToolTest(BaseVirtTest):
    def __init__(self, test, params, env):
        super().__init__(test, params, env)
        self._open_session_list = []
        self.vm = None
        self.script_name = "CollectSystemInfo.ps1"  # Assuming script is named CollectSystemInfo.ps1

    def _get_session(self, params, vm):
        if not vm:
            vm = self.vm
        vm.verify_alive()
        timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)
        return session

    def _cleanup_open_session(self):
        try:
            for s in self._open_session_list:
                if s:
                    s.close()
        except Exception:
            pass

    def run_once(self, test, params, env):
        BaseVirtTest.run_once(self, test, params, env)
        if self.start_vm == "yes":
            pass

    def cleanup(self, test, params, env):
        self._cleanup_open_session()

    @error_context.context_aware
    def setup(self, test, params, env):
        BaseVirtTest.setup(self, test, params, env)
        if self.start_vm == "yes":
            session = self._get_session(params, self.vm)
            self._open_session_list.append(session)

            # 创建工作目录
            error_context.context("Create tmp work dir since testing "
                                  "would create lots of "
                                  "dir and files.", LOG_JOB.info)
            self.tmp_dir = params['test_tmp_dir']
            session.cmd(params['cmd_create_dir'] % self.tmp_dir)

            error_context.context("Change to the temporary "
                                  "work directory.", LOG_JOB.info)
            # 在工作临时目录中执行脚本
            session.cmd("cd %s" % self.tmp_dir)



    def _check_tool_exist(self, test, params, session):
        # will includ into above fuc run_once
        error_context.context("Check whether debug tool exists.", LOG_JOB.info)
        cmd_check_dir = params['cmd_check_dir' % debug_tool_path]
        file_check_list = params['file_check_list']
        s, o = session.cmd_status_output(cmd_check_dir)
        if s == 0 and o:
            for file in file_check_list:
                if file in o:
                    test.error('File %s should exist under %s' % (file, debug_tool_path))
        else:
            test.error('The debug tool path doesn not exist. Please contact with vendor.')
            return s == 1
        self.script_path = script_path
        return s == 0

    def _cleanup_files(self, log_folder, dump_folder, log_zip, dump_zip):
        # 清理文件， 目录， powershell 命令:
        'Remove-Item -Recurse -Force "C:\ExtractedFiles"'
        # This function can be customized to clean up or archive files after test
        cmd_clean_logfoler(self.params[cmd_clean_files] % log_folder)
        cmd_clean_dumpfolder(self.params[cmd_clean_files] % dump_folder)
        cmd_clean_logzip(self.params[cmd_clean_files] % log_zip)
        cmd_clean_dumpzip(self.params[cmd_clean_files] % dump_zip)
        session.cmd(cmd_clean_logfolder)
        if dump_folder:
            session.cmd(cmd_clean_dumpfolder)
        session.cmd(cmd_clean_logzip)
        if dump_zip:
            session.cmd(cmd_clean_dumpzip)

    def _check_file_zip(self, test, params, env):
        # Check the folder and zip package
        pass



class WinDebugToolTestBasicCheck(WinDebugToolTest):

    @error_context.context_aware
    def windegtool_check_script_execution(self, test, params, env):
        if not self.vm:
            self.vm = env.get_vm(params["main_vm"])
            self.vm.verify_alive()

        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)
        # Running the PowerShell script on the VM
        include_sensitive_data = self.params.get("include_sensitive_data", False)
        sensitive_data_flag = "-IncludeSensitiveData" if include_sensitive_data else ""

        # Ensure the script runs with an unrestricted execution policy
        cmd_unrestrict_policy = self.params['cmd_unrestrict_policy']
        session.cmd(cmd_unrestrict_policy)

        # Execute the command on the VM
        self.script_path = "E:\\tools\\debug\\CollectSystemInfo.ps1"
        cmd_run_deg_tool = f"powershell {self.script_path} {sensitive_data_flag}"
        s, o = session.cmd_status_output(cmd_run_deg_tool, timeout=300)

        log_folder_path_pattern = r"Log folder path: (.+)"
        log_folder_match = re.search(log_folder_path_pattern, o)
        if log_folder_match:
            log_folder_path = log_folder_match.group(1)
            print(f"Log folder path: {log_folder_path}")
            if log_folder_path:
                # 拼接 ZIP 文件路径
                log_zip_path = log_folder_path + ".zip"
                # 确保路径合法性
                log_zip_path = os.path.normpath(log_zip_path)
                print(f"Log zip path: {log_zip_path}")
            return log_folder_path, log_zip_path
        else:
            test.fail("debug tool run failed, please check it.")

    @error_context.context_aware
    def windegtool_check_zip_package(self, test, params, env):
        error_context.context("Extract ZIP and check the data files.", LOG_JOB.info)
        # cmd解压缩命令
        session.cmd("cd %s" % self.tmp_dir)
        extract_folder = "zip_package"+"_extract"
        s, o = session.cmd_status_output(params['cmd_extract_zip'] % (zip_package, extract_folder))
        if s:
            test.error("Extract ZIP failed, please take a look and check.")

        error_context.context("Compare the folders", LOG_JOB.info)
        # Check the size of unzip folder and original folder.
        extract_folder_size = session.cmd_output(params["cmd_check_folder_size"] % extract_folder)
        log_folder_size = session.cmd_output(params["cmd_check_folder_size"] % log_folder_path)
        if log_folder_size != extract_folder_size:
            test.fail("ZIP package have problem, since the size of it is not same with the original log folder.")

    def windegtool_check_run_tools_multi_times(self, test, params, env):
        error_context.context("Run scripts 100 times and check there is no problem", LOG_JOB.info)
        # 1. cmd 运行脚本100次
        # 2. 检查所有文件是否都在


    def windegtool_check_user_friendliness(self, test, params, env):
        # 1. 运行无效参数， 看脚本是否可以运行
        #2. 运行脚本， 但是5秒钟后中断脚本运行， 查看：
            # 2.1 是否有'Collecting_Status.txt'来记录脚本运行进程， 以告知用户
        # 3. Clean the folder that was interrupted.
        #     3.1 `Remove - Item - Path.\SystemInfo_2024 - xx_xx - xx\ -ErrorActionSilentlyContinue - Force - Recurse`
        # 4. Re-running a script after an abnormal interruption
        pass

    def windegtool_check_disk_registry_collection(self, test, param, env):
        
        pass

    def windegtool_check_includeSensitiveData_collection(self, test, param, env):
        pass

    def windegtool_check_trigger_driver_collection(self, test, param, env):
        pass

    def windegtool_check_networkadapter_collection(self, test, param, env):
        pass

    def windegtool_check_documentation(self, test, param, env):
        # 1. Check all relevant documents to ensure they are complete. (README.md,LICENSE,CollectSystemInfo.ps1)
        # 2. Follow the script according to the documentation to ensure all steps and instructions are correct.
        pass

    def run_once(self, test, params, env):
        WinDebugToolTest.run_once(self, test, params, env)

        windegtool_check_type = self.params["windegtool_check_type"]
        chk_type = "windegtool_check_%s" % windegtool_check_type
        if hasattr(self, chk_type):
            func = getattr(self, chk_type)
            func(test, params, env)
        else:
            test.error("Could not find matching test, check your config file")


def run(test, params, env):
    """
    Test CollectSystemInfo.ps1 tool, this case will:
    1) Start VM with virtio-win rpm package.
    2) Execute CollectSystemInfo.ps1 with&without param
    '-IncludeSensitiveData'.
    3) Run some basic test for CollectSystemInfo.ps1.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    collectinfotool_test = WinDebugToolTestBasicCheck(test, params, env)
    collectinfotool_test.execute(test, params, env)