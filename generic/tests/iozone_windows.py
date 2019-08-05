import os
import logging

from virttest import postprocess_iozone
from virttest import utils_misc
from virttest import utils_test
from virttest import utils_disk
from virttest import error_context


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

    def run_iozone_parallel(timeout):
        """ Run the iozone parallel. """
        iozone_sessions = []
        iozone_threads = []
        thread_maps = {}

        for _ in disk_letters:
            iozone_sessions.append(vm.wait_for_login(timeout=360))
        for iozone_session, disk_letter in zip(iozone_sessions, disk_letters):
            args = (iozone_cmd.format(disk_letter), iozone_timeout)
            thread_maps[disk_letter] = (iozone_session.cmd, args)
            iozone_thread = utils_misc.InterruptedThread(iozone_session.cmd, args)
            iozone_thread.setName(disk_letter)
            iozone_threads.append(iozone_thread)
            iozone_thread.start()

        start_time = time.time()
        while time.time() - start_time <= timeout:
            for iozone_thread in iozone_threads:
                if iozone_thread.is_alive():
                    continue
                else:
                    thread_name = iozone_thread.getName()
                    iozone_threads.remove(iozone_thread)
                    iozone_threads.append(
                        utils_misc.InterruptedThread(thread_maps[thread_name][0],
                                                     thread_maps[thread_name][1]))
                    iozone_threads[-1].setName(thread_name)
                    iozone_threads[-1].start()

        for iozone_thread in iozone_threads:
            iozone_thread.join()

        logging.info('All the iozone threads are done.')

    def check_gpt_labletype(disk_index):
        """
        """
        output = session.cmd_output("echo list disk > test.dp & diskpart /s test.dp && del test.dp")
        print(output)
        pattern = r'Disk %s.+?B\s{8}\*' % disk_index
        if re.search(pattern, output):
            return True
        return False

    timeout = int(params.get("login_timeout", 360))
    iozone_timeout = int(params.get("iozone_timeout"))
    disk_letters = params.get("disk_letter", 'C').split()
    disk_indexes = params.get("disk_index", "2").split()
    disk_fstypes = params.get("disk_fstype", "ntfs").split()
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
        for index, letter, fstype in zip(disk_indexes, disk_letters, disk_fstypes):
            utils_misc.format_windows_disk(session, index, letter, fstype=fstype)

    if params.get("gpt_check", "no") == "yes":
        if not check_gpt_labletype(params.get("disk_index")):
            test.fail("Disk partition type is not gpt")

    cmd = params["iozone_cmd"]
    iozone_cmd = utils_misc.set_winutils_letter(session, cmd)
    error_context.context("Running IOzone command on guest, timeout %ss"
                          % iozone_timeout, logging.info)

    status, results = session.cmd_status_output(cmd=iozone_cmd,
                                                timeout=iozone_timeout)
    error_context.context("Write results to %s" % results_path, logging.info)
    if status != 0:
        test.fail("iozone test failed: %s" % results)

    with open(results_path, 'w') as file:
        file.write(results)

    if params.get("post_result", "no") == "yes":
        error_context.context("Generate graph of test result", logging.info)
        post_result(results_path, analysisdir)
