"""
Module for IO throttling relevant interfaces.
"""

import copy
import json
import logging
import random
import re
import string
import tempfile
from math import ceil
from multiprocessing.pool import ThreadPool
from time import sleep

from virttest.qemu_devices.qdevices import QThrottleGroup
from virttest.qemu_monitor import QMPCmdError
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_version import VersionInterval

LOG_JOB = logging.getLogger("avocado.test")


class ThrottleError(Exception):
    """General Throttle error"""

    pass


class ThrottleGroupManager(object):
    """
    General operations for Throttle group.
    """

    def __init__(self, vm):
        """
        :param vm:VM object.
        """
        self._vm = vm
        self._monitor = vm.monitor

    def set_monitor(self, monitor):
        """
        Set the default monitor.

        :param monitor: QMPMonitor monitor.
        """
        self._monitor = monitor

    # object-add
    def add_throttle_group(self, group_id, props):
        """
        hot-plug throttle group object.

        :param group_id: Throttle group id.
        :param props: Dict of throttle group properties.
        :return: QThrottleGroup object.
        """

        dev = QThrottleGroup(group_id, props)
        try:
            self._vm.devices.simple_hotplug(dev, self._monitor)
            return dev
        except QMPCmdError:
            self._vm.devices.remove(dev)

    # object-del
    def delete_throttle_group(self, group_id):
        """
        hot-unplug throttle group object.

        :param group_id: Throttle group id.
        :return: True for succeed.
        """

        dev = self.get_throttle_group(group_id)
        if dev:
            self._vm.devices.simple_unplug(dev, self._monitor)
            return True
        else:
            LOG_JOB.error("Can not find throttle group")
            return False

    def get_throttle_group(self, group_id):
        """
        Search throttle group in vm devices.

        :param group_id: Throttle group id.
        :return: QThrottleGroup object. None for not found or something wrong.
        """

        devs = self._vm.devices.get_by_qid(group_id)
        if len(devs) != 1:
            LOG_JOB.error("There are %d devices %s", len(devs), group_id)
            return None
        return devs[0]

    def get_throttle_group_props(self, group_id):
        """
        Get the attributes of throttle group object via qmp command.

        :param group_id: Throttle group id.
        :return: Dictionary of throttle group properties.
        """

        try:
            return self._monitor.qom_get(group_id, "limits")
        except QMPCmdError as e:
            LOG_JOB.error("qom_get %s %s ", group_id, str(e))

    # qom-set
    def update_throttle_group(self, group_id, props):
        """
        Update throttle group properties.

        :param group_id: Throttle group id.
        :param props: New throttle group properties.
        """

        dev = self.get_throttle_group(group_id)
        if dev:
            tmp_dev = QThrottleGroup(group_id, props)
            self._monitor.qom_set(group_id, "limits", tmp_dev.raw_limits)
            dev.raw_limits = tmp_dev.raw_limits
        else:
            raise ThrottleError("Can not find throttle group")

    # x-blockdev-reopen
    def change_throttle_group(self, image, group_id):
        """
        Change image to other throttle group.

        :param image: Image name of disk.
        :param group_id: New throttle group id.
        """

        node_name = "drive_" + image

        throttle_blockdev = self._vm.devices.get_by_qid(node_name)[0]

        old_throttle_group = self._vm.devices.get_by_qid(
            throttle_blockdev.get_param("throttle-group")
        )[0]
        new_throttle_group = self._vm.devices.get_by_qid(group_id)[0]
        file = throttle_blockdev.get_param("file")
        args = {
            "driver": "throttle",
            "node-name": node_name,
            "file": file,
            "throttle-group": group_id,
        }
        if self._vm.devices.qemu_version in VersionInterval("[6.1.0, )"):
            self._monitor.blockdev_reopen({"options": [args]})
        else:
            self._monitor.x_blockdev_reopen(args)

        for bus in old_throttle_group.child_bus:
            bus.remove(throttle_blockdev)

        throttle_blockdev.parent_bus = ({"busid": group_id}, {"type": "ThrottleGroup"})
        throttle_blockdev.set_param("throttle-group", group_id)

        for bus in new_throttle_group.child_bus:
            bus.insert(throttle_blockdev)


