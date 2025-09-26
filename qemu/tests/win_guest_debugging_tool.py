import logging
import re
import threading
import time
from distutils.util import strtobool

from aexpect.exceptions import ShellTimeoutError
from virttest import (
    error_context,
)

LOG_JOB = logging.getLogger("avocado.test")


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
        self.script_dir = None
        self.script_name = params.get("script_name", "")
        self.script_path = params.get("script_path", "")
        self.tmp_dir = params.get("test_tmp_dir", "")

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

            error_context.context("Check whether debug tool exists.", LOG_JOB.info)
            cmd_get_debug_tool_script = (
                params["cmd_search_file_global"] % self.script_name
            )
            script_path = str(
                session.cmd_output(cmd_get_debug_tool_script, timeout=360)
            ).strip()
            if script_path:
                self.script_path = script_path
                self.script_dir = self.script_path.replace(self.script_name, "").rstrip(
                    "\\"
                )
            else:
                test.error(
                    "The tool script file CollectSystemInfo.ps1 was not "
                    "found. Please check."
                )

            error_context.context(
                "Create tmp work dir since testing would create lots of dir and files.",
                LOG_JOB.info,
            )
            session.cmd_output(params["cmd_create_dir"] % self.tmp_dir)

    def _check_generated_files(self, session, path, sensitive_data=False):
        output = str(session.cmd_output(f"dir /b {path}")).strip()

        target_files = (
            self.params["target_dump_files"]
            if sensitive_data
            else self.params["target_files"]
        ).split(",")

        for target_file in target_files:
            if target_file not in output:
                self.test.error(f"{target_file} is not included, please check it.")

    def _get_path(self, output, session, sensitive_data=False):
        log_folder_path = re.search(r"Log folder path: (.+)", output).group(1)
        self._check_generated_files(session, log_folder_path)
        log_zip_path = f"{log_folder_path}.zip"

        if sensitive_data:
            dump_folder_match = re.search(r"Dump folder path: (.+)", output)
            if dump_folder_match:
                dump_folder_path = dump_folder_match.group(1)
                self._check_generated_files(
                    session, dump_folder_path, sensitive_data=True
                )
                dump_zip_path = f"{dump_folder_path}.zip"
                return log_folder_path, log_zip_path, dump_folder_path, dump_zip_path

        return log_folder_path, log_zip_path


