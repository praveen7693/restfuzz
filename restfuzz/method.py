# Copyright 2017 Red Hat
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import yaml
import os
import json
import itertools # noqa

from restfuzz.utils import debug
from restfuzz.event import Event


class Method:
    # Method object created from yaml description
    def __init__(self, kwarg, base_url):
        self.base_url = base_url
        self.name = kwarg['name']
        self.http_method = kwarg['url'][0]
        self.url = kwarg['url'][1]
        if self.url[0] == "/":
            self.url = self.url[1:]
        self.inputs = kwarg.setdefault('inputs', {})
        self.outputs = kwarg.setdefault('outputs', {})
        self.enabled = True

        # check method requirements/outputs
        self.requires = set()
        self.produces = set()
        for k, v in self.iter_inputs():
            if v['_type'] in ('resource', 'list_resource'):
                self.requires.add(v.setdefault('resource_name', k))

        for k, v in self.outputs.items():
            self.produces.add(k)

    def iter_inputs(self, data_set=None):
        # recursive generator of input definition from schema
        # yield input name, input description
        if data_set is None:
            data_set = self.inputs

        if not isinstance(data_set, dict):
            raise RuntimeError(
                "%s: Missing type in input/output description" % data_set)
        for k, v in data_set.items():
            if '_type' in v:
                yield (k, v)
            else:
                for k2, v2 in self.iter_inputs(v):
                    if '_type' in v2:
                        yield (k2, v2)

    def check_requirements(self, resources):
        for i in self.requires:
            if i in resources:
                return True

    def call(self, api, params=None):
        # Encode inputs
        url = "%s/%s" % (self.base_url, self.url)
        json_input = None
        content_type = 'application/json'
        if params:
            if "url_input" in params:
                url_input = params['url_input']
                try:
                    url = url % url_input
                except (KeyError, ValueError):
                    pass
                del params['url_input']
                if params:
                    if "raw_data" in params:
                        try:
                            json_input = params["raw_data"].encode(
                                'utf-8', errors='ignore')
                            content_type = 'application/octet-stream'
                        except Exception:
                            pass
                    else:
                        json_input = json.dumps(params)
                params['url_input'] = url_input
            else:
                json_input = json.dumps(params)

        # Call
        event = Event(self.name, self.http_method, url, json_input)
        resp = api.request(self.http_method, url, json_input, content_type)
        event.set_resp(resp)

        outputs = {}
        if resp.status_code >= 200 and resp.status_code < 300 and resp.text:
            # Extract outputs from method results
            try:
                json_output = resp.json()
            except ValueError:
                return event
            for output in self.outputs:
                value = None
                try:
                    value = eval(
                        self.outputs[output]['json_extract'])(json_output)
                except Exception:
                    debug("Could not decode output [%s] with %s" % (
                        json_output, self.outputs[output]))
                if not value:
                    continue
                if not isinstance(value, list):
                    value = [value]
                outputs[output] = value
            event.outputs = outputs

        return event

    def __repr__(self):
        return "<Method(%s)>" % (self.name)


def load_yaml(fobj, methods, base_url=None):
    # Store methods in methods dictionary
    d = yaml.load(fobj)
    if base_url is not None:
        d["base_url"] = base_url
    if not d or "base_url" not in d or "methods" not in d:
        raise RuntimeError("Invalid yaml...")
    for method in d['methods']:
        m = Method(method, d['base_url'])
        if m.name in methods:
            print("Skipping duplicate method name %s" % m.name)
            continue
            # raise RuntimeError("Duplicate method name '%s'" % m.name)
        methods[m.name] = m


def load_methods(folder_or_file, base_url=None):
    files = []
    if os.path.isdir(folder_or_file):
        for fname in filter(lambda d: d.endswith('.yaml'),
                            os.listdir(folder_or_file)):
            files.append("%s/%s" % (folder_or_file, fname))
    elif os.path.isfile(folder_or_file) and folder_or_file.endswith('.yaml'):
        files.append(folder_or_file)
    if not files:
        raise RuntimeError("Invalid api_descriptions, need .yaml files")

    methods = {}
    for fname in files:
        try:
            load_yaml(open(fname), methods, base_url)
        except Exception:
            print("Couldn't load %s" % fname)
    return methods
