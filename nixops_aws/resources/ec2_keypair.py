# -*- coding: utf-8 -*-

# Automatic provisioning of EC2 key pairs.

import nixops.util
import nixops.resources
import nixops_aws.ec2_utils
from nixops_aws.backends import ec2

from .types.ec2_keypair import Ec2KeypairOptions


class EC2KeyPairDefinition(nixops.resources.ResourceDefinition):
    """Definition of an EC2 key pair."""

    config: Ec2KeypairOptions

    @classmethod
    def get_type(cls):
        return "ec2-keypair"

    @classmethod
    def get_resource_type(cls):
        return "ec2KeyPairs"

    def __init__(self, name: str, config: nixops.resources.ResourceEval):
        nixops.resources.ResourceDefinition.__init__(self, name, config)
        self.keypair_name = self.config.name
        self.region = self.config.region
        self.access_key_id = self.config.accessKeyId

    def show_type(self):
        return "{0} [{1}]".format(self.get_type(), self.region)


class EC2KeyPairState(nixops.resources.ResourceState[EC2KeyPairDefinition]):
    """State of an EC2 key pair."""

    state = nixops.util.attr_property(
        "state", nixops.resources.ResourceState.MISSING, int
    )
    keypair_name = nixops.util.attr_property("ec2.keyPairName", None)
    public_key = nixops.util.attr_property("publicKey", None)
    private_key = nixops.util.attr_property("privateKey", None)
    access_key_id = nixops.util.attr_property("ec2.accessKeyId", None)
    region = nixops.util.attr_property("ec2.region", None)

    @classmethod
    def get_type(cls):
        return "ec2-keypair"

    def __init__(self, depl, name, id):
        nixops.resources.ResourceState.__init__(self, depl, name, id)
        self._conn = None

    def show_type(self):
        s = super(EC2KeyPairState, self).show_type()
        if self.region:
            s = "{0} [{1}]".format(s, self.region)
        return s

    @property
    def resource_id(self):
        return self.keypair_name

    def get_definition_prefix(self):
        return "resources.ec2KeyPairs."

    def _connect(self):
        if self._conn:
            return self._conn
        self._conn = nixops_aws.ec2_utils.connect(self.region, self.access_key_id)
        return self._conn

    def create(self, defn, check, allow_reboot, allow_recreate):

        self.access_key_id = (
            defn.access_key_id or nixops_aws.ec2_utils.get_access_key_id()
        )
        if not self.access_key_id:
            raise Exception(
                "please set ‘accessKeyId’, $EC2_ACCESS_KEY or $AWS_ACCESS_KEY_ID"
            )

        # Generate the key pair locally.
        if not self.public_key:
            (private, public) = nixops.util.create_key_pair(
                type="rsa"
            )  # EC2 only supports RSA keys.
            with self.depl._db:
                self.public_key = public
                self.private_key = private

        # Upload the public key to EC2.
        if check or self.state != self.UP:

            self.region = defn.region

            # Sometimes EC2 DescribeKeypairs return empty list on invalid
            # identifiers, which results in a IndexError exception from within boto,
            # work around that until we figure out what is causing this.
            try:
                kp = self._connect().get_key_pair(defn.keypair_name)
            except IndexError:
                kp = None

            # Don't re-upload the key if it exists and we're just checking.
            if not kp or self.state != self.UP:
                if kp:
                    self._connect().delete_key_pair(defn.keypair_name)
                self.log("uploading EC2 key pair ‘{0}’...".format(defn.keypair_name))
                self._connect().import_key_pair(
                    defn.keypair_name, self.public_key.encode()
                )

            with self.depl._db:
                self.state = self.UP
                self.keypair_name = defn.keypair_name

    def destroy(self, wipe=False):
        def keypair_used():
            for m in self.depl.active_resources.values():
                if type(m) is ec2.EC2State:
                    if m.key_pair == self.keypair_name:  # type: ignore
                        return m
            return None

        m = keypair_used()
        if m:
            raise Exception(
                "keypair ‘{0}’ is still in use by ‘{1}’ ({2})".format(
                    self.keypair_name, m.name, m.vm_id
                )
            )

        if not self.depl.logger.confirm(
            "are you sure you want to destroy keypair ‘{0}’?".format(self.keypair_name)
        ):
            return False

        if self.state == self.UP:
            self.log("deleting EC2 key pair ‘{0}’...".format(self.keypair_name))
            self._connect().delete_key_pair(self.keypair_name)

        return True

    def check(self):
        try:
            kp = self._connect().get_key_pair(self.keypair_name)
        except IndexError:
            kp = None
        if kp is None:
            self.state = self.MISSING