class WinDebugToolTestBasicCheck(WinDebugToolTest):
    def __init__(self, test, params, env):
        super().__init__(test, params, env)

    @error_context.context_aware
    def run_tool_scripts(self, session, return_zip_path=False):
        error_context.context(
            "Run Debug tool script to Query original info or value.", LOG_JOB.info
        )
        # Running the PowerShell script on the VM
        include_sensitive_data = bool(strtobool(self.params["include_sensitive_data"]))
        sensitive_data_flag = "-IncludeSensitiveData" if include_sensitive_data else ""

        # Execute the command on the VM
        cmd_run_deg_tool = (
            f"powershell.exe -ExecutionPolicy Bypass -File {self.script_path} "
            f"{sensitive_data_flag}"
        )
        s, o = session.cmd_status_output(cmd_run_deg_tool, timeout=360)

        paths = self._get_path(o, session, sensitive_data=include_sensitive_data)
        if include_sensitive_data:
            log_folder_path, log_zip_path, dump_folder_path, dump_zip_path = paths
            if not all(paths):
                self.test.fail("Debug tool run failed, please check it.")
            return paths if return_zip_path else (log_folder_path, dump_folder_path)
        else:
            log_folder_path, log_zip_path = paths
            if not all(paths):
                self.test.fail("Debug tool run failed, please check it.")
            return paths if return_zip_path else log_folder_path

    @error_context.context_aware
    def windegtool_check_script_execution(self, test, params, env):
        """
        Verify basic script execution functionality:
        1. Launch Windows guest and execute debug tool script
        2. Verify log folder and zip file are generated correctly
        3. Check for any execution errors

        :param test: QEMU test object
        :param params: Dictionary with test parameters
        :param env: Dictionary with the test environment
        """
        if not self.vm:
            self.vm = env.get_vm(params["main_vm"])
            self.vm.verify_alive()

        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)
        session.cmd("cd %s" % self.tmp_dir)

        log_folder_path, log_zip_path = self.run_tool_scripts(
            session, return_zip_path=True
        )
        if not (log_zip_path and log_folder_path):
            test.fail("debug tool run failed, please check it.")

    @error_context.context_aware
    def windegtool_check_zip_package(self, test, params, env):
        """
        Verify zip package functionality:
        1. Run debug tool to generate logs
        2. Extract generated ZIP file
        3. Compare extracted folder with original log folder
        4. Verify folder sizes match

        :param test: QEMU test object
        :param params: Dictionary with test parameters
        :param env: Dictionary with the test environment
        """
        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)
        session.cmd("cd %s" % self.tmp_dir)

        log_folder_path, log_zip_path = self.run_tool_scripts(
            session, return_zip_path=True
        )
        if not (log_zip_path and log_folder_path):
            test.fail("debug tool run failed, please check it.")

        error_context.context("Extract ZIP and check the data files.", LOG_JOB.info)
        session.cmd("cd %s" % self.tmp_dir)
        extract_folder = log_zip_path + "_extract"
        s, o = session.cmd_status_output(
            params["cmd_extract_zip"] % (log_zip_path, extract_folder)
        )
        if s:
            test.error("Extract ZIP failed, please take a look and check.")

        error_context.context("Compare the folders", LOG_JOB.info)
        extract_folder_size = session.cmd_output(
            params["cmd_check_folder_size"] % extract_folder
        )
        log_folder_size = session.cmd_output(
            params["cmd_check_folder_size"] % log_folder_path
        )
        if log_folder_size != extract_folder_size:
            test.fail(
                "ZIP package have problem, since the size of it "
                "is not same with the original log folder."
            )

    @error_context.context_aware
    def windegtool_check_run_tools_multi_times(self, test, params, env):
        """
        Verify script stability with multiple executions:
        1. Run debug tool multiple times in sequence
        2. Verify each execution succeeds and generates logs
        3. Clean up logs between runs
        4. Check for any errors or inconsistencies

        :param test: QEMU test object
        :param params: Dictionary with test parameters
        :param env: Dictionary with the test environment
        """
        if not self.vm:
            self.vm = env.get_vm(params["main_vm"])
            self.vm.verify_alive()

        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)
        session.cmd("cd %s" % self.tmp_dir)

        error_context.context(
            "Run scripts 100 times and check there is no problem", LOG_JOB.info
        )
        for i in range(1, 5):
            log_folder_path, log_zip_path = self.run_tool_scripts(
                session, return_zip_path=True
            )
            if not (log_zip_path and log_folder_path):
                test.fail("debug tool run failed, please check it.")
            cmd_remove_zip = params["cmd_remove_dir"] % log_zip_path
            cmd_remove_folder = params["cmd_remove_dir"] % log_folder_path
            cmd_clean_dir = "%s && %s" % (cmd_remove_folder, cmd_remove_zip)
            session.cmd(cmd_clean_dir)

    @error_context.context_aware
    def windegtool_check_user_friendliness(self, test, params, env):
        """
        Test script's user-friendly features:
        1. Test invalid parameter handling and error messages
        2. Test script interruption handling
        3. Verify interrupt signal file generation
        4. Test script recovery after interruption

        :param test: QEMU test object
        :param params: Dictionary with test parameters
        :param env: Dictionary with the test environment
        """

        def _run_script(session):
            cmd_run_deg_tool = (
                f"powershell.exe -ExecutionPolicy Bypass -File {self.script_path}"
            )
            try:
                session.cmd_output(cmd_run_deg_tool, timeout=5)
            except ShellTimeoutError as e:
                LOG_JOB.info("Script execution timed out as expected: %s", str(e))
                pass
            except Exception as e:
                LOG_JOB.error("Unexpected error during script execution: %s", str(e))
                test.error(f"Script execution failed with unexpected error: {str(e)}")

        def _kill_powershell_process(session1):
            session1.cmd(params["cmd_kill_powershell_process"])
            session1.cmd(params["cmd_kill_powershell_process1"])

        if not self.vm:
            self.vm = env.get_vm(params["main_vm"])
            self.vm.verify_alive()

        session = self._get_session(params, self.vm)
        session1 = self._get_session(params, self.vm)
        self._open_session_list.extend([session, session1])

        error_context.context(
            "Run script with various of invalid parameters.", LOG_JOB.info
        )
        session.cmd("cd %s" % self.tmp_dir)
        session.cmd("rd /S /Q %s" % self.tmp_dir)
        session.cmd_output(params["cmd_create_dir"] % self.tmp_dir)
        invalid_params = list(params["invalid_params"].split(","))
        expect_output_prompt = params["expect_output_prompt"]
        for invalid_param in invalid_params:
            cmd_run_deg_tool = (
                f"powershell.exe -ExecutionPolicy Bypass -File {self.script_path} "
                f"{invalid_param}"
            )
            o = session.cmd_output(cmd_run_deg_tool, timeout=360)
            if expect_output_prompt not in o:
                test.fail(
                    "There should be friendly reminder output %s, telling "
                    "users how to run the script with reasonable parameters"
                    "please check it." % expect_output_prompt
                )

        error_context.context(
            "Interrupt script when it's running to check the signal file.",
            LOG_JOB.info,
        )
        script_thread = threading.Thread(target=_run_script(session))
        kill_thread = threading.Thread(target=_kill_powershell_process(session1))
        script_thread.start()
        time.sleep(5)
        kill_thread.start()
        script_thread.join()
        kill_thread.join()

        script_interrupt_signal_file = params["script_interrupt_signal_file"]
        log_path = session.cmd_output(params["cmd_query_path"]).split()[0]
        session.cmd("cd %s" % log_path)
        output = session.cmd_output("dir")
        if script_interrupt_signal_file not in output:
            test.fail(
                f"There should be one {script_interrupt_signal_file} once the script"
                f" is interrupted, but there isn't. Please check it."
            )

        error_context.context(
            "Clean invalid files and re-run script again to check "
            "whether it could be run well.",
            LOG_JOB.info,
        )
        session.cmd("cd ../")
        session.cmd(params["cmd_dir_del"] % log_path)
        self.run_tool_scripts(session)

    @error_context.context_aware
    def windegtool_check_disk_registry_collection(self, test, params, env):
        """
        Test disk and registry information collection:
        1. Collect initial registry values
        2. Compare values between registry and collected file
        3. Modify registry entries and verify changes are captured
        4. Test registry key creation and deletion
        5. Verify accurate collection of modified values

        :param test: QEMU test object
        :param params: Dictionary with test parameters
        :param env: Dictionary with the test environment
        """
        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)
        session.cmd("cd %s" % self.tmp_dir)

        error_context.context(
            "Run script first to collect 'virtio_disk.txt'.", LOG_JOB.info
        )
        log_folder_path = self.run_tool_scripts(session)
        virtio_disk_filepath = params["virtio_disk_filepath"] % log_folder_path
        exist_reg_item = params["exist_reg_item"]
        reg_subkey1, reg_subkey2 = params["reg_subkey1"], params["reg_subkey2"]
        iotimeoutvalue_file = int(
            session.cmd_output(
                params["cmd_findstr_in_file"]
                % (virtio_disk_filepath, (exist_reg_item + "\\" + reg_subkey1))
            )
            .split(":")[-1]
            .strip()
        )
        timeoutvalue_file = int(
            session.cmd_output(
                params["cmd_findstr_in_file"]
                % (virtio_disk_filepath, (exist_reg_item + "\\" + reg_subkey2))
            )
            .split(":")[-1]
            .strip()
        )
        iotimeoutvalue_cmd = int(
            session.cmd_output(params["cmd_reg_query"] % (exist_reg_item, reg_subkey1))
        )
        timeoutvalue_cmd = int(
            session.cmd_output(params["cmd_reg_query"] % (exist_reg_item, reg_subkey2))
        )
        if (
            iotimeoutvalue_cmd != iotimeoutvalue_file
            or timeoutvalue_cmd != timeoutvalue_file
        ):
            test.error(
                "The value of %s and %s is not same between %s and cmd, Please "
                "have a check" % (reg_subkey1, reg_subkey2, virtio_disk_filepath)
            )

        error_context.context(
            "Edit exist value and create new sub-key for "
            "vioscsi/viostor for non-exist value",
            LOG_JOB.info,
        )
        new_reg_item = params["new_reg_item"]
        cmd_reg_add_item = params["cmd_reg_add_item"] % (new_reg_item, new_reg_item)
        cmd_reg_add_item_key = params["cmd_reg_add_item_key"]
        cmd_reg_set_value = params["cmd_reg_set_value"]
        try:
            key_value1, key_value2 = (
                int(params["key_value1"]),
                int(params["key_value2"]),
            )

            s, o = session.cmd_status_output(cmd_reg_add_item)
            if not s:
                session.cmd_output(
                    cmd_reg_add_item_key % (new_reg_item, new_reg_item, reg_subkey1)
                )
                session.cmd_output(
                    cmd_reg_add_item_key % (new_reg_item, new_reg_item, reg_subkey2)
                )
            else:
                test.error(
                    "Add register item for vioscsi/viostor failed, please help check."
                )

            session.cmd_output(
                cmd_reg_set_value % (exist_reg_item, reg_subkey1, key_value1)
            )
            session.cmd_output(
                cmd_reg_set_value % (new_reg_item, reg_subkey1, key_value1)
            )
            session.cmd_output(
                cmd_reg_set_value % (new_reg_item, reg_subkey2, key_value2)
            )

            error_context.context("Re-run guest debug tool script", LOG_JOB.info)
            new_log_folder_path = self.run_tool_scripts(session)
            new_virtio_disk_filepath = (
                params["virtio_disk_filepath"] % new_log_folder_path
            )
            cmd_findstr_in_file = params["cmd_findstr_in_file"]
            exist_iotimeoutvalue_file = int(
                session.cmd_output(
                    cmd_findstr_in_file
                    % (new_virtio_disk_filepath, (exist_reg_item + "\\" + reg_subkey1))
                )
                .split(":")[-1]
                .strip()
            )
            new_iotimeoutvalue_file = int(
                session.cmd_output(
                    cmd_findstr_in_file
                    % (new_virtio_disk_filepath, (new_reg_item + "\\" + reg_subkey1))
                )
                .split(":")[-1]
                .strip()
            )
            new_timeoutvalue_file = int(
                session.cmd_output(
                    cmd_findstr_in_file
                    % (new_virtio_disk_filepath, (new_reg_item + "\\" + reg_subkey2))
                )
                .split(":")[-1]
                .strip()
            )

            cmd_reg_query = params["cmd_reg_query"]
            exist_iotimeoutvalue_cmd = int(
                session.cmd_output(cmd_reg_query % (exist_reg_item, reg_subkey1))
            )
            new_iotimeoutvalue_cmd = int(
                session.cmd_output(cmd_reg_query % (new_reg_item, reg_subkey1))
            )
            new_timeoutvalue_cmd = int(
                session.cmd_output(cmd_reg_query % (new_reg_item, reg_subkey2))
            )
            if (
                exist_iotimeoutvalue_cmd != exist_iotimeoutvalue_file
                or new_iotimeoutvalue_cmd != new_iotimeoutvalue_file
                or new_timeoutvalue_cmd != new_timeoutvalue_file
            ):
                test.error(
                    "The value of %s and %s is not same between %s and cmd, Please "
                    "have a check" % (reg_subkey1, reg_subkey2, new_log_folder_path)
                )
        finally:
            session.cmd_output(params["cmd_reg_del"] % new_reg_item)
            session.cmd_output(
                cmd_reg_set_value % (exist_reg_item, reg_subkey1, iotimeoutvalue_cmd)
            )

    @error_context.context_aware
    def windegtool_check_includeSensitiveData_collection(self, test, params, env):
        """
        Test sensitive data collection functionality:
        1. Trigger BSOD using specified method
        2. Verify memory dump files are generated
        3. Run debug tool with sensitive data collection
        4. Verify all dump files are properly collected

        :param test: QEMU test object
        :param params: Dictionary with test parameters
        :param env: Dictionary with the test environment
        """
        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)

        error_context.context("Trigger BSOD situation.", LOG_JOB.info)
        crash_method = params["crash_method"]
        if crash_method == "nmi":
            timeout = int(params.get("timeout", 360))
            self.vm.monitor.nmi()
            time.sleep(timeout)
            self.vm.reboot(session, method=params["reboot_method"], timeout=timeout)

        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)
        session.cmd("cd %s" % self.tmp_dir)

        error_context.context("Check the dmp files are existed.", LOG_JOB.info)
        cmd_check_dmp_files = params["cmd_check_files"] % params["memory_dmp_file"]
        cmd_check_minidmp_dir = params["cmd_check_files"] % params["mini_dmp_folder"]
        output = session.cmd_output(
            "%s && %s" % (cmd_check_dmp_files, cmd_check_minidmp_dir)
        )
        if "dmp" not in output:
            test.error("Dump file should be existed, please have a check")
        else:
            self.run_tool_scripts(session)

    @error_context.context_aware
    def windegtool_check_trigger_driver_msinfo_collection(self, test, params, env):
        """
        Test system and driver information collection:
        1. Collect initial system name and driver info
        2. Change system name and modify driver state
        3. Verify changes are captured in subsequent collection
        4. Check setupapi logs for driver operations
        5. Verify accurate reflection of system changes

        :param test: QEMU test object
        :param params: Dictionary with test parameters
        :param env: Dictionary with the test environment
        """
        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)

        error_context.context(
            "Run script firstly to check system name and driver info.", LOG_JOB.info
        )
        session.cmd("cd %s" % self.tmp_dir)
        log_path = self.run_tool_scripts(session)
        msinfo_file_path = params["msinfo_file_path"] % log_path
        drv_list_file_path = params["drv_list_file_path"] % log_path
        target_driver = params["target_driver"]

        old_systemname = str(
            session.cmd_output(
                params["cmd_query_from_file"] % (msinfo_file_path, "System Name:")
            ).split(":")[1]
        ).strip()
        systemname_guest = str(
            session.cmd_output(params["cmd_check_systemname"])
        ).strip()
        if old_systemname != systemname_guest:
            test.error(
                "The system name are different between cmd and file that"
                " collect by tool, Please have a check"
            )
        drvinfo_output = session.cmd_output(
            params["cmd_query_from_file"] % (drv_list_file_path, target_driver)
        )
        if target_driver not in drvinfo_output:
            test.error(
                "%s doesn't installed, there is no info about it, "
                "Please have a check and change another target driver to test"
            )

        error_context.context(
            "Change the system name and uninstall certain driver.", LOG_JOB.info
        )
        new_system_name = params["new_system_name"]
        session.cmd(params["cmd_change_systemname"] % new_system_name)
        win_ver = str(
            session.cmd_output(params["cmd_query_ver_vm"], timeout=60)
        ).strip()
        if "2016" not in win_ver:
            driver_oem_file = session.cmd_output(
                params["cmd_query_oem_inf"] % target_driver
            ).strip()
            cmd_uninstall_driver = params["cmd_uninstall_driver"] % driver_oem_file
            s, o = session.cmd_status_output(cmd_uninstall_driver)
        else:
            cmd_get_2k16inf = params["cmd_search_2k16_inf_file_global"] % (
                target_driver + ".inf"
            )
            w2k16_inf = str(session.cmd_output(cmd_get_2k16inf, timeout=60)).strip()
            cmd_install_driver = params["cmd_install_driver"] % w2k16_inf
            s, o = session.cmd_status_output(cmd_install_driver)
        if s or "Fail" in o:
            test.error("Fail to execute %s driver, please check it." % target_driver)

        error_context.context(
            "Re-Run script after rebooting to check whether system"
            " name and driver info changed.",
            LOG_JOB.info,
        )
        session.cmd_output(params["reboot_command"])
        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)

        session.cmd("cd %s" % self.tmp_dir)
        new_log_path = self.run_tool_scripts(session)
        new_msinfo_file_path = params["msinfo_file_path"] % new_log_path
        new_drv_list_file_path = params["drv_list_file_path"] % new_log_path
        new_setupapi_dev_file_path = params["setupapi_dev_file_path"] % new_log_path
        new_systemname_file = params["cmd_query_from_file"] % (
            new_msinfo_file_path,
            "System Name:",
        )
        new_systemname = session.cmd_output(new_systemname_file).split(":")[1].strip()
        if new_system_name.upper() not in str(new_systemname):
            test.fail("New systemname wasn't captured by tool, Please have a check")
        new_drvinfo_output = session.cmd_output(
            params["cmd_query_from_file"] % (new_drv_list_file_path, target_driver)
        )
        if target_driver in new_drvinfo_output:
            test.fail(
                "Driver should be uninstalled, but tool wasn't captured this "
                "situation, Please have a check"
            )
        if "2016" not in win_ver:
            regex_cmd = cmd_uninstall_driver.replace(" ", r"\s+").replace(".", r"\.")
            setupapi_output = session.cmd_output(
                params["cmd_query_from_file"] % (new_setupapi_dev_file_path, regex_cmd)
            )
            if "/delete-driver" not in setupapi_output:
                test.fail(
                    "Driver execution operation was not captured, Please have a check."
                )
        else:
            setupapi_output = session.cmd_output(
                params["cmd_query_from_file"]
                % (new_setupapi_dev_file_path, "pnputil.exe")
            )
            if "/add-driver" not in setupapi_output:
                test.fail(
                    "Driver execution operation was not captured, Please have a check."
                )

    @error_context.context_aware
    def windegtool_check_networkadapter_collection(self, test, params, env):
        """
        Test network adapter information collection:
        1. Collect baseline network adapter settings
        2. Modify DNS and Jumbo Packet settings
        3. Verify changes are captured in collected data
        4. Test network setting restoration
        5. Verify accuracy of collected network information

        :param test: QEMU test object
        :param params: Dictionary with test parameters
        :param env: Dictionary with the test environment
        """
        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)
        session.cmd("cd %s" % self.tmp_dir)

        error_context.context(
            "Run tool script firstly, and conducting raw data comparison tests",
            LOG_JOB.info,
        )
        adapter_name = session.cmd_output(params["check_adapter_name"]).strip()
        original_log_path = self.run_tool_scripts(session)

        original_networkfile_path = params["networkfile_path"] % original_log_path
        raw_jp_value_from_file = session.cmd_output(
            params["cmd_findstr_in_file"] % (original_networkfile_path, "Jumbo Packet")
        )
        original_jp_value_from_file = int(raw_jp_value_from_file.split()[5])
        original_jp_value_from_cmd = int(
            session.cmd_output(params["check_adapter_jp_info"] % adapter_name)
        )
        if original_jp_value_from_cmd != original_jp_value_from_file:
            test.error(
                "Network info collection seems have problem, the value of"
                "Jumbo Packet is not same between file and cmd."
            )

        ipconfigfile_path = params["ipconfigfile_path"] % original_log_path
        original_ipconfig = session.cmd_output(
            params["cmd_findstr_in_file"] % (ipconfigfile_path, adapter_name)
        )
        dns_info = session.cmd_output(params["cmd_get_dns"]).split()
        for dns_info_item in dns_info:
            if dns_info_item not in original_ipconfig:
                test.error(
                    "DNS %s wasn't captured, please have a check" % dns_info_item
                )

        error_context.context(
            "Change the dhcp and check whether the file changed", LOG_JOB.info
        )
        static_dns = params["static_dns"]
        session.cmd_output(
            params["cmd_set_dns"] % (adapter_name, static_dns), timeout=360
        )

        log_folder_path_new = self.run_tool_scripts(session)
        ipconfigfile_path = params["ipconfigfile_path"] % log_folder_path_new
        new_ipconfig_output = session.cmd_output(
            params["cmd_findstr_in_file"] % (ipconfigfile_path, static_dns)
        )
        if static_dns not in new_ipconfig_output:
            test.fail("DNS should be changed but it's not, please check it.")
        else:
            error_context.context(
                "Checkpoint is pass, Re-enable adapter for next checkpoint.",
                LOG_JOB.info,
            )
            session.cmd(params["cmd_set_dns_dhcp"] % adapter_name)

        error_context.context(
            "Changed the 'Jumbo Packet' value and compare.", LOG_JOB.info
        )
        try:
            session.cmd_output(
                params["cmd_set_adapter_jp_info"] % (adapter_name, 9014), timeout=360
            )
        except ShellTimeoutError as e:
            LOG_JOB.warning("Network adapter setting timed out: %s", str(e))
            # Verify the setting was actually changed
            cmd = params["check_adapter_jp_info"] % adapter_name
            actual_value = int(session.cmd_output(cmd))
            if actual_value != 9014:
                test.error("Failed to change Jumbo Packet value")

            # Create new session only if needed
            try:
                session = self._get_session(params, self.vm)
                self._open_session_list.append(session)
                session.cmd("cd %s" % self.tmp_dir)
            except Exception as e:
                test.error(
                    "Failed to create new session after network change: %s" % str(e)
                )

        log_folder_path_new = self.run_tool_scripts(session)
        networkfile_path = params["networkfile_path"] % log_folder_path_new
        raw_jp_value = session.cmd_output(
            params["cmd_findstr_in_file"] % (networkfile_path, "Jumbo Packet")
        )
        new_jp_value = int(raw_jp_value.split()[5])
        if original_jp_value_from_file == new_jp_value:
            test.fail(
                "Jumbo Packet should not be same with the original one,Please check it."
            )
        if new_jp_value != 9014:
            test.error(
                "Jumbo Packet should be the new value, but it's not somehow,"
                "Please check it."
            )

        error_context.context("Recover the env.", LOG_JOB.info)
        try:
            session.cmd(
                params["cmd_set_adapter_jp_info"]
                % (adapter_name, original_jp_value_from_file)
            )
        except ShellTimeoutError as e:
            LOG_JOB.warning("Network adapter recovery setting timed out: %s", str(e))
            # Verify if the setting was actually changed despite timeout
            try:
                change_back_jp_value = int(
                    session.cmd_output(params["check_adapter_jp_info"] % adapter_name)
                )
                if change_back_jp_value != original_jp_value_from_file:
                    err_msg = (
                        f"expected {original_jp_value_from_file}, "
                        f"got {change_back_jp_value}"
                    )
                    test.error(err_msg)

                # Only create new session if verification passed
                try:
                    session = self._get_session(params, self.vm)
                    self._open_session_list.append(session)
                    session.cmd("cd %s" % self.tmp_dir)
                except Exception as e:
                    test.error(f"Failed to create new session after recovery: {str(e)}")
            except Exception as e:
                test.error(f"Failed to verify network adapter recovery: {str(e)}")

        # Final verification
        change_back_jp_value = int(
            session.cmd_output(params["check_adapter_jp_info"] % adapter_name)
        )
        if change_back_jp_value != original_jp_value_from_file:
            test.error(
                "Please have a check, the value wasn't changed back to original."
            )

    @error_context.context_aware
    def windegtool_check_documentation(self, test, params, env):
        """
        Verify documentation completeness and accuracy:
        1. Check presence of all required documentation files
        2. Verify command examples in documentation
        3. Test executable commands from documentation
        4. Verify command output matches documentation

        :param test: QEMU test object
        :param params: Dictionary with test parameters
        :param env: Dictionary with the test environment
        """

        def _clean_output(output):
            lines = output.splitlines()
            cleaned_lines = []

            for line in lines:
                line = line.strip()
                if not line or "powershell" in line:
                    continue
                cleaned_lines.append(line)
            return "\n".join(cleaned_lines)

        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)

        error_context.context(
            "Check all relevant official documents to ensure they are complete",
            LOG_JOB.info,
        )
        output = str(session.cmd_output("dir %s\\" % self.script_dir)).strip()
        standard_docs = (params["standard_docs"]).split(",")
        for standard_doc in standard_docs:
            if standard_doc not in output:
                test.error(
                    f"There is no file {standard_doc}, please contact with vendor."
                )

        error_context.context(
            "Address usable commands and execute them to ensure "
            "they are executable and accurate",
            LOG_JOB.info,
        )
        target_doc_path = "%s\\%s" % (self.script_dir, params["target_doc"])
        target_output = str(
            session.cmd_output(params["query_cmd_from_file"] % target_doc_path)
        ).strip()
        executable_cmds = _clean_output(target_output).splitlines()
        executable_cmd_final = 'powershell.exe -Command "'
        for executable_cmd in executable_cmds:
            executable_cmd_final += executable_cmd + "; "
        executable_cmd_final = executable_cmd_final.rstrip("; ") + '"'
        session.cmd(params["cmd_cp_file"] % (self.script_path, self.tmp_dir))
        session.cmd("cd %s" % self.tmp_dir)
        s, o = session.cmd_status_output(executable_cmd_final, timeout=360)

        include_sensitive_data = (
            True if "-IncludeSensitiveData" in executable_cmd_final else False
        )
        paths = self._get_path(o, session, sensitive_data=include_sensitive_data)
        if not all(paths):
            test.fail("Debug tool run failed, please check it.")

    @error_context.context_aware
    def windegtool_check_IO_limits(self, test, params, env):
        """
        Test IO metrics collection functionality:
        1. Collect baseline IO metrics
        2. Generate IO load in background
        3. Collect metrics during IO load
        4. Compare metrics to verify increased IO activity
        5. Verify accuracy of IO metrics collection

        :param test: QEMU test object
        :param params: Dictionary with test parameters
        :param env: Dictionary with the test environment
        """

        def _run_continuous_io(session, stop_event):
            """Helper function to continuously create and delete files"""
            i = 0
            while not stop_event.is_set():
                try:
                    session.cmd(params["cmd_fsutil"], timeout=30)
                    session.cmd(params["cmd_del_file"], timeout=30)
                    i += 1
                    if i >= 10:  # Limit iterations to prevent infinite loop
                        break
                except Exception as e:
                    LOG_JOB.error("Error in IO task: %s", str(e))
                    break

        session = self._get_session(params, self.vm)
        session1 = self._get_session(params, self.vm)
        self._open_session_list.extend([session, session1])
        session.cmd("cd %s" % self.tmp_dir)

        error_context.context(
            "Run script first time to collect baseline IO metrics", LOG_JOB.info
        )
        first_log_path = self.run_tool_scripts(session)

        # Get first IO limits file
        cmd_get_io = params["cmd_get_io_folder"] % first_log_path
        first_io_file = session.cmd_output(cmd_get_io).strip()
        if not first_io_file:
            test.error("Cannot find IO limits file in %s" % first_log_path)

        # Read first IO metrics
        first_metrics = {}
        first_output = session.cmd_output(params["cmd_cat_io"] % first_io_file)
        for line in first_output.splitlines():
            if "Disk" in line and ":" in line:
                key = line.split(":")[1].strip()
                value = float(line.split(":")[2].strip().split()[0].replace(",", ""))
                first_metrics[key] = value

        error_context.context(
            "Run script second time with continuous IO in background", LOG_JOB.info
        )

        # Start continuous IO in background
        stop_event = threading.Event()
        io_thread = threading.Thread(
            target=_run_continuous_io, args=(session1, stop_event)
        )
        io_thread.start()

        # Wait briefly for IO to start
        time.sleep(3)

        # Run debug tool while IO is running
        try:
            second_log_path = self.run_tool_scripts(session)
        finally:
            # Stop IO thread
            stop_event.set()
            io_thread.join(timeout=30)

        # Get second IO limits file
        cmd_get_io = params["cmd_get_io_folder"] % second_log_path
        second_io_file = session.cmd_output(cmd_get_io).strip()
        if not second_io_file:
            test.error("Cannot find IO limits file in %s" % second_log_path)

        # Read second IO metrics and compare
        second_output = session.cmd_output(params["cmd_cat_io"] % second_io_file)
        any_increased = False
        for line in second_output.splitlines():
            if "Disk" in line and ":" in line:
                key = line.split(":")[1].strip()
                value = float(line.split(":")[2].strip().split()[0].replace(",", ""))
                if key in first_metrics:
                    if value > first_metrics[key]:
                        any_increased = True
                        LOG_JOB.info(
                            "%s increased from %f to %f", key, first_metrics[key], value
                        )

        if not any_increased:
            test.fail("No IO metrics increased during continuous IO test")

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
    "-IncludeSensitiveData".
    3) Run some basic test for CollectSystemInfo.ps1.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    collectinfotool_test = WinDebugToolTestBasicCheck(test, params, env)
    collectinfotool_test.execute(test, params, env)