def _online_disk_windows(session, index, timeout=360):
    """
    Online disk in windows guest.

    :param session: Session object connect to guest.
    :param index: Physical disk index.
    :param timeout: Timeout for cmd execution in seconds.
    :return: The output of cmd
    """

    disk = "disk_" + "".join(random.sample(string.ascii_letters + string.digits, 4))
    online_cmd = "echo select disk %s > " + disk
    online_cmd += " && echo online disk noerr >> " + disk
    online_cmd += " && echo clean >> " + disk
    online_cmd += " && echo attributes disk clear readonly >> " + disk
    online_cmd += " && echo detail disk >> " + disk
    online_cmd += " && diskpart /s " + disk
    online_cmd += " && del /f " + disk
    return session.cmd(online_cmd % index, timeout=timeout)


def _get_drive_path(session, params, image):
    """
    Get the disk name by image serial in guest.

    :param session: Session object connect to guest.
    :param params: params of running ENV.
    :param image: image name of disk in qemu.
    :return: The disk path in guest
    """

    image_params = params.object_params(image)
    os_type = params["os_type"]
    extra_params = image_params["blk_extra_params"]
    serial = re.search(r"(serial|wwn)=(\w+)", extra_params, re.M).group(2)
    if os_type == "windows":
        cmd = "wmic diskdrive where SerialNumber='%s' get Index,Name"
        disks = session.cmd_output(cmd % serial)
        info = disks.splitlines()
        if len(info) > 1:
            attr = info[1].split()
            _online_disk_windows(session, attr[0])
            return attr[1]

    return get_linux_drive_path(session, serial)


