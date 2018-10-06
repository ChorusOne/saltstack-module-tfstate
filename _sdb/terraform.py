# -*- coding: utf-8 -*-
# pylint: disable=import-error
'''
Terraform tfstate SDB Module
:maintainer:    Joe Bowman
:maturity:      New
:platform:      all
.. versionadded:: 2018.03
This module allows access to Terraform tfstate using an ``sdb://`` URI.
Base configuration instructions are documented in the execution module docs.
Below are noted extra configuration required for the sdb module, but the base
configuration must also be completed.
Like all sdb modules, the tfstate module requires a configuration profile to
be configured in either the minion configuration file or a pillar. This profile
requires setting the ``driver`` parameter to ``tfstate`` and ``uri`` parameter
to the uri of your state file. Currently supported URIs are local and s3 bucket
based state files.:
.. code-block:: yaml
    mytfstate
      driver: tfstate
Once configured you can access data using a URL such as:
.. code-block:: yaml
    password: sdb://mytfstate/aws_instance.myhost/public_ip
In this URL, ``mytfstate`` refers to the configuration profile,
``aws_instance.myhost`` is the identifier of the resource you wish to query,
and ``public_ip`` is the key of the attribute for which you wish to return data.
'''

# import python libs
from __future__ import absolute_import, print_function, unicode_literals
import logging
import os
import json
import hashlib
import binascii
import boto3
import time
import re
import salt.exceptions

LOG = logging.getLogger(__name__)

__func_alias__ = {
    'set_': 'set'
}


def __virtual__():
    return True


def set_(*args, **kwargs):  # pylint: disable=W0613
    '''
    Setting a value is not supported; edit the YAML files directly
    '''
    raise salt.exceptions.NotImplemented()


def get(key, profile=None):
    '''
    Get a value from the terraform tfstate.
    '''
    backends = {
        'file': get_file,
        's3': get_s3
    }
    try:
        func = backends.get(profile.get('backend'), 'notimplmented_backend')
        retval = func(key, profile)
    except Exception as exception:
        LOG.error('Failed to read value! %s: %s', key, exception)
        raise salt.exceptions.CommandExecutionError(exception)

    return retval


def notimplmented_backend():
    '''
    If we try to define a backend that is unsupported, throw.
    '''
    raise salt.exceptions.NotImplemented()


def get_s3(key, profile):
    '''
    Fetch state file from s3 bucket. Currently only supports IAM roles,
    .aws/credentials files and env_vars.
    '''
    s3_res = boto3.resource('s3')
    hashfunc = hashlib.md5()
    hashfunc.update(profile.get('key'))
    hash = binascii.hexlify(hashfunc.digest())
    if os.path.exists('/tmp/salt_tfstate_{}'.format(hash)) == False:
        print ("Fetching tfstate from s3")
        s3_res.Object(profile.get('bucket'), profile.get('key')).download_file('/tmp/salt_tfstate_{}'.format(hash))
    else:
        stat = os.stat('/tmp/salt_tfstate_{}'.format(hash))
        if stat.st_mtime + profile.get('cache_duration', 60) < time.time():
            print ("Cache is stale; refreshing from s3...")
            s3_res.Object(profile.get('bucket'), profile.get('key')).download_file('/tmp/salt_tfstate_{}'.format(hash))
        else:
            print ("Using cache...")
    return parse_tfstate_file(key, '/tmp/salt_tfstate_{}'.format(hash))


def get_file(key, profile):
    '''
    Fetch tfstate from a file.
    '''
    return parse_tfstate_file(key, profile.get('tfstatefile'))


def parse_tfstate_file(full_key, file_path):
    '''
    Parse the provided tfstate file, and search for the key.
    '''

    key, attr = full_key.split('/')
    key_parts = key.split('.')

    with open(file_path) as tffile:
        data = json.load(tffile)

    ## this looks a little cludgy, but essentially convert the list of modules
    ## to a map using the path (this has to be unique in TF) as the key.
    modules_orig = data.get('modules')
    data.update({'modules': {}})

    for k in modules_orig:
        data.get('modules').update({':'.join(k.get('path')): k})

    result = parse_identifier(key_parts, attr, data)
    if type(result) == 'string':
        return result
    else:
        return json.dumps(result)


def parse_identifier(key_parts, attr, data):
    '''
    Attempt to parse the given identifier. See README.md for more details.
    '''
    if key_parts[0] == 'module':
        ## if we are module.* or module.host_*...then use regexp to gather all the possible modules.
        if '*' in key_parts[1]:
            pattern = re.compile(key_parts[1].replace('*','.+'))
            mod_paths = [part for part in data.get('modules') if pattern.search(part)]
        ## otherwise, just split by comma for the possible module paths i.e. module.host_saltmaster,host_dns...
        else:
            mod_paths = ['root:{}'.format(part) for part in key_parts[1].split(',')]
        key_parts = key_parts[2:]
    else:
        ## no module, just the root.
        mod_paths = ['root']

    if key_parts[0] == 'output':
        ## we only care about outputs.
        result = [data.get('modules', {}).get(p, {}).get('outputs', {}).get(key_parts[1], {}).get('value', '') for p in mod_paths]
    else:
        ## fetch one or more resources
        result = [fetch_resource(key_parts, attr, data.get('modules', {}).get(p, {}).get('resources', {})) for p in mod_paths]
    return flatten(result)


def flatten(result):
    '''
    Flatten any lists containing a single value.
    '''
    if type(result) in [list, tuple, set]:
        if len(result) == 1:
            return flatten(result[0])
        else:
            return [flatten(x) for x in result]
    else:
        return result


def fetch_resource(key_parts, attr, data):
    '''
    Fetch the resource from a subset of data, given a reference.
    '''
    ### combine the key_parts, see we can check for the existence of wildcarc character or commas, which we handle differently.
    resource_key = '.'.join(key_parts)

    if '*' in resource_key:
        ### if one or more wildcard chars are found, replace with .+ and return matches using regexp.
        pattern = re.compile(resource_key.replace('*','.+'))
        resources = [data.get(key) for key in data if pattern.search(key)]
    elif ',' in resource_key:
        ### if we have a comma (we only handle the first comma atm, because otherwise this gets insanely complex), find matches.
        resources = []
        split_part = [k for k in key_parts if ',' in k][0]
        for key_part in split_part.split(','):
            print(resource_key.replace(split_part, key_part))
            resources.append(data.get(resource_key.replace(split_part, key_part)))
    else:
        ### otherwise, fetch the single resource matching the combined key_parts.
        resources = [data.get(resource_key, {})]

    if '*' in attr:
        ### check the attr param for wildcard chars, and go regexp to find matches.
        pattern = re.compile(attr.replace('*','.+'))
        return [{k: resource.get('primary', {}).get('attributes', {}).get(k, None) for k in resource.get('primary', {}).get('attributes', {}) if pattern.match(k)} for resource in resources]
    elif ',' in attr:
        ### as above, handle comma separated attributes.
        return [{k: resource.get('primary', {}).get('attributes', {}).get(k, None) for k in attr.split(',')} for resource in resources]
    else:
        ## otherwise return the full match.
        return [resource.get('primary', {}).get('attributes', {}).get(attr, None) for resource in resources]
