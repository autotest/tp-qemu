import json
import re

from virttest import data_dir, qemu_storage


def run(test, params, env):
    """
    Luks key management by qemu-img amend command
    1. Create a luks image
    2. (1) Add a new password to a free keyslot (with_specified_index 1)
       e.g. qemu-img amend --object secret,id=sec0,data=redhat
            --object secret,id=sec1,data=amend
            -o keyslot=1,state=active,new-secret=sec1
            'json:{"file": {"driver": "file", "filename": "stg.luks"},
            "driver": "luks", "key-secret": "sec0"}'
       (2) check slots -> active is True
    3. (1) Add a new password to a free keyslot (not setting keyslot index)
       e.g qemu-img amend --object secret,id=sec0,data=redhat
            --object secret,id=sec1,data=amend
            -o state=active,new-secret=sec1
            'json:{"file": {"driver": "file", "filename": "stg.luks"},
            "driver": "luks", "key-secret": "sec0"}'
       (2) check slots -> active is True
    4. Negative test, overwrite active keyslot 0
    5. Negative test, add a new password to invalid keyslot 8
       It must be between 0 and 7
    6. (1) Erase password from keyslot by giving a keyslot index
       in this case, adding a password to keyslot 7 and then erase it
       e.g. qemu-img amend --object secret,id=sec0,data=redhat
            --object secret,id=sec1,data=amend
            -o state=inactive,keyslot=7
            'json:{"file": {"driver": "file", "filename": "base.luks"},
            "driver": "luks", "key-secret": "sec0"}'
       (2) check slots -> active is False
    7. (1) Erase password from keyslot by giving the password
       in this case, adding a password to keyslot 7 and then erase it
       e.g. qemu-img amend --object secret,id=sec0,data=redhat
            --object secret,id=sec1,data=amend
            -o state=inactive,old-secret=sec1
            'json:{"file": {"driver": "file", "filename": "base.luks"},
            "driver": "luks", "key-secret": "sec0"}'
       (2) check slots -> active is False
    8. Negative test, erase the only active keyslot 0

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    err_info = params.get("err_info")
    root_dir = data_dir.get_data_dir()
    stg = params["images"]
    stg_params = params.object_params(stg)
    stg_img = qemu_storage.QemuImg(stg_params, root_dir, stg)
    stg_img.create(stg_params)

    erase_password = params.get("erase_password")
    if erase_password:
        # add a new password to keyslot and then erase it
        stg_img.amend(stg_params, ignore_status=True)

        # for luks-insied-qcow2, prefixed with encrypt.
        # e.g. amend_encrypt.state = inactive
        # luks likes amend_state = inactive
        encrypt = "encrypt." if stg_img.image_format == "qcow2" else ""
        stg_params.pop("amend_%snew-secret" % encrypt)
        stg_params["amend_%sstate" % encrypt] = "inactive"
        if erase_password == "password":
            stg_params.pop("amend_%skeyslot" % encrypt)
            stg_params["amend_%sold-secret" % encrypt] = stg_params["amend_secret_id"]

    cmd_result = stg_img.amend(stg_params, ignore_status=True)
    if err_info:
        if not re.search(err_info, cmd_result.stderr.decode(), re.I):
            test.fail(
                "Failed to get error information. The actual error "
                "information is %s." % cmd_result.stderr.decode()
            )
    elif cmd_result.exit_status != 0:
        test.fail(
            "Failed to amend image %s. The error information is "
            "%s." % (stg_img.image_filename, cmd_result.stderr.decode())
        )
    else:
        info = json.loads(stg_img.info(output="json"))
        if stg_img.image_format == "qcow2":
            key_state = stg_params["amend_encrypt.state"]
            key_slot = params.get_numeric("amend_encrypt.keyslot", 1)
            state = info["format-specific"]["data"]["encrypt"]["slots"][key_slot][
                "active"
            ]
        else:
            key_state = stg_params["amend_state"]
            key_slot = params.get_numeric("amend_keyslot", 1)
            state = info["format-specific"]["data"]["slots"][key_slot]["active"]
        key_state = True if key_state == "active" else False
        if key_state != state:
            test.fail("The key state is %s, it should be %s." % (state, key_state))