class ThrottleTester(object):
    """
    FIO test for in throttle group disks, It contains building general fio
    command and check the result of fio command output.
    Example of usage:
        ...
        fio = generate_instance(params, vm, 'fio')
        tt = ThrottleTester("group1",["img1","img2"])
        tt.set_fio(fio)
        tt.build_default_option()
        tt.build_images_fio_option()
        tt.start()

    """

    # Default data struct of expected result.
    raw_expected = {
        "burst": {
            "read": 0,
            "write": 0,
            "total": 0,
            "burst_time": 0,
            "burst_empty_time": 0,
        },
        "normal": {"read": 0, "write": 0, "total": 0},
    }
    # Default data struct of raw image data.
    raw_image_data = {"name": "", "fio_option": "", "output": {}}

    def __init__(self, test, params, vm, session, group, images=None):
        """

        :param test: Context of test.
        :param params: params of running ENV.
        :param vm: VM object.
        :param session: Session object connect to guest.
        :param group: Throttle group name.
        :param images: list of relevant images names.
        """

        self._test = test
        self._vm = vm
        self._session = session
        self._monitor = vm.monitor
        self._fio = None
        self._params = params
        self.group = group
        # shared fio option without --filename
        self._fio_option = ""
        self.images = images.copy() if images else []
        self._throttle = {
            "images": {
                image: copy.deepcopy(ThrottleTester.raw_image_data) for image in images
            },
            "expected": copy.deepcopy(ThrottleTester.raw_expected),
        }
        self._margin = 0.3

    @staticmethod
    def _generate_output_by_json(output):
        """
        Convert fio command output to dict object.

        :param output: fio command output with option --output-format=json.
        :return: dict of fio command output.
        """

        with tempfile.TemporaryFile(mode="w+") as tmp:
            tmp.write(output)
            tmp.seek(0)
            line = tmp.readline()
            begin_flag = False
            block_index = 1
            block = {}
            data = ""
            while line:
                if line == "{\n":
                    if not begin_flag:
                        begin_flag = True
                    else:
                        # error
                        break
                if begin_flag:
                    data += line
                if line == "}\n":
                    if begin_flag:
                        begin_flag = False
                    else:
                        # error
                        break
                    block[block_index] = json.loads(data)
                    data = ""
                    block_index += 1

                line = tmp.readline()

            if begin_flag:
                LOG_JOB.error("Wrong data format")
                return {}
            return block

    def set_fio(self, fio):
        """
        Set fio instance.

        :param fio: fio instance.
        """

        self._fio = fio

    def run_fio(self, *args):
        """
        Start to fio command in guest.

        :param args: image data,data struct refer to raw_image_data.
        :return: fio command output.
        """

        if not self._fio:
            self._test.error("Please set fio first")
        image_info = args[0]
        fio_option = image_info["fio_option"]
        session = self._vm.wait_for_login()
        cmd = " ".join((self._fio.cfg.fio_path, fio_option))
        burst = self._throttle["expected"]["burst"]
        expected_burst = burst["read"] + burst["write"] + burst["total"]
        if expected_burst:
            cmd += " && " + cmd
        LOG_JOB.info("run_fio:%s", cmd)
        out = session.cmd(cmd, 1800)
        image_info["output"] = self._generate_output_by_json(out)
        return image_info["output"]

    def check_output(self, images):
        """
        Check the output whether match the expected result.

        :param images: list of participating images.
        :return: True for succeed.
        """

        burst = self._throttle["expected"]["burst"]
        expected_burst = burst["read"] + burst["write"] + burst["total"]

        normal = self._throttle["expected"]["normal"]
        expected_normal = normal["read"] + normal["write"] + normal["total"]

        # Indeed no throttle
        if expected_normal == 0:
            LOG_JOB.info("Skipping checking on the empty throttle")
            return True

        sum_burst = 0
        sum_normal = 0
        num_images = len(images)
        for image in images:
            output = self._throttle["images"][image]["output"]  # type: dict
            num_samples = len(output)
            LOG_JOB.debug("Check %s in total %d images.", image, num_images)
            if expected_burst:
                if num_samples < 2:
                    self._test.error("At lease 2 Data samples:%d" % num_samples)
                read = output[1]["jobs"][0]["read"]["iops"]
                write = output[1]["jobs"][0]["write"]["iops"]
                total = read + write
                sum_burst += total
            else:
                if num_samples < 1:
                    self._test.error("At lease 1 Data samples:%d" % num_samples)

            read = output[num_samples]["jobs"][0]["read"]["iops"]
            write = output[num_samples]["jobs"][0]["write"]["iops"]
            total = read + write
            sum_normal += total

        LOG_JOB.debug(
            "expected_burst:%d %d expected_normal:%d %d",
            expected_burst,
            sum_burst,
            expected_normal,
            sum_normal,
        )
        if expected_burst:
            real_gap = abs(expected_burst - sum_burst)
            if real_gap <= expected_burst * self._margin:
                LOG_JOB.debug("Passed burst %d %d", expected_burst, sum_burst)
            else:
                self._test.fail("Failed burst %d %d", expected_burst, sum_burst)

        if abs(expected_normal - sum_normal) <= expected_normal * self._margin:
            LOG_JOB.debug(
                "Passed normal verification %d %d", expected_normal, sum_normal
            )
        else:
            self._test.fail("Failed normal %d %d" % (expected_normal, sum_normal))

        return True

    def start_one_image_test(self, image):
        """
        Process one disk throttle testing.

        :param image: name of image
        :return: True for succeed,False or test error raised if failed.
        """

        LOG_JOB.debug("Start one image run_fio :%s", image)
        self.run_fio(self._throttle["images"][image])
        return self.check_output([image])

    def start_all_images_test(self):
        """
        Process multi disks throttle testing parallel.

        :return: True for succeed,False or test error raised if failed.
        """

        num = len(self.images)
        pool = ThreadPool(num)

        for img in self.images:
            LOG_JOB.debug("Start all images run_fio :%s", img)
            pool.apply_async(self.run_fio, (self._throttle["images"][img],))
        pool.close()
        pool.join()
        return self.check_output(self.images)

    def start(self):
        """
        Process one disk and multi disks throttle testing.

        :return: True for succeed,False or test error raised if failed.
        """

        ret = False
        num = len(self.images)
        if num:
            ret = self.start_one_image_test(self.images[0])
            if ret and num > 1:
                self.wait_empty_burst()
                ret = self.start_all_images_test()

        return ret

    def wait_empty_burst(self):
        """
        Wait some time to empty burst
        """
        burst = self._throttle["expected"]["burst"]
        if "burst_empty_time" in burst.keys():
            LOG_JOB.debug("Wait empty %d", burst["burst_empty_time"])
            sleep(burst["burst_empty_time"])

    def set_image_fio_option(self, image, option):
        """
        Set fio option for specific image.

        :param image: image name
        :param option: full fio option for image,which executed by run_fio
        """

        self._throttle["images"][image]["fio_option"] = option

    def set_throttle_expected(self, expected, reset=False):
        """
        Set expected result for testing. it stores in throttle["expected"].
        The key-value pairs refer to default_expected.

        :param expected: Dict of the expected result
        :param reset: True for reset data before update.
        """

        if reset:
            self._throttle["expected"] = copy.deepcopy(ThrottleTester.raw_expected)
        if expected:
            for k, v in expected.items():
                if isinstance(v, dict):
                    self._throttle["expected"][k].update(expected[k])
                else:
                    self._throttle["expected"][k] = expected[k]

    def set_fio_option(self, option):
        """
        Set the default fio option for all images without --filename

        :param option: the fio option
        """

        self._fio_option = option

    def build_default_option(self):
        """
        Generate default fio option for all images. It also generates expected
        result according to throttle group property.
        """

        tgm = ThrottleGroupManager(self._vm)
        attrs = tgm.get_throttle_group_props(self.group)

        option = "--direct=1 --name=test --iodepth=1 --thread"
        option += "  --output-format=json "

        iops_size = attrs["iops-size"]
        iops_size = 4096 if iops_size == 0 else iops_size

        bps_read = attrs["bps-read"]
        bps_read_max = attrs["bps-read-max"]
        bps_read_max_length = attrs["bps-read-max-length"]
        bps_total = attrs["bps-total"]
        bps_total_max = attrs["bps-total-max"]
        bps_total_max_length = attrs["bps-total-max-length"]
        bps_write = attrs["bps-write"]
        bps_write_max = attrs["bps-write-max"]
        bps_write_max_length = attrs["bps-write-max-length"]
        iops_read = attrs["iops-read"]
        iops_read_max = attrs["iops-read-max"]
        iops_read_max_length = attrs["iops-read-max-length"]
        iops_total = attrs["iops-total"]
        iops_total_max = attrs["iops-total-max"]
        iops_total_max_length = attrs["iops-total-max-length"]
        iops_write = attrs["iops-write"]
        iops_write_max = attrs["iops-write-max"]
        iops_write_max_length = attrs["iops-write-max-length"]

        burst_read_iops = 0
        burst_write_iops = 0
        burst_total_iops = 0
        normal_read_iops = 0
        normal_write_iops = 0
        normal_total_iops = 0

        burst_time = 0
        burst_empty_time = 0

        # reset expected result
        self.set_throttle_expected(None, True)

        def _count_normal_iops(variables, iops_type):
            iops_val = variables["iops_%s" % iops_type]
            bps_val = variables["bps_%s" % iops_type]
            normal_iops = 0
            if iops_val != 0 or bps_val != 0:
                bps = int(bps_val / iops_size)
                iops = iops_val
                if (iops >= bps != 0) or iops == 0:
                    normal_iops = bps
                elif (bps >= iops != 0) or bps == 0:
                    normal_iops = iops
            self.set_throttle_expected({"normal": {iops_type: normal_iops}})
            return normal_iops

        def _count_burst_iops(variables, iops_type):
            iops_max = variables["iops_%s_max" % iops_type]
            iops_length = variables["iops_%s_max_length" % iops_type]
            bps_max = variables["bps_%s_max" % iops_type]
            bps_length = variables["bps_%s_max_length" % iops_type]
            normal_iops = variables["normal_%s_iops" % iops_type]
            burst_iops = 0
            empty_time = burst_empty_time
            full_time = burst_time
            if iops_max != 0 or bps_max != 0:
                bps = int(bps_max * bps_length / iops_size)
                iops = iops_max * iops_length
                burst_full = 0
                if (iops >= bps != 0) or iops == 0:
                    burst_full = bps
                    burst_iops = int(bps_max / iops_size)
                elif (bps >= iops != 0) or bps == 0:
                    burst_full = iops
                    burst_iops = iops_max

                empty_time = burst_full / normal_iops
                full_time = burst_full / (burst_iops - normal_iops)
                empty_time = ceil(max(empty_time, burst_empty_time))
                full_time = int(max(full_time, burst_time))

            self.set_throttle_expected({"burst": {iops_type: burst_iops}})
            return burst_iops, empty_time, full_time

        # count normal property
        local_vars = locals()
        normal_write_iops = _count_normal_iops(local_vars, "write")
        normal_read_iops = _count_normal_iops(local_vars, "read")
        normal_total_iops = _count_normal_iops(local_vars, "total")

        # count burst property
        local_vars = locals()
        burst_write_iops, burst_empty_time, burst_time = _count_burst_iops(
            local_vars, "write"
        )
        burst_read_iops, burst_empty_time, burst_time = _count_burst_iops(
            local_vars, "read"
        )
        burst_total_iops, burst_empty_time, burst_time = _count_burst_iops(
            local_vars, "total"
        )

        runtime = self._params.get("throttle_runtime", 60)
        if burst_time:
            runtime = burst_time
            self.set_throttle_expected(
                {
                    "burst": {
                        "burst_time": burst_time,
                        "burst_empty_time": burst_empty_time,
                    }
                }
            )

        if (normal_read_iops and normal_write_iops) or normal_total_iops:
            mode = "randrw"
        elif normal_read_iops:
            mode = "randread"
        elif normal_write_iops:
            mode = "randwrite"
        else:
            mode = "randrw"

        option += " --rw=%s --bs=%d --runtime=%s" % (mode, iops_size, runtime)

        LOG_JOB.debug(self._throttle["expected"])
        LOG_JOB.debug("fio_option:%s", option)
        self._fio_option = option

    def build_image_fio_option(self, image):
        """
        Build fio relevant info for image.

        :param image: name of image
        :return: dict of image relevant data.
        """

        if image not in self._throttle["images"].keys():
            self._throttle["images"].update(
                {image: copy.deepcopy(ThrottleTester.raw_image_data)}
            )

        name = _get_drive_path(self._session, self._params, image)
        image_data = self._throttle["images"][image]
        image_data["name"] = name
        image_data["fio_option"] = self._fio_option + " --filename=%s" % name
        return image_data

    def build_images_fio_option(self):
        """
        Build fio relevant info for all images.

        :return: dict of all images relevant data.
        """

        for image in self.images:
            self.build_image_fio_option(image)
        return self._throttle["images"]

    def attach_image(self, image):
        """
        Attach new image into throttle group.

        :param image: image name.
        """

        self.images.append(image)

    def detach_image(self, image):
        """
        Detach image from throttle group.

        :param image: image name.
        """

        self.images.remove(image)


