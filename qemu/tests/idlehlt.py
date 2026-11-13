import os
import re
import shutil
import signal
import time

from avocado.utils import process
from virttest import error_context, utils_misc
from virttest.utils_misc import verify_dmesg, verify_secure_guest, verify_secure_host


@error_context.context_aware
def run(test, params, env):
    """
    Verify Idle HLT intercept and that the guest generates idle-halt exits.

    1) Cancel unless cpuid and trace-cmd are installed and CPUID
       0x8000000A EDX bit 30 is set. For SEV/SNP, verify the host
       module parameter.
    2) Select an OVMF BIOS and record kvm:kvm_exit events filtered by
       hlt_exit_reason.
    3) Boot the guest, check dmesg, and for SEV/SNP verify the guest.
    4) Stop the recorder and fail if the report contains no idle-halt
       exits.

    :param test: QEMU test object for logging and test control.
    :param params: Cartesian parameters. Reads login_timeout,
        hlt_exit_reason, bios_path, bios_path_candidates,
        vm_secure_guest_type, module_name, param_name, module_status,
        vm_sev_policy, and <secure_guest_type>_guest_check.
    :param env: Dictionary with test environment, including VM configuration.
    """

    def select_bios_path():
        candidates = []
        for path in [params.get("bios_path")] + params.objects("bios_path_candidates"):
            if path and path not in candidates:
                candidates.append(path)
        for path in candidates:
            if os.path.exists(path):
                test.log.info("Using BIOS path %s", path)
                return path
        test.cancel("OVMF BIOS not found. Looked for: %s" % ", ".join(candidates))

    def stop_trace_cmd():
        if trace_job is None or trace_job.sp.poll() is not None:
            return
        try:
            os.kill(trace_job.sp.pid, signal.SIGINT)
            if not utils_misc.wait_for(
                lambda: trace_job.sp.poll() is not None, 60, 1, 3
            ):
                test.log.warning("trace-cmd did not exit after SIGINT")
        except ProcessLookupError:
            return
        except OSError as exc:
            test.log.warning("Failed to stop trace-cmd: %s", exc)

    error_context.context("Checking required host tools", test.log.info)
    if not shutil.which("cpuid"):
        test.cancel("cpuid is not installed")
    if not shutil.which("trace-cmd"):
        test.cancel("trace-cmd is not installed")

    secure_guest_type = params.get("vm_secure_guest_type")
    if secure_guest_type is not None:
        supported_secureguest = ["sev", "snp"]
        if secure_guest_type not in supported_secureguest:
            test.cancel(
                "Testcase does not support vm_secure_guest_type %s" % secure_guest_type
            )
        module_name = params.get("module_name")
        param_name = params.get("param_name")
        if not module_name:
            test.cancel("Missing config parameter: module_name")
        if not param_name:
            test.cancel("Missing config parameter: param_name")
        verify_secure_host(
            secure_guest_type=secure_guest_type,
            module_name=module_name,
            param_name=param_name,
            expected_values=params.objects("module_status"),
        )

    error_context.context("Checking Idle HLT Intercept feature", test.log.info)
    result = process.run("cpuid -1 -r -l 0x8000000A", shell=True, ignore_status=True)
    if result.exit_status != 0:
        test.cancel(
            "Failed to execute cpuid command: %s"
            % result.stderr.decode(errors="replace")
        )
    edx_match = re.search(
        r"edx\s*=\s*0x([0-9a-fA-F]+)", result.stdout.decode(errors="replace")
    )
    if not edx_match:
        test.cancel("Could not parse EDX from cpuid output.")
    if not (int(edx_match.group(1), 16) & (1 << 30)):
        test.cancel("Idle HLT Intercept feature is not supported on this platform.")
    test.log.info("Idle HLT Intercept feature is supported.")

    bios_path = select_bios_path()
    timeout = params.get_numeric("login_timeout", 240)
    hlt_exit_reason = params.get("hlt_exit_reason", "0x0a6")
    trace_file = os.path.join(test.debugdir, "trace.dat")
    trace_cmd = "trace-cmd record -e kvm:kvm_exit -f 'exit_reason == %s' -o %s" % (
        hlt_exit_reason,
        trace_file,
    )
    trace_job = None
    vm = None
    session = None
    try:
        error_context.context("Recording kvm:kvm_exit with trace-cmd", test.log.info)
        trace_job = utils_misc.BgJob(trace_cmd)
        time.sleep(1)
        if trace_job.sp.poll() is not None:
            err = trace_job.sp.stderr.read()
            test.error("trace-cmd exited early: %s" % err)

        error_context.context("Booting the guest", test.log.info)
        vm = env.get_vm(params["main_vm"])
        vm.params["bios_path"] = bios_path
        vm.create()
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        verify_dmesg()
        if secure_guest_type is not None:
            guest_check_cmd_param = "%s_guest_check" % secure_guest_type
            guest_check_cmd = params.get(guest_check_cmd_param)
            if not guest_check_cmd:
                test.cancel("Missing config parameter: %s" % guest_check_cmd_param)
            verify_secure_guest(
                session=session,
                vm=vm,
                secure_guest_type=secure_guest_type,
                guest_check_cmd=guest_check_cmd,
                expected_policy=params.get("vm_sev_policy"),
            )
        time.sleep(5)
        stop_trace_cmd()
        error_context.context(
            "Checking trace-cmd report for idle-halt exits", test.log.info
        )
        report = process.run(
            "trace-cmd report -N -i %s" % trace_file,
            shell=True,
            ignore_status=True,
            verbose=False,
        )
        if report.exit_status != 0:
            test.error(
                "trace-cmd report failed: %s" % report.stderr.decode(errors="replace")
            )
        trace_output = report.stdout.decode(errors="replace")
        idle_hlt_exits = trace_output.count("reason idle-halt")
        if not idle_hlt_exits:
            lines = [line for line in trace_output.splitlines() if line.strip()]
            if len(lines) > 10:
                sample = lines[:5] + ["..."] + lines[-5:]
            else:
                sample = lines
            test.fail(
                "No idle-halt exits detected in trace-cmd output "
                "(%d kvm_exit lines). Sample:\n%s"
                % (trace_output.count("kvm_exit:"), "\n".join(sample))
            )
        test.log.info("Detected %d idle-halt exits in trace-cmd output", idle_hlt_exits)
    finally:
        stop_trace_cmd()
        if session is not None:
            try:
                session.close()
            except Exception as exc:
                test.log.warning("Failed to close session: %s", exc)
        if vm is not None:
            try:
                vm.destroy()
            except Exception as exc:
                test.log.warning("Failed to destroy VM: %s", exc)
