import logging
import re
import time

from avocado.utils import process
from virttest import data_dir, env_process, error_context, utils_misc
from virttest.utils_windows import wmic

from qemu.tests.qemu_guest_agent import QemuGuestAgentBasicCheckWin

LOG_JOB = logging.getLogger("avocado.test")


class QemuGuestAgentUpdateTest(QemuGuestAgentBasicCheckWin):
    @error_context.context_aware
    def gagent_check_pkg_update(self, test, params, env):
        """
        Update qemu-ga-win pkg.

        steps:
            1)boot up guest.
            2)install the previous qemu-ga in guest.
                a.for virtio-win method,change to download iso.
                b.for url method,need to find the previous version and get
                the download cmd.
            3)update to the latest one.
            4)qemu-ga basic test.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """

        def _change_agent_media(cdrom_virtio):
            """
            Only for virtio-win method,change virtio-win iso.

            :param cdrom_virtio: iso file
            """
            LOG_JOB.info("Change cdrom to %s", cdrom_virtio)
            virtio_iso = utils_misc.get_path(data_dir.get_data_dir(), cdrom_virtio)
            vm.change_media("drive_virtio", virtio_iso)

            LOG_JOB.info("Wait until device is ready")
            vol_virtio_key = "VolumeName like '%virtio-win%'"
            timeout = 10
            end_time = time.time() + timeout
            while time.time() < end_time:
                time.sleep(2)
                virtio_win_letter = utils_misc.get_win_disk_vol(session, vol_virtio_key)
                if virtio_win_letter:
                    break
            if not virtio_win_letter:
                test.fail("Couldn't get virtio-win volume letter.")

        def _get_pkg_download_cmd():
            """
            Only for url method to get the previous qemu-ga version and get the
            download cmd for this pkg.
            """
            qga_html = "/tmp/qemu-ga.html"
            qga_url = params["qga_url"]
            qga_html_download_cmd = "wget %s -O %s" % (qga_url, qga_html)
            process.system(
                qga_html_download_cmd, float(params.get("login_timeout", 360))
            )

            with open(qga_html, "r") as f:
                lines = f.readlines()
            list_qga = []
            for line in lines:
                if "qemu-ga-win" in line:
                    list_qga.append(line)
            tgt_line = list_qga[-2]
            # qemu-ga-win-7.5.0-2.el7ev
            qga_pattern = re.compile(r"%s" % params["qga_pattern"])
            qga_pre_pkg = qga_pattern.findall(tgt_line)[0]
            LOG_JOB.info("The previous qemu-ga version is %s.", qga_pre_pkg)

            # https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/
            #   archive-qemu-ga/qemu-ga-win-7.5.0-2.el7ev/
            qga_url_pre = r"%s/%s/%s" % (qga_url, qga_pre_pkg, self.qemu_ga_pkg)
            qga_host_path = params["gagent_host_path"]
            params["gagent_download_cmd"] = "wget %s -O %s" % (
                qga_url_pre,
                qga_host_path,
            )

        def _qga_install():
            """
            Install qemu-ga pkg.
            """
            qga_pkg_path = self.get_qga_pkg_path(
                self.qemu_ga_pkg, test, session, params, vm
            )
            self.gagent_install_cmd = params.get("gagent_install_cmd") % qga_pkg_path
            self.gagent_install(session, vm)

        error_context.context("Boot up vm.", LOG_JOB.info)
        params["start_vm"] = "yes"
        latest_qga_download_cmd = params["gagent_download_cmd"]
        env_process.preprocess_vm(test, params, env, params["main_vm"])
        vm = self.env.get_vm(params["main_vm"])
        session = self._get_session(params, vm)

        if params.get("driver_uninstall", "no") == "yes":
            error_context.context("Uninstall vioser driver in guest.", LOG_JOB.info)
            device_name = params["device_name"]
            driver_name = params["driver_name"]
            inf_names_get_cmd = wmic.make_query(
                "path win32_pnpsigneddriver",
                "DeviceName like '%s'" % device_name,
                props=["InfName"],
                get_swch=wmic.FMT_TYPE_LIST,
            )
            inf_names = wmic.parse_list(session.cmd(inf_names_get_cmd, timeout=360))
            for inf_name in inf_names:
                pnp_cmd = "pnputil /delete-driver %s /uninstall /force"
                uninst_store_cmd = params.get("uninst_store_cmd", pnp_cmd) % inf_name
                s, o = session.cmd_status_output(uninst_store_cmd, 360)
                if s not in (0, 3010):
                    # for vioser, they need system reboot
                    # acceptable status: OK(0), REBOOT(3010)
                    test.error(
                        "Failed to uninstall driver '%s' from store, "
                        "details:\n%s" % (driver_name, o)
                    )

        error_context.context("Install the previous qemu-ga in guest.", LOG_JOB.info)
        gagent_download_url = params["gagent_download_url"]
        rpm_install = "rpm_install" in gagent_download_url
        if self._check_ga_pkg(session, params["gagent_pkg_check_cmd"]):
            LOG_JOB.info("Uninstall the one which is installed.")
            self.gagent_uninstall(session, vm)

        if self.gagent_src_type == "virtio-win" or rpm_install:
            _change_agent_media(params["cdrom_virtio_downgrade"])
        elif self.gagent_src_type == "url":
            _get_pkg_download_cmd()
        else:
            self.test.error("Only support 'url' and 'virtio-win' method.")

        _qga_install()

        error_context.context("Update qemu-ga to the latest one.", LOG_JOB.info)
        if self.gagent_src_type == "virtio-win" or rpm_install:
            _change_agent_media(params["cdrom_virtio"])
        else:
            params["gagent_download_cmd"] = latest_qga_download_cmd

        _qga_install()

        error_context.context("Basic test for qemu-ga.", LOG_JOB.info)
        args = [params.get("gagent_serial_type"), params.get("gagent_name")]
        self.gagent_create(params, vm, *args)
        self.gagent_verify(params, vm)


def run(test, params, env):
    """
    Update qemu-ga-win installer.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    gagent_test = QemuGuestAgentUpdateTest(test, params, env)
    gagent_test.execute(test, params, env)