class ThrottleGroupsTester(object):
    """
    This class mainly testing multi groups parallel or specified group
    Example of usage:
        ...
        fio = generate_instance(params, vm, 'fio')
        t1 = ThrottleTester("group1",["img1","img2"])
        t1.set_fio(fio)
        t1.build_default_option()
        t1.build_images_fio_option()
        t2 = ThrottleTester("group1",["img1","img2"])
        t2.set_fio(fio)
        t2.build_default_option()
        t2.build_images_fio_option()
        testers = ThrottleGroupsTester([t1,t2])
        testers.start()
    """

    def __init__(self, testers):
        self.testers = testers.copy()

    @staticmethod
    def proc_wrapper(func):
        """Wrapper to log exception"""
        try:
            return func()
        except Exception as e:
            LOG_JOB.exception(e)
            raise

    def start_group_test(self, group):
        """
        Start one group testing.

        :param group: group name
        """
        for tester in self.testers:
            if tester.group == group:
                tester.start()
                break
        else:
            raise ThrottleError("No found the corresponding group tester.")

    def start(self):
        """
        Start multi groups testing parallel.
        """
        num = len(self.testers)
        pool = ThreadPool(num)

        results = {}
        for tester in self.testers:
            LOG_JOB.debug("Start tester :%s", tester.group)
            result = pool.apply_async(self.proc_wrapper, (tester.start,))
            results[tester.group] = result
        pool.close()
        pool.join()

        success = True
        for group, result in results.items():
            if not result.successful():
                LOG_JOB.error("Find unexpected result on %s", group)
                success = False

        if not success:
            raise ThrottleError("Throttle testing failed,please check log.")

        LOG_JOB.debug("ThrottleGroupsParallelTester End")
