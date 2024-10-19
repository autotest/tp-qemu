import json
import logging
import os
import re
import time

from avocado.utils import archive, process
from virttest import data_dir, utils_misc, utils_net

LOG_JOB = logging.getLogger("avocado.test")

STATE_READY = "Ready"
STATE_NOT_READY = "NotReady"


class HLKError(Exception):
    def __init__(self, *args):
        Exception.__init__(self, *args)


class HLKRunError(HLKError):
    def __init__(self, *args):
        Exception.__init__(self, *args)


class HLKServer(object):
    def __init__(self, test, vm_server):
        """
        Initial HLKServer instance.

        :param test: Test object.
        :type test: test.VirtTest
        :param vm_server: VM Server object.
        :type vm_server: qemu_vm.VM
        """
        src_link = os.path.join(data_dir.get_deps_dir("hlk"), "hlk_studio.ps1")
        self._test = test
        self._vm = vm_server
        self._vm.copy_files_to(src_link, "c:\\", timeout=60)
        self._session = self._vm.wait_for_login(timeout=360)
        LOG_JOB.info("Getting HLK Server hostname:")
        hostname = self._session.cmd("hostname").strip()
        self._session.set_prompt(r"toolsHLK@%s" % hostname)
        LOG_JOB.info("Starting to run HLK Server powershell script:")
        self._session.cmd_output('powershell -command "c:\\hlk_studio.ps1"')

    def close(self):
        """Close session."""
        self._session.close()

    def get_default_pool(self):
        """Get default pool."""
        LOG_JOB.info("Getting default pool:")
        machines = self._session.cmd_output("getdefaultpool")
        LOG_JOB.info(machines)
        return [json.loads(machine) for machine in machines.splitlines()]

    def create_pool(self, name):
        """
        Create a pool.

        :param name: Pool name.
        :type name: str
        """
        LOG_JOB.info('Creating pool "%s":', name)
        self._session.cmd_output("createpool %s" % name)

    def move_machine_from_default_pool(self, machine_name, dst_pool_name):
        """
        Move machine from default pool to another pool.

        :param machine_name: Machine name.
        :type machine_name: str
        :param dst_pool_name: Destination pool name.
        :type dst_pool_name: str
        """
        LOG_JOB.info(
            'Moving machine "%s" from default pool to pool "%s":',
            machine_name,
            dst_pool_name,
        )
        cmd = "movemachinefromdefaultpool %s %s" % (machine_name, dst_pool_name)
        self._session.cmd_output(cmd)

    def set_machine_state(self, machine_name, pool_name, state, timeout=360):
        """
        Set machine state to "Ready" or "NotReady"

        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :param state: State to be set.
        :type state: STATE_READY or STATE_NOT_READY
        :param timeout: Timeout for setting in seconds.
        :type timeout: int
        """
        LOG_JOB.info(
            'Setting machine "%s" of pool "%s" to state "%s":',
            machine_name,
            pool_name,
            state,
        )
        cmd = "setmachinestate %s %s %s" % (machine_name, pool_name, state)
        self._session.cmd_output(cmd, timeout)

    def list_machine_targets(self, machine_name, pool_name, timeout=60):
        """
        List machine targets.

        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :param timeout: Timeout for listing in seconds.
        :type timeout: int
        :return: Information of targets,
                 format: ["$Target0_Name,$Target0_Key,$Target0_Type",
                          "$Target1_Name,$Target1_Key,$Target1_Type", ...]
        :type: list
        """
        cmd = "listmachinetargets %s %s" % (machine_name, pool_name)
        targets = self._session.cmd_output(cmd, timeout)
        LOG_JOB.info(targets)
        return [target for target in targets.splitlines()]

    def get_machine_target(self, target_name, machine_name, pool_name, timeout=60):
        """
        Get machine target.

        :param target_name: Target name.
        :type target_name: str
        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :param timeout: Timeout for getting in seconds.
        :type timeout: int
        :return: Information of target,
                 format: ["$Target0_Name", "$Target0_Key", "$Target0_Type"]
        :type: list
        """
        LOG_JOB.info(
            'Getting target "%s" of machine "%s" of pool "%s":',
            target_name,
            machine_name,
            pool_name,
        )
        targets = self.list_machine_targets(machine_name, pool_name, timeout)
        for target in targets:
            if target_name in target:
                target = target.split(",")
                LOG_JOB.info("key: %s, type: %s", target[1], target[2])
                return target

    def get_machine_target_key(self, target_name, machine_name, pool_name, timeout=60):
        """
        Get machine target key.

        :param target_name: Target name.
        :type target_name: str
        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :param timeout: Timeout for getting in seconds.
        :type timeout: int
        :return: Target key.
        :type: str
        """
        return self.get_machine_target(target_name, machine_name, pool_name, timeout)[
            1
        ].replace("&", '"&"')

    def list_projects(self, timeout=60):
        """
        List projects.

        :param timeout: Timeout for listing in seconds.
        :type timeout: int
        :return: Projects information,
                 format: [{"project_name": "$Project_Name",
                           "creation_time": "$Project.CreationTime",
                           "modified_time": "$Project.ModifiedTime",
                           "status": "$Project.Info.Status"},
                           {"project_name1": "$Project_Name",
                           ...}, ...]
        :rtype: list
        """
        projects = self._session.cmd_output("listprojects", timeout)
        return [json.loads(project) for project in projects.splitlines()]

    def get_project(self, name):
        """
        Get project.

        :param name: Project name.
        :type name: str
        :return: Project information,
                 format: {"project_name": "$Project_Name",
                          "creation_time": "$Project.CreationTime",
                          "modified_time": "$Project.ModifiedTime",
                          "status": "$Project.Info.Status"}
        :rtype: dict
        """
        for project in self.list_projects():
            if project["project_name"] == name:
                LOG_JOB.info(project)
                return project

    def create_project(self, name):
        """
        Create project.

        :param name: Project name.
        :type name: str
        """
        LOG_JOB.info('Creating project "%s":', name)
        self._session.cmd_output("createproject %s" % name)

    def create_project_target(
        self, target_key, project_name, machine_name, pool_name, timeout=60
    ):
        """
        Create project target.

        :param target_key: Target key.
        :type target_key: str
        :param project_name: Project name.
        :type project_name: str
        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :param timeout: Timeout for creating in seconds.
        :type timeout: int
        """
        LOG_JOB.info(
            'Creating project target by target key "%s" of "%s":',
            target_key,
            project_name,
        )
        cmd = "createprojecttarget %s %s %s %s" % (
            target_key,
            project_name,
            machine_name,
            pool_name,
        )
        self._session.cmd_output(cmd, timeout)

    def list_tests(self, target_key, project_name, machine_name, pool_name, timeout=60):
        """
        List tests.

        :param target_key: Target key.
        :type target_key: str
        :param project_name: Project name.
        :type project_name: str
        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :param timeout: Timeout for listing in seconds.
        :type timeout: int
        :return: Tests information,
                 format: [{"test_name": "$Test_Name",
                           "test_id": "$Test_id",
                           "test_type": "$Test_Type",
                           "estimated_runtime": "$Test_EstimatedRuntime",
                           "requires_special_configuration": "$Test_RequiresSpecialConfiguration",
                           "requires_supplemental_content": "$tTest_RequiresSupplementalContent",
                           "test_status": "$Test_Status",
                           "execution_state": "$Test_ExecutionState"},
                           {"test1_name": "$Test1_Name",,
                           ...}, ...]
        :rtype: list
        """  # noqa: E501
        cmd = "listtests %s %s %s %s" % (
            target_key,
            project_name,
            machine_name,
            pool_name,
        )
        tests = self._session.cmd_output(cmd, timeout)
        return [json.loads(test) for test in tests.splitlines()]

    def get_target_test(
        self, test_name, target_key, project_name, machine_name, pool_name, timeout=60
    ):
        """
        Get target test.

        :param test_name: Test name.
        :type test_name: str
        :param target_key: Target key.
        :type target_key: str
        :param project_name: Project name.
        :type project_name: str
        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :param timeout: Timeout for listing in seconds.
        :type timeout: int
        :return: Target test information,
                 format: {"test_name": "$Test_Name",
                          "test_id": "$Test_id",
                          "test_type": "$Test_Type",
                          "estimated_runtime": "$Test_EstimatedRuntime",
                          "requires_special_configuration": "$Test_RequiresSpecialConfiguration",
                          "requires_supplemental_content": "$tTest_RequiresSupplementalContent",
                          "test_status": "$Test_Status",
                          "execution_state": "$Test_ExecutionState"}
        :rtype: dict
        """  # noqa: E501
        tests = self.list_tests(
            target_key, project_name, machine_name, pool_name, timeout
        )
        for test in tests:
            if test["test_name"] == test_name:
                return test

    def get_target_test_id(
        self, test_name, target_key, project_name, machine_name, pool_name, timeout=60
    ):
        """
        Get target test ID.

        :param test_name: Test name.
        :type test_name: str
        :param target_key: Target key.
        :type target_key: str
        :param project_name: Project name.
        :type project_name: str
        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :param timeout: Timeout for listing in seconds.
        :type timeout: int
        :return: Target test ID.
        :rtype: str
        """
        LOG_JOB.info('Getting target id of test "%s":', test_name)
        test_id = self.get_target_test(
            test_name, target_key, project_name, machine_name, pool_name, timeout
        )["test_id"]
        LOG_JOB.info(test_id)
        return test_id

    def queue_test(self, test_id, target_key, project_name, machine_name, pool_name):
        """
        Get target test id.

        :param test_id: Test ID.
        :type test_id: str
        :param target_key: Target key.
        :type target_key: str
        :param project_name: Project name.
        :type project_name: str
        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        """
        LOG_JOB.info('Queuing a test, test id "%s":', test_id)
        cmd = "queuetest %s %s %s %s %s" % (
            test_id,
            target_key,
            project_name,
            machine_name,
            pool_name,
        )
        self._session.cmd_output(cmd)

    def zip_test_result_logs(
        self, result_index, test_id, target_key, project_name, machine_name, pool_name
    ):
        """
        Zip test result logs.

        :param result_index: Index of test result.
        :type result_index: str
        :param test_id: Test ID.
        :type test_id: str
        :param target_key: Target key.
        :type target_key: str
        :param project_name: Project name.
        :type project_name: str
        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :return: Output of command.
        :rtype: str
        """
        cmd = "ziptestresultlogs %s %s %s %s %s %s" % (
            result_index,
            test_id,
            target_key,
            project_name,
            machine_name,
            pool_name,
        )
        LOG_JOB.info(
            'Zipping the index %s of test result logs of test id "%s":',
            result_index,
            test_id,
        )
        output = self._session.cmd_output(cmd)
        LOG_JOB.info(output)
        return output

    def list_test_results(
        self, test_id, target_key, project_name, machine_name, pool_name
    ):
        """
        List test results.

        :param test_id: Test ID.
        :type test_id: str
        :param target_key: Target key.
        :type target_key: str
        :param project_name: Project name.
        :type project_name: str
        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :return: Output of command.
        :rtype: str
        """
        cmd = "listtestresults %s %s %s %s %s" % (
            test_id,
            target_key,
            project_name,
            machine_name,
            pool_name,
        )
        return self._session.cmd_output(cmd)

    def list_tests_results(
        self, tests_id, target_key, project_name, machine_name, pool_name
    ):
        """
        List tests results.

        :param tests_id: List of tests ID.
        :type tests_id: list
        :param target_key: Target key.
        :type target_key: str
        :param project_name: Project name.
        :type project_name: str
        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :return: Output of results.
        :rtype: str
        """
        results = ""
        LOG_JOB.info("Getting tests results:")
        host_path = os.path.join(self._test.resultsdir, "hlk_test_result_logs")
        if not os.path.exists(host_path):
            os.makedirs(host_path)
        for test_id in tests_id:
            output = self.list_test_results(
                test_id, target_key, project_name, machine_name, pool_name
            )
            results_index = re.findall(r"Test result index :\s+(\d+)", output, re.M)
            for result_index in results_index:
                o = self.zip_test_result_logs(
                    result_index,
                    test_id,
                    target_key,
                    project_name,
                    machine_name,
                    pool_name,
                )
                zip_path = o.splitlines()[-1]
                LOG_JOB.info(
                    "Uploading the test result from %s to %s:", zip_path, host_path
                )
                self._vm.copy_files_from(zip_path, host_path)
            results = results + output

        LOG_JOB.info(results)
        return results

    def run_tests(
        self,
        tests_id,
        target_key,
        project_name,
        machine_name,
        pool_name,
        timeout=600,
        step=3,
    ):
        """
        Run tests.

        :param tests_id: List of tests ID.
        :type tests_id: list
        :param target_key: Target key.
        :type target_key: str
        :param project_name: Project name.
        :type project_name: str
        :param machine_name: Machine name.
        :type machine_name: str
        :param pool_name: Pool name.
        :type pool_name: str
        :param timeout: Timeout for running in seconds.
        :type timeout: int
        :param step: Time to sleep between attempts in seconds.
        :type step: int
        :raise: HLKRunError, if run timeout or found error messages.
        """
        for test_id in tests_id:
            self.queue_test(test_id, target_key, project_name, machine_name, pool_name)

        if not utils_misc.wait_for(
            lambda: "NotRunning" == self.get_project(project_name)["status"],
            timeout,
            step=step,
        ):
            raise HLKRunError("Timeout for running tests.")

        resutls = self.list_tests_results(
            tests_id, target_key, project_name, machine_name, pool_name
        )
        err_msg = []
        for result in resutls.splitlines():
            if "Task error message" in result:
                err_msg.append(result.strip())
        if err_msg:
            raise HLKRunError("Found task error messages:%s" % err_msg)

    def simple_run_test(
        self, pool_name, project_name, target_name, tests_name, timeout=14400, step=600
    ):
        """
        Simple run test.

        :param pool_name: Pool name.
        :type pool_name: str
        :param project_name: Project name.
        :type project_name: str
        :param target_name: Target name.
        :type target_name: str
        :param tests_name: List of tests name.
        :type tests_name: str
        :param timeout: Timeout for running in seconds.
        :type timeout: int
        :param step: Time to sleep between attempts in seconds.
        :type step: int
        """
        default_pool = self.get_default_pool()[0]
        machine_name = default_pool["machine_name"]
        self.create_pool(pool_name)
        self.move_machine_from_default_pool(machine_name, pool_name)
        self.set_machine_state(machine_name, pool_name, STATE_READY)
        # FIXME: Sleep to provide buffer to execute next steps.
        time.sleep(60)
        self.create_project(project_name)
        target_key = self.get_machine_target_key(target_name, machine_name, pool_name)
        self.create_project_target(target_key, project_name, machine_name, pool_name)

        tests_id = []
        for test_name in tests_name:
            test_id = self.get_target_test_id(
                test_name, target_key, project_name, machine_name, pool_name
            )
            tests_id.append(test_id)

        self.run_tests(
            tests_id, target_key, project_name, machine_name, pool_name, timeout, step
        )


