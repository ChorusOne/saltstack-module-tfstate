# saltstack-module-tfstate
Saltstack module to access attributes of dynamically created assets directly from Terraform's tfstate file for use in pillar.

## Installation 

1. To use this module, you must ensure that it is available from your master's fileserver root; the easiest way to acheive this is to utilize `gitfs` by adding the following to your /etc/salt/master file:
```
fileserver_backends:
  - root
  - gitfs
  
gitfs_remotes:
  - https://github.com/ChorusOne/saltstack-module-tfstate.git
```

2. and in the same file, for s3 backend:

```
mytfstate:  ##
  driver: terraform
  backend: s3
  bucket: my-bucket-name
  key: my-tfstate-file.tfstate
```

   or, for file-based:
```
mytfstate:
  driver: terraform
  backend: file
  tfstatefile: /opt/terraform/tfstate.tfstate
```

3. Restart `salt-master`
4. Run `sudo salt-run fileserver.update`
5. Run `sudo salt-run saltutil.sync_all`, and look for `sdb.terraform` in the output.

You are ready to use the `sdb://<profile>/<resource_type>.<resource_name>/<attribute>` syntax in your pillar:
```
  ...
  ip: sdb://mytfstate/aws_instance.host/public_ip # for resources created in the environment root
  ...
  ip: sdb://mytfstate/module.my_module.aws_instance.host/private_ip # for resources created by a module
  ...
  {% if salt['sdb.get']('sdb://mytfstate/aws_instance.host/public_ip') == '10.0.0.1' %}
  ...
  {% endif %}
```

