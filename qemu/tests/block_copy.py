import time
import random
import logging

from avocado.utils import process

from virttest import data_dir
from virttest import error_context
from virttest import utils_misc
from virttest import utils_test
from virttest import qemu_monitor
from virttest import qemu_storage


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
    default_params = {"cancel_timeout": 6,
                      "wait_timeout": 600,
                      "login_timeout": 360,
                      "check_timeout": 3,
                      "max_speed": 0,
                      "default_speed": 0}
    trash_files = []
    opening_sessions = []
    processes = []

    def __init__(self, test, params, env, tag):
        self.tag = tag
        self.env = env
        self.test = test
        self.params = params
        self.device = "drive_%s" % tag
        self.data_dir = data_dir.get_data_dir()
        self.vm = self.get_vm()
        self.image_file = self.get_image_file()
        self.job_id = None

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

    def get_session(self):
        """
        get a session object;
        """
        count = 0
        params = self.parser_test_args()
        while count < len(self.opening_sessions):
            session = self.opening_sessions[count]
            if session.is_responsive():
                return session
            session.close()
            self.opening_sessions.pop(count)
            count += 1
            continue
        timeout = params["login_timeout"]
        session = self.vm.wait_for_login(timeout=timeout)
        self.opening_sessions.append(session)
        return session

    def get_status(self):
        """
        return block job info dict;
        """
        def _get_status():
            try:
                return self.vm.get_job_status(self.device)
            except qemu_monitor.MonitorLockError:
                pass
            return dict()

        ret = utils_misc.wait_for(_get_status, timeout=120, step=0.1)
        return dict() if ret is None else ret

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
            logging.warn("Undefined test phase '%s'" % tag)

    def is_cancelled(self, job_id=None):
        if not job_id:
            job_id = self.job_id
        if not job_id:
            return bool(self.vm.monitor.get_event_by_id(
                "BLOCK_JOB_CANCELLED", job_id))
        return not bool(self.get_status())

    @error_context.context_aware
    def cancel(self):
        """
        cancel active job on given image;
        """
        error_context.context("cancel block copy job", logging.info)
        params = self.parser_test_args()
        timeout = params.get("cancel_timeout")
        self.vm.cancel_block_job(self.device)
        cancelled = utils_misc.wait_for(self.is_cancelled, timeout=timeout)
        assert cancelled, "Cancel block job timeout in %ss" % timeout

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
        logging.info("Pause block job.")
        self.vm.pause_block_job(self.device)
        time.sleep(0.5)
        assert self.is_paused(), "Job on device '%s' is not paused" % self.device

    def resume_job(self):
        """
        resume a paused job.
        """
        logging.info("Resume block job.")
        self.vm.resume_block_job(self.device)
        assert not self.is_paused(), "Job on device '%s' is not running" % self.device

    @error_context.context_aware
    def set_speed(self):
        """
        set limited speed for block job;
        """
        params = self.parser_test_args()
        max_speed = params.get("max_speed")
        expected_speed = int(params.get("expected_speed", max_speed))
        error_context.context("set speed to %s B/s" % expected_speed,
                              logging.info)
        self.vm.set_job_speed(self.device, expected_speed)
        speed = int(self.get_status()["speed"])
        msg = "Unexpect job speed %s, expect is %s" % (speed, expected_speed)
        assert speed == expected_speed, msg

    @error_context.context_aware
    def reboot(self):
        """
        reboot VM, alias of vm.reboot();
        """
        error_context.context("reboot vm", logging.info)
        params = self.parser_test_args()
        timeout = params["login_timeout"]
        method = params.get("reboot_method", "shell")
        session = self.get_session()
        session = self.vm.reboot(
            session=session,
            timeout=timeout,
            method=method)
        self.opening_sessions.append(session)

    @error_context.context_aware
    def stop(self):
        """
        stop vm and verify it is really paused;
        """
        error_context.context("stop vm", logging.info)
        self.vm.pause()
        return self.vm.verify_status("paused")

    @error_context.context_aware
    def resume(self):
        """
        resume vm and verify it is really running;
        """
        error_context.context("resume vm", logging.info)
        self.vm.resume()
        return self.vm.verify_status("running")

    @error_context.context_aware
    def verify_alive(self):
        """
        check guest can response command correctly;
        """
        error_context.context("verify guest alive", logging.info)
        params = self.parser_test_args()
        session = self.get_session()
        cmd = params.get("alive_check_cmd", "dir")
        return session.cmd(cmd, timeout=120)

    def get_image_file(self):
        """
        return file associated with device
        """
        return qemu_storage.QemuImg(
            self.params, self.data_dir, self.tag).image_filename

    def get_backingfile(self, method="monitor"):
        """
        return backingfile of the device, if not return None;
        """
        return self.vm.monitor.get_backingfile(self.device)

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
                func = getattr(self, test)
                bg = utils_test.BackgroundTest(func, ())
                bg.start()
                if bg.is_alive():
                    self.processes.append(bg)

    def job_finished(self):
        """
        check if block job finished;
        """
        event = "BLOCK_JOB_COMPLETED"
        job_id = self.job_id or self.device
        return self.vm.monitor.get_event_by_id(event, job_id)

    def wait_for_finished(self):
        """
        waiting until block job finished
        """
        params = self.parser_test_args()
        timeout = params.get("wait_timeout")
        utils_misc.wait_for(self.job_finished, timeout=timeout)

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
        return bool(self.vm.monitor.get_event_by_id(
            "BLOCK_JOB_READY", self.job_id))

    def wait_for_steady(self):
        """
        check block job status, utils timeout; if still not go
        into steady status, raise TestFail exception;
        """
        params = self.parser_test_args()
        timeout = params.get("wait_timeout")
        steady = utils_misc.wait_for(self.is_steady, timeout=timeout)
        message = "Wait job to steady timeout in '%s' seconds" % timeout
        assert steady, message

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
        for vm in self.env.get_all_vms():
            if vm.is_alive():
                vm.destroy()
            time.sleep(1)
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
        file_create_cmd = utils_misc.set_winutils_letter(
            session, file_create_cmd)
        test_exists_cmd = params.get("test_exists_cmd", "test -f FILE")
        if session.cmd_status(test_exists_cmd.replace("FILE", file_name)):
            session.cmd(
                file_create_cmd.replace(
                    "FILE",
                    file_name),
                timeout=200)
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
        status, output = session.cmd_status_output("md5sum -c %s.md5" % file_name,
                                                   timeout=200)
        if status != 0:
            self.test.fail("File %s changed, md5sum check output: %s"
                           % (file_name, output))

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
            logging.debug("event_list: %s" % event_list)
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
        logging.info("Hot unplug device %s" % self.device)
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

    @error_context.context_aware
    def create_snapshots(self):
        """
        create live snapshot_chain, snapshots chain define in $snapshot_chain
        """
        kwargs = dict()
        params = self.parser_test_args()
        if params.get("snapshot_format"):
            kwargs["format"] = params["snapshot_format"]
        if params.get("snapshot_create_mode"):
            kwargs["mode"] = params["snapshot_create_mode"]
        snapshot_chain = params["snapshot_chain"].split()
        error_context.context("create live snapshots", logging.info)
        image_dir = utils_misc.get_path(self.data_dir, "images")
        snapshot_files = [
            utils_misc.get_path(
                image_dir,
                f) for f in snapshot_chain]
        for index, snapshot_file in enumerate(snapshot_files):
            base_file = (
                index and [snapshot_files[index - 1]] or [self.image_file])[0]
            self.vm.live_snapshot(
                self.device,
                base_file,
                snapshot_file,
                **kwargs)
        self.trash_files.extend(snapshot_files)