def install_hlk_client(vm_client, vm_server, timeout=1200):
    """
    Install HLK client inside windows guest.

    :param vm_client: VM client object.
    :type vm_client: qemu_vm.VM
    :param vm_server: VM server object.
    :type vm_server: qemu_vm.VM
    :param timeout: Timeout for installing.
    :type timeout: int
    """
    client_session = vm_client.wait_for_login(timeout=600)
    server_session = vm_server.wait_for_login(timeout=600)
    server_mac = vm_server.virtnet[0].mac
    server_ip = utils_net.get_guest_ip_addr(server_session, server_mac, "windows")
    client_session.cmd(r"REG DELETE HKCR\pysFile /f")
    inst_cmd = r"\\%s\HLKInstall\Client\Setup.cmd /qn ICFAGREE=Yes" % server_ip
    client_session.cmd(inst_cmd, timeout)


def download_hlk_server_image(params, src_img_uri, timeout=1800):
    """
    Download HLK Server image.

    :param params: Dictionary with the test parameters.
    :type params: utils_params.Params
    :param src_img_uri: Source HLK Server image URI.
    :type src_img_uri: str
    :param timeout: Timeout for downloading.
    :type timeout: int
    :return: Dictionary source image information, format:
             {'image_name': '${image_name}',
             'image_size': '${image_size}',
             'image_format': '${image_format}'}
    :rtype: dict
    :raise: HLKError, if URI is invalid or not supported.
    """
    if re.search(r'(^http:)|(^https:)|(^ftp")|(^ftps:")', src_img_uri):
        src_img_name = src_img_uri.split("/")[-1]
        dst_img_path = os.path.join(data_dir.DATA_DIR, "images", src_img_name)
        dst_img_dir = os.path.dirname(dst_img_path)

        if not os.path.exists(dst_img_path):
            LOG_JOB.info("Checking HLK Server URI %s:", src_img_uri)
            curl_check_cmd = "curl -I -L -k -m 120 %s" % src_img_uri
            output = process.run(curl_check_cmd).stdout_text
            if "File not found" in output:
                raise HLKError("Invalid URI %s." % src_img_uri)

            LOG_JOB.info(
                "Downloading HLK Server from %s to %s/:", src_img_uri, dst_img_dir
            )
            curl_download_cmd = "curl -o %s %s" % (dst_img_path, src_img_uri)
            process.run(curl_download_cmd, timeout)
        else:
            LOG_JOB.info("Found HLK Server image: %s.", dst_img_path)

        if archive.is_archive(dst_img_path):
            LOG_JOB.info("Uncompressing %s :", dst_img_path)
            img_name = archive.uncompress(dst_img_path, dst_img_dir)
            dst_img_path = os.path.join(dst_img_dir, img_name)
            LOG_JOB.info("The uncompressed destination path: %s", dst_img_path)

        qemu_binary = utils_misc.get_qemu_img_binary(params)
        info_cmd = "%s info %s --output=json" % (qemu_binary, dst_img_path)
        info_dict = json.loads(process.run(info_cmd).stdout_text)
        dst_img = {
            "image_name": info_dict["filename"].split(".")[0],
            "image_size": info_dict["virtual-size"],
            "image_format": info_dict["format"],
        }
        return dst_img

    else:
        raise HLKError("No supported URI: %s." % src_img_uri)
