# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
from proboscis.asserts import assert_equal
from proboscis.asserts import assert_not_equal
from proboscis.asserts import assert_raises
from proboscis.asserts import assert_is_not_none
from proboscis.asserts import assert_true
from proboscis import test
from proboscis import SkipTest
from proboscis import before_class
from proboscis.decorators import time_out
from reddwarf.tests.util import poll_until
from reddwarf.tests.util import test_config
from reddwarf import tests
from reddwarf.tests import util
from reddwarf.tests.api.instances import WaitForGuestInstallationToFinish
from reddwarf.tests.api.instances import instance_info
from reddwarf.tests.api.instances import GROUP_START
from reddwarf.tests.util.users import Requirements
from reddwarf.tests.api.instances import assert_unprocessable
#from reddwarfclient import backups
from reddwarfclient import exceptions
from datetime import datetime
# Define groups
GROUP = "dbaas.api.backups"
GROUP_POSITIVE = GROUP + ".positive"
GROUP_NEGATIVE = GROUP + ".negative"
# Define Globals
BACKUP_NAME = 'backup_test'
BACKUP_DESC = 'test description for backup'
BACKUP_DB_NAME = "backup_DB"
backup_name = None
backup_desc = None

databases = []
users = []
backup_resp = None


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      depends_on_groups=[GROUP_START],
      groups=[GROUP])
