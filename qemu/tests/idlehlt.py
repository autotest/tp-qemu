import os
import re
import shutil
import time

from avocado.utils import archive, build, process
from virttest import error_context
from virttest.utils_misc import verify_dmesg, verify_secure_guest, verify_secure_host


@error_context.context_aware
def run(test, params, env):
    """
    QEMU test case to verify the Idle HLT Intercept feature and
    monitor idle-halt exits using ftrace.

    :param test: QEMU test object for logging and test control.
    :param params: Dictionary with test parameters (e.g., vm_secure_guest_type,
                   url_cpuid_tool).
    :param env: Dictionary with test environment, including VM configuration.
    """

    def setup_ftrace(hlt_exit_reason):
        # Set up ftrace
        error_context.context("Configuring ftrace for kvm:kvm_exit", test.log.info)
        if not os.path.exists(trace_dir):
            test.cancel("ftrace not available at {}".format(trace_dir))

        try:
            with open(os.path.join(trace_dir, "tracing_on"), "w") as f:
                f.write("0")
            with open(os.path.join(trace_dir, "trace"), "w") as f:
                f.write("")
            with open(os.path.join(trace_dir, "events/kvm/kvm_exit/enable"), "w") as f:
                f.write("1")
            filter_text = "exit_reason == " + hlt_exit_reason
            with open(os.path.join(trace_dir, "events/kvm/kvm_exit/filter"), "w") as f:
                f.write(filter_text)
            test.log.info(
                "ftrace configured for kvm:kvm_exit with exit_reason == %s.",
                hlt_exit_reason,
            )
        except (IOError, PermissionError) as e:
            test.cancel("Failed to configure ftrace: {}".format(e))

    def cpuid_tool_build():
        """
        Build and install cpuid from source tarball if not already installed.
        """
        error_context.context("Building cpuid tool from source", test.log.info)
        test.log.info("Using cpuid source URL: %s", url_cpuid_tool)

        # Check for build tools
        for tool in ["make", "gcc", "tar"]:
            if not shutil.which(tool):
                test.cancel(
                    f"Build tool {tool} not found. Please install it "
                    f"(e.g., 'sudo apt install build-essential')."
                )

        try:
            # Download the tarball
            tarball = test.fetch_asset(url_cpuid_tool)
            test.log.info("Downloaded cpuid source: %s", tarball)

            # Extract tarball
            source_dir_name = os.path.basename(tarball).split(".src.tar.")[0]
            sourcedir = os.path.join(test.teststmpdir, source_dir_name)
            archive.extract(tarball, test.teststmpdir)
            test.log.info("Extracted cpuid source to %s", sourcedir)

            # Build and install (use sudo for make install)
            build.make(sourcedir, extra_args="install", ignore_status=False)
            test.log.info("Successfully built and installed cpuid")

            # Verify installation
            cpuid_path = shutil.which("cpuid")
            if not cpuid_path:
                test.fail("cpuid binary not found in PATH after installation")

            # Verify cpuid works
            result = process.run("cpuid --version", shell=True, ignore_status=True)
            if result.exit_status != 0:
                test.fail(
                    "Installed cpuid tool failed to execute: {}".format(
                        result.stderr.decode()
                    )
                )
            test.log.info(
                "cpuid tool installed and verified: %s", result.stdout.decode().strip()
            )

        except Exception as e:
            test.cancel("Failed to build/install test prerequisite: {}".format(e))

    if params.get("vm_secure_guest_type"):
        secure_guest_type = params.get("vm_secure_guest_type")
        supported_secureguest = ["sev", "snp"]
        if secure_guest_type not in supported_secureguest:
            test.cancel(
                "Testcase does not support vm_secure_guest_type %s" % secure_guest_type
            )
        # Check host kernel sev support
        verify_secure_host(params)
    error_context.context("Setting up test environment", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)
    trace_dir = params.get("trace_dir", "/sys/kernel/tracing")
    hlt_exit_reason = params.get("hlt_exit_reason", "0x0a6")
    url_cpuid_tool = params.get(
        "url_cpuid_tool",
        default="http://www.etallen.com/cpuid/cpuid-20250513.src.tar.gz",
    )
    # Check if cpuid is installed; build if not
    if not shutil.which("cpuid"):
        test.log.info("cpuid tool not found, attempting to build from source")
        cpuid_tool_build()

    # Check Idle HLT Intercept feature
    error_context.context("Checking Idle HLT Intercept feature", test.log.info)
    try:
        result = process.run(
            "cpuid -1 -r -l 0x8000000A", shell=True, ignore_status=True
        )
        if result.exit_status != 0:
            test.cancel(
                "Failed to execute cpuid command: {}".format(result.stderr.decode())
            )
        output = result.stdout.decode()
        edx_match = re.search(r"edx\s*=\s*0x([0-9a-fA-F]+)", output)
        if not edx_match:
            test.cancel("Could not parse EDX from cpuid output.")
        edx = int(edx_match.group(1), 16)
        if not (edx & (1 << 30)):
            test.cancel("Idle HLT Intercept feature is not supported on this platform.")
        test.log.info("Idle HLT Intercept feature is supported.")

    except process.CmdError as e:
        test.cancel("Error executing cpuid: {}".format(e))
    # Set up ftrace
    setup_ftrace(hlt_exit_reason)
    try:
        # Enable ftrace
        with open(os.path.join(trace_dir, "tracing_on"), "w") as f:
            f.write("1")
        vm_name = params["main_vm"]
        vm = env.get_vm(vm_name)
        vm.create()
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        verify_dmesg()
        if "secure_guest_type" in locals() and secure_guest_type:
            verify_secure_guest(session, params, vm)
        time.sleep(5)
        with open(os.path.join(trace_dir, "tracing_on"), "w") as f:
            f.write("0")
        with open(os.path.join(trace_dir, "trace"), "r") as f:
            trace_output = f.read()
        if "idle-halt" not in trace_output:
            test.fail("No idle-halt exits detected in ftrace output.")
        else:
            test.log.info(
                "Idle-halt exits detected in ftrace output:\n%s", trace_output
            )
    except Exception as e:
        test.fail("Test failed: %s" % str(e))
    finally:
        try:
            if os.path.exists(os.path.join(trace_dir, "tracing_on")):
                with open(os.path.join(trace_dir, "tracing_on"), "w") as f:
                    f.write("0")
                with open(
                    os.path.join(trace_dir, "events/kvm/kvm_exit/enable"), "w"
                ) as f:
                    f.write("0")
                with open(
                    os.path.join(trace_dir, "events/kvm/kvm_exit/filter"), "w"
                ) as f:
                    f.write("0")
                with open(os.path.join(trace_dir, "trace"), "w") as f:
                    f.write("")
                test.log.info("ftrace cleaned up.")
        except (IOError, PermissionError) as e:
            test.log.warning("Failed to clean up ftrace: %s", e)
        if "session" in locals() and session:
            session.close()
            vm.destroy()
