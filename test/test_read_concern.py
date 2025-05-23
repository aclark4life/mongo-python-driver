# Copyright 2015-present MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test the read_concern module."""
from __future__ import annotations

import sys
import unittest

sys.path[0:0] = [""]

from test import IntegrationTest, client_context
from test.utils_shared import OvertCommandListener

from bson.son import SON
from pymongo.errors import OperationFailure
from pymongo.read_concern import ReadConcern

_IS_SYNC = True


class TestReadConcern(IntegrationTest):
    listener: OvertCommandListener

    @client_context.require_connection
    def setUp(self):
        super().setUp()
        self.listener = OvertCommandListener()
        self.client = self.rs_or_single_client(event_listeners=[self.listener])
        self.db = self.client.pymongo_test
        client_context.client.pymongo_test.create_collection("coll")

    def tearDown(self):
        client_context.client.pymongo_test.drop_collection("coll")

    def test_read_concern(self):
        rc = ReadConcern()
        self.assertIsNone(rc.level)
        self.assertTrue(rc.ok_for_legacy)

        rc = ReadConcern("majority")
        self.assertEqual("majority", rc.level)
        self.assertFalse(rc.ok_for_legacy)

        rc = ReadConcern("local")
        self.assertEqual("local", rc.level)
        self.assertTrue(rc.ok_for_legacy)

        self.assertRaises(TypeError, ReadConcern, 42)

    def test_read_concern_uri(self):
        uri = f"mongodb://{client_context.pair}/?readConcernLevel=majority"
        client = self.rs_or_single_client(uri, connect=False)
        self.assertEqual(ReadConcern("majority"), client.read_concern)

    def test_invalid_read_concern(self):
        coll = self.db.get_collection("coll", read_concern=ReadConcern("unknown"))
        # We rely on the server to validate read concern.
        with self.assertRaises(OperationFailure):
            coll.find_one()

    def test_find_command(self):
        # readConcern not sent in command if not specified.
        coll = self.db.coll
        coll.find({"field": "value"}).to_list()
        self.assertNotIn("readConcern", self.listener.started_events[0].command)

        self.listener.reset()

        # Explicitly set readConcern to 'local'.
        coll = self.db.get_collection("coll", read_concern=ReadConcern("local"))
        coll.find({"field": "value"}).to_list()
        self.assertEqualCommand(
            SON(
                [
                    ("find", "coll"),
                    ("filter", {"field": "value"}),
                    ("readConcern", {"level": "local"}),
                ]
            ),
            self.listener.started_events[0].command,
        )

    def test_command_cursor(self):
        # readConcern not sent in command if not specified.
        coll = self.db.coll
        (coll.aggregate([{"$match": {"field": "value"}}])).to_list()
        self.assertNotIn("readConcern", self.listener.started_events[0].command)

        self.listener.reset()

        # Explicitly set readConcern to 'local'.
        coll = self.db.get_collection("coll", read_concern=ReadConcern("local"))
        (coll.aggregate([{"$match": {"field": "value"}}])).to_list()
        self.assertEqual({"level": "local"}, self.listener.started_events[0].command["readConcern"])

    def test_aggregate_out(self):
        coll = self.db.get_collection("coll", read_concern=ReadConcern("local"))
        (coll.aggregate([{"$match": {"field": "value"}}, {"$out": "output_collection"}])).to_list()

        # Aggregate with $out supports readConcern MongoDB 4.2 onwards.
        if client_context.version >= (4, 1):
            self.assertIn("readConcern", self.listener.started_events[0].command)
        else:
            self.assertNotIn("readConcern", self.listener.started_events[0].command)


if __name__ == "__main__":
    unittest.main()
