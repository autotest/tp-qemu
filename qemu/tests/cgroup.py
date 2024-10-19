"""
cgroup test (on KVM guest)
:author: Lukas Doktor <ldoktor@redhat.com>
:copyright: 2011 Red Hat, Inc.
"""

import os
import re
import threading
import time

from aexpect import ExpectProcessTerminatedError, ExpectTimeoutError, ShellTimeoutError
from avocado.core import exceptions
from avocado.utils import astring, process
from virttest import env_process, error_context, qemu_monitor, utils_misc
from virttest.env_process import preprocess
from virttest.staging import utils_memory
from virttest.staging.utils_cgroup import Cgroup, CgroupModules, get_load_per_cpu
from virttest.utils_test import VMStress

# Serial ID of the attached disk
RANDOM_DISK_NAME = "RANDOM46464634164145"


class SparseRange(list):
    """
    Turns kernel-like sparse array into list of values
    """

    def __init__(self, value):
        """
        :param value: sparse array string (eg.: "0-1,16-17")
        """
        super(SparseRange, self).__init__()
        try:
            for section in value.split(","):
                vals = section.split("-")
                if len(vals) == 1:  # single value
                    self.append(int(vals[0]))
                else:  # range
                    self.extend(range(int(vals[0]), int(vals[1]) + 1))
        except ValueError as details:
            raise ValueError("Can't parse SparseRange from %s: %s" % (value, details))

    def str_slice(self, start=0, stop=None, step=1):
        """
        :param start: slice start
        :param stop: slice stop
        :param step: slice step
        :return: kernel-like sparce array string from existing values
        """

        def append_section(out, sect_start, sect_stop):
            if sect_start == sect_stop:
                out.append(str(sect_start))
            else:
                out.append("%d-%d" % (sect_start, sect_stop))

        if stop is None:
            stop = len(self)
        out = []
        items = iter(self[start:stop:step])
        try:
            sect_start = next(items)
            sect_stop = sect_start
        except StopIteration:
            return ""
        for cur in items:
            if sect_stop == cur - 1:
                sect_stop = cur
            else:
                append_section(out, sect_start, sect_stop)
                sect_start = cur
                sect_stop = cur
        append_section(out, sect_start, sect_stop)
        return ",".join(out)


