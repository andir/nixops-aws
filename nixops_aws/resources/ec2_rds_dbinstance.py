# -*- coding: utf-8 -*-

# Automatic provisioning of AWS RDS Database Instances.

import boto.rds
import nixops.resources
import nixops.util
import nixops_aws.ec2_utils
import time
from uuid import uuid4
from . import ec2_rds_dbsecurity_group
from .ec2_rds_dbsecurity_group import EC2RDSDbSecurityGroupState

from .types.ec2_rds_dbinstance import Ec2RdsDbinstanceOptions


class EC2RDSDbInstanceDefinition(nixops.resources.ResourceDefinition):
    """Definition of an EC2 RDS Database Instance."""

    config: Ec2RdsDbinstanceOptions

    @classmethod
    def get_type(cls):
        return "ec2-rds-dbinstance"

    @classmethod
    def get_resource_type(cls):
        return "rdsDbInstances"

    def __init__(self, name: str, config: nixops.resources.ResourceEval):
        super(EC2RDSDbInstanceDefinition, self).__init__(name, config)
        # rds specific params

        self.rds_dbinstance_id = self.config.id
        self.rds_dbinstance_allocated_storage = self.config.allocatedStorage
        self.rds_dbinstance_instance_class = self.config.instanceClass
        self.rds_dbinstance_master_username = self.config.masterUsername
        self.rds_dbinstance_master_password = self.config.masterPassword
        self.rds_dbinstance_port = self.config.port
        self.rds_dbinstance_engine = self.config.engine
        self.rds_dbinstance_db_name = self.config.dbName
        self.rds_dbinstance_multi_az = self.config.multiAZ
        self.rds_dbinstance_security_groups = []
        for sg_name in self.config.securityGroups:
            self.rds_dbinstance_security_groups.append(sg_name)
        # TODO: implement remainder of boto.rds.RDSConnection.create_dbinstance parameters

        # common params
        self.region = self.config.region
        self.access_key_id = self.config.accessKeyId

    def show_type(self):
        return "{0} [{1}]".format(self.get_type(), self.region)


