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
import json
import boto3
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
    If we try to define a backend that is unsupported, throwself.
    '''
    raise salt.exceptions.NotImplemented()


def get_s3(key, profile):
    '''
    Fetch state file from s3 bucket. Currently only supports IAM roles,
    .aws/credentials files and env_vars.
    TODO: support caching.
    '''
    s3_res = boto3.resource('s3')
    s3_res.Object(profile.get('bucket'), profile.get('key')).download_file('/tmp/salt_tfstate')
    return parse_tfstate_file(key, '/tmp/salt_tfstate')


def get_file(key, profile):
    '''
    Fetch tfstate from a file.
    '''
    return parse_tfstate_file(key, profile.get('tfstatefile'))


def parse_tfstate_file(full_key, file_path):
    '''
    Parse the provided tfstate file, and search for the keyself.
    TODO: support array values
    TODO: support splat values
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

    if key_parts[0] == 'module':
        ## we're checking for a module
        mod_path = 'root:{}'.format(key_parts[1])
        key_parts = key_parts[2:]
    else:
        mod_path = 'root'

    ## TODO: add support here for indexed and splat-style operators.
    resource = data.get('modules').get(mod_path).get('resources').get('.'.join(key_parts))

    return resource.get('primary').get('attributes').get(attr)
