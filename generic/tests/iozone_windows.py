import logging
import os
import re

from autotest.client import utils

from avocado.core import exceptions
from virttest import error_context
from virttest import postprocess_iozone
from virttest import utils_misc


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
    def create_partition(create_partition_cmd, timeout, session):
        has_dispart = re.findall("diskpart", create_partition_cmd, re.I)
        if (params.get("os_type") == 'windows' and has_dispart):
            error_context.context("Get disk list in guest")
            list_disk_cmd = params["list_disk_cmd"]
            status, output = session.cmd_status_output(list_disk_cmd,
                                                       timeout=timeout)
            for i in re.findall("Disk*.(\d+)\s+Offline", output):
                error_context.context("Set disk '%s' to online status" % i,
                              logging.info)
                set_online_cmd = params["set_online_cmd"] % i
                status, output = session.cmd_status_output(set_online_cmd,
                                                           timeout=timeout)
                if status != 0:
                    raise exceptions.TestFail("Can not set disk online %s"
                                               % output)

        error_context.context("Create partition on disk", logging.info)
        status, output = session.cmd_status_output(create_partition_cmd,
                                                   timeout=timeout)
        if status != 0:
            raise exceptions.TestFail("Failed to create partition: %s"
                                       % output)

    def format_disk(timeout, session):
        format_cmd = params["format_cmd"]
        error_context.context("Format the disk with cmd '%s'" % format_cmd,
                      logging.info)
        status, output = session.cmd_status_output(format_cmd,
                                                   timeout=timeout)
        if status != 0:
            raise exceptions.TestFail("Failed to format disk: %s" % output)

    def iozone_test(result_path, analysisdir, disk_letter, session):
        win_utils = utils_misc.get_winutils_vol(session)
        iozone_cmd = params.get("iozone_cmd") % (win_utils, disk_letter)
        t = int(params.get("iozone_timeout"))
        error_context.context("Running IOzone command in guest, timeout %s"
                              % t)
        results = session.cmd_output(cmd=iozone_cmd, timeout=t)
        if params.get("analysis_result", "no") == "yes":
            utils.open_write_close(result_path, results)
            logging.info("Iteration succeed, postprocessing")
            a = postprocess_iozone.IOzoneAnalyzer(list_files=[result_path],
                                                 output_dir=analysisdir)
            a.analyze()
            p = postprocess_iozone.IOzonePlotter(results_file=result_path,
                                                 output_dir=analysisdir)
            p.plot_all()

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    result_path = os.path.join(test.resultsdir,
                                'raw_output_%s' % test.iteration)
    analysisdir = os.path.join(test.resultsdir, 'analysis_%s' % test.iteration)
    create_partition_cmd = params.get("create_partition_cmd")
    disk_letter = params.get("disk_letter")
    if not disk_letter:
        device_key = params.get("device_key", "VolumeName='Windows'")
        disk_letter = utils_misc.get_win_disk_vol(session, device_key)

    if create_partition_cmd:
        create_partition(create_partition_cmd, timeout, session)
    if params.get("format_disk", "no") == "yes":
        format_disk(timeout, session)
    iozone_test(result_path, analysisdir, disk_letter, session)
