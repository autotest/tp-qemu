import copy
import itertools
import json
import re
import statistics as st
import time

from avocado.utils import process
from virttest import env_process, utils_disk
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number

from provider.storage_benchmark import generate_instance


def run(test, params, env):
    """
    Test the performance improvement with option:queue-size/num-queues

    1) Boot guest with data disks that with different option set
    2) Use fio to test disk performance
    3) Compare the result of different disk

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _get_window_disk_index_by_serial(serial):
        idx_info = get_disk_props_by_serial_number(session, serial, ["Index"])
        if idx_info:
            return idx_info["Index"]
        test.fail("Not find expected disk %s" % serial)

    def preprocess_fio_opts(results):
        """expand fio options"""
        fio_rw = params.get("fio_rw", "null").split()
        fio_bs = params.get("fio_bs", "null").split()
        fio_iodepth = params.get("fio_iodepth", "null-").split()
        fio_items = itertools.product(fio_rw, fio_bs, fio_iodepth)
        fio_combination = ""
        for sub_fio in fio_items:
            cmd = ""
            logger.debug(sub_fio)
            rw = sub_fio[0]
            bs = sub_fio[1]
            iodepth = sub_fio[2]
            name = "%s-%s-%s" % (rw, bs, iodepth)
            name = name.replace("null-", "")
            if rw != "null":
                cmd += " --rw=%s " % rw
            if bs != "null":
                cmd += " --bs=%s " % bs
            if iodepth != "null-":
                cmd += " --iodepth=%s " % iodepth
            if cmd:
                fio_combination += " --stonewall --name=%s" % name + cmd

        fio_opts = params["fio_cmd"]

        fio_opts += params.get("fio_addition_cmd", "")
        fio_opts += params.get("fio_stonewall_cmd", "")
        fio_opts += fio_combination
        results["fio_opts"] = fio_opts
        logger.debug(fio_opts)
        return fio_opts

    def preprcess_fio_filename(img):
        """get filename for img"""

        disk_size = params["image_size_%s" % img]
        fio_raw_device = params.get("fio_raw_device_%s" % img, "no")
        fio_filename = params.get("fio_filename_%s" % img)
        if fio_filename:
            return fio_filename
        if os_type == "windows":
            logger.info("Get windows disk index that to be formatted")
            disk_id = _get_window_disk_index_by_serial(img)

            if not utils_disk.update_windows_disk_attributes(session, disk_id):
                test.error("Failed to enable data disk %s" % disk_id)

            if fio_raw_device == "yes":
                return r"\\.\PHYSICALDRIVE%s" % disk_id

            disk_letter = utils_disk.configure_empty_windows_disk(
                session, disk_id, disk_size
            )[0]
            fio_filename = disk_letter + ":\\test.dat"
        else:
            dev = get_linux_drive_path(session, img)
            logger.debug(dev)
            if fio_raw_device == "yes":
                return dev
            mount_dir = "/home/%s" % (dev.replace("/dev/", ""))
            cmd = "mkfs.xfs {0} && mkdir -p {1} && mount {0} {1}".format(dev, mount_dir)
            session.cmd_output(cmd)
            fio_filename = "%s/test.img" % mount_dir

        if not fio_filename:
            test.fail("Can not get output file path in guest.")

        return fio_filename

    def preprocess_fio_data(results):
        """Init FIO result data structure
        {"images"=["img1",],
         "fio_items"=[]
         "fio_opts"=""
         "img1"={
             "filename": "",
             "global_options": {},
             "jobs": {
                 "job1":{
                     "iops_avg":0,
                     lat_avg:0,
                     "bw":[],
                     "iops":[],
                     "lat":[],
                     "job_runtime":0,
                     "options":{},
                     "job_cmd":""

                 },
                 "job2":{}

             },
             "results":[]
             "cmd": "",
             "cmds":[],
             "location": "",
             "disk_name":""
             }

         }

        """
        results["images"] = params["compare_images"].split()
        opts = preprocess_fio_opts(results)
        for img in results["images"]:
            results[img] = {
                "filename": "",
                "global_options": {},
                "jobs": {},
                "cmd": "",
                "cmds": [],
                "location": "",
                "results": [],
            }
            results[img]["location"] = params.get("fio_cmd_location_%s" % img, "vm")
            # guest fio
            if results[img]["location"] == "vm":
                fio_bin = fio.cfg.fio_path
            else:
                if os_type == "windows":
                    fio_bin = "fio --ioengine=libaio "
                else:
                    fio_bin = "fio"

            filename = preprcess_fio_filename(img)
            results[img]["cmd"] = "%s %s" % (fio_bin, opts % filename)
            cmds = results[img]["cmd"].split("--stonewall")
            if len(cmds) > 2 and fio_run_mode == "separate":
                for i in range(1, len(cmds)):
                    results[img]["cmds"].append(cmds[0] + cmds[i])

        logger.debug(results)

    def run_fio_test(results):
        """
        run the dd command and compare the results of the two disks,
        and then return the comparison result
        """
        for i in range(run_times + 1):
            logger.debug("Start %s / %s IO test", i, run_times)
            record = True if i + 1 == run_times else False

            for img in results["images"]:
                if results[img]["location"] == "vm":
                    runner = session.cmd_output
                else:
                    runner = process.getoutput

                if fio_iteration_cmd:
                    logger.debug(fio_iteration_cmd)
                    runner(fio_iteration_cmd)

                if results[img]["cmds"]:
                    cmd_num = len(results[img]["cmds"])
                    for idx, cmd in enumerate(results[img]["cmds"]):
                        logger.debug("Run sub-cmd %s/%s:%s", idx, cmd_num, cmd)
                        img_output = runner(cmd, cmd_timeout)
                        if i > 0:
                            # discard first result
                            parse_fio_result(img_output, img, results, record)
                else:
                    logger.debug("Run full-cmd: %s", results[img]["cmd"])
                    img_output = runner(results[img]["cmd"], cmd_timeout)
                    if i > 0:
                        # discard first result
                        parse_fio_result(img_output, img, results, record)

                if fio_interval:
                    time.sleep(fio_interval)

    def parse_fio_result(cmd_output, img, results, record=False):
        # if record:
        #     logger.debug(cmd_output)
        try:
            json_output = json.loads(cmd_output)
            img_result = results[img]
            if record:
                img_result["results"].append(copy.deepcopy(json_output))
            if "directory" in json_output["global options"]:
                filename = json_output["global options"]["directory"]
            else:
                filename = json_output["global options"]["filename"]
            if img_result.get("filename"):
                if filename != img_result["filename"]:
                    test.fail("Wrong data %s %s" % (filename, img_result["filename"]))
            else:
                # init global info
                global_options = copy.deepcopy(json_output["global options"])
                img_result["filename"] = filename
                img_result["global_options"] = global_options
                img_result["jobs"] = {}
                if os_type == "linux":
                    disk_name = "unknown"
                    if json_output.get("disk_util"):
                        disk_name = json_output["disk_util"][0]["name"]
                    img_result["disk_name"] = disk_name

            jobs = img_result["jobs"]
            for job in json_output["jobs"]:
                jobname = job["jobname"]
                if jobname not in jobs:
                    # init job info
                    logger.debug("Add job: %s %s", filename, jobname)
                    jobs[jobname] = {
                        "options": job["job options"].copy(),
                        "iops": [],
                        "iops_avg": 0,
                        "lat": [],
                        "lat_avg": 0,
                        "job_runtime": 0,
                        "bw": [],
                    }
                read = int(job["read"]["iops"])
                write = int(job["write"]["iops"])
                iops = read + write
                bw = int(job["read"]["bw"]) + int(job["write"]["bw"])
                lat = int(job["read"]["lat_ns"]["mean"]) + int(
                    job["write"]["lat_ns"]["mean"]
                )
                logger.debug(
                    "Get %s %s  runtime:%s IOPS read:%s write:%s sum:%s",
                    filename,
                    jobname,
                    job["job_runtime"],
                    read,
                    write,
                    iops,
                )
                img_result["jobs"][jobname]["iops"].append(iops)
                img_result["jobs"][jobname]["lat"].append(lat)
                img_result["jobs"][jobname]["bw"].append(bw)
                img_result["jobs"][jobname]["job_runtime"] = job["job_runtime"]

            return img_result

        except Exception as err:
            logger.error("Exception:%s %s", err, cmd_output)
            raise err

    def remove_maximum_deviation(alist):
        if not alist:
            return -1
        average = sum(alist) * 1.0 / len(alist)
        max_deviation = 0
        pos = 0
        for i, a in enumerate(alist):
            if abs(a - average) > max_deviation:
                max_deviation = abs(a - average)
                pos = i
        return alist.pop(pos)

    def compare_fio_result(results):
        # preprocess data to smooth data
        for img in results["images"]:
            jobs = results[img]["jobs"]
            for key in jobs.keys():
                job = jobs[key]
                raw_iops = job["iops"]
                raw_lat = job["lat"]
                logger.debug("%s raw %s iops:%s", img, key, raw_iops)
                job["sample_iops"] = raw_iops.copy()
                job["sample_lat"] = raw_lat.copy()
                iops = job["sample_iops"]
                lat = job["sample_lat"]

                # Discard maximum deviation
                if run_times > 3:
                    drop_num = round(run_times * (1 - sampling_rate))
                    logger.debug("Drop %s sample data...", drop_num)
                    for i in range(drop_num):
                        remove_maximum_deviation(iops)
                        remove_maximum_deviation(lat)
                sample_num = len(iops)
                iops_avg = int(sum(iops) / sample_num)
                job["iops_avg"] = iops_avg
                job["iops_std"] = 0 if sample_num == 1 else st.stdev(iops)
                job["iops_dispersion"] = round(job["iops_std"] / iops_avg, 6)
                job["lat_avg"] = int(sum(lat) / sample_num)
                logger.debug(
                    "%s smooth %s iops:%s AVG:%s lat:%s V:%s%%",
                    img,
                    key,
                    iops,
                    iops_avg,
                    job["lat_avg"],
                    job["iops_dispersion"] * 100,
                )
        # compare data
        unexpected_result = {}
        warning_result = {}
        for idx in range(len(results["images"]) - 1):
            obj1_name = results["images"][idx]
            obj2_name = results["images"][idx + 1]
            obj1_jobs = results[obj1_name]["jobs"]
            obj2_jobs = results[obj2_name]["jobs"]

            for key in obj1_jobs.keys():
                obj1_job = obj1_jobs[key]
                obj2_job = obj2_jobs[key]
                obj1_avg = obj1_job["iops_avg"]
                obj2_avg = obj2_job["iops_avg"]
                obj1_v = obj1_job["iops_dispersion"]
                obj2_v = obj2_job["iops_dispersion"]
                if (obj1_v > dispersion) or (obj2_v > dispersion):
                    logger.warning(
                        "Test result %s is unstable(>%s) %s:%s %s:%s",
                        key,
                        dispersion,
                        obj1_name,
                        obj1_v,
                        obj2_name,
                        obj2_v,
                    )
                gap = round(((obj2_avg - obj1_avg) / obj1_avg * 100), 1)
                ratio = round((obj1_avg / obj2_avg * 100), 1)
                logger.debug(
                    "%s-%s: %-20s: %-10s %-10s (ratio: %-5s%%) (gap: %-5s%%)",
                    obj1_name,
                    obj2_name,
                    key,
                    obj1_avg,
                    obj2_avg,
                    ratio,
                    gap,
                )

                if obj1_avg > obj2_avg:
                    r = (obj1_name, obj2_name, obj1_avg, obj2_avg)
                    rs = None
                    if obj1_avg > obj2_avg * (1 + error_threshold):
                        rs = unexpected_result
                    elif obj1_avg > obj2_avg * (1 + warn_threshold):
                        # warn threshold
                        rs = warning_result

                    if rs is not None:
                        if rs.get(key):
                            rs[key].append(r)
                        else:
                            rs[key] = [r]

        # final result
        if unexpected_result:
            test.fail("Get Unexpected: %s" % unexpected_result)
        if warning_result:
            logger.warning("Get Warning :%s", warning_result)

    def get_disk_iops(disk):
        cmd = host_test_cmd % disk
        logger.debug(cmd)
        cmd_output = process.getoutput(cmd)
        try:
            json_output = json.loads(cmd_output)
            job = json_output["jobs"][0]
            read = int(job["read"]["iops"])
            write = int(job["write"]["iops"])
            iops = read + write
            logger.debug("Find read:%s write:%s total:%s", read, write, iops)
            return iops
        except Exception as err:
            logger.error("Exception:%s %s", err, cmd_output)
            raise err

    def choose_fastest_disk(disks):
        logger.debug("Choose disk in: %s", disks)
        if len(disks) < 2:
            return disks[0]

        max_speed_disk = disks[0]
        max_speed = 0

        for disk in disks:
            iops = get_disk_iops(disk)
            logger.debug("Get speed on %s with %s", disk, iops)
            if iops > max_speed:
                max_speed = iops
                max_speed_disk = disk
        return max_speed_disk

    def check_host_iops(disk, iops_req):
        iops = get_disk_iops(disk)
        logger.debug("Checking performance %s : %s", iops, iops_req)
        if iops < iops_req:
            test.cancel("IO Performance is too low %s < %s" % (iops, iops_req))

    def process_selected_disk(disk):
        """format and mount disk"""
        out = process.getoutput("lsblk -s -p %s -O -J" % disk)
        out = json.loads(out)

        device = out["blockdevices"][0]
        if device.get("fstype"):
            logger.debug("%s fstype:%s", disk, device.get("fstype"))
        else:
            execute_operation("host", "mkfs.xfs -f %s " % disk)

        execute_operation("host", "mount %s %s && mount" % (disk, fio_dir))
        umount_cmd = "umount -fl %s;" % fio_dir
        params["post_command"] = umount_cmd + params.get("post_command", "")

    def auto_select_disk():
        """select empty disk"""
        if select_disk_request != "yes":
            return
        disks = []
        min_size = select_disk_minimum_size
        size_req = 1024 * 1024 * 1024 * min_size

        if select_disk_name:
            logger.debug("Checking specified disk:%s", select_disk_name)
            status_out = process.getstatusoutput("lsblk -p -O -J %s" % select_disk_name)
            if status_out[0] == 0:
                out = json.loads(status_out[1])
                disk = out["blockdevices"][0] if out["blockdevices"] else None
                if disk:
                    process_disk = True
                    if disk["fstype"] == "mpath_member":
                        process_disk = False
                        test.cancel("Please use mpath instead of raw device")
                    if disk.get("mountpoint") or (
                        disk.get("children") and disk["type"] != "mpath"
                    ):
                        process_disk = False
                        logger.debug(
                            "Skip %s due to mounted or not empty", select_disk_name
                        )
                    if process_disk:
                        return process_selected_disk(select_disk_name)
            else:
                logger.warning("Can not find disk:%s", select_disk_name)

        logger.debug("Start choosing disk ...")
        out = json.loads(process.getoutput("lsblk -p -b -O -J "))
        for disk in out["blockdevices"]:
            name = disk["name"]
            logger.debug(
                "Checking %s: type:%s fstype:%s", name, disk["type"], disk["fstype"]
            )
            if disk["type"] != "disk" and disk["type"] != "mpath":
                logger.debug("Skip %s the type:%s is not support", name, disk["type"])
                continue
            if disk.get("mountpoint"):
                logger.debug("Skip %s due to mounted or not empty", name)
                continue
            if int(disk.get("size")) < size_req:
                logger.debug("Skip %s due to size is too small", name)
                continue
            # check mpath
            if disk.get("children"):
                if disk["fstype"] != "mpath_member":
                    logger.debug("Skip %s due to not empty", name)
                    continue

            disk_add = True
            if disk["type"] == "disk" and disk["fstype"] == "mpath_member":
                # check potential mpath
                disk_add = False
                if len(disk.get("children")) == 1:
                    mpath = disk.get("children")[0]
                    if not mpath.get("mountpoint"):
                        name = mpath["name"]
                        disk_add = True
            if not disk_add:
                continue
            logger.debug("Find disk:%s", name)
            disks.append(name)

        if len(disks):
            disks.append(host_test_file)
            disks = list(set(disks))
            disk = choose_fastest_disk(disks)
            logger.debug("Choose disk %s", disk)
            if disk != host_test_file:
                process_selected_disk(disk)

    def host_func_demo():
        output = process.getoutput("echo 'hello host'", timeout=cmd_timeout)
        logger.debug("Execute host_func_test:output:\n%s", output)

    def guest_func_demo():
        output = session.cmd_output("echo 'hello guest'", timeout=cmd_timeout)
        logger.debug("Execute guest_func_test:output:\n%s", output)

    def check_default_mq():
        check_default_mq_cmd = params["check_default_mq_cmd"]
        dev = preprcess_fio_filename("stg2").replace("/dev", "")
        check_default_mq_cmd %= dev
        output = session.cmd_output(check_default_mq_cmd)
        logger.debug(output)
        output = output.split("\n")[0]

        default_mq_nums = len(re.split(r"[ ]+", output))
        if default_mq_nums != int(params["vcpu_maxcpus"]):
            test.fail(
                "Default num-queue value(%s) not equal vcpu nums(%s)"
                % (default_mq_nums, int(params["vcpu_maxcpus"]))
            )

    def execute_operation(where, cmd):
        # function
        if cmd in locals_var:
            logger.debug("Execute function %s", cmd)
            return locals_var[cmd]()
        # cmd line
        if where == "host":
            output = process.getoutput(cmd, timeout=cmd_timeout)
        else:
            output = session.cmd_output(cmd, timeout=cmd_timeout)
        logger.debug("Execute %s cmd %s:output:\n%s", where, cmd, output)

    logger = test.log
    os_type = params["os_type"]
    login_timeout = params.get_numeric("login_timeout", 360)
    guest_operation = params.get("guest_operation")
    fio_iteration_cmd = params.get("fio_iteration_cmd")
    fio_run_mode = params.get("fio_run_mode", "separate")
    fio_interval = params.get_numeric("fio_interval")
    cmd_timeout = params.get_numeric("fio_cmd_timeout", 1800)
    run_times = params.get_numeric("run_times", 1)
    fio_dir = params["fio_dir"]
    test_results = {}
    host_test_cmd = params["host_test_cmd"]
    host_test_file = fio_dir + "/test.img"
    check_host_iops_req = params.get_numeric("check_host_iops_req", 0)
    guest_init_operation = params.get("guest_init_operation")
    host_init_operation = params.get("host_init_operation")
    guest_deinit_operation = params.get("guest_deinit_operation")
    host_deinit_operation = params.get("host_deinit_operation")
    sampling_rate = params.get_numeric("sampling_rate", 0.8, float)
    dispersion = params.get_numeric("dispersion", 0.1, float)
    error_threshold = params.get_numeric("error_threshold", 0.1, float)
    warn_threshold = params.get_numeric("warn_threshold", 0.05, float)
    boot_wait_time = params.get_numeric("boot_wait_time", 60)
    select_disk_request = params.get("select_disk_request")
    select_disk_name = params.get("select_disk_name", "")
    select_disk_minimum_size = params.get_numeric("select_disk_minimum_size", 20)
    vm = None

    locals_var = locals()

    if host_init_operation:
        logger.debug("Execute host init :  %s", host_init_operation)
        execute_operation("host", host_init_operation)

    auto_select_disk()

    if check_host_iops_req > 0:
        check_host_iops(host_test_file, check_host_iops_req)

    if params["not_preprocess"] != "no":
        logger.debug("Ready boot VM : %s", params["images"])
        env_process.process(
            test, params, env, env_process.preprocess_image, env_process.preprocess_vm
        )

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    # Wait system init
    time.sleep(boot_wait_time)

    fio = generate_instance(params, vm, "fio")

    if guest_init_operation:
        logger.debug("Execute guest init: %s", guest_init_operation)
        execute_operation("guest", guest_init_operation)

    if guest_operation:
        logger.debug("Execute guest: %s", guest_operation)
        execute_operation("guest", guest_operation)

    preprocess_fio_data(test_results)
    run_fio_test(test_results)

    if guest_deinit_operation:
        logger.debug("Execute guest deinit : %s", guest_deinit_operation)
        execute_operation("guest", guest_deinit_operation)
    if host_deinit_operation:
        logger.debug("Execute host deinit: %s", host_deinit_operation)
        execute_operation("host", host_deinit_operation)

    compare_fio_result(test_results)
