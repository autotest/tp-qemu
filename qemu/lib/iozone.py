import logging
import os

from avocado.core import exceptions
from virttest import utils_misc
from virttest import postprocess_iozone as iop


class Iozone(object):
    """
    Prepare iozone env, run iozone on guest, clean up iozone env.
    """
    def __init__(self, test, params, vm, session):
        """
        run setup of iozone test
        """
        self.params = params
        self.session = session
        self.test = test
        self.vm = vm
        self.results_path = ""
        self.timeout = float(params.get("iozone_timeout"))
        check_cmd = params.get("check_cmd")
        download_cmd = params.get("download_cmd")
        setup_cmd = params.get("setup_cmd")
        install_status = self.__install_check(check_cmd)
        if not install_status:
            self.__setup(download_cmd, setup_cmd)

    def __session_check(self):
        """
        check if session is alive, if not, start a new session
        """
        if not self.session.is_alive():
            self.session = self.vm.wait_for_login()

    def __install_check(self, check_cmd):
        """
        check if iozone installed in guest
        """
        if check_cmd:
            output = self.session.cmd_output(check_cmd)
            if "iozone -h" in output:
                return True
            else:
                return False

    def __setup(self, download_cmd, setup_cmd):
        """
        Download iozone and install it in guest
        """
        if download_cmd and setup_cmd:
            logging.info("Download iozone tarball")
            self.session.cmd(download_cmd, timeout=self.timeout)
            logging.info("Setup iozone")
            self.session.cmd(setup_cmd, timeout=self.timeout)

    def run(self, session, test_cmd, disk_letter):
        """
        Run iozone test in guest

        :param session: used for running iozone on multi sessions
        :param test_cmd: iozone test cmd, like iozone -a or iozone -aZR -f
                         I:\testiozone
        :param disk_letter: to specify iozone_results for disks,like
                            iozone_result_vda
        :return: iozone run status and result.
        """
        # run iozone on the same device in parallel is not supported
        status, output = session.cmd_status_output(test_cmd,
                                                   timeout=self.timeout)
        if self.params.get("record_results", "yes"):
            self.results_path = os.path.join(self.test.resultsdir,
                                             'iozone_result_%s' % disk_letter)
            logging.debug("Write results to %s" % self.results_path)
            try:
                with open(self.results_path, 'a') as iozone_result:
                    iozone_result.write(output)
            except:
                error_msg = "Failed to write iozone test results to file:"
                error_msg += "%s" % self.results_path
                os.remove(self.results_path)
                raise exceptions.TestFail(error_msg)

            if self.params.get("post_results", "no") == "yes":
                self.__post_result(disk_letter)

        return status, output

    def __post_result(self, test_disk):
        """
        Post result after iozone test, generate a series graphs
        """
        # use this function, params "-i" for iozone is not suggested.
        # suggest usage:iozone.exe -azR -r 64k -n 125M -g 512M -M -f
        # I:\testfile". Otherwise, your result can't be analysed correctly.
        logging.info("Generate graph of test result")
        analysisdir = os.path.join(self.test.resultsdir, 'result_analysis_%s'
                                   % test_disk)
        iozone_analyzer = iop.IOzoneAnalyzer(list_files=[self.results_path],
                                             output_dir=analysisdir)
        iozone_analyzer.analyze()
        iozone_plotter = iop.IOzonePlotter(results_file=self.results_path,
                                           output_dir=analysisdir)
        iozone_plotter.plot_all()

    def clean(self):
        """
        Clean old iozone packet after test in guest
        """
        clean_cmd = self.params.get("clean_cmd")
        if clean_cmd:
            self.__session_check()
            cmd = self.session.cmd_output
            running = utils_misc.wait_for(lambda: "iozone" not in cmd
                                          (self.params.get("iozone_pid_check")
                                           ), self.timeout, 0, 5)
            if not running:
                logging.warning("Iozone is still running, force to kill it")
                self.session.cmd(self.params.get("iozone_stop_cmd"))
            status = cmd(clean_cmd, timeout=self.timeout)
            if status:
                raise exceptions.TestError("Failed to cleanup iozone")