@error_context.context_aware
def run(test, params, env):
    """
    Tests the cgroup functions on KVM guests.
    """

    # Func
    def assign_vm_into_cgroup(vm, cgroup, pwd=None):
        """
        Assigns all threads of VM into cgroup
        :param vm: desired VM
        :param cgroup: cgroup handler
        :param pwd: desired cgroup's pwd, cgroup index or None for root cgroup
        """
        cgroup.set_cgroup(vm.get_shell_pid(), pwd)
        for i in range(10):
            for pid in vm.get_qemu_threads():
                try:
                    cgroup.set_cgroup(int(pid), pwd)
                except Exception as detail:  # Process might not already exist
                    if os.path.exists("/proc/%s/" % pid):
                        raise detail
                    else:  # Thread doesn't exist, try it again
                        break
            else:  # All PIDs moved
                break
        else:
            raise exceptions.TestFail(
                "Failed to move all VM threads to new cgroup" " in %d trials" % i
            )

    def distance(actual, reference):
        """
        Absolute value of relative distance of two numbers
        :param actual: actual value
        :param reference: reference value
        :return: relative distance abs((a-r)/r) (float)
        """
        return abs(float(actual - reference) / reference)

    def get_dd_cmd(direction, count=None, blocksize=None):
        """
        Generates dd_cmd string
        :param direction: {read,write,bi} dd direction
        :param dev: used device ('vd?')
        :param count: count parameter of dd
        :param blocksize: blocksize parameter of dd
        :return: dd command string
        """
        if direction == "read":
            params = "if=$FILE of=/dev/null iflag=direct"
        elif direction == "write":
            params = "if=/dev/zero of=$FILE oflag=direct"
        else:
            params = "if=$FILE of=$FILE iflag=direct oflag=direct"
        if blocksize:
            params += " bs=%s" % blocksize
        if count:
            params += " count=%s" % count
        return (
            "export FILE=$(ls /dev/disk/by-id/*%s | tail -n 1); touch /tmp/cgroup_lock"
            " ; while [ -e /tmp/cgroup_lock ]; do dd %s ; done"
            % (RANDOM_DISK_NAME, params)
        )

    def get_device_driver():
        """
        Discovers the used block device driver {ide, scsi, virtio_blk}
        :return: Used block device driver {ide, scsi, virtio}
        """
        return params.get("drive_format", "virtio")

    def get_maj_min(dev):
        """
        Returns the major and minor numbers of the dev device
        :return: Tuple(major, minor) numbers of the dev device
        """
        try:
            rdev = os.stat(dev).st_rdev
            ret = (os.major(rdev), os.minor(rdev))
        except Exception as details:
            raise exceptions.TestFail("get_maj_min(%s) failed: %s" % (dev, details))
        return ret

    def rm_scsi_disks(no_disks):
        """
        Removes no_disks scsi_debug disks from the last one.
        :param no_disks: How many disks to remove
        :note: params['cgroup_rmmod_scsi_debug'] == "yes" => rmmod scsi_debug
        """
        process.system(
            "echo -%d > /sys/bus/pseudo/drivers/scsi_debug/add_host" % no_disks,
            shell=True,
        )

        if params.get("cgroup_rmmod_scsi_debug", "no") == "yes":
            process.system("rmmod scsi_debug")

    def param_add_scsi_disks():
        """
        Adds scsi_debug disk to every VM in params['vms']
        :param prefix: adds prefix to drive name
        """
        if process.system("lsmod | grep scsi_debug", ignore_status=True, shell=True):
            process.system("modprobe scsi_debug dev_size_mb=8 add_host=0")
        for name in params["vms"].split(" "):
            disk_name = "scsi-debug-" + name
            process.system(
                "echo 1 > /sys/bus/pseudo/drivers/scsi_debug/" "add_host", shell=True
            )
            time.sleep(1)  # Wait for device init
            dev = process.getoutput("ls /dev/sd* | tail -n 1", shell=True)
            # Enable idling in scsi_debug drive
            process.system(
                "echo 1 > /sys/block/%s/queue/rotational" % (dev.split("/")[-1]),
                shell=True,
            )
            vm_disks = params.get("images_%s" % name, params.get("images", "image1"))
            params["images_%s" % name] = "%s %s" % (vm_disks, disk_name)
            params["image_name_%s" % disk_name] = dev
            params["image_snapshot_%s" % disk_name] = "no"
            params["image_format_%s" % disk_name] = "raw"
            params["remove_image_%s" % disk_name] = "no"
            params["image_raw_device_%s" % disk_name] = "yes"
            params["drive_cache_%s" % disk_name] = params.get("drive_cache", "none")
            params["drive_serial_%s" % disk_name] = RANDOM_DISK_NAME

    def param_add_file_disks(size, prefix="hd2-"):
        """
        Adds file disk to every VM in params['vms']
        :param size: Disk size (1M)
        :param prefix: adds prefix to drive name
        """
        for name in params["vms"].split(" "):
            vm_disks = params.get("images_%s" % name, params.get("images", "image1"))
            disk_name = prefix + name
            params["images_%s" % name] = "%s %s" % (vm_disks, disk_name)
            params["image_size_%s" % disk_name] = size
            params["image_name_%s" % disk_name] = disk_name
            params["image_snapshot_%s" % disk_name] = "no"
            params["force_create_image_%s" % disk_name] = "yes"
            params["image_format_%s" % disk_name] = "raw"
            params["create_with_dd_%s" % disk_name] = "yes"
            params["remove_image_%s" % disk_name] = "yes"
            params["drive_cache_%s" % disk_name] = params.get("drive_cache", "none")
            params["drive_serial_%s" % disk_name] = RANDOM_DISK_NAME

    def param_add_vms(no_vms):
        """
        Defines $no_vms in params
        :param no_vms: Desired number of VMs
        :note: All defined VMs are overwritten.
        """
        params["vms"] = ""
        for i in range(no_vms):
            params["vms"] += "vm%s " % i
        params["vms"] = params["vms"][:-1]

    # Tests
    @error_context.context_aware
    def blkio_bandwidth():
        """
        Sets blkio.weight for each VM and measure the actual distribution
        of read/write speeds.
        :note: VMs are created in test
        :param cfg: cgroup_test_time - test duration '60'
        :param cfg: cgroup_weights - list of R/W weights '[100, 1000]'
        :param cfg: cgroup_limit{ ,_read,_write} - allowed R/W threshold '0.1'
        """

        def _test(direction):
            """
            Executes loop of dd commands, kills it after $test_time and
            verifies the speeds using median.
            :param direction: "read" / "write"
            :return: "" on success or err message when fails
            """
            out = []
            # Initiate dd loop on all VMs (2 sessions per VM)
            # can't set bs for scsi_debug, default is 512b
            dd_cmd = get_dd_cmd(direction, count=3)
            for i in range(no_vms):
                sessions[i * 2].sendline(dd_cmd)
            time.sleep(test_time)
            for i in range(no_vms):
                # Force stats in case no dd cmd finished
                sessions[i * 2 + 1].sendline(stat_cmd)
            for i in range(no_vms):
                out.append(sessions[i * 2].read_until_output_matches([re_dd])[1])
            # Stop all transfers (on 2nd sessions)
            for i in range(no_vms):
                sessions[i * 2 + 1].sendline(kill_cmd)
            # Read the rest of the stats
            for i in range(no_vms):
                out[-1] = out[-1] + sessions[i * 2].read_up_to_prompt(
                    timeout=120 + test_time
                )

            for i in range(no_vms):
                # Get all dd loops' statistics
                # calculate avg from duration and data
                duration = 0
                data = 0
                if len(out[i]) > 5:
                    out[i] = out[i][1:-1]
                for _ in re.findall(re_dd, out[i])[1:-1]:
                    data += int(_[0])
                    duration += float(_[2])
                out[i] = int(data / duration)

            # normalize each output according to cgroup_weights
            # Calculate the averages from medians / weights
            sum_out = float(sum(out))
            sum_weights = float(sum(weights))
            for i in range(len(weights)):
                # [status, norm_weights, norm_out, actual]
                out[i] = ["PASS", weights[i] / sum_weights, out[i] / sum_out, out[i]]

            err = ""
            limit = float(
                params.get(
                    "cgroup_limit_%s" % direction, params.get("cgroup_limit", 0.1)
                )
            )
            # if any of norm_output doesn't ~ match norm_weights, log it.
            for i in range(len(out)):
                if out[i][2] > (out[i][1] + limit) or out[i][2] < (out[i][1] - limit):
                    out[i][0] = "FAIL"
                    err += "%d, " % i

            test.log.info(
                "blkio_bandwidth_%s: dd statistics\n%s",
                direction,
                astring.tabular_output(
                    out, ["status", "norm_weights", "norm_out", "actual"]
                ),
            )

            if err:
                err = "blkio_bandwidth_%s: limits [%s] were broken" % (
                    direction,
                    err[:-2],
                )
                test.log.debug(err)
                return err + "\n"
            return ""

        test.log.info("Init")
        try:
            weights = eval(params.get("cgroup_weights", "[100, 1000]"))
            if type(weights) is not list:
                raise TypeError
        except TypeError:
            raise exceptions.TestError(
                "Incorrect configuration: param "
                "cgroup_weights have to be list-like string '[1, 2]'"
            )
        test_time = int(params.get("cgroup_test_time", 60))
        test.log.info("Prepare VMs")
        # Prepare enough VMs each with 1 disk for testing
        no_vms = len(weights)
        param_add_vms(no_vms)
        param_add_file_disks("1M")
        preprocess(test, params, env)

        vms = []
        sessions = []  # 2 sessions per VM
        timeout = int(params.get("login_timeout", 360))
        for name in params["vms"].split():
            vms.append(env.get_vm(name))
            sessions.append(vms[-1].wait_for_login(timeout=timeout))
            sessions.append(vms[-1].wait_for_login(timeout=30))

        test.log.info("Setup test")
        modules = CgroupModules()
        if modules.init(["blkio"]) != 1:
            raise exceptions.TestFail("Can't mount blkio cgroup modules")
        blkio = Cgroup("blkio", "")
        blkio.initialize(modules)
        for i in range(no_vms):
            blkio.mk_cgroup()
            assign_vm_into_cgroup(vms[i], blkio, i)
            blkio_weight = params.get("blkio_weight_file")
            blkio.set_property(blkio_weight, weights[i], i)

        # Fails only when the session is occupied (Timeout)
        # ; true is necessarily when there is no dd present at the time
        kill_cmd = "rm -f /tmp/cgroup_lock; killall -9 dd; true"
        stat_cmd = "killall -SIGUSR1 dd; true"
        re_dd = (
            r"(\d+) bytes \(\d+\.*\d* \w*(, \d+\.*\d* \w*)?\) copied, "
            r"(\d+\.*\d*) s, \d+\.*\d* \w./s"
        )
        err = ""
        try:
            test.log.info("Read test")
            err += _test("read")
            # verify sessions between tests
            for session in sessions:
                session.cmd("true")
            test.log.info("Write test")
            err += _test("write")
            if err:
                test.log.error("Results:\n%s", err)
            else:
                test.log.info("Speeds distributed accordingly to blkio.weight.")

        finally:
            test.log.info("Cleanup")
            for i in range(no_vms):
                # stop all workers
                sessions[i * 2 + 1].sendline(kill_cmd)
            for session in sessions:
                # try whether all sessions are clean
                session.cmd("true")
                session.close()

            del blkio
            del modules

            for i in range(len(vms)):
                vms[i].destroy()

        test.log.info("Results")
        if err:
            raise exceptions.TestFail(err)
        else:
            return "Speeds distributed accordingly to blkio.weight."

    @error_context.context_aware
    def blkio_throttle():
        """
        Tests the blkio.throttle.{read,write}_bps_device cgroup capability.
        It sets speeds accordingly to current scenario and let it run for
        $test_time seconds. Afterwards it verifies whether the speeds matches.
        :note: VMs are created in test
        :note: Uses scsi_debug disks
        :param cfg: cgroup_test_time - test duration '60'
        :param cfg: cgroup_limit{ ,_read,_write} - allowed R/W threshold '0.1'
        :param cfg: cgroup_speeds list of simultaneous speeds
                    [speed1, speed2,..] '[1024]'
        """
        test.log.info("Init")
        try:
            speeds = eval(params.get("cgroup_speeds", "[1024]"))
            if type(speeds) is not list:
                raise TypeError
        except TypeError:
            raise exceptions.TestError(
                "Incorrect configuration: param "
                "cgroup_speeds have to be list of strings"
                "eg. [1024] or [1024,2048,8192]."
            )

        # Make param suitable for multitest and execute it.
        return blkio_throttle_multi([[_] for _ in speeds])

    @error_context.context_aware
    def blkio_throttle_multi(speeds=None):
        """
        Tests the blkio.throttle.{read,write}_bps_device cgroup capability.
        It sets speeds accordingly to current scenario and let it run for
        $test_time seconds. Afterwards it verifies whether the speeds matches.
        All scenarios have to have the same number of speeds (= no_vms).
        :note: VMs are created in test
        :note: Uses scsi_debug disks
        :param cfg: cgroup_test_time - test duration '60'
        :param cfg: cgroup_limit{ ,_read,_write} - allowed R/W threshold '0.1'
        :param cfg: cgroup_speeds list of lists defining [[vm1],[vm2],..]]
                    and speeds [[speed1],[speed2],..],..].
                    '[[1024,0,2048,0,8192]]'
        """

        def _test(direction, blkio):
            """
            Executes loop of small dd transfers changes cgroups and measures
            speeds.
            :param direction: "read" / "write"
            :return: "" on success or err message when fails
            """
            # Test
            # can't set bs for scsi_debug, default is 512b
            dd_cmd = get_dd_cmd(direction, count=3)
            float(
                params.get(
                    "cgroup_limit_%s" % direction, params.get("cgroup_limit", 0.1)
                )
            )
            # every scenario have list of results [[][][]]
            out = []
            # every VM have one output []
            for i in range(no_vms):
                out.append([])
            for j in range(no_speeds):
                _ = ""
                for i in range(no_vms):
                    # assign all VMs to current scenario cgroup
                    assign_vm_into_cgroup(vms[i], blkio, i * no_speeds + j)
                    _ += "vm%d:%d, " % (i, speeds[i][j])
                test.log.debug(
                    "blkio_throttle_%s: Current speeds: %s", direction, _[:-2]
                )
                # Restart all transfers (on 1st sessions)
                for i in range(no_vms):
                    sessions[i * 2].sendline(dd_cmd)
                time.sleep(test_time)
                # Read stats
                for i in range(no_vms):
                    # Force stats in case no dd cmd finished
                    sessions[i * 2 + 1].sendline(stat_cmd)
                for i in range(no_vms):
                    out[i].append(sessions[i * 2].read_until_output_matches([re_dd])[1])
                # Stop all transfers (on 2nd sessions)
                for i in range(no_vms):
                    sessions[i * 2 + 1].sendline(kill_cmd)
                # Read the rest of the stats
                for i in range(no_vms):
                    out[i][-1] = out[i][-1] + sessions[i * 2].read_up_to_prompt(
                        timeout=120 + test_time
                    )

            # bash needs some time...
            time.sleep(1)
            for i in range(no_vms):
                test.log.debug("Setting unlimited speed")
                assign_vm_into_cgroup(vms[i], blkio, -1)
                sessions[i * 2 + 1].sendline(kill_cmd)

            # Verification
            err = ""
            # [PASS/FAIL, iteration, vm, speed, actual]
            output = []
            for j in range(len(out[i])):
                for i in range(no_vms):
                    # calculate avg from duration and data
                    duration = 0
                    data = 0
                    for _ in re.findall(re_dd, out[i][j]):
                        data += int(_[0])
                        duration += float(_[2])
                    output.append(
                        ["PASS", j, "vm%d" % i, speeds[i][j], int(data / duration)]
                    )
                    # Don't measure unlimited speeds
                    if speeds[i][j] == 0:
                        output[-1][0] = "INF"
                        output[-1][3] = "(inf)"
                    elif output[-1][4] > speeds[i][j]:
                        err += "vm%d:%d, " % (i, j)
                        output[-1][0] = "FAIL"

            # TODO: Unlimited speed fluctuates during test
            test.log.info(
                "blkio_throttle_%s: dd statistics\n%s",
                direction,
                astring.tabular_output(
                    output, ["result", "it", "vm", "speed", "actual"]
                ),
            )
            if err:
                err = "blkio_throttle_%s: limits [%s] were broken" % (
                    direction,
                    err[:-2],
                )
                test.log.debug(err)
                return err + "\n"
            return ""

        test.log.info("Init")
        no_speeds = 0
        if speeds:  # blkio_throttle
            no_speeds = len(speeds[0])
        else:  # blkio_throttle_multi
            try:
                speeds = eval(params.get("cgroup_speeds", "[[1024,0,2048,0,8192]]"))
                if type(speeds) is not list:
                    raise TypeError
                if type(speeds[0]) is not list:
                    test.log.warning("cgroup_speeds have to be listOfLists")
                    speeds = [speeds]
                no_speeds = len(speeds[0])
                for speed in speeds:
                    if type(speed) is not list:
                        test.log.error("One of cgroup_speeds sublists is not " "list")
                        raise TypeError
                    if len(speed) != no_speeds:
                        test.log.error(
                            "cgroup_speeds sublists have different " "lengths"
                        )
                        raise TypeError
            except TypeError:
                raise exceptions.TestError(
                    "Incorrect configuration: param "
                    "cgroup_speeds have to be listOfList-"
                    "like string with same lengths. "
                    "([[1024]] or [[0,1024],[1024,2048]])"
                )
        # Minimum testing time is 30s (dd must copy few blocks)
        test_time = max(int(params.get("cgroup_test_time", 60)) / no_speeds, 30)

        test.log.info("Prepare VMs")
        # create enough of VMs with scsi_debug attached disks
        no_vms = len(speeds)
        param_add_vms(no_vms)
        param_add_scsi_disks()
        preprocess(test, params, env)

        vms = []
        sessions = []
        timeout = int(params.get("login_timeout", 360))
        # 2 sessions per VM
        for name in params["vms"].split():
            vms.append(env.get_vm(name))
            sessions.append(vms[-1].wait_for_login(timeout=timeout))
            sessions.append(vms[-1].wait_for_login(timeout=30))

        test.log.info("Setup test")
        modules = CgroupModules()
        if modules.init(["blkio"]) != 1:
            raise exceptions.TestFail("Can't mount blkio cgroup modules")
        blkio = Cgroup("blkio", "")
        blkio.initialize(modules)
        for i in range(no_vms):
            # Set speeds for each scsi_debug device for each VM
            dev = get_maj_min(params["image_name_scsi-debug-%s" % vms[i].name])
            for j in range(no_speeds):
                speed = speeds[i][j]
                blkio.mk_cgroup()
                if speed == 0:  # Disable limit (removes the limit)
                    blkio.set_property(
                        "blkio.throttle.write_bps_device",
                        "%s:%s %s" % (dev[0], dev[1], speed),
                        i * no_speeds + j,
                        check="",
                    )
                    blkio.set_property(
                        "blkio.throttle.read_bps_device",
                        "%s:%s %s" % (dev[0], dev[1], speed),
                        i * no_speeds + j,
                        check="",
                    )
                else:  # Enable limit (input separator ' ', output '\t')
                    blkio.set_property(
                        "blkio.throttle.write_bps_device",
                        "%s:%s %s" % (dev[0], dev[1], speed),
                        i * no_speeds + j,
                        check="%s:%s\t%s" % (dev[0], dev[1], speed),
                    )
                    blkio.set_property(
                        "blkio.throttle.read_bps_device",
                        "%s:%s %s" % (dev[0], dev[1], speed),
                        i * no_speeds + j,
                        check="%s:%s\t%s" % (dev[0], dev[1], speed),
                    )
        blkio.mk_cgroup()  # last one is unlimited

        # ; true is necessarily when there is no dd present at the time
        kill_cmd = "rm -f /tmp/cgroup_lock; killall -9 dd; true"
        stat_cmd = "killall -SIGUSR1 dd; true"
        re_dd = (
            r"(\d+) bytes \(\d+\.*\d* \w*(, \d+\.*\d* \w*)?\) copied, "
            r"(\d+\.*\d*) s, \d+\.*\d* \w./s"
        )
        err = ""
        try:
            test.log.info("Read test")
            err += _test("read", blkio)
            # verify sessions between tests
            for session in sessions:
                session.cmd("true", timeout=600)
            test.log.info("Write test")
            err += _test("write", blkio)

            if err:
                test.log.error("Results\n%s", err)

        finally:
            test.log.info("Cleanup")
            for i in range(no_vms):
                # stop all workers
                sessions[i * 2 + 1].sendline(kill_cmd)

            del blkio
            del modules

            for session in sessions:
                # try whether all sessions are clean
                session.cmd("true", timeout=600)
                session.close()

            for i in range(len(vms)):
                vms[i].destroy()

            rm_scsi_disks(no_vms)

        test.log.info("Results")
        if err:
            raise exceptions.TestFail(err)
        else:
            return "Throughputs matched the prescriptions."

    @error_context.context_aware
    def cpu_cfs_util():
        """
        Tests cfs scheduler utilisation when cfs_period_us and cfs_quota_us
        are set for each virtual CPU with multiple VMs.
        Each VM have double the previous created one (1, 2, 4, 8..) up to
        twice physical CPUs overcommit. cfs quotas are set to 1/2 thus VMs
        should consume exactly 100%. It measures the difference.
        :note: VMs are created in test
        :param cfg: cgroup_test_time - test duration '60'
        :param cfg: cgroup_limit - allowed threshold '0.05' (5%)
        """
        test.log.info("Setup test")
        modules = CgroupModules()
        if modules.init(["cpu"]) != 1:
            raise exceptions.TestFail("Can't mount cpu cgroup modules")
        cgroup = Cgroup("cpu", "")
        cgroup.initialize(modules)
        host_cpus = open("/proc/cpuinfo").read().count("processor")

        # Create first VM
        params["smp"] = 1
        params["vcpu_sockets"] = 1
        params["vcpu_maxcpus"] = host_cpus
        params["vms"] = "vm0"
        preprocess(test, params, env)

        test.log.info("Prepare VMs")
        vms = []
        sessions = []
        serials = []
        timeout = 1.5 * int(params.get("login_timeout", 360))
        # First one
        vms.append(env.get_all_vms()[0])
        cpu_pids = vms[0].get_vcpu_pids(debug=False)

        smp = len(cpu_pids)
        cgroup.mk_cgroup()
        cgroup.set_property("cpu.cfs_period_us", 100000, 0)
        cgroup.set_property("cpu.cfs_quota_us", 50000 * smp, 0)
        assign_vm_into_cgroup(vms[0], cgroup, 0)
        for j in range(smp):
            cgroup.mk_cgroup(0)
            cgroup.set_property("cpu.cfs_period_us", 100000, -1)
            cgroup.set_property("cpu.cfs_quota_us", 50000, -1)
            cgroup.set_cgroup(cpu_pids[j], -1)
            sessions.append(vms[0].wait_for_login(timeout=timeout))
        serials.append(vms[0].wait_for_serial_login(timeout=30))
        serials[0].cmd("touch /tmp/cgroup-cpu-lock")
        vm_cpus = smp

        # Clone the first one with different 'smp' setting
        _params = params
        i = 1
        while vm_cpus < 2 * host_cpus:
            vm_name = "clone%d" % i
            smp = min(2 * smp, 2 * host_cpus - vm_cpus)
            _params["smp"] = smp
            vms.append(vms[0].clone(vm_name, _params))
            env.register_vm(vm_name, vms[-1])
            vms[-1].create()
            pwd = cgroup.mk_cgroup()
            cgroup.set_property("cpu.cfs_period_us", 100000, -1)
            # Total quota is for ALL vCPUs
            cgroup.set_property("cpu.cfs_quota_us", 50000 * smp, -1)
            assign_vm_into_cgroup(vms[-1], cgroup, -1)
            cpu_pids = vms[-1].get_vcpu_pids(debug=False)

            for j in range(smp):
                cgroup.mk_cgroup(pwd)
                cgroup.set_property("cpu.cfs_period_us", 100000, -1)
                # Quota for current vcpu
                cgroup.set_property("cpu.cfs_quota_us", 50000, -1)
                cgroup.set_cgroup(cpu_pids[j], -1)
                sessions.append(vms[-1].wait_for_login(timeout=timeout))
            serials.append(vms[-1].wait_for_serial_login(timeout=30))
            serials[-1].cmd("touch /tmp/cgroup-cpu-lock")
            vm_cpus += smp
            i += 1

        cmd = "renice -n 10 $$; "
        cmd += "while [ -e /tmp/cgroup-cpu-lock ] ; do :; done"
        kill_cmd = "rm -f /tmp/cgroup-cpu-lock"

        stats = []
        # test_time is 1s stabilization, 1s first meass., 9s second and the
        # rest of cgroup_test_time as 3rd meassurement.
        test_time = max(1, int(params.get("cgroup_test_time", 60)) - 11)
        err = []
        try:
            test.log.info("Test")
            for session in sessions:
                session.sendline(cmd)

            time.sleep(1)
            stats.append(open("/proc/stat", "r").readline())
            time.sleep(1)
            stats.append(open("/proc/stat", "r").readline())
            time.sleep(9)
            stats.append(open("/proc/stat", "r").readline())
            time.sleep(test_time)
            stats.append(open("/proc/stat", "r").readline())
            for session in serials:
                session.sendline("rm -f /tmp/cgroup-cpu-lock")

            # /proc/stat first line is cumulative CPU usage
            # 1-8 are host times, 8-9 are guest times (on older kernels only 8)
            test.log.info("Verification")
            # Start of the test (time 0)
            stats[0] = [int(_) for _ in stats[0].split()[1:]]
            stats[0] = [sum(stats[0][0:8]), sum(stats[0][8:])]
            # Calculate relative stats from time 0
            for i in range(1, len(stats)):
                stats[i] = [int(_) for _ in stats[i].split()[1:]]
                try:
                    stats[i] = float(sum(stats[i][8:]) - stats[0][1]) / (
                        sum(stats[i][0:8]) - stats[0][0]
                    )
                except ZeroDivisionError:
                    test.log.error("ZeroDivisionError in stats calculation")
                    stats[i] = False
            limit = 1 - float(params.get("cgroup_limit", 0.05))

            for i in range(1, len(stats)):
                # Utilisation should be 100% - allowed treshold (limit)
                if stats[i] < limit:
                    test.log.debug(
                        "%d: the utilisation of guest time is %s, "
                        "smaller than limit %s",
                        i,
                        stats[i],
                        limit,
                    )
                    err.append(i)

        finally:
            test.log.info("Cleanup")
            del cgroup
            del modules

            for i in range(len(serials)):
                # stop all workers
                serials[i].sendline(kill_cmd)
            for session in sessions:
                # try whether all sessions are clean
                session.cmd("true")
                session.close()

            for i in range(1, len(vms)):
                vms[i].destroy()

        test.log.info("Results")
        if err:
            err = "The host vs. guest CPU time ratio is over %s in %s cases" % (
                limit,
                err,
            )
            raise exceptions.TestFail(err)
        else:
            return "Guest times are over %s%%: %s" % (limit, stats[1:])

    @error_context.context_aware
    def cpu_share():
        """
        Sets cpu.share shares for different VMs and measure the actual
        utilisation distribution over physical CPUs
        :param cfg: cgroup_use_max_smp - use smp = all_host_cpus
        :param cfg: cgroup_test_time - test duration '60'
        :param cfg: smp - no_vcpus per VM. When smp <= 0 .. smp = no_host_cpus
        :param cfg: cgroup_speeds - list of speeds of each vms [vm0, vm1,..].
                    List is sorted in test! '[10000, 100000]'
        """

        def _get_stat(f_stats, _stats=None):
            """Reads CPU times from f_stats[] files and sumarize them."""
            if _stats is None:
                _stats = []
                for i in range(len(f_stats)):
                    _stats.append(0)
            stats = []
            for i in range(len(f_stats)):
                f_stats[i].seek(0)
                stats.append(f_stats[i].read().split()[13:17])
                stats[i] = sum([int(_) for _ in stats[i]]) - _stats[i]
            return stats

        test.log.info("Init")
        try:
            speeds = eval(params.get("cgroup_speeds", "[10000, 100000]"))
            if type(speeds) is not list:
                raise TypeError
        except TypeError:
            raise exceptions.TestError(
                "Incorrect configuration: param "
                "cgroup_speeds have to be list-like string '[1, 2]'"
            )

        host_cpus = open("/proc/cpuinfo").read().count("processor")
        # when smp <= 0 use smp = no_host_cpus
        vm_cpus = int(params.get("smp", 0))  # cpus per VM
        params["vcpu_maxcpus"] = host_cpus
        # Use smp = no_host_cpu
        if vm_cpus <= 0 or params.get("cgroup_use_max_smp") == "yes":
            params["smp"] = host_cpus
            vm_cpus = host_cpus
        no_speeds = len(speeds)
        # All host_cpus have to be used with no_speeds overcommit
        no_vms = host_cpus * no_speeds // vm_cpus
        no_threads = no_vms * vm_cpus
        sessions = []
        serials = []
        modules = CgroupModules()
        if modules.init(["cpu"]) != 1:
            raise exceptions.TestFail("Can't mount cpu cgroup modules")
        cgroup = Cgroup("cpu", "")
        cgroup.initialize(modules)

        test.log.info("Prepare VMs")
        param_add_vms(no_vms)
        preprocess(test, params, env)

        # session connections are spread vm1, vm2, vm3, ... With more vcpus
        # the second round is similar after the whole round (vm1, vm2, vm1, ..)
        # vms are spread into cgroups vm1=cg1, vm2=cg2, vm3=cg3 // % no_cgroup
        # when we go incrementally through sessions we got always different cg
        vms = env.get_all_vms()
        timeout = 1.5 * int(params.get("login_timeout", 360))
        for i in range(no_threads):
            sessions.append(vms[i % no_vms].wait_for_login(timeout=timeout))

        for i in range(no_speeds):
            cgroup.mk_cgroup()
            cgroup.set_property("cpu.shares", speeds[i], i)
        for i in range(no_vms):
            assign_vm_into_cgroup(vms[i], cgroup, i % no_speeds)
            sessions[i].cmd("touch /tmp/cgroup-cpu-lock")
            serials.append(vms[i].wait_for_serial_login(timeout=30))

        test.log.info("Test")
        try:
            f_stats = []
            err = []
            # Time 0
            for vm in vms:
                f_stats.append(open("/proc/%d/stat" % vm.get_pid(), "r"))

            time_init = 2
            # there are 6 tests
            time_test = max(int(params.get("cgroup_test_time", 60)) / 6, 5)
            thread_count = 0  # actual thread number
            stats = []
            cmd = "renice -n 10 $$; "  # new ssh login should pass
            cmd += "while [ -e /tmp/cgroup-cpu-lock ]; do :; done"
            # Occupy all host_cpus with 1 task (no overcommit)
            for thread_count in range(0, host_cpus):
                sessions[thread_count].sendline(cmd)
            time.sleep(time_init)
            _stats = _get_stat(f_stats)
            time.sleep(time_test)
            stats.append(_get_stat(f_stats, _stats))

            # Overcommit on 1 cpu
            thread_count += 1
            sessions[thread_count].sendline(cmd)
            time.sleep(time_init)
            _stats = _get_stat(f_stats)
            time.sleep(time_test)
            stats.append(_get_stat(f_stats, _stats))

            # no_speeds overcommit on all CPUs
            for i in range(thread_count + 1, no_threads):
                sessions[i].sendline(cmd)
            time.sleep(time_init)
            _stats = _get_stat(f_stats)
            for j in range(3):
                __stats = _get_stat(f_stats)
                time.sleep(time_test)
                stats.append(_get_stat(f_stats, __stats))
            stats.append(_get_stat(f_stats, _stats))

            # Verify results
            err = ""
            # accumulate stats from each cgroup
            for j in range(len(stats)):
                for i in range(no_speeds, len(stats[j])):
                    stats[j][i % no_speeds] += stats[j][i]
                stats[j] = stats[j][:no_speeds]
            # I.
            i = 0
            # only first #host_cpus guests were running
            dist = distance(min(stats[i][:host_cpus]), max(stats[i][:host_cpus]))
            # less vms, lower limit. Maximal limit is 0.2
            if dist > min(0.15 + 0.01 * len(vms), 0.2):
                err += "1, "
                test.log.error(
                    "1st part's limits broken. Utilisation should be"
                    " equal. stats = %s, distance = %s",
                    stats[i],
                    dist,
                )
            else:
                test.log.info("1st part's distance = %s", dist)
            # II.
            i += 1
            dist = distance(min(stats[i]), max(stats[i]))
            if host_cpus % no_speeds == 0 and no_speeds <= host_cpus:
                if dist > min(0.15 + 0.01 * len(vms), 0.2):
                    err += "2, "
                    test.log.error(
                        "2nd part's limits broken, Utilisation "
                        "should be equal. stats = %s, distance = %s",
                        stats[i],
                        dist,
                    )
                else:
                    test.log.info("2nd part's distance = %s", dist)
            else:
                test.log.warning(
                    "2nd part's verification skipped (#cgroup,#cpu),"
                    " stats = %s,distance = %s",
                    stats[i],
                    dist,
                )

            # III.
            # normalize stats, then they should have equal values
            i += 1
            for i in range(i, len(stats)):
                norm_stats = [
                    float(stats[i][_]) / speeds[_] for _ in range(len(stats[i]))
                ]
                dist = distance(min(norm_stats), max(norm_stats))
                if dist > min(0.15 + 0.02 * len(vms), 0.25):
                    err += "3, "
                    test.log.error(
                        "3rd part's limits broken; utilisation "
                        "should be in accordance to self.speeds. "
                        "stats=%s, norm_stats=%s, distance=%s, "
                        "speeds=%s,it=%d",
                        stats[i],
                        norm_stats,
                        dist,
                        speeds,
                        i - 1,
                    )
                else:
                    test.log.info("3rd part's norm_dist = %s", dist)

            if err:
                err = "[%s] parts broke their limits" % err[:-2]
                test.log.error(err)
            else:
                test.log.info("Cpu utilisation enforced successfully")

        finally:
            test.log.info("Cleanup")
            del cgroup

            for i in range(len(serials)):
                # stop all workers
                serials[i].sendline("rm -f /tmp/cgroup-cpu-lock")
            for session in sessions:
                # try whether all sessions are clean
                session.cmd("true")
                session.close()

            for i in range(len(vms)):
                vms[i].destroy()

            del modules

        test.log.info("Results")
        if err:
            raise exceptions.TestFail(err)
        else:
            return "Cpu utilisation enforced successfully"

    @error_context.context_aware
    def cpuset_cpus():
        """
        Pins main_thread and each vcpu acoordingly to scenario setup
        and measures physical CPU utilisation.
        When nothing is set the test uses smp vcpus. When cgroup_cpuset is
        specified it forces smp to fit cpuset prescription. Last but not least
        you can force the test to use half of the host cpus.
        @warning: Default verification method assumes 100% utilisation on each
                  used CPU. You can force cgroup_verify results.
        :param cfg: cgroup_use_half_smp - force smp = no_host_cpus / 2
        :param cfg: cgroup_test_time - scenerio duration '1'
        :param cfg: cgroup_limit - allowed threshold '0.05' (5%)
        :params cfg: cgroup_cpuset - list of lists defining cpu pinning.
                     [[1st_scenario],[2nd_scenario], ...]
                     [[main_thread, vcpu0, vcpu1, ...], ...]
                     eg. [[None, '0,3', '1', '2', '1-2'], ['0', '0', '1'.....]]
                     'by default 5 specific scenarios'
        :params cfg: cgroup_verify - list of lists defining verification
                     physical CPUs utilisations
                     [[1st_scenario],[2nd_scenario], ...]
                     [[cpu0_util,cpu1_util,...], ...]
                     eg. [[50, 100, 100, 50], [100, 100, 0, 0]]
                     'by default it assumes each used CPU will be 100%
                     utilised'
        """

        def _generate_cpusets(vm_cpus, cpus):
            """
            Generates 5 cpusets scenerios
            :param vm_cpus: number of virtual CPUs
            :param cpus: Physical CPU layout
            """
            cpusets = []
            # OO__
            if len(cpus) > vm_cpus:
                cpuset = cpus.str_slice(0, vm_cpus)
                # all cpus + main_thread
                cpusets.append([cpuset for _ in range(len(cpus) + 1)])
            # __OO
            if len(cpus) > vm_cpus:
                cpuset = cpus.str_slice(len(cpus) - vm_cpus)
                cpusets.append([cpuset for _ in range(len(cpus) + 1)])
            # O___
            cpusets.append([str(cpus[0]) for _ in range(len(cpus) + 1)])
            # _OO_
            cpuset = cpus.str_slice(1, 1 + vm_cpus)
            cpusets.append([cpuset for _ in range(len(cpus) + 1)])
            # O_O_
            cpuset = cpus.str_slice(0, min(vm_cpus * 2, len(cpus)), 2)
            cpusets.append([cpuset for _ in range(len(cpus) + 1)])
            return cpusets

        def _generate_verification(cpusets, cpus):
            """
            Calculates verification data.
            @warning: Inaccurate method, every pinned CPU have to have 100%
                      utilisation!
            :param cpusets: cpusets scenarios
            :param cpus: Physical CPU layout
            """
            verify = []
            # For every scenerio
            for cpuset in cpusets:
                verify.append([0 for _ in range(len(cpus))])
                # For every vcpu (skip main_thread, it doesn't consume much)
                for vcpu in cpuset[1:]:
                    vcpu = SparseRange(vcpu)
                    for vcpu_pin in vcpu:
                        verify[-1][cpus.index(vcpu_pin)] = 100
            return verify

        test.log.info("Init")
        cpusets = None
        verify = None
        try:
            cpusets = eval(params.get("cgroup_cpuset", "None"))
            if not ((type(cpusets) is list) or (cpusets is None)):
                raise Exception
        except Exception:
            raise exceptions.TestError(
                "Incorrect configuration: param cgroup_"
                "cpuset have to be list of lists, where "
                "all sublist have the same length and "
                "the length is ('smp' + 1). Or 'None' for "
                "default.\n%s" % cpusets
            )
        try:
            verify = eval(params.get("cgroup_verify", "None"))
            if not ((type(cpusets) is list) or (cpusets is None)):
                raise Exception
        except Exception:
            raise exceptions.TestError(
                "Incorrect configuration: param cgroup_"
                "verify have to be list of lists or 'None' "
                "for default/automatic.\n%s" % verify
            )

        limit = float(params.get("cgroup_limit", 0.05)) * 100

        test_time = int(params.get("cgroup_test_time", 1))

        vm = env.get_all_vms()[0]
        modules = CgroupModules()
        if modules.init(["cpuset"]) != 1:
            raise exceptions.TestFail("Can't mount cpu cgroup modules")
        cgroup = Cgroup("cpuset", "")
        cgroup.initialize(modules)

        cpus = SparseRange(cgroup.get_property("cpuset.cpus")[0])
        mems = SparseRange(cgroup.get_property("cpuset.mems")[0])

        vm_cpus = int(params.get("smp", 1))
        # If cpuset specified, set smp accordingly
        if cpusets:
            if len(cpus) < (len(cpusets[0]) - 1):
                err = (
                    "Not enough host CPUs to run this test with selected "
                    "cpusets (cpus=%s, cpusets=%s)" % (len(cpus), cpusets)
                )
                test.log.error(err)
                raise exceptions.TestSkipError(err)
            vm_cpus = len(cpusets[0]) - 1  # Don't count main_thread to vcpus
            for i in range(len(cpusets)):
                # length of each list have to be 'smp' + 1
                if len(cpusets[i]) != (vm_cpus + 1):
                    err = (
                        "cpusets inconsistent. %d sublist have different "
                        " length. (param cgroup_cpusets in cfg)." % i
                    )
                    test.log.error(err)
                    raise exceptions.TestError(err)
        # if cgroup_use_half_smp, set smp accordingly
        elif params.get("cgroup_use_half_smp") == "yes":
            vm_cpus = len(cpus) // 2
            if len(cpus) == 2:
                test.log.warning("Host have only 2 CPUs, using 'smp = all cpus'")
                vm_cpus = 2

        if vm_cpus <= 1:
            test.log.error("Test requires at least 2 vCPUs.")
            raise exceptions.TestSkipError("Test requires at least 2 vCPUs.")
        # Check whether smp changed and recreate VM if so
        if vm_cpus != (params.get_numeric("smp") or params.get_numeric("vcpu_maxcpus")):
            test.log.info("Expected VM reload.")
            params["vcpu_maxcpus"] = params["smp"] = vm_cpus
            vm.create(params=params)
        # Verify vcpus matches prescription
        vcpus = vm.get_vcpu_pids(debug=False)

        if len(vcpus) != vm_cpus:
            raise exceptions.TestFail(
                "Incorrect number of vcpu PIDs; smp=%s vcpus=" "%s" % (vm_cpus, vcpus)
            )

        if not cpusets:
            test.log.info("Generating cpusets scenerios")
            cpusets = _generate_cpusets(vm_cpus, cpus)

        if verify:  # Verify exists, check if it's correct
            for _ in verify:
                if len(_) != len(cpus):
                    err = (
                        "Incorrect cgroup_verify. Each verify sublist have "
                        "to have length = no_host_cpus"
                    )
                    test.log.error(err)
                    raise exceptions.TestError(err)
        else:  # Generate one
            test.log.info("Generating cpusets expected results")
            try:
                verify = _generate_verification(cpusets, cpus)
            except IndexError:
                raise exceptions.TestError(
                    "IndexError occurred while generating "
                    "verification data. Probably mismatched"
                    " no_host_cpus and cgroup_cpuset cpus"
                )

        test.log.info("Prepare")
        for i in range(len(cpus) + 1):
            cgroup.mk_cgroup()
            cgroup.set_property("cpuset.cpus", cpus.str_slice(), i)
            cgroup.set_property("cpuset.mems", mems.str_slice(), i)
            if i == 0:
                assign_vm_into_cgroup(vm, cgroup, 0)
            elif i <= vm_cpus:
                cgroup.set_cgroup(vcpus[i - 1], i)

        timeout = int(params.get("login_timeout", 360))
        sessions = []
        stats = []
        serial = vm.wait_for_serial_login(timeout=timeout)
        cmd = "renice -n 10 $$; "  # new ssh login should pass
        cmd += "while [ -e /tmp/cgroup-cpu-lock ]; do :; done"
        for i in range(vm_cpus * 2):
            sessions.append(vm.wait_for_login(timeout=timeout))
            sessions[-1].cmd("touch /tmp/cgroup-cpu-lock")
            sessions[-1].sendline(cmd)

        cpu_time_type = params.get_numeric("cpu_time_type")
        try:
            test.log.info("Test")
            for i in range(len(cpusets)):
                cpuset = cpusets[i]
                test.log.debug("testing: %s", cpuset)
                # setup scenario
                for i in range(len(cpuset)):
                    cgroup.set_property("cpuset.cpus", cpuset[i], i)
                # Time 0
                _load = get_load_per_cpu()
                time.sleep(test_time)
                # Stats after test_time
                _load_diff = get_load_per_cpu(_load)
                stats.append(list(map(list, zip(*_load_diff)))[cpu_time_type][1:])

            serial.cmd("rm -f /tmp/cgroup-cpu-lock")
            err = ""

            test.log.info("Verification")
            # Normalize stats
            for i in range(len(stats)):
                stats[i] = [(_ / test_time) for _ in stats[i]]
            # Check
            # header and matrix variables are only for "beautiful" log
            header = ["scen"]
            header.extend([" cpu%d" % i for i in cpus])
            matrix = []
            for i in range(len(stats)):
                matrix.append(["%d" % i])
                for j in range(len(stats[i])):
                    if (stats[i][j] < (verify[i][j] - limit)) or (
                        stats[i][j] > (verify[i][j] + limit)
                    ):
                        err += "%d(%d), " % (i, j)
                        matrix[-1].append("%3d ! %d" % (verify[i][j], stats[i][j]))
                    else:
                        matrix[-1].append("%3d ~ %d" % (verify[i][j], stats[i][j]))
            test.log.info(
                "Results (theoretical ~ actual):\n%s",
                astring.tabular_output(matrix, header),
            )
            if err:
                err = "Scenerios %s FAILED" % err
                test.log.error(err)
            else:
                test.log.info("All utilisations match prescriptions.")

        finally:
            test.log.info("Cleanup")
            serial.cmd("rm -f /tmp/cgroup-cpu-lock")
            del cgroup
            del modules

        test.log.info("Results")
        if err:
            raise exceptions.TestFail(err)
        else:
            return "All utilisations match prescriptions."

    @error_context.context_aware
    def cpuset_cpus_switching():
        """
        Tests the cpuset.cpus cgroup feature. It stresses all VM's CPUs
        while switching between cgroups with different setting.
        :param cfg: cgroup_test_time - test duration '60'
        """
        test.log.info("Init")
        try:
            test_time = int(params.get("cgroup_test_time", 60))
        except ValueError:
            raise exceptions.TestError(
                "Incorrect configuration: param "
                "cgroup_test_time have to be an integer"
            )

        test.log.info("Prepare")
        modules = CgroupModules()
        if modules.init(["cpuset"]) != 1:
            raise exceptions.TestFail("Can't mount cpuset cgroup modules")
        cgroup = Cgroup("cpuset", "")
        cgroup.initialize(modules)

        timeout = int(params.get("login_timeout", 360))
        vm = env.get_all_vms()[0]
        serial = vm.wait_for_serial_login(timeout=timeout)
        vm_cpus = int(params.get("smp", 1))
        cpus = SparseRange(cgroup.get_property("cpuset.cpus")[0])
        if len(cpus) < 2:
            raise exceptions.TestFail(
                "This test needs at least 2 CPUs on " "host, cpuset=%s" % cpus
            )
        # Comments are for vm_cpus=2, no_cpus=4, _SC_CLK_TCK=100
        cgroup.mk_cgroup()  # oooo
        cgroup.set_property("cpuset.cpus", cpus.str_slice(), 0)
        cgroup.set_property("cpuset.mems", 0, 0)
        cgroup.mk_cgroup()  # O___
        cgroup.set_property("cpuset.cpus", cpus[0], 1)
        cgroup.set_property("cpuset.mems", 0, 1)
        cgroup.mk_cgroup()  # _OO_
        cgroup.set_property("cpuset.cpus", cpus.str_slice(1, 3), 2)
        cgroup.set_property("cpuset.mems", 0, 2)
        assign_vm_into_cgroup(vm, cgroup, 0)

        test.log.info("Test")
        err = ""
        try:
            cmd = "renice -n 10 $$; "  # new ssh login should pass
            cmd += "while [ -e /tmp/cgroup-cpu-lock ]; do :; done"
            sessions = []
            # start stressers
            for i in range(vm_cpus):
                sessions.append(vm.wait_for_login(timeout=30))
                sessions[i].cmd("touch /tmp/cgroup-cpu-lock")
                sessions[i].sendline(cmd)

            test.log.info(
                "Some harmless IOError messages of non-existing "
                "processes might occur."
            )
            i = 0
            t_stop = time.time() + test_time  # run for $test_time seconds
            while time.time() < t_stop:
                assign_vm_into_cgroup(vm, cgroup, i % 3)
                i += 1

            test.log.info("Verification")
            serial.sendline("rm -f /tmp/cgroup-cpu-lock")

            try:
                vm.verify_alive()
            except Exception as exc_details:
                err += "VM died (no_switches=%s): %s\n" % (i, exc_details)

            if err:
                err = err[:-1]
                test.log.error(err)
            else:
                test.log.info("VM survived %d cgroup switches", i)

        finally:
            test.log.info("Cleanup")
            del cgroup
            del modules

            serial.sendline("rm -f /tmp/cgroup-cpu-lock")

            for session in sessions:
                # try whether all sessions are clean
                session.cmd("true")
                session.close()

        test.log.info("Results")
        if err:
            raise exceptions.TestFail(err)
        else:
            return "VM survived %d cgroup switches" % i

    @error_context.context_aware
    def cpuset_mems_switching():
        """
        Tests the cpuset.mems pinning. It changes cgroups with different
        mem nodes while stressing memory.
        :param cfg: cgroup_test_time - test duration '60'
        :param cfg: cgroup_cpuset_mems_mb - override the size of memory blocks
                    'by default 1/2 of VM memory'
        """
        test.log.info("Init")
        test_time = int(params.get("cgroup_test_time", 10))
        vm = env.get_all_vms()[0]

        test.log.info("Prepare")
        modules = CgroupModules()
        if modules.init(["cpuset"]) != 1:
            raise exceptions.TestFail("Can't mount cpuset cgroup modules")
        cgroup = Cgroup("cpuset", "")
        cgroup.initialize(modules)

        mems = SparseRange(cgroup.get_property("cpuset.mems")[0])
        if len(mems) < 2:
            raise exceptions.TestSkipError(
                "This test needs at least 2 memory nodes, " "detected mems %s" % mems
            )
        # Create cgroups
        all_cpus = cgroup.get_property("cpuset.cpus")[0]
        for mem in mems:
            cgroup.mk_cgroup()
            cgroup.set_property("cpuset.mems", mem, -1)
            cgroup.set_property("cpuset.cpus", all_cpus, -1)
            cgroup.set_property("cpuset.memory_migrate", 1)

        timeout = int(params.get("login_timeout", 360))
        sessions = []
        sessions.append(vm.wait_for_login(timeout=timeout))
        sessions.append(vm.wait_for_login(timeout=30))

        # Don't allow to specify more than 1/2 of the VM's memory
        size = int(params.get("mem", 1024)) / 2
        if params.get("cgroup_cpuset_mems_mb") is not None:
            size = min(size, int(params.get("cgroup_cpuset_mems_mb")))

        test.log.info("Test")
        err = ""
        try:
            test.log.info(
                "Some harmless IOError messages of non-existing "
                "processes might occur."
            )
            sessions[0].sendline(
                "dd if=/dev/zero of=/dev/null bs=%dM " "iflag=fullblock" % size
            )

            i = 0
            sessions[1].cmd("killall -SIGUSR1 dd")
            t_stop = time.time() + test_time
            while time.time() < t_stop:
                i += 1
                assign_vm_into_cgroup(vm, cgroup, i % len(mems))
            sessions[1].cmd("killall -SIGUSR1 dd; true")
            try:
                out = sessions[0].read_until_output_matches([r"(\d+)\+\d records out"])[
                    1
                ]
                if len(re.findall(r"(\d+)\+\d records out", out)) < 2:
                    out += sessions[0].read_until_output_matches(
                        [r"(\d+)\+\d records out"]
                    )[1]
            except ExpectTimeoutError:
                err = "dd didn't produce expected output: %s" % out

            if not err:
                sessions[1].cmd("killall dd; true")
                dd_res = re.findall(r"(\d+)\+(\d+) records in", out)
                dd_res += re.findall(r"(\d+)\+(\d+) records out", out)
                dd_res = [int(_[0]) + int(_[1]) for _ in dd_res]
                if dd_res[1] <= dd_res[0] or dd_res[3] <= dd_res[2]:
                    err = "dd stoped sending bytes: %s..%s, %s..%s" % (
                        dd_res[0],
                        dd_res[1],
                        dd_res[2],
                        dd_res[3],
                    )
            if err:
                test.log.error(err)
            else:
                out = (
                    "Guest moved %stimes in %s seconds while moving %d "
                    "blocks of %dMB each" % (i, test_time, dd_res[3], size)
                )
                test.log.info(out)
        finally:
            test.log.info("Cleanup")
            del cgroup
            del modules

            for session in sessions:
                # try whether all sessions are clean
                session.cmd("true")
                session.close()

        test.log.info("Results")
        if err:
            raise exceptions.TestFail(err)
        else:
            return "VM survived %d cgroup switches" % i

    @error_context.context_aware
    def devices_access():
        """
        Tests devices.list capability. It tries hot-adding disk with different
        devices.list permittions and verifies whether it pass or fails.
        It tests booth RO and RW mode.
        :note: VM is destroyed after this test (in order to remove the attached
               disks)
        :note: supported monitor CMDs are pci_add, drive_add and RH-drive_add
                RH-QMP-drive_add
        """

        def _set_permissions(cgroup, permissions):
            """
            Wrapper for setting permissions to first cgroup
            :param self.permissions: is defined as a list of dictionaries:
               {'property': control property, 'value': permition value,
                'check_value': check value (from devices.list property),
                'read_results': excepced read results T/F,
                'write_results': expected write results T/F}
            """
            cgroup.set_property(
                "devices." + permissions["property"],
                permissions["value"],
                cgroup.cgroups[0],
                check=permissions["check_value"],
                checkprop="devices.list",
            )

        def _add_drive(monitor, monitor_type, disk, name, readonly=False):
            """
            Hot-adds disk to monitor's VM.
            :param monitor: VM's monitor.
            :param monitor_type: which command to use for hot-adding. (string)
            :param disk: pwd to disk
            :param name: id name given to this disk in VM
            :param readonly: Use readonly? 'False'
            """
            if readonly:
                readonly_str = "on"
            else:
                readonly_str = "off"
            if monitor_type == "HUMAN PCI_ADD":
                out = monitor.cmd(
                    "pci_add auto storage file=%s,readonly=%s,"
                    "if=virtio,id=%s" % (disk, readonly_str, name)
                )
                if "all in use" in out:  # All PCIs used
                    return -1  # restart machine and try again
                if name not in monitor.cmd("info block"):
                    return False
            elif monitor_type == "HUMAN DRIVE_ADD":
                monitor.cmd(
                    "drive_add auto file=%s,readonly=%s,if=none,id=%s"
                    % (disk, readonly_str, name)
                )
                if name not in monitor.cmd("info block"):
                    return False
            elif monitor_type == "HUMAN RH":
                monitor.cmd(
                    "__com.redhat_drive_add id=%s,file=%s,readonly=%s"
                    % (name, disk, readonly_str)
                )
                if name not in monitor.cmd("info block"):
                    return False
            elif monitor_type == "QMP RH":
                monitor.cmd_obj(
                    {
                        "execute": "__com.redhat_drive_add",
                        "arguments": {"file": disk, "id": name, "readonly": readonly},
                    }
                )
                output = monitor.cmd_obj({"execute": "query-block"})
                for out in output["return"]:
                    try:
                        if out["device"] == name:
                            return True
                    except KeyError:
                        pass
                return False
            else:
                return False

            return True

        def _get_scsi_debug_disk():
            cmd = (
                "ls -1 /sys/bus/pseudo/drivers/scsi_debug/adapter*/"
                "host*/target*/*/block | grep ^sd | head -1"
            )
            name = process.system_output(
                cmd, shell=True, verbose=False, ignore_status=True
            ).decode()
            if not name:
                return None
            node_path = "/dev/%s" % name
            if not os.path.exists(node_path):
                return None
            return node_path

        test.log.info("Setup test")
        vm = env.get_all_vms()[0]
        # Try to find suitable monitor
        monitor_type = None
        for i_monitor in range(len(vm.monitors)):
            monitor = vm.monitors[i_monitor]
            if isinstance(monitor, qemu_monitor.QMPMonitor):
                out = monitor.cmd_obj({"execute": "query-commands"})
                try:
                    if {"name": "__com.redhat_drive_add"} in out["return"]:
                        monitor_type = "QMP RH"
                        break
                except KeyError:
                    test.log.info("Incorrect data from QMP, skipping: %s", out)
                    continue
            else:
                out = monitor.cmd("help")
                if "\ndrive_add " in out:
                    monitor_type = "HUMAN DRIVE_ADD"
                    break
                elif "\n__com.redhat_drive_add " in out:
                    monitor_type = "HUMAN RH"
                    break
                elif "\npci_add " in out:
                    monitor_type = "HUMAN PCI_ADD"
                    break
        if monitor_type is None:
            raise exceptions.TestSkipError(
                "Not detected any suitable monitor cmd. "
                "Supported methods:\nQMP: __com.redhat_"
                "drive_add\nHuman: drive_add, pci_add, "
                "__com.redhat_drive_add"
            )
        test.log.debug("Using monitor type: %s", monitor_type)

        modules = CgroupModules()
        if modules.init(["devices"]) != 1:
            raise exceptions.TestFail("Can't mount blkio cgroup modules")
        devices = Cgroup("devices", "")
        devices.initialize(modules)
        devices.mk_cgroup()

        # Add one scsi_debug disk which will be used in testing
        if process.system("lsmod | grep scsi_debug", ignore_status=True, shell=True):
            process.system("modprobe scsi_debug dev_size_mb=8 add_host=0")
        process.system(
            "echo 1 > /sys/bus/pseudo/drivers/scsi_debug/add_host", shell=True
        )
        disk = utils_misc.wait_for(_get_scsi_debug_disk, 5)
        if not disk:
            test.error("Could not get the device node generated by scsi_debug")
        dev = "%s:%s" % get_maj_min(disk)
        permissions = [
            {
                "property": "deny",
                "value": "a",
                "check_value": "",
                "result": False,
                "result_read": False,
            },
            {
                "property": "allow",
                "value": "b %s r" % dev,
                "check_value": True,
                "result": False,
                "result_read": True,
            },
            {
                "property": "allow",
                "value": "b %s w" % dev,
                "check_value": "b %s rw" % dev,
                "result": True,
                "result_read": True,
            },
            {
                "property": "deny",
                "value": "b %s r" % dev,
                "check_value": "b %s w" % dev,
                "result": False,
                "result_read": False,
            },
            {
                "property": "deny",
                "value": "b %s w" % dev,
                "check_value": "",
                "result": False,
                "result_read": False,
            },
            {
                "property": "allow",
                "value": "a",
                "check_value": "a *:* rwm",
                "result": True,
                "result_read": True,
            },
        ]

        assign_vm_into_cgroup(vm, devices, 0)

        test.log.info("Test")
        err = ""
        name = "idTest%s%d"
        try:
            i = 0
            while i < len(permissions):
                perm = permissions[i]
                _set_permissions(devices, perm)
                test.log.debug(
                    "Setting permissions: {%s: %s}, value: %s",
                    perm["property"],
                    perm["value"],
                    devices.get_property("devices.list", 0),
                )
                results = ""
                out = _add_drive(monitor, monitor_type, disk, name % ("R", i), True)
                if out == -1:
                    test.log.warning("All PCIs full, recreating VM")
                    vm.create()
                    monitor = vm.monitors[i_monitor]
                    assign_vm_into_cgroup(vm, devices, 0)
                    continue
                if perm["result_read"] and not out:
                    results += "ReadNotAttached, "
                elif not perm["result_read"] and out:
                    results += "ReadAttached, "

                out = _add_drive(monitor, monitor_type, disk, name % ("RW", i), False)
                if out == -1:
                    test.log.warning("All PCIs full, recreating VM")
                    vm.create()
                    monitor = vm.monitors[i_monitor]
                    assign_vm_into_cgroup(vm, devices, 0)
                    continue
                if perm["result"] and not out:
                    results += "RWNotAttached, "
                elif not perm["result"] and out:
                    results += "RWAttached, "

                if results:
                    test.log.debug("%d: FAIL: %s", i, results[:-2])
                    err += "{%d: %s}, " % (i, results[:-2])
                else:
                    test.log.info("%d: PASS", i)
                i += 1

            if err:
                err = "Some restrictions weren't enforced:\n%s" % err[:-2]
                test.log.error(err)
            else:
                test.log.info("All restrictions enforced.")

        finally:
            test.log.info("Cleanup")
            vm.destroy()  # "Safely" remove devices :-)
            rm_scsi_disks(1)
            del devices
            del modules

        test.log.info("Results")
        if err:
            raise exceptions.TestFail(err)
        else:
            return "All restrictions enforced."

    @error_context.context_aware
    def freezer():
        """
        Tests the freezer.state cgroup functionality. (it freezes the guest
        and unfreeze it again)
        :param cfg: cgroup_test_time - test duration '60'
        """

        def _get_stat(pid):
            """
            Gather statistics of pid+1st level subprocesses cpu usage
            :param pid: PID of the desired process
            :return: sum of all cpu-related values of 1st level subprocesses
            """
            out = None
            for i in range(10):
                try:
                    out = process.getoutput(
                        "cat /proc/%s/task/*/stat" % pid, shell=True
                    )
                except process.CmdError:
                    out = None
                else:
                    break
            out = out.split("\n")
            ret = 0
            for i in out:
                ret += sum([int(_) for _ in i.split(" ")[13:17]])
            return ret

        test.log.info("Init")
        try:
            test_time = int(params.get("cgroup_test_time", 60))
        except ValueError:
            raise exceptions.TestError(
                "Incorrect configuration: param "
                "cgroup_test_time have to be an integer"
            )

        timeout = int(params.get("login_timeout", 360))
        vm = env.get_all_vms()[0]
        vm_cpus = vm.cpuinfo.smp  # cpus per VM
        serial = vm.wait_for_serial_login(timeout=timeout)
        sessions = []
        for _ in range(vm_cpus):
            sessions.append(vm.wait_for_login(timeout=timeout))

        test.log.info("Prepare")
        modules = CgroupModules()
        if modules.init(["freezer"]) != 1:
            raise exceptions.TestFail("Can't mount freezer cgroup modules")
        cgroup = Cgroup("freezer", "")
        cgroup.initialize(modules)
        cgroup.mk_cgroup()
        assign_vm_into_cgroup(vm, cgroup, 0)

        test.log.info("Test")
        err = ""
        try:
            for session in sessions:
                session.cmd("touch /tmp/freeze-lock")
                session.sendline("while [ -e /tmp/freeze-lock ]; do :; done")
            cgroup = cgroup
            pid = vm.get_pid()

            # Let it work for short, mid and long period of time
            for tsttime in [0.5, 3, test_time]:
                test.log.debug("FREEZING (%ss)", tsttime)
                # Freezing takes some time, DL is 1s
                cgroup.set_property(
                    "freezer.state", "FROZEN", cgroup.cgroups[0], check=False
                )
                time.sleep(1)
                _ = cgroup.get_property("freezer.state", 0)
                if "FROZEN" not in _:
                    err = "Coundn't freze the VM: state %s" % _
                    break
                stat_ = _get_stat(pid)
                time.sleep(tsttime)
                stat = _get_stat(pid)
                if stat != stat_:
                    err = (
                        "Process was running in FROZEN state; stat=%s, "
                        "stat_=%s, diff=%s" % (stat, stat_, stat - stat_)
                    )
                    break
                test.log.debug("THAWING (%ss)", tsttime)
                cgroup.set_property("freezer.state", "THAWED", 0)
                stat_ = _get_stat(pid)
                time.sleep(tsttime)
                stat = _get_stat(pid)
                if (stat - stat_) < (90 * tsttime):
                    err = (
                        "Process was not active in FROZEN state; stat=%s, "
                        "stat_=%s, diff=%s" % (stat, stat_, stat - stat_)
                    )
                    break

            if err:
                test.log.error(err)
            else:
                test.log.info("Freezer works fine")

        finally:
            test.log.info("Cleanup")
            del cgroup
            serial.sendline("rm -f /tmp/freeze-lock")

            for session in sessions:
                session.cmd("true")
                session.close()

            del modules

        if err:
            raise exceptions.TestFail(err)
        else:
            return "Freezer works fine"

    def _get_rss(status):
        """
        Get VmRSS without RssShmem from /proc/$PID/status output

        The RssShmem can be accounted to different process making the
        overall sum of VmRSS greater than set in limit_in_bytes
        """
        rss = int(re.search(r"VmRSS:[\t ]*(\d+) kB", status).group(1))
        shmem = int(re.search(r"RssShmem:[\t ]*(\d+) kB", status).group(1))
        return rss - shmem

    @error_context.context_aware
    def memory_limit(memsw=False):
        """
        Tests the memory.limit_in_bytes or memory.memsw.limit_in_bytes cgroup
        capability. It tries to allocate bigger block than allowed limit.
        memory.limit_in_bytes: Qemu process should be swaped out and the
                               block created.
        memory.memsw.limit_in_bytes: Qemu should be killed with err 137.
        :param memsw: Whether to run memsw or rss mem only test
        :param cfg: cgroup_memory_limit_kb - (4kb aligned) test uses
                    1.1 * memory_limit memory blocks for testing
                    'by default 1/2 of VM memory'
        """
        test.log.info("Init")
        try:
            mem_limit = params.get("cgroup_memory_limit_kb", None)
            if mem_limit is not None:
                mem_limit = int(mem_limit)
        except ValueError:
            raise exceptions.TestError(
                "Incorrect configuration: param cgroup_"
                "memory_limit_kb have to be an integer"
            )

        vm = env.get_all_vms()[0]

        test.log.info("Prepare")
        # Don't allow to specify more than 1/2 of the VM's memory
        mem = int(params.get("mem", 1024)) * 512
        if mem_limit:
            mem = min(mem, mem_limit)
        else:
            mem_limit = mem
        # There have to be enough free swap space and hugepages can't be used
        if not memsw:
            if params.get("setup_hugepages") == "yes":
                err = "Hugepages can't be used in this test."
                test.log.error(err)
                raise exceptions.TestSkipError(err)
            if utils_memory.read_from_meminfo("SwapFree") < (mem * 0.1):
                err = "Not enough free swap space"
                test.log.error(err)
                raise exceptions.TestSkipError(err)
        # We want to copy slightely over "mem" limit
        mem *= 1.1
        modules = CgroupModules()
        if modules.init(["memory"]) != 1:
            raise exceptions.TestFail("Can't mount memory cgroup modules")
        cgroup = Cgroup("memory", "")
        cgroup.initialize(modules)
        cgroup.mk_cgroup()
        cgroup.set_property("memory.move_charge_at_immigrate", "3", 0)
        cgroup.set_property_h("memory.limit_in_bytes", "%dK" % mem_limit, 0)
        if memsw:
            try:
                cgroup.get_property("memory.memsw.limit_in_bytes", 0)
            except exceptions.TestError as details:
                test.log.error(
                    "Can't get memory.memsw.limit_in_bytes info."
                    "Do you have support for memsw? (try passing"
                    "swapaccount=1 parameter to kernel):%s",
                    details,
                )
                raise exceptions.TestSkipError(
                    "System doesn't support memory.memsw.*"
                    " or swapaccount is disabled."
                )
            cgroup.set_property_h("memory.memsw.limit_in_bytes", "%dK" % mem_limit, 0)

        test.log.info("Expected VM reload")
        try:
            vm.create()
        except Exception as failure_detail:
            raise exceptions.TestFail(
                "init: Failed to recreate the VM: %s" % failure_detail
            )
        assign_vm_into_cgroup(vm, cgroup, 0)
        timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)

        # VM already eat-up more than allowed by this cgroup
        fstats = open("/proc/%s/status" % vm.get_pid(), "r")
        rss = _get_rss(fstats.read())
        if rss > mem_limit:
            raise exceptions.TestFail(
                "Init failed to move VM into cgroup, VmRss"
                "=%s, expected=%s" % (rss, mem_limit)
            )

        try:
            test.log.info("Test")
            """
            Let VM allocate huge block:
            1) memsw: During allocation limit of rss+swap should be exceeded
                      and VM should be killed with err 137.
            2) rsslimit: Allocation should pass, rss+swap should be greater
                         than mem_limit.
            * Max execution time is limited to mem / 10
            * Checking every 0.1s
            """
            session.sendline(
                "dd if=/dev/zero of=/dev/null bs=%dK count=1 " "iflag=fullblock" % mem
            )

            max_rss = 0
            max_rssswap = 0
            out = ""
            err = ""
            for _ in range(int(mem / 1024)):
                try:
                    fstats.seek(0)
                    status = fstats.read()
                    rss = _get_rss(status)
                    max_rss = max(rss, max_rss)
                    swap = int(re.search(r"VmSwap:[\t ]*(\d+) kB", status).group(1))
                    max_rssswap = max(rss + swap, max_rssswap)
                except Exception as details:
                    if memsw and not vm.is_alive():
                        # VM got SIGTERM as expected, finish the test
                        break
                    else:
                        err = details
                        break
                try:
                    out += session.read_up_to_prompt(timeout=0.1)
                except ExpectTimeoutError:
                    # 0.1s passed, lets begin the next round
                    pass
                except ShellTimeoutError as details:
                    if memsw and not vm.is_alive():
                        # VM was killed, finish the test
                        break
                    else:
                        err = details
                        break
                except ExpectProcessTerminatedError as detail:
                    if memsw:
                        err = (
                            "dd command died (VM should die instead): %s\n"
                            "Output:%s\n" % (detail, out)
                        )
                    else:
                        err = "dd command died (should pass): %s\nOutput:" "\n%s" % (
                            detail,
                            out,
                        )
                    break
                else:  # dd command finished
                    break

            test.log.info("Verification")
            if err:
                test.log.error(err)
            elif memsw:
                if max_rssswap > mem_limit:
                    err = "The limit was broken: max_rssswap=%s, limit=%s" % (
                        max_rssswap,
                        mem_limit,
                    )
                elif vm.process.get_status() != 137:  # err: Limit exceeded
                    err = "VM exit code is %s (should be %s)" % (
                        vm.process.get_status(),
                        137,
                    )
                else:
                    out = (
                        "VM terminated as expected. Used rss+swap: %d, "
                        "limit %s" % (max_rssswap, mem_limit)
                    )
                    test.log.info(out)
            else:  # only RSS limit
                exit_nr = session.cmd_output("echo $?")[:-1]
                if max_rss > mem_limit * 1.05:
                    # Allow 5% pages to be in-progress of swapping out
                    err = "The limit was broken: max_rss=%s, limit=%s (+5%%)" % (
                        max_rss,
                        mem_limit,
                    )
                elif exit_nr != "0":
                    err = "dd command failed(%s) output: %s" % (exit_nr, out)
                elif max_rssswap < mem_limit:
                    err = (
                        "VM didn't consume expected amount of memory. %d:%d"
                        " Output of dd cmd: %s" % (max_rssswap, mem_limit, out)
                    )
                else:
                    out = "Created %dMB block with %.2f memory overcommit" % (
                        mem / 1024,
                        float(max_rssswap) / mem_limit,
                    )
                    test.log.info(out)

        finally:
            test.log.info("Cleanup")

            if vm.is_alive():
                session.cmd("true")

            session.close()

            del cgroup
            del modules

        test.log.info("Results")
        if err:
            raise exceptions.TestFail(err)
        else:
            return out

    def memory_memsw_limit():
        """
        Executes the memory_limit test with parameter memsw.
        It tries to allocate bigger block than allowed limit. Qemu should be
        killed with err 137.
        :param cfg: cgroup_memory_limit_kb - test uses 1.1 * memory_limit
                    memory blocks for testing 'by default 1/2 of VM memory'
        """
        return memory_limit(memsw=True)

    def memory_move():
        """
        Tests the memory.move_charge_at_immigrate cgroup capability. It changes
        memory cgroup while running the guest system.
        :param cfg: cgroup_test_time - test duration '60'
        :param cfg: cgroup_memory_move_mb - override the size of memory blocks
                    'by default 1/2 of VM memory'
        """
        test.log.info("Init")
        test_time = int(params.get("cgroup_test_time", 10))
        vm = env.get_all_vms()[0]

        test.log.info("Prepare")
        modules = CgroupModules()
        if modules.init(["memory"]) != 1:
            raise exceptions.TestFail("Can't mount memory cgroup modules")
        cgroup = Cgroup("memory", "")
        cgroup.initialize(modules)
        # Two cgroups
        cgroup.mk_cgroup()
        cgroup.mk_cgroup()
        cgroup.set_property("memory.move_charge_at_immigrate", "3", 0)
        cgroup.set_property("memory.move_charge_at_immigrate", "3", 1)

        timeout = int(params.get("login_timeout", 360))
        sessions = []
        sessions.append(vm.wait_for_login(timeout=timeout))
        sessions.append(vm.wait_for_login(timeout=30))

        # Don't allow to specify more than 1/2 of the VM's memory
        size = int(params.get("mem", 1024)) / 2
        if params.get("cgroup_memory_move_mb") is not None:
            size = min(size, int(params.get("cgroup_memory_move_mb")))

        err = ""
        try:
            test.log.info("Test")
            test.log.info(
                "Some harmless IOError messages of non-existing "
                "processes might occur."
            )
            sessions[0].sendline(
                "dd if=/dev/zero of=/dev/null bs=%dM " "iflag=fullblock" % size
            )

            i = 0
            sessions[1].cmd("killall -SIGUSR1 dd ; true")
            t_stop = time.time() + test_time
            while time.time() < t_stop:
                i += 1
                assign_vm_into_cgroup(vm, cgroup, i % 2)
            sessions[1].cmd("killall -SIGUSR1 dd; true")
            try:
                out = sessions[0].read_until_output_matches([r"(\d+)\+\d records out"])[
                    1
                ]
                if len(re.findall(r"(\d+)\+\d records out", out)) < 2:
                    out += sessions[0].read_until_output_matches(
                        [r"(\d+)\+\d records out"]
                    )[1]
            except ExpectTimeoutError:
                err = "dd didn't produce expected output: %s" % out

            if not err:
                sessions[1].cmd("killall dd; true")
                dd_res = re.findall(r"(\d+)\+(\d+) records in", out)
                dd_res += re.findall(r"(\d+)\+(\d+) records out", out)
                dd_res = [int(_[0]) + int(_[1]) for _ in dd_res]
                if dd_res[1] <= dd_res[0] or dd_res[3] <= dd_res[2]:
                    err = "dd stoped sending bytes: %s..%s, %s..%s" % (
                        dd_res[0],
                        dd_res[1],
                        dd_res[2],
                        dd_res[3],
                    )

            if err:
                test.log.error(err)
            else:
                out = (
                    "Guest moved %stimes in %s seconds while moving %d "
                    "blocks of %dMB each" % (i, test_time, dd_res[3], size)
                )
                test.log.info(out)

        finally:
            test.log.info("Cleanup")
            sessions[1].cmd("killall dd; true")
            for session in sessions:
                session.cmd("true")
                session.close()

            del cgroup
            del modules

        if err:
            test.log.error(err)
        else:
            return out

    def cfs_bandwidth():
        """
        CFS bandwidth limit
        """

        def stress_thread():
            session.cmd(stress_cmd, 120)

        test.log.info("Setup cgroup subsystem: cpu")
        modules = CgroupModules()
        if modules.init(["cpu"]) != 1:
            test.fail("Can't mount cpu cgroup modules")
        cgroup = Cgroup("cpu", "")
        cgroup.initialize(modules)

        # Create VM with smp=1
        params["smp"] = 1
        params["vcpu_sockets"] = 1
        vm_name = params["main_vm"]
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(params["main_vm"])
        login_timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=login_timeout)

        cgroup.mk_cgroup()
        cgroup.set_property("cpu.cfs_period_us", 100000, 0)
        cgroup.set_property("cpu.cfs_quota_us", 50000, 0)
        assign_vm_into_cgroup(vm, cgroup, 0)

        check_install_stress = params["check_install_stress"]
        if session.cmd_status(check_install_stress):
            VMStress(vm, "stress", params).install()

        test.log.info("Check the cpu utilization")
        stress_cmd = params["stress_cmd"]
        stress_t = threading.Thread(target=stress_thread)
        stress_t.start()
        count = 0
        while count < 6:
            time.sleep(10)
            o = process.system_output(
                "top -b -p %s -n 3 | tail -1" % vm.get_pid(), shell=True
            ).decode()
            if float(o.split()[-4]) <= 51:
                count = count + 1
                test.log.debug(
                    "CPU utilization of guest is: %.2f%%", float(o.split()[-4])
                )
            else:
                test.fail(
                    "CPU utilization of guest is: %.2f%%, it should be about "
                    "50" % float(o.split()[-4])
                )
        stress_t.join()

    # Main
    # Executes test specified by cgroup_test variable in cfg
    fce = None
    _fce = params.get("cgroup_test")
    test.log.info("Executing test: %s", _fce)
    try:
        fce = locals()[_fce]
    except KeyError:
        raise exceptions.TestSkipError(
            "Test %s doesn't exist. Check 'cgroup_test' "
            "variable in subtest.cfg" % _fce
        )
    else:
        return fce()
