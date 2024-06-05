from typing import Optional

from diffsync import DiffSync
from nautobot.ipam.models import VLAN
from nautobot.apps.jobs import register_jobs, Job
from nautobot_ssot.contrib import NautobotModel, NautobotAdapter
from nautobot_ssot.jobs import DataSource
from pynetbox import api

name = "Custom Jobs"

# Step 1 - data modeling
class VLANModel(NautobotModel):
    """DiffSync model for VLANs."""
    _model = VLAN
    _modelname = "vlan"
    _identifiers = ("vid", "group__name")
    _attributes = ("description",)

    vid: int
    group__name: Optional[str] = None
    description: Optional[str] = None

# Step 2.1 - the Nautobot adapter
class MySSoTNautobotAdapter(NautobotAdapter):
    """DiffSync adapter for Nautobot."""
    vlan = VLANModel
    top_level = ("vlan",)

    def __init__(self, *args, job, **kwargs):
        super().__init__(*args, job=job, **kwargs)

# Step 2.2 - the remote adapter
class MySSoTRemoteAdapter(DiffSync):
    """DiffSync adapter for remote system."""
    vlan = VLANModel
    top_level = ("vlan",)

    def __init__(self, *args, api_client, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_client = api_client

    def load(self):
        for vlan in self.api_client.ipam.vlans.all():
            group_name = vlan.group.name if vlan.group else None
            loaded_vlan = self.vlan(vid=vlan.vid, group__name=group_name, description=vlan.description)
            self.add(loaded_vlan)

# Step 3 - the job
class ExampleDataSource(DataSource, Job):
    """SSoT Job class."""
    class Meta:
        name = "Netbox Nautobot VLAN Sync"
        description = "Sync VLAN vid, group, description from Netbox to Nautobot"

    def init_api(self):
        url = "https://example.com"
        token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        netbox = api(
            url=url,
            token=token,
        )
        netbox.http_session.verify = False
        return netbox

    def load_source_adapter(self):
        netbox_api = self.init_api()
        self.source_adapter = MySSoTRemoteAdapter(api_client=netbox_api)
        self.source_adapter.load()

    def load_target_adapter(self):
        self.target_adapter = MySSoTNautobotAdapter(job=self)
        self.target_adapter.load()

register_jobs(ExampleDataSource)
