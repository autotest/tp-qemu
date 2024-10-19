import os
import re
import signal

from avocado.utils import process
from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Qemu reboot test:
    1) Boot up a windows guest.
    2) Run stress tool on host.
    3) After guest starts up, start the ftrace.
    4) Reboot VM inside guest.
    5.1) If the guest reboot successfully, then stop the trace-cmd and remove
         the trace.dat file.
    5.2) If guest hang, stop the trace-cmd and generate the readable report
         file.
    6) if 5.2, Check whether the trace.txt includes the error log.
    7) Repeat step 3~6.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def find_trace_cmd():
        if process.system("ps -a | grep trace-cmd", ignore_status=True, shell=True):
            return False
        else:
            return True

    if os.system("which trace-cmd"):
        test.cancel("Please install trace-cmd.")

    timeout = float(params.get("login_timeout", 240))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    reboot_method = params["reboot_method"]
    stress_cmd = params.get("stress_cmd", "stress --vm 4 --vm-bytes 1000M")

    trace_o = os.path.join(test.debugdir, "trace.dat")
    trace_cmd = "trace-cmd record -b 20000 -e kvm -o %s" % trace_o
    trace_cmd = params.get("trace_cmd", trace_cmd)
    re_trace = params.get("re_trace", "kvm_inj_exception:    #GP")

    report_file = os.path.join(test.debugdir, "trace.txt")
    trace_report_cmd = "trace-cmd report -i %s > %s " % (trace_o, report_file)
    try:
        error_context.context("Run stress tool on host.", test.log.info)
        stress_job = utils_misc.BgJob(stress_cmd)
        # Reboot the VM
        for num in range(int(params.get("reboot_count", 1))):
            error_context.context(
                "Reboot guest '%s'. Repeat %d" % (vm.name, num + 1), test.log.info
            )
            trace_job = utils_misc.BgJob(trace_cmd)
            try:
                session = vm.reboot(session, reboot_method, 0, timeout)
            except Exception:
                txt = "stop the trace-cmd and generate the readable report."
                error_context.context(txt, test.log.info)
                os.kill(trace_job.sp.pid, signal.SIGINT)
                if not utils_misc.wait_for(lambda: not find_trace_cmd(), 120, 60, 3):
                    test.log.warning("trace-cmd could not finish after 120s.")
                trace_job = None
                process.system(trace_report_cmd, shell=True)
                with open(report_file) as report_f:
                    report_txt = report_f.read()
                txt = "Check whether the trace.txt includes the error log."
                error_context.context(txt, test.log.info)
                if re.findall(re_trace, report_txt, re.S):
                    msg = "Found %s in trace log %s" % (re_trace, report_file)
                    test.fail(msg)
            else:
                txt = "stop the trace-cmd and remove the trace.dat file."
                error_context.context(txt, test.log.info)
                os.kill(trace_job.sp.pid, signal.SIGINT)
                if not utils_misc.wait_for(lambda: not find_trace_cmd(), 120, 60, 3):
                    test.log.warning("trace-cmd could not finish after 120s.")
                trace_job = None
                process.system("rm -rf %s" % trace_o, timeout=60)
    finally:
        if session:
            session.close()
        if stress_job and stress_job.sp.poll() is None:
            utils_misc.kill_process_tree(stress_job.sp.pid, 9)
        if trace_job:
            if trace_job.sp.poll() is None:
                os.kill(trace_job.sp.pid, signal.SIGINT)
