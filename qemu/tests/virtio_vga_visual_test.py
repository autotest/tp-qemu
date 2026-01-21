import logging
import os
import re
import shutil
import time
from subprocess import PIPE, Popen

from avocado.utils import process
from virttest import data_dir, error_context, ppm_utils, utils_misc
from virttest.utils_windows import wmic

from provider import win_driver_utils

LOG_JOB = logging.getLogger("avocado.test")


class VNCEnvironmentManager:
    """Manages VNC testing environment setup on the host machine."""

    def __init__(self, params):
        self.params = params

        # Tool configuration
        self.tool_name = "gvncviewer-customize"
        self.tool_url = params.get("gvncviewer_tool_url", "")
        self.tool_install_path = "/usr/bin/gvncviewer-customize"
        self.tool_download_path = "/tmp/%s" % self.tool_name

        # Display configuration
        self.display_num = params.get("vnc_display_num", "99")
        self.display_resolution = params.get("vnc_display_resolution", "1920x1080")
        self.display_depth = params.get("vnc_display_depth", "24")

        # State tracking
        self.display_process = None
        self.rhel_version = None
        self.display_type = None  # 'xvfb' or 'xwayland'

    def _run_cmd(self, cmd, check=True, timeout=60, shell=False):
        """Execute shell command with error handling."""
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd

        try:
            result = process.run(
                cmd_str,
                timeout=timeout,
                ignore_status=not check,
                shell=shell,
                verbose=False,
            )

            return result.exit_status, result.stdout_text, result.stderr_text

        except process.CmdError as e:
            if check:
                raise RuntimeError(
                    "Command failed: %s\nSTDERR: %s" % (cmd_str, e.result.stderr_text)
                )
            return e.result.exit_status, e.result.stdout_text, e.result.stderr_text

    def detect_rhel_version(self):
        """Detect RHEL major version."""
        try:
            if os.path.exists("/etc/redhat-release"):
                with open("/etc/redhat-release", "r") as f:
                    content = f.read()
                match = re.search(r"release\s+(\d+)", content, re.IGNORECASE)
                if match:
                    version = int(match.group(1))
                    self.rhel_version = version
                    return version
        except Exception:
            pass

        # Default to RHEL 9
        self.rhel_version = 9
        return 9

    def install_gdm(self):
        """Install GDM if not present."""
        rc, _, _ = self._run_cmd(["rpm", "-q", "gdm"], check=False)
        if rc == 0:
            return True

        self._run_cmd(["yum", "install", "-y", "gdm"], timeout=300)
        return True

    def install_xvfb(self):
        """Install Xvfb for RHEL 8/9."""
        rc, _, _ = self._run_cmd(["which", "Xvfb"], check=False)
        if rc == 0:
            self.display_type = "xvfb"
            return True

        self._run_cmd(["yum", "install", "-y", "xorg-x11-server-Xvfb"], timeout=300)
        self.display_type = "xvfb"
        return True

    def install_xwayland(self):
        """Install xwayland-run for RHEL 10+."""
        rc, _, _ = self._run_cmd(["which", "xwfb-run"], check=False)
        if rc == 0:
            self.display_type = "xwayland"
            return True

        self._run_cmd(["yum", "install", "-y", "xwayland-run"], timeout=300)
        self.display_type = "xwayland"
        return True

    def start_xvfb(self):
        """Start Xvfb virtual display server."""
        display = ":%s" % self.display_num
        resolution = "%sx%s" % (self.display_resolution, self.display_depth)

        # Check if display already running by checking lock file
        lock_file = "/tmp/.X%s-lock" % self.display_num
        if os.path.exists(lock_file):
            os.environ["DISPLAY"] = display
            return True

        # Start Xvfb in background
        cmd = ["Xvfb", display, "-screen", "0", resolution, "-fbdir", "/tmp"]

        self.display_process = Popen(
            cmd, stdout=PIPE, stderr=PIPE, start_new_session=True
        )

        time.sleep(2)

        # Verify it's running
        if self.display_process.poll() is not None:
            _, stderr = self.display_process.communicate()
            raise RuntimeError("Xvfb failed to start: %s" % stderr.decode())

        # Set DISPLAY environment variable
        os.environ["DISPLAY"] = display

        return True

    def download_tool(self):
        """Download gvncviewer-customize from server."""
        if not self.tool_url:
            raise ValueError("gvncviewer_tool_url not specified in test parameters")

        # Remove old download
        if os.path.exists(self.tool_download_path):
            os.remove(self.tool_download_path)

        # Use curl or wget
        rc, _, _ = self._run_cmd(["which", "curl"], check=False)
        if rc == 0:
            self._run_cmd(
                ["curl", "-L", "-o", self.tool_download_path, self.tool_url],
                timeout=120,
            )
        else:
            self._run_cmd(
                ["wget", "-O", self.tool_download_path, self.tool_url], timeout=120
            )

        # Verify download
        if (
            not os.path.exists(self.tool_download_path)
            or os.path.getsize(self.tool_download_path) == 0
        ):
            raise RuntimeError("Tool download failed")

        return self.tool_download_path

    def install_tool(self):
        """Install gvncviewer-customize to /usr/bin."""
        # Check if already installed and executable
        if os.path.exists(self.tool_install_path) and os.access(
            self.tool_install_path, os.X_OK
        ):
            return True

        # Download if needed
        if not os.path.exists(self.tool_download_path):
            self.download_tool()

        # Make executable and move to /usr/bin
        os.chmod(self.tool_download_path, 0o755)
        self._run_cmd(["mv", self.tool_download_path, self.tool_install_path])

        # Verify installation
        if not os.path.exists(self.tool_install_path) or not os.access(
            self.tool_install_path, os.X_OK
        ):
            raise RuntimeError("Tool installation failed")

        return True

    def setup(self):
        """Complete environment setup process."""
        # Detect RHEL version
        version = self.detect_rhel_version()

        # Install GDM
        self.install_gdm()

        # Install display server based on RHEL version
        if version >= 10:
            # RHEL 10+: Use xwayland-run
            self.install_xwayland()
        else:
            # RHEL 8/9: Use Xvfb
            self.install_xvfb()
            self.start_xvfb()

        # Download and install tool
        self.install_tool()

        LOG_JOB.debug(
            "VNC Environment: VNC environment ready: RHEL %d, display=%s, tool=%s",
            version,
            self.display_type,
            self.tool_install_path,
        )

        return True

    def cleanup(self):
        """Clean up resources."""
        if self.display_process:
            try:
                LOG_JOB.debug(
                    "VNC Environment: Stopping Xvfb (PID %d)", self.display_process.pid
                )
                self.display_process.terminate()
                self.display_process.wait(timeout=5)
            except Exception:
                pass

        if "DISPLAY" in os.environ:
            del os.environ["DISPLAY"]


