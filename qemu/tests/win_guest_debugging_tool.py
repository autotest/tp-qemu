import logging
import re
import threading
import time

from aexpect.exceptions import ShellTimeoutError
from virttest import error_context

LOG_JOB = logging.getLogger("avocado.test")


class WinDebugToolTest:
    """
    Test class for the Windows Guest Debugging Tool.
    This class encapsulates the logic for testing the CollectSystemInfo.ps1 script.
    """

    def __init__(self, test, params, env):
        self.test = test
        self.params = params
        self.env = env
        self.vm = None
        self.session = None
        self.script_name = self.params.get("script_name", "CollectSystemInfo.ps1")
        self.script_path = ""
        self.script_dir = ""
        self.tmp_dir = self.params.get("test_tmp_dir", "${tmp_dir}\\testtmpdir")
        self._open_sessions = []

    def _get_session(self, new=False):
        """
        Gets a new or existing session to the VM.
        Manages sessions to avoid leaving them open.
        """
        if self.session and not new:
            # Ensure the existing session is tracked
            if self.session not in self._open_sessions:
                self._open_sessions.append(self.session)
            return self.session
        self.vm.verify_alive()
        timeout = self.params.get_numeric("login_timeout", 360)
        session = self.vm.wait_for_login(timeout=timeout)
        self._open_sessions.append(session)
        if new:
            return session
        self.session = session
        return self.session

    def _cleanup_sessions(self):
        """Closes all tracked sessions."""
        for s in self._open_sessions:
            try:
                if s:
                    s.close()
            except Exception as e:
                LOG_JOB.warning("Failed to close session: %s", e)
        self._open_sessions.clear()

    def setup(self):
        """
        Initial setup for the test environment on the guest VM.
        """
        self.vm = self.env.get_vm(self.params["main_vm"])
        self.vm.verify_alive()
        self.session = self._get_session()

        error_context.context("Locating debug tool script.", LOG_JOB.info)
        cmd = self.params["cmd_search_file_global"] % self.script_name
        raw = str(self.session.cmd_output(cmd, timeout=360))
        matches = [l.strip() for l in raw.splitlines() if l.strip()]
        if not matches:
            self.test.error(f"'{self.script_name}' not found on the guest.")
        if len(matches) > 1:
            self.test.log.info(
                "Multiple '%s' found; using first: %r",
                self.script_name,
                matches[:5],
            )
        self.script_path = matches[0]
        self.script_dir = self.script_path.replace(self.script_name, "").rstrip("\\")

        error_context.context("Creating temporary work directory.", LOG_JOB.info)
        self.session.cmd_output(self.params["cmd_create_dir"] % self.tmp_dir)
        self.session.cmd(f'cd "{self.tmp_dir}"')

        # Disable IE Enhanced Security Configuration for Win2016 if configured
        if self.params.get("cmd_disable_ie_esc_admin"):
            error_context.context(
                "Disabling IE Enhanced Security Configuration.", LOG_JOB.info
            )
            self.session.cmd(self.params["cmd_disable_ie_esc_admin"])
            self.session.cmd(self.params["cmd_disable_ie_esc_user"])

    def _run_script_and_get_paths(self, extra_args=""):
        """
        Runs the CollectSystemInfo.ps1 script and parses its output for file paths.

        :param extra_args: String of extra arguments to pass to the script.
        :return: A dictionary containing paths for logs and dumps.
        """
        cmd = (
            "powershell.exe -ExecutionPolicy Bypass "
            f'-File "{self.script_path}" {extra_args}'
        )
        script_timeout = int(self.params.get("script_execution_timeout", 720))
        status, output = self.session.cmd_status_output(cmd, timeout=script_timeout)

        if status != 0:
            self.test.fail(f"Script execution failed with status {status}")

        paths = {
            "log_folder": None,
            "log_zip": None,
            "dump_folder": None,
            "dump_zip": None,
        }

        log_folder_match = re.search(r"Log folder path: (.+)", output)
        if log_folder_match:
            paths["log_folder"] = log_folder_match.group(1).strip()
            paths["log_zip"] = f"{paths['log_folder']}.zip"
            self._check_generated_files(paths["log_folder"], is_dump=False)

        dump_folder_match = re.search(r"Dump folder path: (.+)", output)
        if dump_folder_match:
            paths["dump_folder"] = dump_folder_match.group(1).strip()
            paths["dump_zip"] = f"{paths['dump_folder']}.zip"
            self._check_generated_files(paths["dump_folder"], is_dump=True)

        if not paths["log_folder"]:
            self.test.fail("Failed to get log folder path from script output.")

        return paths

    def _check_generated_files(self, path, is_dump=False):
        """
        Verifies that the expected files are generated in the given path.
        """
        output = str(self.session.cmd_output(f'dir /b "{path}"')).strip()
        present = {line.strip() for line in output.splitlines() if line.strip()}
        target_files_key = "target_dump_files" if is_dump else "target_files"
        target_files = self.params[target_files_key].split(",")

        missing_files = [f for f in target_files if f not in present]
        if missing_files:
            self.test.error(
                f"Missing generated files in '{path}': {', '.join(missing_files)}"
            )

    def _execute_test_variant(self):
        """
        Dynamically calls the test method based on the 'windegtool_check_type'
        parameter from the configuration.
        """
        check_type = self.params.get("windegtool_check_type")
        if not check_type:
            self.test.error("'windegtool_check_type' not specified in config.")

        test_method_name = f"_check_{check_type}"
        if not hasattr(self, test_method_name):
            self.test.error(f"Unknown test type: '{check_type}'")
        test_method = getattr(self, test_method_name)

        LOG_JOB.info("--- Running test variant: %s ---", check_type)
        test_method()
        LOG_JOB.info("--- Finished test variant: %s ---", check_type)

    @error_context.context_aware
    def _check_script_execution(self):
        """
        Verifies basic script execution and that log/zip files are created.
        """
        paths = self._run_script_and_get_paths()
        if not (paths["log_folder"] and paths["log_zip"]):
            self.test.fail(
                "Basic script execution failed to produce log folder or zip."
            )

    @error_context.context_aware
    def _check_zip_package(self):
        """
        Verifies that the generated zip package is valid and matches the source folder.
        """
        paths = self._run_script_and_get_paths()
        log_folder, log_zip = paths["log_folder"], paths["log_zip"]

        error_context.context(
            "Extracting ZIP and comparing folder sizes.", LOG_JOB.info
        )
        extract_folder = f"{log_folder}_extracted"
        cmd_extract = self.params["cmd_extract_zip"] % (log_zip, extract_folder)
        status, _ = self.session.cmd_status_output(cmd_extract)
        if status != 0:
            self.test.error("Failed to extract the generated ZIP file.")

        size_cmd = self.params["cmd_check_folder_size"]
        original_size_str = self.session.cmd_output(size_cmd % log_folder).strip()
        extracted_size_str = self.session.cmd_output(size_cmd % extract_folder).strip()

        try:
            original_size = int(original_size_str.replace(",", ""))
            extracted_size = int(extracted_size_str.replace(",", ""))
        except ValueError:
            self.test.error(
                "Failed to parse folder sizes: "
                f"original='{original_size_str}', "
                f"extracted='{extracted_size_str}'"
            )

        if original_size != extracted_size:
            self.test.fail(
                "Size of original log folder and extracted folder do not "
                f"match. Original: {original_size_str}, Extracted: {extracted_size_str}"
            )

    @error_context.context_aware
    def _check_run_tools_multi_times(self):
        """
        Verifies script stability by running it multiple times in a loop.
        """
        error_context.context(
            "Running script 5 times for stability check.", LOG_JOB.info
        )
        for i in range(5):
            LOG_JOB.info("Running iteration %d...", i + 1)
            paths = self._run_script_and_get_paths()
            # Clean up for the next iteration
            self.session.cmd(self.params["cmd_remove_dir"] % paths["log_folder"])
            self.session.cmd(self.params["cmd_remove_dir"] % paths["log_zip"])

    @error_context.context_aware
    def _check_user_friendliness(self):
        """
        Tests user-friendly features like invalid parameter handling and
        interruption recovery.
        """
        # 1. Test invalid parameter handling
        error_context.context("Testing invalid parameter handling.", LOG_JOB.info)
        invalid_params = self.params["invalid_params"].split(",")
        expected_prompt = self.params["expect_output_prompt"]
        for param in invalid_params:
            cmd = (
                "powershell.exe -ExecutionPolicy Bypass "
                f"-File {self.script_path} {param}"
            )
            output = self.session.cmd_output(cmd, timeout=360)
            if expected_prompt not in output:
                self.test.fail(
                    "Script did not show expected friendly prompt for "
                    f"invalid param '{param}'."
                )

        # 2. Test interruption handling
        error_context.context("Testing script interruption handling.", LOG_JOB.info)
        session2 = self._get_session(new=True)

        def run_and_interrupt():
            try:
                # This is expected to time out when the process is terminated
                cmd = f"powershell.exe -ExecutionPolicy Bypass -File {self.script_path}"
                self.session.cmd_output(cmd, timeout=10)
            except ShellTimeoutError:
                LOG_JOB.info(
                    "Script execution timed out as expected after interruption."
                )
            except Exception as e:
                self.test.error(f"Unexpected error during script execution: {e}")

        script_thread = threading.Thread(target=run_and_interrupt)
        script_thread.start()
        time.sleep(5)  # Let the script run for a bit

        # Terminate the process from another session. Use cmd_status_output to
        # ignore non-zero exit codes, as processes may not exist.
        LOG_JOB.debug("Attempting to terminate powershell.exe process.")
        status1, output1 = session2.cmd_status_output(
            self.params["cmd_kill_powershell_process"]
        )
        LOG_JOB.debug(
            "Terminate powershell result - status: %s, output: %r",
            status1,
            output1,
        )

        LOG_JOB.debug("Attempting to terminate msinfo32.exe process.")
        status2, output2 = session2.cmd_status_output(
            self.params["cmd_kill_powershell_process1"]
        )
        LOG_JOB.debug(
            "Terminate msinfo32 result - status: %s, output: %r", status2, output2
        )
        script_thread.join()

        # Verify signal file exists
        # Find the latest SystemInfo directory
        find_cmd = (
            'powershell.exe -Command "'
            "Get-ChildItem -Directory -Filter SystemInfo_* | "
            "Sort-Object LastWriteTime -Descending | "
            "Select-Object -First 1 -ExpandProperty Name"
            '"'
        )
        query_output = self.session.cmd_output(find_cmd)
        output_lines = query_output.splitlines()

        if not output_lines or not output_lines[0].strip():
            # Fallback to original command if the new one fails
            query_cmd = self.params["cmd_query_path"]
            query_output = self.session.cmd_output(query_cmd)
            output_lines = query_output.splitlines()

        if not output_lines or not output_lines[0].strip():
            self.test.error("Failed to find SystemInfo directory.")

        # Construct the full path to the log directory
        log_path = output_lines[0].strip()
        if not log_path.startswith("C:\\") and not log_path.startswith(self.tmp_dir):
            log_path = f"{self.tmp_dir}\\{log_path}"

        signal_file = self.params["script_interrupt_signal_file"]
        dir_output = self.session.cmd_output(f'dir "{log_path}"')

        if signal_file not in dir_output:
            self.test.fail(
                f"Interruption signal file '{signal_file}' was not created. "
                f"Directory contents: {dir_output}"
            )

        # 3. Test recovery
        error_context.context(
            "Testing script recovery after interruption.", LOG_JOB.info
        )
        self.session.cmd(self.params["cmd_dir_del"] % log_path)
        self._check_script_execution()  # A simple run to confirm it works again

    @error_context.context_aware
    def _check_trigger_driver_msinfo_collection(self):
        """
        Tests collection of dynamically changing system and driver info.
        """
        # 1. Baseline
        paths = self._run_script_and_get_paths()
        guest_sysname = self.session.cmd_output(
            self.params["cmd_check_systemname"]
        ).strip()
        msinfo_file = f"{paths['log_folder']}\\msinfo32.txt"

        # Extract system name from the first line that contains a colon
        raw_query_output = self.session.cmd_output(
            self.params["cmd_query_from_file"] % (msinfo_file, "System Name")
        )
        file_sysname_raw = ""
        for line in raw_query_output.splitlines():
            if ":" in line:
                file_sysname_raw = line.split(":")[-1].strip()
                break

        # Clean both values to compare only alphanumeric parts and hyphens
        clean_guest_sysname = re.sub(r"[^A-Z0-9-]", "", guest_sysname.upper())
        clean_file_sysname = re.sub(r"[^A-Z0-9-]", "", file_sysname_raw.upper())

        if clean_guest_sysname != clean_file_sysname:
            self.test.error(
                f"Initial system name mismatch between guest and collected file. "
                f"Guest: '{clean_guest_sysname}', File: '{clean_file_sysname}'"
            )

        # 2. Modify system
        error_context.context(
            "Changing system name and uninstalling driver.", LOG_JOB.info
        )
        new_name = self.params["new_system_name"]
        self.session.cmd(self.params["cmd_change_systemname"] % new_name)
        target_driver = self.params["target_driver"]
        oem_inf = self.session.cmd_output(
            self.params["cmd_query_oem_inf"] % target_driver
        ).strip()
        driver_uninstalled = False
        if oem_inf:
            # Disable the device first before uninstalling driver
            if self.params.get("cmd_disable_device"):
                LOG_JOB.info(
                    "Disabling device '%s' before driver uninstall.", target_driver
                )
                status, output = self.session.cmd_status_output(
                    self.params["cmd_disable_device"] % (target_driver, target_driver)
                )
                if status != 0:
                    LOG_JOB.warning(
                        "Failed to disable device '%s': %s", target_driver, output
                    )

            # Uninstall the driver
            status, output = self.session.cmd_status_output(
                self.params["cmd_uninstall_driver"] % oem_inf
            )
            if status != 0:
                LOG_JOB.warning(
                    "Failed to uninstall driver '%s' (oem_inf: %s): %s",
                    target_driver,
                    oem_inf,
                    output,
                )
            else:
                driver_uninstalled = True
                LOG_JOB.info("Successfully uninstalled driver '%s'.", target_driver)
        else:
            LOG_JOB.warning(
                "Could not find OEM INF for '%s', skipping uninstall.",
                target_driver,
            )

        # 3. Reboot and verify
        self.session.cmd_output(self.params["reboot_command"])
        self.session = self._get_session(new=True)
        self.session.cmd(f'cd "{self.tmp_dir}"')

        new_paths = self._run_script_and_get_paths()
        new_msinfo_file = f"{new_paths['log_folder']}\\msinfo32.txt"
        new_query_output = self.session.cmd_output(
            self.params["cmd_query_from_file"] % (new_msinfo_file, "System Name")
        )

        # Extract system name from the first line that contains a colon
        new_file_sysname = ""
        for line in new_query_output.splitlines():
            if ":" in line:
                new_file_sysname = line.split(":")[-1].strip()
                break
        if new_name.upper() not in new_file_sysname.upper():
            self.test.fail("System name change was not captured by the script.")

        drv_list_file = f"{new_paths['log_folder']}\\drv_list.csv"
        drv_list_output = self.session.cmd_output(
            self.params["cmd_query_from_file"] % (drv_list_file, target_driver)
        )
        if driver_uninstalled and target_driver in drv_list_output:
            self.test.fail(
                "Uninstalled driver is still present in the collected driver list."
            )

    @error_context.context_aware
    def _check_networkadapter_collection(self):
        """
        Tests collection of network adapter settings.
        """
        adapter_name = self.session.cmd_output(
            self.params["check_adapter_name"]
        ).strip()
        original_jp_value = int(
            self.session.cmd_output(self.params["check_adapter_jp_info"] % adapter_name)
        )

        # 1. Modify Jumbo Packet
        error_context.context("Modifying 'Jumbo Packet' setting.", LOG_JOB.info)
        new_jp_value = 9014
        try:
            self.session.cmd_output(
                self.params["cmd_set_adapter_jp_info"] % (adapter_name, new_jp_value),
                timeout=360,
            )
        except ShellTimeoutError:
            LOG_JOB.warning(
                "Timeout occurred while setting Jumbo Packet. Verifying change..."
            )
            # Re-establish session if it was dropped
            self.session = self._get_session(new=True)
            self.session.cmd(f'cd "{self.tmp_dir}"')

        current_jp_value = int(
            self.session.cmd_output(self.params["check_adapter_jp_info"] % adapter_name)
        )
        if current_jp_value != new_jp_value:
            self.test.error(f"Failed to set Jumbo Packet value to {new_jp_value}.")

        # 2. Run script and verify
        paths = self._run_script_and_get_paths()
        network_file = f"{paths['log_folder']}\\NetworkInterfaces.txt"
        jp_from_file_raw = self.session.cmd_output(
            self.params["cmd_findstr_in_file"] % (network_file, "Jumbo Packet")
        )

        # Split by multiple spaces to get columns from the first line
        # Format: AdapterName  DisplayName  DisplayValue  RegistryName  RegistryValue
        first_line = jp_from_file_raw.splitlines()[0] if jp_from_file_raw else ""
        columns = re.split(r"\s{2,}", first_line.strip())

        # The DisplayValue should be the 3rd column (index 2)
        jp_from_file = 0
        if len(columns) >= 3:
            jp_from_file_str = re.sub(r"\D", "", columns[2])
            jp_from_file = int(jp_from_file_str) if jp_from_file_str else 0

        if jp_from_file != new_jp_value:
            self.test.fail(
                f"Jumbo Packet change not captured. Expected {new_jp_value}, "
                f"got {jp_from_file}."
            )

        # 3. Cleanup
        error_context.context(
            "Restoring original 'Jumbo Packet' setting.", LOG_JOB.info
        )
        try:
            self.session.cmd_output(
                self.params["cmd_set_adapter_jp_info"]
                % (adapter_name, original_jp_value),
                timeout=360,
            )
        except ShellTimeoutError:
            LOG_JOB.warning(
                "Timeout occurred while restoring Jumbo Packet. Verifying change..."
            )
            self.session = self._get_session(new=True)

        final_jp_value = int(
            self.session.cmd_output(self.params["check_adapter_jp_info"] % adapter_name)
        )
        if final_jp_value != original_jp_value:
            self.test.error(f"Failed to restore Jumbo Packet to {original_jp_value}.")

    @error_context.context_aware
    def _check_documentation(self):
        """
        Verifies the tool's documentation is complete and its examples are accurate.
        """
        error_context.context(
            "Checking for standard documentation files.", LOG_JOB.info
        )
        dir_output = self.session.cmd_output(f'dir "{self.script_dir}"')
        standard_docs = [
            doc.strip().strip('"') for doc in self.params["standard_docs"].split(",")
        ]
        for doc in standard_docs:
            if doc not in dir_output:
                self.test.error(f"Standard documentation file '{doc}' is missing.")

        error_context.context("Testing command examples from README.md.", LOG_JOB.info)
        readme_path = f"{self.script_dir}\\{self.params['target_doc']}"

        # Extract PowerShell command from README
        cmd_output = self.session.cmd_output(
            self.params["query_cmd_from_file"] % readme_path
        )

        # Find the command that runs the .ps1 script
        command_line = ""
        lines = cmd_output.splitlines()
        for i, line in enumerate(lines):
            if "```powershell" in line and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if ".ps1" in next_line:
                    command_line = next_line
                    break
        if not command_line:
            self.test.fail("Could not find a valid .ps1 command example in README.md.")

        # Copy script to tmp_dir to run the example command
        self.session.cmd(self.params["cmd_cp_file"] % (self.script_path, "."))

        # Convert PowerShell syntax to cmd.exe compatible format
        if command_line.startswith(".\\"):
            ps_script_and_args = command_line[2:]
            full_command = (
                f"powershell.exe -ExecutionPolicy Bypass -File {ps_script_and_args}"
            )
        else:
            full_command = command_line

        # Execute the command from documentation
        status, output = self.session.cmd_status_output(full_command, timeout=360)

        # Verify it ran successfully by checking for output paths
        log_folder_match = re.search(r"Log folder path: (.+)", output)
        if not log_folder_match:
            self.test.fail(
                f"Command from documentation failed to execute successfully. "
                f"Status: {status}, Output: {output}"
            )

    @error_context.context_aware
    def _check_disk_registry_collection(self):
        """
        Tests the accuracy of disk and registry information collection.
        """
        # 1. Get baseline
        paths = self._run_script_and_get_paths()
        virtio_disk_file = self.params["virtio_disk_filepath"] % paths["log_folder"]
        exist_reg = self.params["exist_reg_item"]
        reg_subkey1, reg_subkey2 = (
            self.params["reg_subkey1"],
            self.params["reg_subkey2"],
        )

        def get_reg_value_from_file(file, item, subkey):
            # Use PowerShell Select-String to handle potential line wrapping and
            # partial matches
            # Context 0,1 gets the matching line and the following line
            cmd = (
                f"powershell.exe -Command \"Select-String -Path '{file}' "
                f"-Pattern '{subkey}' -Context 0,1 | "
                f'ForEach-Object {{ $_.Line; $_.Context.PostContext }}"'
            )
            output = self.session.cmd_output(cmd).strip()

            if not output:
                self.test.error(
                    f"Registry key '{subkey}' not found in file '{file}'. "
                    f"Please check if the file contains registry information."
                )

            # Parse the output
            lines = output.splitlines()
            for i, line in enumerate(lines):
                if item in line and ":" in line:
                    # Ensure subkey is a distinct word to avoid partial matches
                    # e.g., 'TimeoutValue' matching 'IoTimeoutValue'
                    if not re.search(rf"\b{re.escape(subkey)}\b", line):
                        continue

                    parts = line.rsplit(":", 1)
                    value_str = parts[1].strip()

                    if value_str.isdigit():
                        return int(value_str)
                    elif not value_str and i + 1 < len(lines):
                        # Check next line for wrapped value
                        next_line = lines[i + 1].strip()
                        if next_line.isdigit():
                            return int(next_line)

            self.test.error(
                f"Could not find registry value for '{item}\\{subkey}'. "
                f"Search results: {output}"
            )

        def get_reg_value_from_guest(item, subkey):
            cmd = self.params["cmd_reg_query"] % (item, subkey)
            return int(self.session.cmd_output(cmd))

        val1_file = get_reg_value_from_file(virtio_disk_file, exist_reg, reg_subkey1)
        val1_guest = get_reg_value_from_guest(exist_reg, reg_subkey1)
        if val1_file != val1_guest:
            self.test.error(f"Initial registry value mismatch for {reg_subkey1}.")

        # 2. Modify registry
        error_context.context("Modifying registry for verification.", LOG_JOB.info)
        new_reg = self.params["new_reg_item"]
        key_val1 = int(self.params["key_value1"])
        key_val2 = int(self.params["key_value2"])

        try:
            # Create new keys and set values
            self.session.cmd(self.params["cmd_reg_add_item"] % (new_reg, new_reg))
            self.session.cmd(
                self.params["cmd_reg_add_item_key"] % (new_reg, new_reg, reg_subkey1)
            )
            self.session.cmd(
                self.params["cmd_reg_add_item_key"] % (new_reg, new_reg, reg_subkey2)
            )
            self.session.cmd(
                self.params["cmd_reg_set_value"] % (exist_reg, reg_subkey1, key_val1)
            )
            self.session.cmd(
                self.params["cmd_reg_set_value"] % (new_reg, reg_subkey1, key_val1)
            )
            self.session.cmd(
                self.params["cmd_reg_set_value"] % (new_reg, reg_subkey2, key_val2)
            )

            # 3. Re-run and verify changes
            new_paths = self._run_script_and_get_paths()
            new_file = self.params["virtio_disk_filepath"] % new_paths["log_folder"]

            if get_reg_value_from_file(new_file, exist_reg, reg_subkey1) != key_val1:
                self.test.fail("Modification of existing registry key not captured.")
            if get_reg_value_from_file(new_file, new_reg, reg_subkey1) != key_val1:
                self.test.fail("Creation of new registry key (1) not captured.")
            if get_reg_value_from_file(new_file, new_reg, reg_subkey2) != key_val2:
                self.test.fail("Creation of new registry key (2) not captured.")

        finally:
            # 4. Cleanup
            error_context.context("Cleaning up registry changes.", LOG_JOB.info)
            self.session.cmd(self.params["cmd_reg_del"] % new_reg)
            self.session.cmd(
                self.params["cmd_reg_set_value"] % (exist_reg, reg_subkey1, val1_guest)
            )

    @error_context.context_aware
    def _check_includeSensitiveData_collection(self):
        """
        Tests the collection of sensitive data (crash dumps).
        """
        error_context.context("Triggering BSOD via NMI.", LOG_JOB.info)
        self.vm.monitor.nmi()
        # Wait for the VM to crash and reboot
        time.sleep(int(self.params.get("timeout", 360)))
        self.vm.reboot(self.session, method=self.params["reboot_method"])
        self.session = self._get_session(new=True)
        self.session.cmd(f'cd "{self.tmp_dir}"')

        error_context.context(
            "Verifying dump file existence post-reboot.", LOG_JOB.info
        )
        dmp_file = self.params["memory_dmp_file"]
        minidmp_folder = self.params["mini_dmp_folder"]
        output = self.session.cmd_output(f'dir "{dmp_file}" && dir "{minidmp_folder}"')
        if "dmp" not in output.lower():
            self.test.error("Memory dump files were not created after BSOD.")

        error_context.context("Running script to collect sensitive data.", LOG_JOB.info)
        paths = self._run_script_and_get_paths(extra_args="-IncludeSensitiveData")
        if not (paths["dump_folder"] and paths["dump_zip"]):
            self.test.fail(
                "Script failed to collect dump files with -IncludeSensitiveData."
            )

    @error_context.context_aware
    def _check_IO_limits(self):
        """
        Tests the collection of IO metrics under load.
        """
        # 1. Get baseline metrics
        error_context.context("Collecting baseline IO metrics.", LOG_JOB.info)
        paths = self._run_script_and_get_paths()
        io_file_path_cmd = self.params["cmd_get_io_folder"] % paths["log_folder"]
        baseline_io_file = self.session.cmd_output(io_file_path_cmd).strip()
        if not baseline_io_file:
            self.test.error("Could not find baseline IO metrics file.")

        baseline_output = self.session.cmd_output(
            self.params["cmd_cat_io"] % baseline_io_file
        )
        baseline_metrics = {
            m[0]: float(m[1].split()[0].replace(",", "")) if len(m) >= 2 else 0.0
            for line in baseline_output.splitlines()
            if "Disk" in line and len(m := line.split(":")[-2:]) >= 2
        }

        # 2. Generate IO load and get new metrics
        error_context.context(
            "Generating IO load and collecting new metrics.", LOG_JOB.info
        )
        session2 = self._get_session(new=True)
        stop_event = threading.Event()

        def io_task():
            """Continuously create and delete a large file."""
            while not stop_event.is_set():
                try:
                    session2.cmd(self.params["cmd_fsutil"], timeout=60)
                    session2.cmd(self.params["cmd_del_file"], timeout=60)
                except Exception as e:
                    LOG_JOB.error("Error in IO task: %s", e)
                    break

        io_thread = threading.Thread(target=io_task)
        io_thread.start()
        time.sleep(5)  # Allow IO to start

        try:
            new_paths = self._run_script_and_get_paths()
        finally:
            stop_event.set()
            io_thread.join(timeout=60)

        # 3. Compare metrics
        new_io_file_path_cmd = (
            self.params["cmd_get_io_folder"] % new_paths["log_folder"]
        )
        new_io_file = self.session.cmd_output(new_io_file_path_cmd).strip()
        new_output = self.session.cmd_output(self.params["cmd_cat_io"] % new_io_file)
        new_metrics = {
            m[0]: float(m[1].split()[0].replace(",", "")) if len(m) >= 2 else 0.0
            for line in new_output.splitlines()
            if "Disk" in line and len(m := line.split(":")[-2:]) >= 2
        }

        if not any(new_metrics.get(k, 0) > v for k, v in baseline_metrics.items()):
            self.test.fail("IO metrics did not increase under load.")
        LOG_JOB.info("IO metrics increased as expected.")

    @error_context.context_aware
    def _check_MTV_firstboot_log_collection(self):
        """
        Verifies that the Firstboot log is correctly collected and renamed.
        """
        firstboot_dir = self.params.get("firstboot_dir")
        firstboot_file = self.params.get("firstboot_file")
        full_path = f"{firstboot_dir}\\{firstboot_file}"
        content = self.params.get("firstboot_content")

        # 1. Check and prepare the environment
        error_context.context(
            "Checking and preparing Firstboot log file.", LOG_JOB.info
        )
        # Check if file exists
        check_cmd = f"powershell.exe -Command \"Test-Path '{full_path}'\""
        exists = self.session.cmd_output(check_cmd).strip().lower() == "true"

        if not exists:
            LOG_JOB.info("Firstboot log not found. Creating it...")
            self.session.cmd(self.params["cmd_create_firstboot_dir"] % firstboot_dir)
            self.session.cmd(
                self.params["cmd_create_firstboot_file"] % (full_path, content)
            )
        else:
            LOG_JOB.info("Firstboot log found. Updating content...")
            self.session.cmd(
                self.params["cmd_create_firstboot_file"] % (full_path, content)
            )

        # 2. Run script
        paths = self._run_script_and_get_paths()

        # 3. Verify collection
        error_context.context(
            "Verifying Firstboot log collection and renaming.", LOG_JOB.info
        )
        collected_name = self.params.get("collected_file_name")
        collected_path = f"{paths['log_folder']}\\{collected_name}"

        # Check existence
        check_collected_cmd = (
            f"powershell.exe -Command \"Test-Path '{collected_path}'\""
        )
        collected_exists = (
            self.session.cmd_output(check_collected_cmd).strip().lower() == "true"
        )

        if not collected_exists:
            self.test.fail(
                f"Collected file '{collected_name}' not found in log folder."
            )

        # Check content
        collected_content = self.session.cmd_output(
            self.params["cmd_check_file_content"] % collected_path
        ).strip()

        if content not in collected_content:
            self.test.fail(
                "Collected file content does not match expected content.\n"
                f"Expected: {content}\n"
                f"Actual: {collected_content}"
            )

    @error_context.context_aware
    def execute(self):
        """
        Main execution flow for the test.
        """
        try:
            self.setup()
            self._execute_test_variant()
        finally:
            self._cleanup_sessions()


def run(test, params, env):
    """
    Entry point for the test.
    """
    # The old BaseVirtTest class is no longer needed.
    # We instantiate our new, self-contained test class and run it.
    win_debug_test = WinDebugToolTest(test, params, env)
    win_debug_test.execute()