class BackupsBase(object):
    """
    Base class for Positive and Negative classes for test cases
    """
    #def set_up(self):
    def __init__(self):
        self.backup_status = None
        self.backup_id = None
        self.restore_id = None
        self.dbaas = util.create_dbaas_client(instance_info.user)

    def _create_backup(self, backup_name, backup_desc, inst_id=None):
        if inst_id is None:
            inst_id = instance_info.id
        backup_resp = instance_info.dbaas.backups.create(backup_name,
                                                         inst_id,
                                                         backup_desc)
        return backup_resp

    def _create_restore(self, client, backup_id):
        restorePoint = {"backupRef": backup_id}
        restore_resp = client.instances.create(
            instance_info.name + "_restore",
            instance_info.dbaas_flavor_href,
            instance_info.volume,
            restorePoint=restorePoint)
        return restore_resp

    def _create_new_restore(self, backup_id, name, flavor=None, volume=None):
        restorePoint = {"backupRef": backup_id}
        restore_resp = instance_info.dbaas.instances.create(
            name + "_restore",
            (1 if flavor is None else flavor),
            {'size': (1 if volume is None else volume)},
            restorePoint=restorePoint)
        return restore_resp

    def _list_backups_by_instance(self, inst_id=None):
        if inst_id is None:
            inst_id = instance_info.id
        return instance_info.dbaas.instances.backups(inst_id)

    def _get_backup_status(self, backup_id):
        return instance_info.dbaas.backups.get(backup_id).status

    def _delete_backup(self, backup_id):
        assert_not_equal(backup_id, None, "Backup ID is not found")
        instance_info.dbaas.backups.delete(backup_id)
        assert_equal(202, instance_info.dbaas.last_http_code)

    def _backup_is_gone(self, backup_id=None):
        result = None
        if backup_id is None:
            backup_id = self.backup_id
        try:
            result = instance_info.dbaas.backups.get(backup_id)
        except exceptions.NotFound:
            assert_equal(result.status, "404",
                         "status error: %r != 404)" % result.status)
        finally:
            return result is None

    def _instance_is_gone(self, inst_id):
        result = None
        try:
            result = instance_info.dbaas.instances.get(inst_id)
            return False
        except exceptions.NotFound:
            return True

    def _result_is_active(self):
        instance = instance_info.dbaas.instances.get(self.restore_id)
        if instance.status == "ACTIVE":
            return True
        else:
            # If its not ACTIVE, anything but BUILD must be an error.
            assert_equal("BUILD", instance.status)
            if instance_info.volume is not None:
                assert_equal(instance.volume.get('used', None), None)
                return False

    def _verify_instance_is_active(self):
        result = instance_info.dbaas.instances.get(instance_info.id)
        return result.status == 'ACTIVE'

    def _verify_instance_status(self, instance_id, status):
        result = instance_info.dbaas.instances.get(instance_id)
        return result.status == status

    def _verify_backup_status(self, backup_id, status):
        result = instance_info.dbaas.backups.get(backup_id)
        return result.status == status

    def _verify_databases(self, db_name):
        databases = instance_info.dbaas.databases.list(instance_info.id)
        dbs = [database.name for database in databases]
        for db in instance_info.databases:
            assert_true(db_name in dbs)


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      groups=[GROUP, GROUP_POSITIVE])
class TestBackupPositive(BackupsBase):
    backup_id = None
    restore_id = None
    database_name = "backup_DB"
    restored_name = "restored_backup"
    restored_desc = "Backup from Restored Instance"

    @test
    def test_create_backup(self):
        databases = []
        databases.append({"name": BACKUP_DB_NAME, "charset": "latin2",
                          "collate": "latin2_general_ci"})
        instance_info.dbaas.databases.create(instance_info.id, databases)
        assert_equal(202, instance_info.dbaas.last_http_code)
        result = self._create_backup(BACKUP_NAME, BACKUP_DESC,
                                     instance_info.id)
        assert_equal(result.name, BACKUP_NAME)
        assert_equal(result.description, BACKUP_DESC)
        assert_equal(result.instance_id, instance_info.id)
        assert_equal(result.status, 'NEW')
        assert_is_not_none(result.id, 'backup.id does not exist')
        assert_is_not_none(result.created, 'backup.created does not exist')
        assert_is_not_none(result.updated, 'backup.updated does not exist')
        instance = instance_info.dbaas.instances.list()[0]
        assert_equal(instance.status, 'BACKUP')
        self.backup_id = result.id
        # Get Backup status by backup id during and after backup creation
        poll_until(lambda: self._verify_backup_status(result.id, 'NEW'),
                   time_out=120, sleep_time=1)
        poll_until(lambda: self._verify_instance_status(instance.id, 'BACKUP'),
                   time_out=120, sleep_time=1)
        poll_until(lambda: self._verify_backup_status(result.id, 'COMPLETED'),
                   time_out=120, sleep_time=1)
        poll_until(lambda: self._verify_instance_status(instance.id, 'ACTIVE'),
                   time_out=120, sleep_time=1)

    @test(runs_after=[test_create_backup])
    def test_list_backups(self):
        result = instance_info.dbaas.backups.list()
        assert_equal(1, len(result))
        backup = result[0]
        assert_equal(backup.name, BACKUP_NAME)
        assert_equal(backup.description, BACKUP_DESC)
        assert_equal(backup.instance_id, instance_info.id)
        assert_equal(backup.status, 'COMPLETED')
        assert_is_not_none(backup.id, 'backup.id does not exist')
        assert_is_not_none(backup.created, 'backup.created does not exist')
        assert_is_not_none(backup.updated, 'backup.updated does not exist')

    @test(runs_after=[test_create_backup])
    def test_list_backups_for_instance(self):
        result = self._list_backups_by_instance()
        assert_equal(1, len(result))
        backup = result[0]
        assert_equal(backup.name, BACKUP_NAME)
        assert_equal(backup.description, BACKUP_DESC)
        assert_equal(backup.instance_id, instance_info.id)
        assert_equal(backup.status, 'COMPLETED')
        assert_is_not_none(backup.id, 'backup.id does not exist')
        assert_is_not_none(backup.created, 'backup.created does not exist')
        assert_is_not_none(backup.updated, 'backup.updated does not exist')

    @test(runs_after=[test_create_backup])
    def test_get_backup(self):
        backup = instance_info.dbaas.backups.get(self.backup_id)
        assert_equal(backup.id, self.backup_id)
        assert_equal(backup.name, BACKUP_NAME)
        assert_equal(backup.description, BACKUP_DESC)
        assert_equal(backup.instance_id, instance_info.id)
        assert_equal(backup.status, 'COMPLETED')
        assert_is_not_none(backup.created, 'backup.created does not exist')
        assert_is_not_none(backup.updated, 'backup.updated does not exist')

    @test(runs_after=[test_create_backup])
    def test_restore_backup(self):
        if test_config.auth_strategy == "fake":
            # We should create restore logic in fake guest agent to not skip
            raise SkipTest("Skipping restore tests for fake mode.")
        restore_resp = self._create_restore(instance_info.dbaas,
                                            self.backup_id)
        assert_equal(200, instance_info.dbaas.last_http_code)
        assert_equal("BUILD", restore_resp.status)
        assert_is_not_none(restore_resp.id, 'restored inst_id does not exist')
        self.restore_id = restore_resp.id
        poll_until(self._result_is_active)
        restored_inst = instance_info.dbaas.instances.get(self.restore_id)
        assert_equal(restored_inst.name, BACKUP_NAME)
        assert_equal(restored_inst.status, 'ACTIVE')
        assert_is_not_none(restored_inst.id, 'restored inst_id does not exist')
        self._verify_databases(BACKUP_DB_NAME)

    @test(runs_after=[test_list_backups, test_list_backups_for_instance],
          always_run=True)
    def test_delete_backup(self):
        self._delete_backup(self.backup_id)
        poll_until(self._backup_is_gone)

    @test(runs_after=[test_restore_backup], always_run=True)
    def test_delete_restored_instance(self):
        if test_config.auth_strategy == "fake":
            raise SkipTest("Skipping delete restored instance for fake mode.")
        # Create a backup to list after instance is deleted
        result = self._create_backup(self.restored_name,
                                     self.restored_desc,
                                     inst_id=self.restore_id)
        assert_equal(200, instance_info.dbaas.last_http_code)
        poll_until(lambda: self._verify_backup_status(result.id, 'COMPLETED'),
                   time_out=120, sleep_time=1)
        instance_info.dbaas.instances.delete(self.restore_id)
        assert_equal(202, instance_info.dbaas.last_http_code)
        poll_until(lambda: self._instance_is_gone(self.restore_id))
        assert_raises(exceptions.NotFound, instance_info.dbaas.instances.get,
                      self.restore_id)

    @test(runs_after=[test_delete_restored_instance])
    def test_list_backups_for_deleted_instance(self):
        if test_config.auth_strategy == "fake":
            raise SkipTest("Skipping deleted instance tests for fake mode.")
        result = self._list_backups_by_instance(inst_id=self.restore_id)
        assert_equal(1, len(result))
        backup = result[0]
        assert_equal(backup.name, self.restored_name)
        assert_equal(backup.description, self.restored_desc)
        assert_equal(backup.instance_id, self.restore_id)
        assert_equal(backup.status, 'COMPLETED')
        assert_is_not_none(backup.id, 'backup.id does not exist')
        assert_is_not_none(backup.created, 'backup.created does not exist')
        assert_is_not_none(backup.updated, 'backup.updated does not exist')


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      groups=[GROUP, GROUP_NEGATIVE])
class TestBackupNegative(BackupsBase):
    databases = []
    users = []
    starttime_list = []
    xtra_instance = None
    xtra_backup = None
    spare_client = None
    spare_user = None

    @before_class
    def setUp(self):
        #instance_info.dbaas.instances.get().
        self.spare_user = test_config.users.find_user(
            Requirements(is_admin=False, services=["reddwarf"]),
            black_list=[instance_info.user.auth_user])
        self.spare_client = util.create_dbaas_client(self.spare_user)

    def test_create_backup(self):
        result = self._create_backup(BACKUP_NAME, BACKUP_DESC,
                                     instance_info.id)
        poll_until(lambda: self._verify_backup_status(result.id, 'COMPLETED'),
                   time_out=120, sleep_time=1)

    @test(runs_after=[test_create_backup])
    def test_create_backup_with_instance_not_active(self):
        name = "spare_instance"
        flavor = 2
        self.databases.append({"name": "db2"})
        self.users.append({"name": "lite", "password": "litepass",
                           "databases": [{"name": "db2"}]})
        volume = {'size': 2}
        self.xtra_instance = instance_info.dbaas.instances.create(
            name,
            flavor,
            volume,
            self.databases,
            self.users)
        assert_equal(200, instance_info.dbaas.last_http_code)
        # immediately create the backup while instance is still in "BUILD"
        try:
            self.xtra_backup = self._create_backup(
                BACKUP_NAME, BACKUP_DESC, inst_id=self.xtra_instance.id)
        except exceptions.UnprocessableEntity:
            assert_equal(422, instance_info.dbaas.last_http_code)
        assert_equal(422, instance_info.dbaas.last_http_code)
        # make sure the instance status goes back to "ACTIVE"
        poll_until(lambda: self._verify_instance_status(self.xtra_instance.id,
                                                        "ACTIVE"),
                   time_out=120, sleep_time=1)
        # Now that it's active, create the backup
        self.xtra_backup = self._create_backup(BACKUP_NAME, BACKUP_DESC)
        assert_equal(202, instance_info.dbaas.last_http_code)
        poll_until(lambda: self._verify_backup_status(self.xtra_backup.id,
                                                      'COMPLETED'),
                   time_out=120, sleep_time=1)
        # DON'T Delete backup instance now, Need it for restore to smaller

    @test(runs_after=[test_create_backup_with_instance_not_active])
    def test_restore_backups_to_smaller_instance(self):
        if test_config.auth_strategy == "fake":
            raise SkipTest("Skipping restore tests for fake mode.")
        # Create a 2GB instance and DB

        # Backup a 2GB Database
        result = self._create_backup("2GB_backup", "restore backup to smaller")
        assert_equal(202, instance_info.dbaas.last_http_code)
        backup_id = result.id
        # Try to restore it to a 1GB instance
        try:
            restore_result = self._create_new_restore(backup_id,
                                                      "1GB instance too small",
                                                      flavor=1,
                                                      volume=1)
        except exceptions.UnprocessableEntity:
            assert_equal(422, instance_info.dbaas.last_http_code)
        # Now delete the backup
        self._delete_backup(backup_id)
        assert_equal(202, instance_info.dbaas.last_http_code)
        poll_until(lambda: self._backup_is_gone(backup_id=backup_id))

    @test
    def test_list_backups_account_not_owned(self):
        raise SkipTest("Please see Launchpad Bug #1188822")
        std_backup = instance_info.dbaas.backups.list()[0]
        try:
            self.spare_client.backups.get(std_backup)
        except exceptions.NotFound:
            assert_equal(404, self.spare_client.last_http_code)
        # The SPARE user should not be able to "get" the STD user backups
        assert_equal(404, self.spare_client.last_http_code)

    @test
    def test_restore_backup_account_not_owned(self):
        if test_config.auth_strategy == "fake":
            raise SkipTest("Skipping restore tests for fake mode.")
        result = self._create_backup("rest_not_owned_backup",
                                     "restoring a backup of a different user")
        assert_equal(202, instance_info.dbaas.last_http_code)
        restore_result = self._create_restore(self.spare_client, result.id)
        assert_equal(404, instance_info.dbaas.last_http_code)

    @test
    def test_delete_backup_account_not_owned(self):
        raise SkipTest("Please see Launchpad Bug #1188822")
        std_backup = instance_info.dbaas.backups.list()[0]
        print("SPARE USER: %r STD BACKUP: %r" %
              (self.spare_user.auth_user,
               self.spare_client.backups.get(std_backup)))
        instance_info.dbaas.backups.delete(std_backup.id)
        print("Resp code: Delete backup no owned: %r " %
              instance_info.dbaas.last_http_code)

    @test
    def test_backup_create_instance_not_found(self):
        """test create backup with unknown instance"""
        assert_raises(exceptions.NotFound, instance_info.dbaas.backups.create,
                      BACKUP_NAME, 'nonexistent_instance', BACKUP_DESC)

    @test
    def test_backup_delete_not_found(self):
        """test delete unknown backup"""
        assert_raises(exceptions.NotFound, instance_info.dbaas.backups.delete,
                      'nonexistent_backup')

    @test
    def test_restore_backup_that_did_not_complete(self):
        if test_config.auth_strategy == "fake":
            raise SkipTest("Skipping restore tests for fake mode.")
        # Backup a 10GB Database
        result = self._create_backup("10GB_backup", "restore before complete")
        backup_id = result.id
        assert_equal(202, instance_info.dbaas.last_http_code)
        # restore immediately, before the backup is completed
        restore_result = self._create_new_restore(backup_id,
                                                  "backup did not complete",
                                                  flavor=2,
                                                  volume=10)
        assert_equal(400, instance_info.dbaas.last_http_code)

    @test
    def test_delete_while_backing_up(self):
        result = self._create_backup("delete_as_backup",
                                     "delete backup while backing up")
        backup_id = result.id
        assert_equal(202, instance_info.dbaas.last_http_code)
        # Dont wait for backup to complete, try to delete it
        try:
            self._delete_backup(backup_id)
        except:
            assert_equal(422, instance_info.dbaas.last_http_code)

    @test
    def test_instance_action_right_after_backup_create(self):
        """test any instance action while backup is running"""
        assert_unprocessable(instance_info.dbaas.instances.resize_instance,
                             instance_info.id, 1)

    @test
    def test_backup_create_another_backup_running(self):
        """test create backup when another backup is running"""
        assert_unprocessable(instance_info.dbaas.backups.create,
                             'backup_test2', instance_info.id,
                             'test description2')

    @test
    def test_backup_delete_still_running(self):
        """test delete backup when it is running"""
        result = instance_info.dbaas.backups.list()
        backup = result[0]
        assert_unprocessable(instance_info.dbaas.backups.delete, backup.id)

    @test
    def test_restore_deleted_backup(self):
        if test_config.auth_strategy == "fake":
            raise SkipTest("Skipping restore tests for fake mode.")
        result = self._create_backup("rest_del_backup",
                                     "restoring a deleted backup")
        backup_id = result.id
        assert_equal(202, instance_info.dbaas.last_http_code)
        self._delete_backup(backup_id)
        poll_until(self._backup_is_gone)
        restore_result = self._create_restore(instance_info.dbaas, backup_id)
        assert_equal(400, instance_info.dbaas.last_http_code)
        print dir(restore_result)

    @test
    def test_delete_deleted_backup(self):
        result = self._create_backup("del_backup", "delete a deleted backup")
        backup_id = result.id
        assert_equal(202, instance_info.dbaas.last_http_code)
        poll_until(lambda: self._verify_backup_status(backup_id, 'COMPLETED'),
                   time_out=120, sleep_time=1)
        self._delete_backup(backup_id)
        poll_until(lambda: self._backup_is_gone(backup_id))
        try:
            self._delete_backup(backup_id)
        except exceptions.NotFound:
            assert_equal(404, instance_info.dbaas.last_http_code)

    @test(runs_after=[test_create_backup_with_instance_not_active,
                      test_restore_backups_to_smaller_instance],
          always_run=True)
    def test_delete_negative_instance(self):
        try:
            self._delete_backup(self.xtra_backup.id)
            assert_equal(202, instance_info.dbaas.last_http_code)
            poll_until(lambda: self._backup_is_gone(self.xtra_backup.id))
        except exceptions.NotFound:
            assert_equal(404, instance_info.dbaas.last_http_code)
        try:
            instance_info.dbaas.instances.delete(self.xtra_instance.id)
            assert_equal(202, instance_info.dbaas.last_http_code)
            poll_until(lambda: self._instance_is_gone(self.xtra_instance.id))
        except exceptions.NotFound:
            assert_equal(404, instance_info.dbaas.last_http_code)
        finally:
            assert_raises(exceptions.NotFound,
                          instance_info.dbaas.instances.get,
                          self.xtra_instance.id)


@test(depends_on_classes=[WaitForGuestInstallationToFinish],
      runs_after=[TestBackupPositive, TestBackupNegative],
      groups=[GROUP, GROUP_NEGATIVE, GROUP_POSITIVE])
class TestBackupCleanup(BackupsBase):
    @test(always_run=True)
    def test_clean_up_backups(self):
        results = instance_info.dbaas.backups.list()
        for backup in results:
            poll_until(lambda: self._verify_backup_status(backup.id,
                                                          'COMPLETED'))
            try:
                self._delete_backup(backup.id)
                assert_equal(202, instance_info.dbaas.last_http_code)
                poll_until(lambda: self._backup_is_gone(backup.id))
            except exceptions.NotFound:
                assert_equal(404, instance_info.dbaas.last_http_code)