class EC2RDSDbInstanceState(nixops.resources.ResourceState[EC2RDSDbInstanceDefinition]):
    """State of an RDS Database Instance."""

    region = nixops.util.attr_property("ec2.region", None)
    access_key_id = nixops.util.attr_property("ec2.accessKeyId", None)
    rds_dbinstance_id = nixops.util.attr_property("ec2.rdsDbInstanceID", None)
    rds_dbinstance_allocated_storage = nixops.util.attr_property(
        "ec2.rdsAllocatedStorage", None, int
    )
    rds_dbinstance_instance_class = nixops.util.attr_property(
        "ec2.rdsInstanceClass", None
    )
    rds_dbinstance_master_username = nixops.util.attr_property(
        "ec2.rdsMasterUsername", None
    )
    rds_dbinstance_master_password = nixops.util.attr_property(
        "ec2.rdsMasterPassword", None
    )
    rds_dbinstance_port = nixops.util.attr_property("ec2.rdsPort", None, int)
    rds_dbinstance_engine = nixops.util.attr_property("ec2.rdsEngine", None)
    rds_dbinstance_db_name = nixops.util.attr_property("ec2.rdsDbName", None)
    rds_dbinstance_endpoint = nixops.util.attr_property("ec2.rdsEndpoint", None)
    rds_dbinstance_multi_az = nixops.util.attr_property("ec2.multiAZ", False)
    rds_dbinstance_security_groups = nixops.util.attr_property(
        "ec2.securityGroups", [], "json"
    )

    requires_reboot_attrs = (
        "rds_dbinstance_id",
        "rds_dbinstance_allocated_storage",
        "rds_dbinstance_instance_class",
        "rds_dbinstance_master_password",
    )

    @classmethod
    def get_type(cls):
        return "ec2-rds-dbinstance"

    def __init__(self, depl, name, id):
        super(EC2RDSDbInstanceState, self).__init__(depl, name, id)
        self._conn = None

    def show_type(self):
        s = super(EC2RDSDbInstanceState, self).show_type()
        if self.region:
            s = "{0} [{1}]".format(s, self.region)
        return s

    def prefix_definition(self, attr):
        return {("resources", "rdsDbInstances"): attr}

    def get_physical_spec(self):
        return {"endpoint": self.rds_dbinstance_endpoint}

    @property
    def resource_id(self):
        return self.rds_dbinstance_id

    def create_after(self, resources, defn):
        return {
            r
            for r in resources
            if isinstance(r, ec2_rds_dbsecurity_group.EC2RDSDbSecurityGroupState,)
        }

    def _connect(self):
        if self._conn:
            return
        (access_key_id, secret_access_key) = nixops_aws.ec2_utils.fetch_aws_secret_key(
            self.access_key_id
        )
        self._conn = boto.rds.connect_to_region(
            region_name=self.region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def _exists(self):
        return self.state != self.MISSING and self.state != self.UNKNOWN

    def _assert_invariants(self, defn):
        # NOTE: it is possible to change region, master_username, port, or db_name
        # by creating a snapshot of the database and recreating the instance,
        # then restoring the snapshot.  Not sure if this is in the scope of what
        # nixops intends to manager for the user, or if it violates the principle
        # of least surprise.

        diff = self._diff_defn(defn)
        diff_attrs = set(diff.keys())

        invariant_attrs = set(
            [
                "region",
                "rds_dbinstance_master_username",
                "rds_dbinstance_engine",
                "rds_dbinstance_port",
                "rds_dbinstance_db_name",
            ]
        )

        violated_attrs = diff_attrs & invariant_attrs
        if len(violated_attrs) > 0:
            message = (
                "Invariant violated: (%s) cannot be changed for an RDS instance"
                % ",".join(violated_attrs)
            )
            for attr in violated_attrs:
                message += "\n%s != %s" % (getattr(self, attr), getattr(defn, attr))
            raise Exception(message)

    def _try_fetch_dbinstance(self, instance_id):
        dbinstance = None
        try:
            dbinstance = self._connect().get_all_dbinstances(instance_id=instance_id)[0]
        except boto.exception.BotoServerError as bse:
            if bse.error_code == "DBInstanceNotFound":
                dbinstance = None
            else:
                raise

        return dbinstance

    def _diff_defn(self, defn):
        attrs = (
            "region",
            "rds_dbinstance_port",
            "rds_dbinstance_engine",
            "rds_dbinstance_multi_az",
            "rds_dbinstance_instance_class",
            "rds_dbinstance_db_name",
            "rds_dbinstance_master_username",
            "rds_dbinstance_master_password",
            "rds_dbinstance_allocated_storage",
            "rds_dbinstance_security_groups",
        )

        def get_state_attr(attr):
            # handle boolean type in the state to avoid triggering false
            # diffs
            if attr == "rds_dbinstance_multi_az":
                return bool(getattr(self, attr))
            else:
                return getattr(self, attr)

        def get_defn_attr(attr):
            if attr == "rds_dbinstance_security_groups":
                return self.fetch_security_group_resources(
                    defn.rds_dbinstance_security_groups
                )
            else:
                return getattr(defn, attr)

        return {
            attr: get_defn_attr(attr)
            for attr in attrs
            if get_defn_attr(attr) != get_state_attr(attr)
        }

    def _requires_reboot(self, defn):
        diff = self._diff_defn(defn)
        return set(self.requires_reboot_attrs) & set(diff.keys())

    def _wait_for_dbinstance(self, dbinstance, state="available"):
        self.log_start("waiting for database instance state=`{0}` ".format(state))
        while True:
            dbinstance.update()
            self.log_continue("[{0}] ".format(dbinstance.status))
            if dbinstance.status not in {
                "creating",
                "backing-up",
                "available",
                "modifying",
            }:
                raise Exception(
                    "RDS database instance ‘{0}’ in an error state (state is ‘{1}’)".format(
                        dbinstance.id, dbinstance.status
                    )
                )
            if dbinstance.status == state:
                break
            time.sleep(6)

    def _copy_dbinstance_attrs(self, dbinstance, security_groups):
        with self.depl._db:
            self.rds_dbinstance_id = dbinstance.id
            self.rds_dbinstance_allocated_storage = int(dbinstance.allocated_storage)
            self.rds_dbinstance_instance_class = dbinstance.instance_class
            self.rds_dbinstance_master_username = dbinstance.master_username
            self.rds_dbinstance_engine = dbinstance.engine
            self.rds_dbinstance_multi_az = dbinstance.multi_az
            self.rds_dbinstance_port = int(dbinstance.endpoint[1])
            self.rds_dbinstance_endpoint = "%s:%d" % dbinstance.endpoint
            self.rds_dbinstance_security_groups = security_groups

    def _to_boto_kwargs(self, attrs):
        attr_to_kwarg = {
            "rds_dbinstance_allocated_storage": "allocated_storage",
            "rds_dbinstance_master_password": "master_password",
            "rds_dbinstance_instance_class": "instance_class",
            "rds_dbinstance_multi_az": "multi_az",
            "rds_dbinstance_security_groups": "security_groups",
        }
        return {attr_to_kwarg[attr]: attrs[attr] for attr in attrs.keys()}

    def _compare_instance_id(self, instance_id):
        # take care when comparing instance ids, as aws lowercases and converts to unicode
        return str(self.rds_dbinstance_id).lower() == str(instance_id).lower()

    def fetch_security_group_resources(self, config):
        security_groups = []
        for sg in config:
            if sg.startswith("res-"):
                res = self.depl.get_typed_resource(
                    sg[4:].split(".")[0],
                    "ec2-rds-dbsecurity-group",
                    EC2RDSDbSecurityGroupState,
                )
                security_groups.append(res._state["groupName"])
            else:
                security_groups.append(sg)
        return security_groups

    def create(self, defn, check, allow_reboot, allow_recreate):
        with self.depl._db:
            self.access_key_id = (
                defn.access_key_id or nixops_aws.ec2_utils.get_access_key_id()
            )
            if not self.access_key_id:
                raise Exception(
                    "please set ‘accessKeyId’, $EC2_ACCESS_KEY or $AWS_ACCESS_KEY_ID"
                )

            if self._exists():
                self._assert_invariants(defn)

            self.region = defn.region

        # fetch our target instance identifier regardless to fail early if needed
        self._connect()
        dbinstance = self._try_fetch_dbinstance(defn.rds_dbinstance_id)

        if self.state == self.UP:
            # if we are changing instance ids and our target instance id already exists
            # there is no reasonable recourse.  bail.
            if dbinstance and not self._compare_instance_id(defn.rds_dbinstance_id):
                raise Exception(
                    "database identifier changed but database with instance_id=%s already exists"
                    % defn.rds_dbinstance_id
                )

            dbinstance = self._try_fetch_dbinstance(self.rds_dbinstance_id)

        with self.depl._db:
            if check or self.state == self.MISSING or self.state == self.UNKNOWN:
                if dbinstance and (
                    self.state == self.MISSING or self.state == self.UNKNOWN
                ):
                    if dbinstance.status == "deleting":
                        self.logger.log(
                            "RDS instance `{0}` is being deleted, waiting...".format(
                                dbinstance.id
                            )
                        )
                        while True:
                            if dbinstance.status == "deleting":
                                continue
                            else:
                                break
                            self.log_continue("[{0}] ".format(dbinstance.status))
                            time.sleep(6)

                    self.logger.log(
                        "RDS instance `{0}` is MISSING but already exists, synchronizing state".format(
                            dbinstance.id
                        )
                    )
                    self.state = self.UP

                if not dbinstance and self.state == self.UP:
                    self.logger.log(
                        "RDS instance `{0}` state is UP but does not exist!"
                    )
                    if not allow_recreate:
                        raise Exception(
                            "RDS instance is UP but does not exist, set --allow-recreate to recreate"
                        )
                    self.state = self.MISSING

                if not dbinstance and (
                    self.state == self.MISSING or self.state == self.UNKNOWN
                ):
                    self.logger.log(
                        "creating RDS database instance ‘{0}’ (this may take a while)...".format(
                            defn.rds_dbinstance_id
                        )
                    )
                    # create a new dbinstance with desired config
                    security_groups = self.fetch_security_group_resources(
                        defn.rds_dbinstance_security_groups
                    )
                    dbinstance = self._connect().create_dbinstance(
                        defn.rds_dbinstance_id,
                        defn.rds_dbinstance_allocated_storage,
                        defn.rds_dbinstance_instance_class,
                        defn.rds_dbinstance_master_username,
                        defn.rds_dbinstance_master_password,
                        port=defn.rds_dbinstance_port,
                        engine=defn.rds_dbinstance_engine,
                        db_name=defn.rds_dbinstance_db_name,
                        multi_az=defn.rds_dbinstance_multi_az,
                        security_groups=security_groups,
                    )

                    self.state = self.STARTING
                    self._wait_for_dbinstance(dbinstance)

                self.region = defn.region
                self.access_key_id = (
                    defn.access_key_id or nixops_aws.ec2_utils.get_access_key_id()
                )
                self.rds_dbinstance_db_name = defn.rds_dbinstance_db_name
                self.rds_dbinstance_master_password = (
                    defn.rds_dbinstance_master_password
                )
                self._copy_dbinstance_attrs(
                    dbinstance, defn.rds_dbinstance_security_groups
                )
                self.state = self.UP

        with self.depl._db:
            if self.state == self.UP and self._diff_defn(defn):
                if dbinstance is None:
                    raise Exception(
                        "state is UP but database instance does not exist. re-run with --check option to synchronize states"
                    )

                # check invariants again since state possibly changed due to check = true
                self._assert_invariants(defn)

                reboot_keys = self._requires_reboot(defn)
                if self._requires_reboot(defn) and not allow_reboot:
                    raise Exception(
                        "changing keys (%s) requires reboot, but --allow-reboot not set"
                        % ", ".join(reboot_keys)
                    )

                diff = self._diff_defn(defn)
                boto_kwargs = self._to_boto_kwargs(diff)
                if not self._compare_instance_id(defn.rds_dbinstance_id):
                    boto_kwargs["new_instance_id"] = defn.rds_dbinstance_id
                boto_kwargs["apply_immediately"] = True

                # first check is for the unlikely event we attempt to modify the db during its maintenance window
                self._wait_for_dbinstance(dbinstance)
                dbinstance = dbinstance.modify(**boto_kwargs)
                # Ugly hack to prevent from waiting on state
                # 'modifying' on sg change as that looks like it's an
                # immediate change in RDS.
                if not (len(boto_kwargs) == 2 and "security_groups" in boto_kwargs):
                    self._wait_for_dbinstance(dbinstance, state="modifying")
                self._wait_for_dbinstance(dbinstance)
                self._copy_dbinstance_attrs(
                    dbinstance, defn.rds_dbinstance_security_groups
                )

    def after_activation(self, defn):
        # TODO: Warn about old instances, but don't clean them up.
        pass

    def destroy(self, wipe=False):
        if self.state == self.UP or self.state == self.STARTING:
            if not self.depl.logger.confirm(
                "are you sure you want to destroy RDS instance ‘{0}’?".format(
                    self.rds_dbinstance_id
                )
            ):
                return False
            self._connect()

            dbinstance = None
            if self.rds_dbinstance_id:
                dbinstance = self._try_fetch_dbinstance(self.rds_dbinstance_id)

            if dbinstance and dbinstance.status != "deleting":
                self.logger.log(
                    "deleting RDS instance `{0}'...".format(self.rds_dbinstance_id)
                )
                final_snapshot_id = "%s-final-snapshot-%s" % (
                    self.rds_dbinstance_id,
                    uuid4().hex,
                )
                self.logger.log("saving final snapshot as %s" % final_snapshot_id)
                self._connect().delete_dbinstance(
                    self.rds_dbinstance_id, final_snapshot_id=final_snapshot_id
                )

                while True:
                    if dbinstance.status == "deleting":
                        continue
                    else:
                        break
                    self.log_continue("[{0}] ".format(dbinstance.status))
                    time.sleep(6)

            else:
                self.logger.log(
                    "RDS instance `{0}` does not exist, skipping.".format(
                        self.rds_dbinstance_id
                    )
                )

            self.state = self.MISSING
        return True
