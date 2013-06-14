# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


import re

import mox

from testtools import skipIf

from heat.common import template_format
from heat.openstack.common.importutils import try_import
from heat.engine.resources import swift
from heat.engine import resource
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db
from heat.tests.utils import parse_stack

swiftclient = try_import('swiftclient.client')

swift_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test OS::Swift::Container resources",
  "Resources" : {
    "SwiftContainerWebsite" : {
      "Type" : "OS::Swift::Container",
      "DeletionPolicy" : "Delete",
      "Properties" : {
        "X-Container-Read" : ".r:*",
        "X-Container-Meta" : {
          "Web-Index" : "index.html",
          "Web-Error" : "error.html"
         }
      }
    },
    "SwiftContainer" : {
      "Type" : "OS::Swift::Container",
      "Properties" : {
      }
    }
  }
}
'''


class swiftTest(HeatTestCase):
    @skipIf(swiftclient is None, 'unable to import swiftclient')
    def setUp(self):
        super(swiftTest, self).setUp()
        self.m.CreateMock(swiftclient.Connection)
        self.m.StubOutWithMock(swiftclient.Connection, 'put_container')
        self.m.StubOutWithMock(swiftclient.Connection, 'delete_container')
        self.m.StubOutWithMock(swiftclient.Connection, 'head_container')
        self.m.StubOutWithMock(swiftclient.Connection, 'get_auth')

        self.container_pattern = 'test_stack-test_resource-[0-9a-z]+'
        setup_dummy_db()

    def create_resource(self, t, stack, resource_name):
        rsrc = swift.SwiftContainer(
            'test_resource',
            t['Resources'][resource_name],
            stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_create_container_name(self):
        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = parse_stack(t)
        rsrc = swift.SwiftContainer(
            'test_resource',
            t['Resources']['SwiftContainer'],
            stack)

        self.assertTrue(re.match(self.container_pattern,
                                 rsrc._create_container_name()))
        self.assertEqual(
            'the_name',
            rsrc._create_container_name('the_name'))

    def test_build_meta_headers(self):
        self.m.UnsetStubs()
        self.assertEqual({}, swift.SwiftContainer._build_meta_headers({}))
        self.assertEqual({}, swift.SwiftContainer._build_meta_headers(None))
        meta = {
            'X-Container-Meta-Web-Index': 'index.html',
            'X-Container-Meta-Web-Error': 'error.html'
        }
        self.assertEqual(meta, swift.SwiftContainer._build_meta_headers({
            "Web-Index": "index.html",
            "Web-Error": "error.html"
        }))

    def test_attributes(self):
        headers = {
            "content-length": "0",
            "x-container-object-count": "82",
            "x-container-write": "None",
            "accept-ranges": "bytes",
            "x-trans-id": "tx08ea48ef2fa24e6da3d2f5c188fd938b",
            "date": "Wed, 23 Jan 2013 22:48:05 GMT",
            "x-timestamp": "1358980499.84298",
            "x-container-read": ".r:*",
            "x-container-bytes-used": "17680980",
            "content-type": "text/plain; charset=utf-8"}

        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Write': None,
             'X-Container-Read': None}
        ).AndReturn(None)
        swiftclient.Connection.get_auth().MultipleTimes().AndReturn(
            ('http://localhost:8080/v_2', None))
        swiftclient.Connection.head_container(
            mox.IgnoreArg()).MultipleTimes().AndReturn(headers)
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')

        ref_id = rsrc.FnGetRefId()
        self.assertTrue(re.match(self.container_pattern,
                                 ref_id))

        self.assertEqual('localhost', rsrc.FnGetAtt('DomainName'))
        url = 'http://localhost:8080/v_2/%s' % ref_id

        self.assertEqual(url, rsrc.FnGetAtt('WebsiteURL'))
        self.assertEqual('82', rsrc.FnGetAtt('ObjectCount'))
        self.assertEqual('17680980', rsrc.FnGetAtt('BytesUsed'))
        self.assertEqual(headers, rsrc.FnGetAtt('HeadContainer'))

        try:
            rsrc.FnGetAtt('Foo')
            raise Exception('Expected InvalidTemplateAttribute')
        except swift.exception.InvalidTemplateAttribute:
            pass

        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})

        rsrc.delete()
        self.m.VerifyAll()

    def test_public_read(self):
        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Write': None,
             'X-Container-Read': '.r:*'}).AndReturn(None)
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        properties = t['Resources']['SwiftContainer']['Properties']
        properties['X-Container-Read'] = '.r:*'
        stack = parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        rsrc.delete()
        self.m.VerifyAll()

    def test_public_read_write(self):
        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Write': '.r:*',
             'X-Container-Read': '.r:*'}).AndReturn(None)
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        properties = t['Resources']['SwiftContainer']['Properties']
        properties['X-Container-Read'] = '.r:*'
        properties['X-Container-Write'] = '.r:*'
        stack = parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        rsrc.delete()
        self.m.VerifyAll()

    def test_website(self):

        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Meta-Web-Error': 'error.html',
             'X-Container-Meta-Web-Index': 'index.html',
             'X-Container-Write': None,
             'X-Container-Read': '.r:*'}).AndReturn(None)
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainerWebsite')
        rsrc.delete()
        self.m.VerifyAll()

    def test_delete_exception(self):

        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Write': None,
             'X-Container-Read': None}).AndReturn(None)
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndRaise(
                swiftclient.ClientException('Test delete failure'))

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        rsrc.delete()

        self.m.VerifyAll()

    def test_delete_retain(self):

        # first run, with retain policy
        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Write': None,
             'X-Container-Read': None}).AndReturn(None)
        # This should not be called
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)

        container = t['Resources']['SwiftContainer']
        container['DeletionPolicy'] = 'Retain'
        stack = parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        # if delete_container is called, mox verify will succeed
        rsrc.delete()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        try:
            self.m.VerifyAll()
        except mox.ExpectedMethodCallsError:
            return

        raise Exception('delete_container was called despite Retain policy')
