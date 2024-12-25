from virttest import utils_misc, utils_qemu, utils_version
from virttest.qemu_devices import qdevices

from provider import backup_utils

from . import virt_encryption


class StorageVolume(object):
    def __init__(self, pool):
        self.name = None
        self.pool = pool
        self._url = None
        self._path = None
        self._capacity = None
        self._key = None
        self._auth = None
        self._format = None
        self._protocol = None
        self.is_allocated = None
        self.preallocation = None
        self.backing = None
        self.encrypt = None
        self.used_by = []
        self._params = None
        # After qemu 9.0.0, raw format node is eliminated by default, but
        # it's still safe to keep it, so the init value is set to False
        self._no_raw_format_node = False
        self.pool.add_volume(self)

    @property
    def url(self):
        if self._url is None:
            if self.name and hasattr(self.pool.helper, "get_url_by_name"):
                url = self.pool.helper.get_url_by_name(self.name)
                self._url = url
        return self._url

    @url.setter
    def url(self, url):
        self._url = url

    @property
    def path(self):
        if self._path is None:
            if self.url and hasattr(self.pool.helper, "url_to_path"):
                path = self.pool.helper.url_to_path(self.url)
                self._path = path
        return self._path

    @path.setter
    def path(self, path):
        self._path = path

    @property
    def key(self):
        if self._key is None:
            if self.pool.TYPE in ("directory", "nfs"):
                self._key = self.path
            else:
                self._key = self.url
        return self._key

    @key.setter
    def key(self, key):
        self._key = key

    @property
    def format(self):
        if self._format is None:
            self._format = qdevices.QBlockdevFormatQcow2(self.name)
        return self._format

    @format.setter
    def format(self, format):
        if format == "qcow2":
            format_cls = qdevices.QBlockdevFormatQcow2
        else:
            format_cls = qdevices.QBlockdevFormatRaw
        self._format = format_cls(self.name)

    @property
    def protocol(self):
        if self._protocol is None:
            if self.pool.TYPE == "directory":
                self._protocol = qdevices.QBlockdevProtocolFile(self.name)
            elif self.pool.TYPE == "rbd":
                self._protocol = qdevices.QBlockdevProtocolRBD(self.name)
            else:
                raise NotImplementedError
        return self._protocol

    @property
    def capacity(self):
        if self._capacity is None:
            if self.key and hasattr(self.pool.helper, "get_size"):
                self._capacity = self.pool.get_size(self.key)
        if self._capacity is None:
            self._capacity = 0
        return int(self._capacity)

    @capacity.setter
    def capacity(self, size):
        self._capacity = float(utils_misc.normalize_data_size(str(size), "B", "1024"))

    @property
    def auth(self):
        if self._auth is None:
            if self.pool.source:
                self._auth = self.pool.source.auth
        return self._auth

    @property
    def raw_format_node_eliminated(self):
        return self._no_raw_format_node

    @raw_format_node_eliminated.setter
    def raw_format_node_eliminated(self, flag):
        self._no_raw_format_node = flag

    def refresh_with_params(self, params):
        if params.get("image_format") == "raw":
            qemu_binary = utils_misc.get_qemu_binary(params)
            qemu_version = utils_qemu.get_qemu_version(qemu_binary)[0]
            if qemu_version in utils_version.VersionInterval(
                backup_utils.BACKING_MASK_PROTOCOL_VERSION_SCOPE
            ):
                self.raw_format_node_eliminated = True

        self._params = params
        self.capacity = params.get("image_size", "100M")
        self.preallocation = params.get("preallocation", "off")
        self.refresh_protocol_by_params(params)

        if not self.raw_format_node_eliminated:
            self.format = params.get("image_format", "qcow2")
            self.refresh_format_by_params(params)

        if self.pool.TYPE == "directory":
            volume_params = params.object_params(self.name)
            self.path = self.pool.get_volume_path_by_param(volume_params)
        elif self.pool.TYPE == "rbd":
            volume_params = params.object_params(self.name)
            self.path = self.pool.get_volume_path_by_param(volume_params)
        else:
            raise NotImplementedError

    def refresh_format_by_params(self, params):
        if self.format.TYPE == "qcow2":
            encrypt = params.get("image_encryption")
            if encrypt and encrypt != "off":
                self.encrypt = (
                    virt_encryption.VolumeEncryption.encryption_define_by_params(params)
                )
                self.format.set_param("encrypt.key-secret", self.encrypt.secret.name)
                self.format.set_param("encrypt.format", self.encrypt.format)

            backing = params.get("backing")
            if backing:
                if params.get("backing_null", "no") == "no":
                    backing_node = "drive_%s" % backing
                    self.format.set_param("backing", backing_node)
                else:
                    self.format.params["backing"] = None

            data_file_name = params.get("image_data_file")
            if data_file_name:
                data_file_node = "drive_%s" % data_file_name
                self.format.set_param("data-file", data_file_node)
        self.format.set_param("file", self.protocol.get_param("node-name"))

        # keep the same setting with libvirt when blockdev-add a format node
        readonly = params.get("image_readonly", "off")
        self.format.set_param("read-only", readonly)

        # Add the protocol node as its child node
        if self.protocol not in self.format.get_child_nodes():
            self.format.add_child_node(self.protocol)

    def refresh_protocol_by_params(self, params):
        if self.protocol.TYPE == "file":
            aio = params.get("image_aio", "threads")
            self.protocol.set_param("filename", self.path)
            self.protocol.set_param("aio", aio)
        elif self.protocol.TYPE == "rbd":
            self.protocol.set_param("pool", self.pool.source.pool_name)
            image_name = self.path.split("/")[-1]
            self.protocol.set_param("image", image_name)
        else:
            raise NotImplementedError

        # keep the same setting with libvirt when blockdev-add a protocol node
        auto_readonly = params.get("image_auto_readonly", "on")
        discard = params.get("image_discard_request", "unmap")
        self.protocol.set_param("auto-read-only", auto_readonly)
        self.protocol.set_param("discard", discard)
        # image_aio:native requires cache.direct:on
        if params.get("image_aio") == "native":
            self.protocol.set_param("cache.direct", "on")
            self.protocol.set_param("cache.no-flush", "off")

    def info(self):
        out = dict()
        out["name"] = self.name
        out["pool"] = str(self.pool)
        out["url"] = self.url
        out["path"] = self.path
        out["key"] = self.key
        # __hash__ uses it when adding a volume object
        out["format"] = (
            self._params.get("image_format", "qcow2") if self._params else None
        )
        out["auth"] = str(self.auth)
        out["capacity"] = self.capacity
        out["preallocation"] = self.preallocation
        out["backing"] = str(self.backing)
        return out

    def generate_qemu_img_options(self):
        fmt = self._params.get("image_format", "qcow2")
        options = f" -f {fmt}"

        if fmt == "qcow2":
            backing_store = self.backing
            if backing_store:
                options += " -b %s" % backing_store.key
            encrypt = self.format.get_param("encrypt")
            if encrypt:
                secret = encrypt.secret
                options += " -%s " % secret.as_qobject().cmdline()
                options += " -o encrypt.format=%s,encrypt.key-secret=%s" % (
                    encrypt.format,
                    secret.name,
                )
        return options

    def hotplug(self, vm):
        if not self.pool.is_running():
            self.pool.start_pool()
        protocol_node = self.protocol
        self.create_protocol_by_qmp(vm)
        cmd, options = protocol_node.hotplug_qmp()
        vm.monitor.cmd(cmd, options)

        if not self.raw_format_node_eliminated:
            format_node = self.format
            # Don't need the format blockdev-create for 'raw'
            if self.format.TYPE != "raw":
                self.format_protocol_by_qmp(vm)
            cmd, options = format_node.hotplug_qmp()
            vm.monitor.cmd(cmd, options)

        self.pool.refresh()

    def create_protocol_by_qmp(self, vm, timeout=120):
        node_name = self.protocol.get_param("node-name")
        options = {"driver": self.protocol.TYPE}
        if self.protocol.TYPE == "file":
            options["filename"] = self.protocol.get_param("filename")
            options["size"] = self.capacity
        elif self.protocol.TYPE == "rbd":
            location = {}
            location["pool"] = self.protocol.get_param("pool")
            location["image"] = self.protocol.get_param("image")
            options["location"] = location
            options["size"] = self.capacity
        else:
            raise NotImplementedError
        arguments = {"options": options, "job-id": node_name, "timeout": timeout}
        return backup_utils.blockdev_create(vm, **arguments)

    def format_protocol_by_qmp(self, vm, timeout=120):
        node_name = self.format.get_param("node-name")
        options = {
            "driver": self.format.TYPE,
            "file": self.protocol.get_param("node-name"),
            "size": self.capacity,
        }
        if self.format.TYPE == "qcow2":
            if self.backing:
                options["backing-fmt"] = self.backing.format.TYPE
                options["backing-file"] = self.backing.path
            if self.encrypt:
                options["encrypt"] = dict()
                key_secret = self.format.get_param("encrypt.key-secret")
                if key_secret:
                    options["encrypt"]["key-secret"] = key_secret
                encrypt_format = self.format.get_param("encrypt.format")
                if encrypt_format:
                    options["encrypt"]["format"] = encrypt_format
            if self._params and self._params.get("image_cluster_size"):
                options["cluster-size"] = int(self._params["image_cluster_size"])
            if self._params.get("image_data_file"):
                options["data-file"] = self.format.get_param("data-file")
                data_file_raw_set = self._params.get("image_data_file_raw")
                data_file_raw = data_file_raw_set in ("on", "yes", "true")
                options["data-file-raw"] = data_file_raw
        arguments = {"options": options, "job-id": node_name, "timeout": timeout}
        backup_utils.blockdev_create(vm, **arguments)

    def __str__(self):
        return "%s-%s(%s)" % (self.__class__.__name__, self.name, str(self.key))

    def __eq__(self, vol):
        if not isinstance(vol, StorageVolume):
            return False
        else:
            return self.info() == vol.info()

    def __hash__(self):
        return hash(str(self.info()))

    def __repr__(self):
        return "'%s'" % self.name

    def as_json(self):
        if not self.raw_format_node_eliminated:
            _, options = self.format.hotplug_qmp()
        else:
            _, options = self.protocol.hotplug_qmp()

        return "json: %s" % options