class VirtioVgaVisualTest:
    """Visual testing framework for virtio-vga driver."""

    def __init__(self, test, params, env):
        self.test = test
        self.params = params
        self.env = env
        self.vm = None
        self.session = None

        # Screenshot directory
        self.results_dir = os.path.join(test.debugdir, "visual_checks")
        if not os.path.exists(self.results_dir):
            os.makedirs(self.results_dir)

        self._open_session_list = []
        self._env_mgr = None
        self._env_setup_done = False

    def _get_session(self):
        """Get a session and track it for cleanup."""
        self.vm.verify_alive()
        timeout = int(self.params.get("login_timeout", 360))
        session = self.vm.wait_for_login(timeout=timeout)
        self._open_session_list.append(session)
        return session

    def _cleanup_open_session(self):
        """Close all tracked sessions and cleanup VNC environment."""
        for s in self._open_session_list:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        self._open_session_list = []

        # Cleanup VNC environment
        if self._env_mgr:
            try:
                self._env_mgr.cleanup()
            except Exception:
                pass

    def _ensure_vnc_environment(self):
        """Ensure VNC environment is set up (one-time operation)."""
        if self._env_setup_done:
            return

        error_context.context("Setting up VNC environment", LOG_JOB.info)

        try:
            self._env_mgr = VNCEnvironmentManager(self.params)
            self._env_mgr.setup()
            self._env_setup_done = True
        except Exception as e:
            raise RuntimeError("Cannot initialize VNC environment: %s" % e)

    def _vnc_screendump(self, filename):
        """Capture screenshot via VNC using gvncviewer-customize tool."""
        # Convert VNC port to display number (e.g., 5900->0, 5901->1)
        vnc_port = self.vm.get_vnc_port()
        vnc_display = vnc_port - 5900
        vnc_host = self.params.get("vnc_host", "127.0.0.1")

        LOG_JOB.info(
            "Capturing VNC screenshot from %s:%s (port %s)",
            vnc_host,
            vnc_display,
            vnc_port,
        )

        # Build command
        cmd = []

        # Add xwayland wrapper for RHEL 10+
        if self._env_mgr.display_type == "xwayland":
            cmd.extend(
                [
                    "xwfb-run",
                    "-c",
                    "mutter",
                    "-s",
                    "\\\\-geometry",
                    "-s",
                    self._env_mgr.display_resolution,
                    "--",
                ]
            )

        # Add gvncviewer-customize command
        cmd.extend(
            [
                self._env_mgr.tool_install_path,
                "-s",
                "%s:%s" % (vnc_host, vnc_display),
                "-c",
            ]
        )

        LOG_JOB.debug("VNC command: %s", " ".join(cmd))

        try:
            # Execute screenshot command
            result = process.run(cmd, timeout=30, ignore_status=True, verbose=False)

            if result.exit_status != 0:
                raise RuntimeError("Screenshot command failed: %s" % result.stderr_text)

            # gvncviewer-customize saves to /home/desktop.png by default
            default_screenshot = "/home/desktop.png"

            if not os.path.exists(default_screenshot):
                raise RuntimeError(
                    "Screenshot file not found at %s" % default_screenshot
                )

            # Ensure output directory exists
            output_dir = os.path.dirname(filename)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)

            # Move screenshot to desired location
            shutil.move(default_screenshot, filename)

            if not os.path.exists(filename):
                raise RuntimeError("Failed to move screenshot to %s" % filename)

            LOG_JOB.info("VNC screenshot saved to %s", filename)
            return os.path.abspath(filename)

        except Exception as e:
            raise RuntimeError("VNC screenshot capture failed: %s" % e)

    def _internal_screendump(self, filename):
        """
        Capture screenshot inside the Windows Guest using PowerShell.

        Transfer to Host. The script 'Capture-Screen.ps1' is expected on
        the winutils.iso.
        """
        cmd_format = self.params.get(
            "internal_screenshot_cmd",
            default="powershell.exe -ExecutionPolicy Bypass -File %s",
        )
        script_path = self.params.get(
            "internal_screenshot_script",
            default=r"WIN_UTILS:\Capture-Screen.ps1",
        )

        # Resolve WIN_UTILS: placeholder to actual drive letter
        script_path = self._resolve_winutils_path(script_path)
        cmd = cmd_format % script_path

        LOG_JOB.info("Executing internal screenshot script from winutils.iso...")
        try:
            output = self.session.cmd_output(cmd, timeout=60)

            match = re.search(r"SUCCESS: Screenshot saved to (.*)", output)
            if not match:
                raise RuntimeError(
                    "Screenshot script failed or output format changed. "
                    "Output:\n%s" % output
                )

            guest_img_path = match.group(1).strip()
            LOG_JOB.debug("Guest saved screenshot to: %s", guest_img_path)

            temp_local_path = os.path.join(
                self.results_dir, "tmp_%s" % os.path.basename(filename)
            )
            self.vm.copy_files_from(guest_img_path, temp_local_path)

            if not os.path.exists(temp_local_path):
                raise RuntimeError(
                    "File transfer reported success but file missing on host."
                )

            final_dir = os.path.dirname(filename)
            if final_dir and not os.path.exists(final_dir):
                os.makedirs(final_dir)

            os.rename(temp_local_path, filename)
            LOG_JOB.info("Internal screenshot successfully saved to %s", filename)

            delete_cmd = self.params.get("delete_file_cmd") % guest_img_path
            self.session.cmd_status(delete_cmd, timeout=30)

            return filename

        except Exception as e:
            LOG_JOB.error("Internal screendump failed: %s", e)
            raise

    def _capture_visual_evidence(self, suffix, use_vnc=False):
        """
        Capture visual evidence using VNC and Internal Guest Screenshot.

        VNC (primary) and Internal Guest Screenshot (diagnostic).
        """
        vnc_path = os.path.join(self.results_dir, "vnc_%s.png" % suffix)
        internal_path = os.path.join(self.results_dir, "internal_%s.png" % suffix)

        vnc_success = False
        primary_screenshot = None

        # Try VNC first if requested
        if use_vnc:
            try:
                primary_screenshot = self._vnc_screendump(vnc_path)
                vnc_success = True
            except Exception as e:
                LOG_JOB.warning("VNC screenshot attempt failed: %s", e)

        # Always capture Internal screenshot as diagnostic backup/truth
        internal_success = False
        try:
            # Check if session is active before attempting internal command
            if self.session and self.session.is_responsive():
                self._internal_screendump(internal_path)
                internal_success = True

                if not primary_screenshot:
                    primary_screenshot = internal_path
                    LOG_JOB.info(
                        "Using Internal screenshot as primary (VNC capture failed)"
                    )
            else:
                LOG_JOB.warning("Session unresponsive, skipping internal screenshot")
        except Exception as e:
            LOG_JOB.warning("Internal screenshot attempt failed: %s", e)

        if not primary_screenshot:
            self.test.fail(
                "Failed to capture visual evidence for '%s': both VNC and "
                "Internal Guest Screenshot failed" % suffix
            )

        # Log which method was used for verification
        screenshot_method = "VNC" if vnc_success else "Internal"
        LOG_JOB.info("Screenshot method for AI verification: %s", screenshot_method)

        return primary_screenshot, vnc_success, internal_success, internal_path

    def _update_driver(self):
        """
        Update or install virtio-vga driver from current ISO.

        Supports both upgrade/downgrade scenarios. The driver update
        takes effect immediately without requiring a reboot.

        :return: Actual installed driver version string
        """
        error_context.context("Updating driver", LOG_JOB.info)

        driver_name = self.params.get("driver_name")
        device_name = self.params.get("device_name")
        device_hwid = self.params.get("device_hwid")
        devcon_path = self.params.get("devcon_path")
        media_type = self.params.get("virtio_win_media_type")

        if not devcon_path:
            self.test.fail("devcon_path not specified in params.")

        devcon_path = self._resolve_winutils_path(devcon_path)

        from virttest.utils_windows import virtio_win

        try:
            get_drive_letter = getattr(virtio_win, "drive_letter_%s" % media_type)
            get_product_dirname = getattr(virtio_win, "product_dirname_%s" % media_type)
            get_arch_dirname = getattr(virtio_win, "arch_dirname_%s" % media_type)
        except AttributeError:
            self.test.error("Not supported virtio win media type '%s'" % media_type)

        viowin_ltr = get_drive_letter(self.session)
        if not viowin_ltr:
            self.test.error("Could not find virtio-win drive in guest")

        guest_name = get_product_dirname(self.session)
        if not guest_name:
            self.test.error("Could not get product dirname of the vm")

        guest_arch = get_arch_dirname(self.session)
        if not guest_arch:
            self.test.error("Could not get architecture dirname of the vm")

        inf_middle_path = (
            "{name}\\{arch}" if media_type == "iso" else "{arch}\\{name}"
        ).format(name=guest_name, arch=guest_arch)
        inf_find_cmd = self.params.get("find_inf_cmd") % (
            viowin_ltr,
            driver_name,
            inf_middle_path,
        )
        inf_path = self.session.cmd(inf_find_cmd, timeout=120).strip()
        LOG_JOB.info("Found inf file '%s'", inf_path)

        get_ver_cmd = self.params.get("get_driver_version_from_inf_cmd") % inf_path
        expected_ver = self.session.cmd(get_ver_cmd, timeout=120)
        expected_ver = expected_ver.strip().split(",", 1)[-1]
        if not expected_ver:
            self.test.error("Failed to find driver version from inf file")
        LOG_JOB.info("Target driver version is '%s'", expected_ver)

        device_found = False
        target_hwid = device_hwid.split()[0]

        devcon_find_cmd_template = self.params.get("devcon_find_cmd")
        for hwid in device_hwid.split():
            find_cmd = devcon_find_cmd_template % (devcon_path, hwid)
            if not re.search(
                "No matching devices found",
                self.session.cmd_output(find_cmd),
                re.I,
            ):
                device_found = True
                target_hwid = hwid
                break

        # Use updateni (works after driver store cleanup) or install for new
        cmd_type = "updateni" if device_found else "install"
        inst_cmd = "%s %s %s %s" % (
            devcon_path,
            cmd_type,
            inf_path,
            target_hwid,
        )
        LOG_JOB.info(
            "%s driver: %s", "Updating" if device_found else "Installing", inst_cmd
        )

        key_to_install_driver = self.params.get("key_to_install_driver", "")
        update_timeout = int(self.params.get("driver_install_timeout", 360))

        status, output = self.session.cmd_status_output(
            inst_cmd, timeout=update_timeout
        )

        if key_to_install_driver and status != 0:
            keys = key_to_install_driver.split(";")
            for key in keys:
                self.vm.send_key(key)
            time.sleep(2)

        if status not in (0, 1):
            self.test.fail(
                "devcon command failed with status %d: %s" % (status, output)
            )

        chk_cmd = self.params.get(
            "vio_driver_chk_cmd", 'driverquery /si | find /i "%s"'
        )
        chk_cmd = chk_cmd % device_name[0:30]
        if not utils_misc.wait_for(
            lambda: not self.session.cmd_status(chk_cmd), 600, 60, 10
        ):
            self.test.fail("Failed to install/update driver '%s'" % driver_name)

        LOG_JOB.info("Driver install/update completed successfully")

        error_context.context("Verifying driver version", LOG_JOB.info)
        time.sleep(3)

        actual_ver = self._get_driver_version(device_name)
        if not actual_ver:
            LOG_JOB.warning(
                "Failed to get driver version, using expected: %s", expected_ver
            )
            return expected_ver

        LOG_JOB.info(
            "Driver version: expected='%s', actual='%s'", expected_ver, actual_ver
        )
        if actual_ver != expected_ver:
            LOG_JOB.warning("Version mismatch detected")

        return actual_ver

    @error_context.context_aware
    def _ensure_driver_installed(self):
        """Ensure the virtio-vga driver is installed."""
        error_context.context("Ensure Driver Installed", LOG_JOB.info)

        device_name = self.params.get("device_name")
        check_cmd = self.params.get("check_driver_installed_cmd") % device_name

        if self.session.cmd_status(check_cmd) == 0:
            error_context.context(
                "Driver '%s' is already installed and OK." % device_name, LOG_JOB.info
            )
            return

        error_context.context(
            "Driver '%s' not found or not OK. Attempting installation..." % device_name,
            LOG_JOB.info,
        )

        driver_name = self.params.get("driver_name")
        device_hwid = self.params.get("device_hwid")
        media_type = self.params.get("virtio_win_media_type")
        devcon_path = self.params.get("devcon_path")

        if not devcon_path:
            self.test.fail("devcon_path not specified in params.")

        devcon_path = self._resolve_winutils_path(devcon_path)

        try:
            win_driver_utils.install_driver_by_virtio_media(
                self.session,
                self.test,
                devcon_path,
                media_type,
                driver_name,
                device_hwid,
            )
        except Exception as e:
            self.test.fail("Failed to install driver: %s" % e)

        if self.session.cmd_status(check_cmd) != 0:
            self.test.fail("Driver verification failed after installation attempt.")

    def _verify_basic_interaction(self, suffix="", use_vnc_screenshot=False):
        """
        Perform basic visual interaction checks.

        Check desktop state and Start Menu.
        """
        error_context.context("Visual Check: Desktop State %s" % suffix, LOG_JOB.info)

        screenshot_path, vnc_success, internal_success, internal_path = (
            self._capture_visual_evidence(
                "desktop_initial_%s" % suffix, use_vnc=use_vnc_screenshot
            )
        )

        prompt_desktop = self.params.get("prompt_desktop_check")
        response = ppm_utils.verify_screen_with_gemini(
            screenshot_path, prompt_desktop, results_dir=self.results_dir
        )

        if "no" in response.lower().split():
            # Primary verification failed, need to diagnose
            if vnc_success and internal_success:
                # VNC verification failed, check Internal as diagnostic
                internal_response = ppm_utils.verify_screen_with_gemini(
                    internal_path, prompt_desktop, results_dir=self.results_dir
                )

                if "yes" in internal_response.lower().split():
                    # Internal is OK, VNC has display issue - ERROR
                    error_msg = (
                        "VNC display abnormal, but Internal Guest Screenshot "
                        "is normal. VNC display/transmission issue detected. "
                        "VNC response: '%s', Internal response: '%s'"
                        % (response, internal_response)
                    )
                    self.test.error(error_msg)
                else:
                    # Both failed - driver issue - FAIL
                    fail_msg = (
                        "Visual check failed: Screen does not look like a "
                        "normal desktop. VNC response: '%s', Internal "
                        "response: '%s'" % (response, internal_response)
                    )
                    self._capture_visual_evidence(
                        "fail_desktop_diagnostic_%s" % suffix,
                        use_vnc=use_vnc_screenshot,
                    )
                    self.test.fail(fail_msg)
            elif not vnc_success and internal_success:
                # VNC capture failed, Internal used as primary
                # Internal verification also failed - driver issue - FAIL
                fail_msg = (
                    "Visual check failed: Screen does not look like a normal "
                    "desktop. VNC capture failed, Internal verification also "
                    "failed. Internal response: '%s'" % response
                )
                self._capture_visual_evidence(
                    "fail_desktop_diagnostic_%s" % suffix, use_vnc=False
                )
                self.test.fail(fail_msg)
            else:
                # No diagnostic available
                self.test.fail(
                    "Visual check failed: Screen does not look like a "
                    "normal desktop. Response: '%s'" % response
                )

        settle_time = 5
        time.sleep(settle_time)

        error_context.context(
            "Visual Check: Start Menu Interaction %s" % suffix, LOG_JOB.info
        )

        prompt_start_menu = self.params.get("prompt_start_menu_check")
        cmd = self.params.get("start_menu_cmd")
        self.session.cmd(cmd)

        time.sleep(3)

        start_time = time.time()
        menu_visible = False
        poll_timeout = 30
        last_vnc_success = False
        last_internal_success = False
        last_internal_path = None

        while time.time() - start_time < poll_timeout:
            screenshot_path, vnc_success, internal_success, internal_path = (
                self._capture_visual_evidence(
                    "poll_start_menu_%s" % suffix, use_vnc=use_vnc_screenshot
                )
            )

            last_vnc_success = vnc_success
            last_internal_success = internal_success
            last_internal_path = internal_path

            resp = ppm_utils.verify_screen_with_gemini(
                screenshot_path,
                prompt_start_menu,
                results_dir=self.results_dir,
                save_failed_image=False,
            )

            if "yes" in resp.lower().split():
                menu_visible = True
                error_context.context(
                    "SUCCESS: Start Menu detected in %s" % screenshot_path,
                    LOG_JOB.info,
                )
                break

            time.sleep(3)

        if not menu_visible:
            # Primary verification failed, need to diagnose
            if last_vnc_success and last_internal_success:
                # VNC verification failed, check Internal as diagnostic
                internal_response = ppm_utils.verify_screen_with_gemini(
                    last_internal_path,
                    prompt_start_menu,
                    results_dir=self.results_dir,
                )

                if "yes" in internal_response.lower().split():
                    # Internal shows menu, VNC has display issue - ERROR
                    error_msg = (
                        "VNC display abnormal, but Internal Guest Screenshot "
                        "is normal. VNC display/transmission issue detected. "
                        "Start Menu not detected via VNC, but visible in "
                        "Internal screenshot. Internal response: '%s'"
                        % internal_response
                    )
                    self.test.error(error_msg)
                else:
                    # Both failed - driver issue - FAIL
                    fail_msg = (
                        "Visual check failed: Start Menu did not open. "
                        "VNC verification failed, Internal verification also "
                        "failed. Internal response: '%s'" % internal_response
                    )
                    self._capture_visual_evidence(
                        "fail_start_menu_diagnostic_%s" % suffix,
                        use_vnc=use_vnc_screenshot,
                    )
                    self.test.fail(fail_msg)
            elif not last_vnc_success and last_internal_success:
                # VNC capture failed, Internal used as primary
                # Internal verification also failed - driver issue - FAIL
                fail_msg = (
                    "Visual check failed: Start Menu did not open. "
                    "VNC capture failed, Internal verification also failed."
                )
                self._capture_visual_evidence(
                    "fail_start_menu_diagnostic_%s" % suffix, use_vnc=False
                )
                self.test.fail(fail_msg)
            else:
                # No diagnostic available
                self.test.fail("Visual check failed: Start Menu did not open.")
        else:
            # Close menu to prevent interference with subsequent tests
            close_menu_cmd = self.params.get(
                "close_menu_cmd",
                'powershell -c "$w=New-Object -ComObject WScript.Shell;'
                "$w.SendKeys('{ESC}')\"",
            )
            try:
                self.session.cmd(close_menu_cmd, timeout=10)
                time.sleep(1)
            except Exception as e:
                LOG_JOB.warning("Failed to close Start Menu: %s", e)

    def _wait_for_shutdown(self):
        """Wait for VM to shutdown, then restart."""
        error_context.context("Waiting for VM to shutdown", LOG_JOB.info)
        timeout = getattr(self.vm, "REBOOT_TIMEOUT", 240)
        if not utils_misc.wait_for(self.vm.is_dead, timeout=timeout):
            self.test.fail("VM failed to shutdown within %d seconds" % timeout)

        error_context.context("Restarting VM", LOG_JOB.info)
        self.vm.create()
        self.session = self._get_session()

    def _get_driver_version(self, device_name):
        """
        Get driver version from guest.

        :param device_name: device name to query
        :return: driver version string or None
        """
        cmd = wmic.make_query(
            "path win32_pnpsigneddriver",
            "DeviceName like '%s'" % device_name,
            props=["DriverVersion"],
            get_swch=wmic.FMT_TYPE_LIST,
        )
        try:
            output = self.session.cmd(cmd, timeout=60)
            ver_list = wmic.parse_list(output)
            if ver_list:
                version = ver_list[0]
                LOG_JOB.info("Current driver version: %s", version)
                return version
            else:
                LOG_JOB.warning("No driver version found for %s", device_name)
                return None
        except Exception as e:
            LOG_JOB.warning("Failed to get driver version: %s", e)
            return None

    def _get_winutils_drive_letter(self):
        """
        Get winutils ISO drive letter using wmic query.

        :return: Drive letter (e.g., 'E:') or None if not found
        """
        volume_name = self.params.get("winutils_volume_name", "WIN_UTILS")
        cmd = self.params.get("get_winutils_drive_cmd") % volume_name

        try:
            output = self.session.cmd_output(cmd, timeout=60)
            # Parse output like "DeviceID=E:"
            for line in output.splitlines():
                line = line.strip()
                if line.startswith("DeviceID="):
                    drive_letter = line.split("=", 1)[1].strip()
                    LOG_JOB.info("Found winutils drive letter: %s", drive_letter)
                    return drive_letter

            LOG_JOB.warning("Winutils drive letter not found in wmic output")
            return None
        except Exception as e:
            LOG_JOB.warning("Failed to get winutils drive letter: %s", e)
            return None

    def _resolve_winutils_path(self, path):
        """Replace WIN_UTILS: placeholder with actual drive letter."""
        if not path or "WIN_UTILS:" not in path:
            return path

        drive_letter = self._get_winutils_drive_letter()
        if not drive_letter:
            self.test.error("Failed to detect winutils drive letter")

        resolved_path = path.replace("WIN_UTILS:", drive_letter)
        LOG_JOB.debug("Resolved path: %s -> %s", path, resolved_path)
        return resolved_path

    def _is_win2016(self):
        """Check if guest OS is Windows 2016."""
        try:
            caption = self.session.cmd_output(
                "wmic os get Caption /format:list", timeout=60
            )
            return "2016" in caption
        except Exception:
            return False

    def _get_windows_version_dirname(self):
        """Get Windows version directory name for virtio-win ISO paths."""
        caption = self.session.cmd_output(
            "wmic os get Caption /format:list", timeout=60
        )
        LOG_JOB.debug("Windows Caption: %s", caption)

        version_map_str = self.params.get("win_version_map", "")
        version_map = {}
        for mapping in version_map_str.split():
            if ":" in mapping:
                key, value = mapping.split(":", 1)
                version_map[key] = value

        for version_key, dirname in version_map.items():
            if version_key in caption:
                LOG_JOB.debug("Matched version '%s' -> '%s'", version_key, dirname)
                return dirname

        self.test.error("Unsupported Windows version: %s" % caption)

    def _is_prewhql_package(self):
        """Check if virtio-win package is prewhql or whql."""
        cdrom_virtio = self.params.get("cdrom_virtio", "")
        is_prewhql = "prewhql" in cdrom_virtio.lower()
        LOG_JOB.info("Package type: %s", "prewhql" if is_prewhql else "whql")
        return is_prewhql

    def _get_viogpudo_driver_paths(self):
        """Get viogpudo driver file paths from virtio-win ISO."""
        from virttest.utils_windows import virtio_win

        driver_name = self.params.get("driver_name")
        media_type = self.params.get("virtio_win_media_type")

        try:
            get_drive_letter = getattr(virtio_win, "drive_letter_%s" % media_type)
            get_arch_dirname = getattr(virtio_win, "arch_dirname_%s" % media_type)
        except AttributeError:
            self.test.error("Not supported virtio win media type '%s'" % media_type)

        viowin_ltr = get_drive_letter(self.session)
        if not viowin_ltr:
            self.test.error("Could not find virtio-win drive in guest")

        guest_arch = get_arch_dirname(self.session)
        if not guest_arch:
            self.test.error("Could not get architecture dirname")

        win_version_dir = self._get_windows_version_dirname()
        base_path = "%s\\%s\\%s\\%s" % (
            viowin_ltr,
            driver_name,
            win_version_dir,
            guest_arch,
        )

        cat_path = "%s\\%s.cat" % (base_path, driver_name)
        sys_path = "%s\\%s.sys" % (base_path, driver_name)
        inf_path = "%s\\%s.inf" % (base_path, driver_name)

        LOG_JOB.info("Driver base path: %s", base_path)
        return cat_path, sys_path, inf_path

    def _verify_signtool_output(self, output, file_path):
        """Verify SignTool output contains success indicators."""
        success_pattern = self.params.get("signtool_success_pattern")
        warnings_pattern = self.params.get("signtool_warnings_pattern")
        errors_pattern = self.params.get("signtool_errors_pattern")

        if not re.search(success_pattern, output):
            LOG_JOB.error("SignTool failed for %s: no success indicator", file_path)
            return False

        if not re.search(warnings_pattern, output):
            LOG_JOB.warning("SignTool has warnings for %s", file_path)

        if not re.search(errors_pattern, output):
            LOG_JOB.error("SignTool has errors for %s", file_path)
            return False

        LOG_JOB.info("SignTool verification passed for %s", file_path)
        return True

    def _reboot_if_win2016(self, context_msg=""):
        """Reboot VM if Windows 2016 (required for driver operations)."""
        if not self._is_win2016():
            return

        error_context.context(
            "Rebooting VM for Windows 2016 %s" % context_msg, LOG_JOB.info
        )
        reboot_timeout = int(self.params.get("reboot_timeout", 240))
        self.session = self.vm.reboot(
            session=self.session, method="shell", timeout=reboot_timeout
        )
        self._open_session_list.append(self.session)

    def _clean_driver_store(self):
        """
        Remove all driver packages from Windows driver store.

        Prevents Windows from auto-selecting wrong driver version during
        updates. Uses robust regex block parsing to avoid mismatches.
        """
        error_context.context("Cleaning driver store", LOG_JOB.info)

        driver_name = self.params.get("driver_name")
        inst_timeout = int(self.params.get("driver_install_timeout", 360))
        is_win2016 = self._is_win2016()

        target_infs = set()

        enum_key = "pnputil_enum_cmd_win2016" if is_win2016 else "pnputil_enum_cmd"
        pnputil_enum_cmd = self.params.get(enum_key)
        try:
            output = self.session.cmd_output(pnputil_enum_cmd, timeout=60)
            output = output.replace("\r\n", "\n").strip()
            driver_blocks = re.finditer(
                r"Published\s+[Nn]ame\s*[:\s]+\s*(oem\d+\.inf)(.*?)"
                r"(?=\n\s*Published\s+[Nn]ame|\Z)",
                output,
                re.IGNORECASE | re.DOTALL,
            )
            for match in driver_blocks:
                inf_file = match.group(1).strip()
                block_content = match.group(2)

                if driver_name.lower() in block_content.lower():
                    target_infs.add(inf_file)

            if target_infs:
                LOG_JOB.info("Identified %d package(s) via PnPUtil", len(target_infs))

        except Exception as e:
            LOG_JOB.warning("Failed to parse pnputil output: %s", e)

        device_name = self.params.get("device_name")
        if device_name:
            try:
                cmd = wmic.make_query(
                    "path win32_pnpsigneddriver",
                    "DeviceName like '%s'" % device_name,
                    props=["InfName"],
                    get_swch=wmic.FMT_TYPE_LIST,
                )
                wmic_output = self.session.cmd_output(cmd, timeout=60)

                wmic_infs = wmic.parse_list(wmic_output)
                if not isinstance(wmic_infs, list):
                    wmic_infs = [wmic_infs]

                for inf in wmic_infs:
                    if inf and isinstance(inf, str):
                        clean_inf = inf.strip()
                        if clean_inf and clean_inf.lower().endswith(".inf"):
                            target_infs.add(clean_inf)
            except Exception as e:
                LOG_JOB.warning("Fallback wmic query failed: %s", e)

        if not target_infs:
            LOG_JOB.info("No driver packages found in store to clean.")
            return

        LOG_JOB.info("Target packages to remove: %s", list(target_infs))

        delete_key = (
            "pnputil_delete_cmd_win2016" if is_win2016 else "pnputil_delete_cmd"
        )
        pnputil_delete_cmd = self.params.get(delete_key)

        removed_count = 0
        for inf_name in target_infs:
            clean_name = inf_name.strip()

            try:
                final_cmd = pnputil_delete_cmd % clean_name
                status, output = self.session.cmd_status_output(final_cmd, inst_timeout)

                if status in (0, 3010, 259):
                    removed_count += 1
                    LOG_JOB.debug("Successfully removed %s", clean_name)
                else:
                    LOG_JOB.warning(
                        "Failed to remove %s (status %d). Output: %s",
                        clean_name,
                        status,
                        output.strip(),
                    )
            except Exception as e:
                LOG_JOB.error("Exception deleting %s: %s", clean_name, e)

        LOG_JOB.info(
            "Cleanup summary: Removed %d/%d packages", removed_count, len(target_infs)
        )

        verify_key = (
            "pnputil_verify_clean_cmd_win2016"
            if is_win2016
            else "pnputil_verify_clean_cmd"
        )
        pnputil_verify_cmd = self.params.get(verify_key) % driver_name
        try:
            verify_output = self.session.cmd_output(pnputil_verify_cmd, timeout=60)
            if driver_name.lower() in verify_output.lower():
                LOG_JOB.warning(
                    "Verification Warning: Driver store may still "
                    "contain packages for '%s'",
                    driver_name,
                )
            else:
                LOG_JOB.info("Driver store verified clean.")
        except Exception:
            LOG_JOB.debug("Verification command skipped or failed.")

    def _uninstall_driver(self):
        """Uninstall virtio-vga driver and remove from driver store."""
        error_context.context("Uninstalling driver", LOG_JOB.info)

        device_name = self.params.get("device_name")
        device_hwid = self.params.get("device_hwid")
        devcon_path = self.params.get("devcon_path")
        inst_timeout = int(self.params.get("driver_install_timeout", 360))

        if not devcon_path:
            self.test.fail("devcon_path not specified in params.")

        devcon_path = self._resolve_winutils_path(devcon_path)

        # Get INF names for installed driver packages
        cmd = wmic.make_query(
            "path win32_pnpsigneddriver",
            "DeviceName like '%s'" % device_name,
            props=["InfName"],
            get_swch=wmic.FMT_TYPE_LIST,
        )
        output = self.session.cmd(cmd, timeout=360)
        inf_names = wmic.parse_list(output)

        if not inf_names:
            LOG_JOB.warning("No driver packages found for '%s'", device_name)
        else:
            LOG_JOB.info("Uninstalling %d driver package(s)", len(inf_names))

        cmd_key = (
            "pnputil_delete_cmd_win2016" if self._is_win2016() else "pnputil_delete_cmd"
        )
        pnputil_delete_cmd = self.params.get(cmd_key)

        for inf_name in inf_names:
            status, output = self.session.cmd_status_output(
                pnputil_delete_cmd % inf_name, inst_timeout
            )
            if status not in (0, 3010):
                self.test.error(
                    "Failed to uninstall driver package '%s': %s" % (inf_name, output)
                )

        # Remove device using devcon
        uninst_cmd = "%s remove %s" % (devcon_path, device_hwid)
        status, output = self.session.cmd_status_output(uninst_cmd, inst_timeout)
        if status > 1:
            self.test.error("Failed to remove device '%s': %s" % (device_name, output))

        LOG_JOB.info("Driver uninstalled successfully")

    def _change_virtio_media(self, cdrom_virtio):
        """Change virtio media to specified ISO."""
        virtio_iso = utils_misc.get_path(data_dir.get_data_dir(), cdrom_virtio)
        error_context.context("Changing virtio media to %s" % virtio_iso, LOG_JOB.info)
        self.vm.change_media("drive_virtio", virtio_iso)

    def _get_current_resolution(self):
        """Get current display resolution."""
        script_path = self._resolve_winutils_path(
            self.params.get("get_resolution_script")
        )
        cmd = self.params.get("get_resolution_cmd") % script_path

        output = self.session.cmd_output(cmd, timeout=60)
        match = re.search(r"(\d+)x(\d+)", output)
        if match:
            return "%sx%s" % (match.group(1), match.group(2))

        LOG_JOB.warning("Failed to parse resolution from output: %s", output)
        return None

    def _set_resolution(self, width, height):
        """Set display resolution."""
        script_path = self._resolve_winutils_path(
            self.params.get("set_resolution_script")
        )
        cmd = self.params.get("set_resolution_cmd") % (
            script_path,
            width,
            height,
        )

        LOG_JOB.debug("Executing resolution change command: %s", cmd)
        status, output = self.session.cmd_status_output(cmd, timeout=60)
        success = status == 0 and "SUCCESS" in output

        LOG_JOB.info(
            "Set resolution %sx%s - Status: %d, Output: %s",
            width,
            height,
            status,
            output.strip(),
        )

        if not success:
            LOG_JOB.warning("Failed to set resolution %sx%s: %s", width, height, output)

        return success

    @error_context.context_aware
    def run_basic_interaction(self):
        """Basic interaction test."""
        self._ensure_driver_installed()
        use_vnc = self.params.get("use_vnc_screenshot", "yes") == "yes"
        self._verify_basic_interaction(suffix="basic", use_vnc_screenshot=use_vnc)

    @error_context.context_aware
    def run_shutdown_with_driver(self):
        """
        Shutdown test.

        Install -> Check -> Loop 5x powerdown -> Final check.
        """
        self._ensure_driver_installed()
        use_vnc = self.params.get("use_vnc_screenshot", "yes") == "yes"
        self._verify_basic_interaction(
            suffix="shutdown_initial", use_vnc_screenshot=use_vnc
        )

        for i in range(5):
            error_context.context("Shutdown loop %d/5" % (i + 1), LOG_JOB.info)
            self.vm.monitor.cmd("system_powerdown")
            self._wait_for_shutdown()

        error_context.context("Final verification after 5 shutdowns", LOG_JOB.info)
        self._verify_basic_interaction(
            suffix="shutdown_final", use_vnc_screenshot=use_vnc
        )

    @error_context.context_aware
    def run_reboot_with_driver(self):
        """
        Reboot test.

        Install -> Check -> Loop 5x reboot -> Final check.
        """
        self._ensure_driver_installed()
        use_vnc = self.params.get("use_vnc_screenshot", "yes") == "yes"
        self._verify_basic_interaction(
            suffix="reboot_initial", use_vnc_screenshot=use_vnc
        )

        reboot_timeout = int(self.params.get("reboot_timeout", 240))

        for i in range(5):
            error_context.context("Reboot loop %d/5" % (i + 1), LOG_JOB.info)
            self.session = self.vm.reboot(
                session=self.session, method="shell", timeout=reboot_timeout
            )
            self._open_session_list.append(self.session)

        error_context.context("Final verification after 5 reboots", LOG_JOB.info)
        self._verify_basic_interaction(
            suffix="reboot_final", use_vnc_screenshot=use_vnc
        )

    @error_context.context_aware
    def run_reset_with_driver(self):
        """
        Reset test.

        Install -> Check -> Loop 5x reset -> Final check.
        """
        self._ensure_driver_installed()
        use_vnc = self.params.get("use_vnc_screenshot", "yes") == "yes"
        self._verify_basic_interaction(
            suffix="reset_initial", use_vnc_screenshot=use_vnc
        )

        reboot_timeout = int(self.params.get("reboot_timeout", 240))

        for i in range(5):
            error_context.context("Reset loop %d/5" % (i + 1), LOG_JOB.info)
            self.session = self.vm.reboot(method="system_reset", timeout=reboot_timeout)
            self._open_session_list.append(self.session)

        error_context.context("Final verification after 5 resets", LOG_JOB.info)
        self._verify_basic_interaction(suffix="reset_final", use_vnc_screenshot=use_vnc)

    @error_context.context_aware
    def run_install_driver_preinstalled(self):
        """Install virtio-vga driver on pre-installed guest."""
        self._ensure_driver_installed()
        use_vnc = self.params.get("use_vnc_screenshot", "yes") == "yes"
        self._verify_basic_interaction(
            suffix="preinstalled", use_vnc_screenshot=use_vnc
        )

    @error_context.context_aware
    def run_install_uninstall_driver(self):
        """Install/uninstall/reinstall driver test."""
        use_vnc = self.params.get("use_vnc_screenshot", "yes") == "yes"
        reboot_timeout = int(self.params.get("reboot_timeout", 240))
        cdrom_virtio = self.params.get("cdrom_virtio")

        self._ensure_driver_installed()
        self._verify_basic_interaction(
            suffix="post_initial_install", use_vnc_screenshot=use_vnc
        )

        error_context.context(
            "Ejecting virtio ISO to prevent auto-reinstall", LOG_JOB.info
        )
        self.vm.eject_cdrom("drive_virtio")

        self._uninstall_driver()

        error_context.context("Rebooting VM after uninstallation", LOG_JOB.info)
        self.session = self.vm.reboot(
            session=self.session, method="shell", timeout=reboot_timeout
        )
        self._open_session_list.append(self.session)

        self._verify_basic_interaction(
            suffix="post_uninstall", use_vnc_screenshot=use_vnc
        )

        error_context.context(
            "Re-inserting virtio ISO for reinstallation", LOG_JOB.info
        )
        self._change_virtio_media(cdrom_virtio)

        self._ensure_driver_installed()

        error_context.context("Rebooting VM after reinstallation", LOG_JOB.info)
        self.session = self.vm.reboot(
            session=self.session, method="shell", timeout=reboot_timeout
        )
        self._open_session_list.append(self.session)

        self._verify_basic_interaction(
            suffix="post_reinstall", use_vnc_screenshot=use_vnc
        )

    @error_context.context_aware
    def run_upgrade_downgrade_driver(self):
        """
        Test driver downgrade and upgrade.

        Cleans driver store before each update to prevent Windows from
        auto-selecting wrong version. No reboot required.
        """
        use_vnc = self.params.get("use_vnc_screenshot", "yes") == "yes"
        cdrom_virtio_downgrade = self.params.get("cdrom_virtio_downgrade")
        cdrom_virtio = self.params.get("cdrom_virtio")
        device_name = self.params.get("device_name")

        if not cdrom_virtio_downgrade:
            self.test.error("cdrom_virtio_downgrade not specified in params")

        self._ensure_driver_installed()
        self._verify_basic_interaction(suffix="initial", use_vnc_screenshot=use_vnc)

        error_context.context("Getting driver version before downgrade", LOG_JOB.info)
        version_before_downgrade = self._get_driver_version(device_name)
        if not version_before_downgrade:
            self.test.error("Failed to get driver version before downgrade")

        error_context.context("Cleaning driver store before downgrade", LOG_JOB.info)
        self._clean_driver_store()

        error_context.context("Downgrading virtio-vga driver", LOG_JOB.info)
        self._change_virtio_media(cdrom_virtio_downgrade)
        self._update_driver()
        self._reboot_if_win2016("after downgrade")

        version_after_downgrade = self._get_driver_version(device_name)
        if version_after_downgrade == version_before_downgrade:
            self.test.fail(
                "Driver downgrade failed: version unchanged (%s)"
                % version_before_downgrade
            )

        LOG_JOB.info(
            "Driver downgrade successful: %s -> %s",
            version_before_downgrade,
            version_after_downgrade,
        )

        self._verify_basic_interaction(
            suffix="after_downgrade", use_vnc_screenshot=use_vnc
        )

        error_context.context("Cleaning driver store before upgrade", LOG_JOB.info)
        self._clean_driver_store()

        error_context.context("Upgrading virtio-vga driver", LOG_JOB.info)
        self._change_virtio_media(cdrom_virtio)
        self._update_driver()
        self._reboot_if_win2016("after upgrade")

        version_after_upgrade = self._get_driver_version(device_name)
        if version_after_upgrade == version_after_downgrade:
            self.test.fail(
                "Driver upgrade failed: version unchanged (%s)"
                % version_after_downgrade
            )

        LOG_JOB.info(
            "Driver upgrade successful: %s -> %s",
            version_after_downgrade,
            version_after_upgrade,
        )

        if version_after_upgrade != version_before_downgrade:
            LOG_JOB.warning(
                "Driver version after upgrade (%s) differs from initial version (%s)",
                version_after_upgrade,
                version_before_downgrade,
            )

        self._verify_basic_interaction(
            suffix="after_upgrade", use_vnc_screenshot=use_vnc
        )

    @error_context.context_aware
    def run_check_driver_signature_signtool(self):
        """Verify viogpudo driver signature using SignTool.exe."""
        self._ensure_driver_installed()

        error_context.context("Locating SignTool utility", LOG_JOB.info)
        signtool_path = self._resolve_winutils_path(self.params.get("signtool_path"))

        error_context.context("Locating driver files", LOG_JOB.info)
        cat_path, sys_path, inf_path = self._get_viogpudo_driver_paths()

        is_prewhql = self._is_prewhql_package()
        verify_option = self.params.get(
            "signtool_verify_option_prewhql"
            if is_prewhql
            else "signtool_verify_option_whql"
        )

        cmd_template = self.params.get("signtool_verify_cmd")
        timeout = int(self.params.get("signature_verify_timeout", 120))

        for file_path in [sys_path, inf_path]:
            error_context.context("Verifying signature: %s" % file_path, LOG_JOB.info)
            verify_cmd = cmd_template % (
                signtool_path,
                verify_option,
                cat_path,
                file_path,
            )
            status, output = self.session.cmd_status_output(verify_cmd, timeout=timeout)

            if status != 0 or not self._verify_signtool_output(output, file_path):
                self.test.fail(
                    "Signature verification failed for %s\n"
                    "Command: %s\nOutput:\n%s" % (file_path, verify_cmd, output)
                )

        use_vnc = self.params.get("use_vnc_screenshot", "yes") == "yes"
        self._verify_basic_interaction(
            suffix="after_signature_check", use_vnc_screenshot=use_vnc
        )

    @error_context.context_aware
    def run_check_driver_signature_sigverif(self):
        """Verify driver signature using sigverif with AutoIT script."""
        self._ensure_driver_installed()

        error_context.context("Locating AutoIT and sigverif", LOG_JOB.info)
        autoit_exe = self._resolve_winutils_path(self.params.get("autoit_exe"))
        sigverif_script = self._resolve_winutils_path(
            self.params.get("sigverif_script")
        )

        error_context.context("Executing sigverif verification", LOG_JOB.info)
        sigverif_cmd = self.params.get("sigverif_cmd") % (autoit_exe, sigverif_script)
        timeout = int(self.params.get("sigverif_timeout", 120))
        status, output = self.session.cmd_status_output(sigverif_cmd, timeout=timeout)

        if status != 0:
            self.test.fail(
                "Sigverif failed with exit code %d\n"
                "Command: %s\nOutput:\n%s" % (status, sigverif_cmd, output)
            )

        use_vnc = self.params.get("use_vnc_screenshot", "yes") == "yes"
        self._verify_basic_interaction(
            suffix="after_sigverif_check", use_vnc_screenshot=use_vnc
        )

    @error_context.context_aware
    def run_boot_multiple_drivers(self):
        self.test.fail("Test action 'boot_multiple_drivers' is not yet implemented.")

    @error_context.context_aware
    def run_install_driver_iommu(self):
        self.test.fail("Test action 'install_driver_iommu' is not yet implemented.")

    @error_context.context_aware
    def run_resolution_modification_auto(self):
        self.test.fail(
            "Test action 'resolution_modification_auto' requires VNC tool integration."
        )

    @error_context.context_aware
    def run_resolution_modification_manual(self):
        """Test manual resolution modification with dual verification."""
        self._ensure_driver_installed()
        use_vnc = self.params.get("use_vnc_screenshot", "yes") == "yes"

        initial_res = self._get_current_resolution()
        if not initial_res:
            self.test.error("Failed to get initial resolution")

        LOG_JOB.info("Initial resolution: %s", initial_res)

        # Get test resolutions from params (space-separated list in cfg)
        test_resolutions_str = self.params.get("test_resolutions", "1920x1080 1024x768")
        test_resolutions = test_resolutions_str.split()

        # Validate resolution format
        for res in test_resolutions:
            if not re.match(r"^\d+x\d+$", res):
                self.test.error(
                    "Invalid resolution format: '%s'. Expected format: "
                    "WIDTHxHEIGHT (e.g., 1920x1080)" % res
                )

        LOG_JOB.info("Testing resolutions: %s", ", ".join(test_resolutions))

        for target_res in test_resolutions:
            width, height = target_res.split("x")
            target_width, target_height = int(width), int(height)

            error_context.context(
                "Changing resolution to %s" % target_res, LOG_JOB.info
            )
            if not self._set_resolution(width, height):
                self.test.fail("Failed to set resolution to %s" % target_res)

            error_context.context(
                "Waiting for resolution change to stabilize", LOG_JOB.info
            )
            time.sleep(5)

            error_context.context("Verifying resolution via Windows API", LOG_JOB.info)
            verified_res = None
            for attempt in range(3):
                current_res = self._get_current_resolution()
                LOG_JOB.debug(
                    "Resolution query attempt %d/3: %s", attempt + 1, current_res
                )

                if current_res == target_res:
                    verified_res = current_res
                    break

                if attempt < 2:
                    time.sleep(2)

            if verified_res != target_res:
                self.test.fail(
                    "Resolution verification failed after 3 attempts: "
                    "expected %s, got %s" % (target_res, verified_res)
                )

            error_context.context(
                "Capturing VNC screenshot for verification", LOG_JOB.info
            )
            screenshot_path, _, _, _ = self._capture_visual_evidence(
                "resolution_%s" % target_res, use_vnc=use_vnc
            )

            error_context.context("Verifying screenshot dimensions", LOG_JOB.info)
            screenshot_width, screenshot_height = ppm_utils.image_size(screenshot_path)
            LOG_JOB.info(
                "Screenshot dimensions: %dx%d (expected: %s)",
                screenshot_width,
                screenshot_height,
                target_res,
            )

            width_diff = abs(screenshot_width - target_width)
            height_diff = abs(screenshot_height - target_height)

            if width_diff > 10 or height_diff > 10:
                self.test.fail(
                    "Screenshot dimension mismatch: expected %s, got "
                    "%dx%d (diff: %dx%d). VNC capture resolution differs "
                    "from guest OS reported resolution."
                    % (
                        target_res,
                        screenshot_width,
                        screenshot_height,
                        width_diff,
                        height_diff,
                    )
                )

            error_context.context(
                "Checking visual quality (no corruption/artifacts)", LOG_JOB.info
            )
            prompt = self.params.get("prompt_desktop_check")
            ai_response = ppm_utils.verify_screen_with_gemini(
                screenshot_path, prompt, results_dir=self.results_dir
            )

            if "no" in ai_response.lower().split():
                self.test.fail(
                    "Visual quality check failed at resolution %s: Desktop "
                    "does not appear normal. AI response: '%s'"
                    % (target_res, ai_response)
                )

        LOG_JOB.info("All resolution changes verified successfully")

    @error_context.context_aware
    def run_desktop_migration(self):
        self.test.fail("Test action 'desktop_migration' is not yet implemented.")

    @error_context.context_aware
    def run_check_driver_after_guest_installer_upgrade(self):
        self.test.fail(
            "Test action 'check_driver_after_guest_installer_upgrade' is "
            "not yet implemented."
        )

    @error_context.context_aware
    def run_trigger_bsod_capture(self):
        self.test.fail("Test action 'trigger_bsod_capture' is not yet implemented.")

    @error_context.context_aware
    def run_install_driver_during_os_install(self):
        self.test.fail(
            "Test action 'install_driver_during_os_install' is not yet implemented."
        )

    def run(self):
        """Main test execution entry point."""
        self.vm = self.env.get_vm(self.params["main_vm"])
        self.vm.verify_alive()

        try:
            self.session = self._get_session()

            # Setup VNC environment before any tests if VNC screenshots are
            # enabled
            use_vnc = self.params.get("use_vnc_screenshot", "yes") == "yes"
            if use_vnc:
                self._ensure_vnc_environment()

            # Dispatcher
            check_type = self.params.get("check_type", "basic_interaction")
            error_context.context(
                "Starting test check_type: %s" % check_type, LOG_JOB.info
            )

            func_name = "run_%s" % check_type
            if hasattr(self, func_name):
                func = getattr(self, func_name)
                func()
            else:
                self.test.fail(
                    "Test check_type '%s' not implemented (missing '%s')."
                    % (check_type, func_name)
                )

        finally:
            self._cleanup_open_session()


@error_context.context_aware
def run(test, params, env):
    """Visual test for virtio-vga driver with AI verification."""
    test_obj = VirtioVgaVisualTest(test, params, env)
    test_obj.run()
