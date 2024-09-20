import socket

from avocado.utils import process
from virttest import data_dir, error_context, qemu_storage, storage, utils_misc

from provider.nbd_image_export import QemuNBDExportImage


@error_context.context_aware
def run(test, params, env):
    """
    1) Create a local file by echo command
    2) Export the file in raw format with qemu-nbd
    3) Access the exported nbd file by qemu-io

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _prepare():
        tag = params["local_image_tag"]
        image_params = params.object_params(tag)

        if image_params.get("create_description_cmd"):
            params["nbd_export_description_%s" % tag] = (
                process.run(
                    image_params["create_description_cmd"],
                    ignore_status=True,
                    shell=True,
                )
                .stdout.decode()
                .strip()
            )

        if image_params.get("create_image_cmd"):
            params["create_image_cmd_%s" % tag] = image_params[
                "create_image_cmd"
            ].format(
                desc=params["nbd_export_description_%s" % tag],
                filename=storage.get_image_filename(
                    image_params, data_dir.get_data_dir()
                ),
            )

        # update nbd image's server to the local host
        localhost = socket.gethostname()
        params["nbd_server_%s" % params["nbd_image_tag"]] = (
            localhost if localhost else "localhost"
        )

    def _get_tls_creds_obj(tag, params):
        tls_str = "--object tls-creds-x509,id={t.aid},endpoint=client,dir={t.tls_creds}"
        tls = storage.StorageAuth.auth_info_define_by_params(tag, params)
        return tls_str.format(t=tls) if tls else ""

    def _get_secret_obj(tag, params):
        secret_str = "--object secret,id={s.aid},data={s.data}"
        secret = storage.ImageSecret.image_secret_define_by_params(tag, params)
        return secret_str.format(s=secret) if secret else ""

    def _make_qemu_io_cmd():
        nbd_image = params["nbd_image_tag"]
        nbd_image_params = params.object_params(nbd_image)

        nbd_image_filename = storage.get_image_filename(nbd_image_params, None)
        nbd_image_format = "-f %s" % nbd_image_params["image_format"]

        tls_obj = _get_tls_creds_obj(nbd_image, nbd_image_params)
        sec_obj = _get_secret_obj(nbd_image, nbd_image_params)
        if tls_obj or sec_obj:
            nbd_image_format = ""
            nbd_image_filename = "'%s'" % qemu_storage.get_image_json(
                nbd_image, nbd_image_params, None
            )

        qemu_io = utils_misc.get_qemu_io_binary(params)
        return params["qemu_io_cmd"].format(
            qemu_io=qemu_io,
            tls_creds=tls_obj,
            secret=sec_obj,
            fmt=nbd_image_format,
            subcmd=params["qemu_io_subcmd"],
            filename=nbd_image_filename,
        )

    _prepare()

    nbd_export = QemuNBDExportImage(params, params["local_image_tag"])
    nbd_export.create_image()
    nbd_export.export_image()

    qemu_io_cmd = _make_qemu_io_cmd()

    try:
        result = process.run(qemu_io_cmd, ignore_status=True, shell=True)
        if result.exit_status != 0:
            test.fail("Failed to execute qemu-io, error: %s" % result.stderr.decode())

        if params.get("msg_check"):
            if params["msg_check"] not in result.stdout.decode().strip():
                test.fail(
                    "Failed to read message(%s) from output(%s)"
                    % (params["msg_check"], result.stderr.decode())
                )

        nbd_export.list_exported_image(
            params["nbd_image_tag"], params.object_params(params["nbd_image_tag"])
        )
    finally:
        nbd_export.stop_export()
