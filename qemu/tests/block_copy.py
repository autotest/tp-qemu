import random
import re
import time

import six
from avocado.utils import process
from virttest import (
    data_dir,
    error_context,
    qemu_monitor,
    qemu_storage,
    storage,
    utils_misc,
)


def speed2byte(speed):
    """
    convert speed to Bytes/s
    """
    if str(speed).isdigit():
        speed = "%sB" % speed
    speed = utils_misc.normalize_data_size(speed, "B")
    return int(float(speed))


class BlockCopy(object):
    """
    Base class for block copy test;
    """

    default_params = {
        "cancel_timeout": 6,
        "wait_timeout": 600,
        "login_timeout": 360,
        "check_timeout": 3,
        "max_speed": 0,
        "default_speed": 0,
    }
    trash_files = []
    opening_sessions = []
    processes = []

    def __init__(self, test, params, env, tag):
        self.tag = tag
        self.env = env
        self.test = test
        self.params = params
        self.vm = self.get_vm()
        if self.vm.monitor.protocol != "qmp":
            self.test.cancel("hmp is not supported in this test.")
        self.data_dir = data_dir.get_data_dir()
        self.device = self.get_device()
        self.image_file = self.get_image_file()

    def parser_test_args(self):
        """
        parser test args, unify speed unit to B/s and set default values;
        """
        params = self.params.object_params(self.tag)
        for key, val in self.default_params.items():
            if not params.get(key):
                params[key] = val
            if key.endswith("timeout"):
                params[key] = float(params[key])
            if key.endswith("speed"):
                params[key] = speed2byte(params[key])
        return params

    def get_vm(self):
        """
        return live vm object;
        """
        vm = self.env.get_vm(self.params["main_vm"])
        if self.params.get("start_vm", "yes") == "yes":
            vm.verify_alive()
        return vm

    def get_device(self):
        """
        according configuration get target device ID;
        """
        image_file = storage.get_image_filename(self.parser_test_args(), self.data_dir)
        self.test.log.info("image filename: %s", image_file)
        return self.vm.get_block({"file": image_file})

    def get_session(self):
        """
        get a session object;
        """
        params = self.parser_test_args()
        session = self.vm.wait_for_login(timeout=params["login_timeout"])
        self.opening_sessions.append(session)
        return session

    def get_status(self):
        """
        return block job info dict;
        """
        count = 0
        while count < 10:
            try:
                return self.vm.get_job_status(self.device)
            except qemu_monitor.MonitorLockError as e:
                self.test.log.warning(e)
            time.sleep(random.uniform(1, 5))
            count += 1
        return {}

    def do_steps(self, tag=None):
        params = self.parser_test_args()
        try:
            for step in params.get(tag, "").split():
                if step and hasattr(self, step):
                    fun = getattr(self, step)
                    fun()
                else:
                    self.test.error("undefined step %s" % step)
        except KeyError:
            self.test.log.warning("Undefined test phase '%s'", tag)

    @error_context.context_aware
    def cancel(self):
        """
        cancel active job on given image;
        """

        def is_cancelled():
            ret = not bool(self.get_status())
            ret &= bool(self.vm.monitor.get_event("BLOCK_JOB_CANCELLED"))
            return ret

        error_context.context("cancel block copy job", self.test.log.info)
        params = self.parser_test_args()
        timeout = params.get("cancel_timeout")
        self.vm.monitor.clear_event("BLOCK_JOB_CANCELLED")
        self.vm.cancel_block_job(self.device)
        cancelled = utils_misc.wait_for(is_cancelled, timeout=timeout)
        if not cancelled:
            msg = "Cancel block job timeout in %ss" % timeout
            self.test.fail(msg)
        self.vm.monitor.clear_event("BLOCK_JOB_CANCELLED")

    def is_paused(self):
        """
        Return block job paused status.
        """
        paused, offset_p = self.paused_status()
        if paused:
            time.sleep(random.uniform(1, 3))
            paused_l, offset_l = self.paused_status()
            paused &= offset_p == offset_l and paused_l
        return paused

    def paused_status(self):
        """
        Get key value for pause status.
        """
        status = self.get_status()
        paused = status.get("paused") and not status.get("busy")
        offset = status.get("offset")
        return paused, offset

    def pause_job(self):
        """
        pause active job;
        """
        if self.is_paused():
            self.test.error("Job has been already paused.")
        self.test.log.info("Pause block job.")
        self.vm.pause_block_job(self.device)
        time.sleep(5)
        if not self.is_paused():
            self.test.fail("Pause block job failed.")

    def resume_job(self):
        """
        resume a paused job.
        """
        if not self.is_paused():
            self.test.error("Job is not paused, can't be resume.")
        self.test.log.info("Resume block job.")
        self.vm.resume_block_job(self.device)
        if self.is_paused():
            self.test.fail("Resume block job failed.")

    @error_context.context_aware
    def set_speed(self):
        """
        set limited speed for block job;
        """
        params = self.parser_test_args()
        max_speed = params.get("max_speed")
        expected_speed = int(params.get("expected_speed", max_speed))
        error_context.context(
            "set speed to %s B/s" % expected_speed, self.test.log.info
        )
        self.vm.set_job_speed(self.device, expected_speed)
        status = self.get_status()
        if not status:
            self.test.fail("Unable to query job status.")
        speed = status["speed"]
        if speed != expected_speed:
            msg = "Set speed fail. (expected speed: %s B/s," % expected_speed
            msg += "actual speed: %s B/s)" % speed
            self.test.fail(msg)

    @error_context.context_aware
    def reboot(self, method="shell", boot_check=True):
        """
        reboot VM, alias of vm.reboot();
        """
        error_context.context("reboot vm", self.test.log.info)
        params = self.parser_test_args()
        timeout = params["login_timeout"]

        if boot_check:
            session = self.get_session()
            return self.vm.reboot(session=session, timeout=timeout, method=method)
        error_context.context("reset guest via system_reset", self.test.log.info)
        self.vm.monitor.clear_event("RESET")
        self.vm.monitor.cmd("system_reset")
        reseted = utils_misc.wait_for(
            lambda: self.vm.monitor.get_event("RESET"), timeout=timeout
        )
        if not reseted:
            self.test.fail(
                "No RESET event received after" "execute system_reset %ss" % timeout
            )
        self.vm.monitor.clear_event("RESET")
        return None

    @error_context.context_aware
    def stop(self):
        """
        stop vm and verify it is really paused;
        """
        error_context.context("stop vm", self.test.log.info)
        self.vm.pause()
        return self.vm.verify_status("paused")

    @error_context.context_aware
    def resume(self):
        """
        resume vm and verify it is really running;
        """
        error_context.context("resume vm", self.test.log.info)
        self.vm.resume()
        return self.vm.verify_status("running")

    @error_context.context_aware
    def verify_alive(self):
        """
        check guest can response command correctly;
        """
        error_context.context("verify guest alive", self.test.log.info)
        params = self.parser_test_args()
        session = self.get_session()
        cmd = params.get("alive_check_cmd", "dir")
        return session.cmd(cmd, timeout=120)

    def get_image_file(self):
        """
        return file associated with device
        """
        blocks = self.vm.monitor.info("block")
        try:
            if isinstance(blocks, six.string_types):
                # ide0-hd0: removable=1 locked=0 file=/tmp/test.img
                image_regex = r"%s.*\s+file=(\S*)" % self.device
                image_file = re.findall(image_regex, blocks)
                if image_file:
                    return image_file[0]
                # ide0-hd0 (#block184): a b c
                # or
                # ide0-hd0 (#block184): a b c (raw)
                image_file = re.findall(r"%s[^:]+: ([^(]+)\(?" % self.device, blocks)
                if image_file:
                    if image_file[0][-1] == " ":
                        return image_file[0][:-1]
                    else:
                        return image_file[0]

            for block in blocks:
                if block["device"] == self.device:
                    return block["inserted"]["file"]
        except KeyError:
            self.test.log.warning("Image file not found for device '%s'", self.device)
            self.test.log.debug("Blocks info: '%s'", blocks)
        return None

    def get_backingfile(self, method="monitor"):
        """
        return backingfile of the device, if not return None;
        """
        if method == "monitor":
            return self.vm.monitor.get_backingfile(self.device)

        qemu_img = qemu_storage.QemuImg(self.params, self.data_dir, self.tag)
        qemu_img.image_filename = self.get_image_file()
        info = qemu_img.info(force_share=True)
        try:
            matched = re.search(r"backing file: +(.*)", info, re.M)
            return matched.group(1)
        except AttributeError:
            self.test.log.warning("No backingfile found, cmd output: %s", info)

    def action_before_start(self):
        """
        run steps before job in steady status;
        """
        return self.do_steps("before_start")

    def action_when_start(self):
        """
        start pre-action in new threads;
        """
        for test in self.params.get("when_start").split():
            if hasattr(self, test):
                fun = getattr(self, test)
                bg = utils_misc.InterruptedThread(fun)
                bg.start()
                if bg.is_alive():
                    self.processes.append(bg)

    def job_finished(self):
        """
        check if block job finished;
        """
        if self.get_status():
            return False
        return bool(self.vm.monitor.get_event("BLOCK_JOB_COMPLETED"))

    def wait_for_finished(self):
        """
        waiting until block job finished
        """
        time_start = time.time()
        params = self.parser_test_args()
        timeout = params.get("wait_timeout")
        finished = utils_misc.wait_for(self.job_finished, timeout=timeout)
        if not finished:
            self.test.fail("Job not finished in %s seconds" % timeout)
        time_end = time.time()
        self.test.log.info("Block job done.")
        return time_end - time_start

    def action_after_finished(self):
        """
        run steps after block job done;
        """
        params = self.parser_test_args()
        # if block job cancelled, no need to wait it;
        if params["wait_finished"] == "yes":
            self.wait_for_finished()
        return self.do_steps("after_finished")

    def is_steady(self):
        """
        check block job is steady status or not;
        """
        params = self.parser_test_args()
        info = self.get_status()
        ret = bool(info and info.get("ready") and not info.get("busy"))
        if params.get("check_event", "no") == "yes":
            ret &= bool(self.vm.monitor.get_event("BLOCK_JOB_READY"))
        return ret

    def wait_for_steady(self):
        """
        check block job status, utils timeout; if still not go
        into steady status, raise TestFail exception;
        """
        params = self.parser_test_args()
        timeout = params.get("wait_timeout")
        self.vm.monitor.clear_event("BLOCK_JOB_READY")
        steady = utils_misc.wait_for(
            self.is_steady, first=3.0, step=3.0, timeout=timeout
        )
        if not steady:
            self.test.fail("Wait mirroring job ready timeout in %ss" % timeout)

    def action_before_steady(self):
        """
        run steps before job in steady status;
        """
        return self.do_steps("before_steady")

    def action_when_steady(self):
        """
        run steps when job in steady status;
        """
        self.wait_for_steady()
        return self.do_steps("when_steady")

    def action_before_cleanup(self):
        """
        run steps before job in steady status;
        """
        return self.do_steps("before_cleanup")

    def clean(self):
        """
        close opening connections and clean trash files;
        """
        for bg in self.processes:
            bg.join()
        while self.opening_sessions:
            session = self.opening_sessions.pop()
            if session:
                session.close()
        if self.vm:
            self.vm.destroy()
        while self.trash_files:
            tmp_file = self.trash_files.pop()
            process.system("rm -f %s" % tmp_file, ignore_status=True)

    def create_file(self, file_name):
        """
        Create file and record m5 value of them.
        :param file_name: the file need to be created
        """
        params = self.params
        session = self.get_session()
        file_create_cmd = params.get("create_command", "touch FILE")
        file_create_cmd = utils_misc.set_winutils_letter(session, file_create_cmd)
        test_exists_cmd = params.get("test_exists_cmd", "test -f FILE")
        if session.cmd_status(test_exists_cmd.replace("FILE", file_name)):
            session.cmd(file_create_cmd.replace("FILE", file_name), timeout=200)
        session.cmd("md5sum %s > %s.md5" % (file_name, file_name), timeout=200)
        sync_cmd = params.get("sync_cmd", "sync")
        sync_cmd = utils_misc.set_winutils_letter(session, sync_cmd)
        session.cmd(sync_cmd)
        session.close()

    def verify_md5(self, file_name):
        """
        Check if the md5 value match the record, raise TestFail if not.
        :param file_name: the file need to be verified.
        """
        session = self.get_session()
        status, output = session.cmd_status_output(
            "md5sum -c %s.md5" % file_name, timeout=200
        )
        if status != 0:
            self.test.fail(
                "File %s changed, md5sum check output: %s" % (file_name, output)
            )

    def reopen(self, reopen_image):
        """
        Closing the vm and reboot it with the backup image.
        :param reopen_image: the image that vm reopen with.
        """
        self.vm.destroy()
        self.params["image_name_%s" % self.tag] = reopen_image
        self.vm.create(params=self.params)
        self.vm.verify_alive()

    def hot_unplug(self):
        """
        Host unplug the source image, check if device deleted and block job cancelled
        or completed, both results is acceptable per different qemu version.
        """
        job_cancelled_events = ["BLOCK_JOB_CANCELLED", "BLOCK_JOB_COMPLETED"]
        device_delete_event = ["DEVICE_DELETED"]
        for event in job_cancelled_events + device_delete_event:
            self.vm.monitor.clear_event(event)

        def is_unplugged():
            event_list = self.vm.monitor.get_events()
            self.test.log.debug("event_list: %s", event_list)
            device_deleted = job_cancelled = False
            for event_str in event_list:
                event = event_str.get("event")
                if event in device_delete_event:
                    device_deleted = True
                if event in job_cancelled_events:
                    job_cancelled = True
            return device_deleted and job_cancelled

        qdev = self.vm.devices
        device = qdev.get_by_params({"drive": self.device})
        if not device:
            self.test.fail("Device does not exist.")
        self.test.log.info("Hot unplug device %s", self.device)
        qdev.simple_unplug(device[0], self.vm.monitor)
        timeout = self.params.get("cancel_timeout", 10)
        unplugged = utils_misc.wait_for(is_unplugged, timeout=timeout)
        if not unplugged:
            self.test.fail("Unplug timeout in %ss" % timeout)

    def create_files(self):
        """
        Create files and record m5 values of them.
        """
        file_names = self.params["file_names"].split()
        for name in file_names:
            self.create_file(name)

    def verify_md5s(self):
        """
        Check if the md5 values matches the record ones.
        """
        file_names = self.params["file_names"].split()
        for name in file_names:
            self.verify_md5(name)
