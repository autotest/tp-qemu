import os
import logging

from autotest.client import utils

from virttest import postprocess_iozone
from virttest import utils_misc
from virttest import utils_test
from virttest import error_context
from avocado.core import exceptions


@error_context.context_aware
def run(test, params, env):
    """
    Run IOzone for windows on a windows guest:
    1) Log into a guest
    2) Execute the IOzone test contained in the winutils.iso
    3) Get results
    4) Postprocess it with the IOzone postprocessing module

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def post_result(results_path, analysisdir):
        """
        Pick results from an IOzone run, generate a series graphs

        :params results_path: iozone test result path
        :params analysisdir: output of analysis result
        """
        a = postprocess_iozone.IOzoneAnalyzer(list_files=[results_path],
                                              output_dir=analysisdir)
        a.analyze()
        p = postprocess_iozone.IOzonePlotter(results_file=results_path,
                                             output_dir=analysisdir)
        p.plot_all()

    def get_driver():
        """
        Get driver name
        """
        driver_name = params.get("driver_name", "")
        drive_format = params.get("drive_format")
        if not driver_name:
            if "scsi" in drive_format:
                driver_name = "vioscsi"
            elif "virtio" in drive_format:
                driver_name = "viostor"
            else:
                driver_name = None
        return driver_name

    timeout = int(params.get("login_timeout", 360))
    iozone_timeout = int(params.get("iozone_timeout"))
    disk_letter = params.get("disk_letter", 'C')
    disk_index = params.get("disk_index", "2")
    results_path = os.path.join(test.resultsdir,
                                'raw_output_%s' % test.iteration)
    analysisdir = os.path.join(test.resultsdir, 'analysis_%s' % test.iteration)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    driver_name = get_driver()
    if driver_name:
        session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                                test, driver_name,
                                                                timeout)
    if params.get("format_disk", "no") == "yes":
        error_context.context("Format disk", logging.info)
        utils_misc.format_windows_disk(session, disk_index,
                                       mountpoint=disk_letter)
    cmd = params["iozone_cmd"]
    iozone_cmd = utils_misc.set_winutils_letter(session, cmd)
    error_context.context("Running IOzone command on guest, timeout %ss"
                          % iozone_timeout, logging.info)

    status, results = session.cmd_status_output(cmd=iozone_cmd,
                                                timeout=iozone_timeout)
    error_context.context("Write results to %s" % results_path, logging.info)
    if status != 0:
        raise exceptions.TestFail("iozone test failed: %s" % results)
    utils.open_write_close(results_path, results)

    if params.get("post_result", "no") == "yes":
        error_context.context("Generate graph of test result", logging.info)
        post_result(results_path, analysisdir)
