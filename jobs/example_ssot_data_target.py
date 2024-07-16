from typing import Optional

from diffsync import DiffSync
from nautobot.ipam.models import VLAN
from nautobot.extras.jobs import ObjectVar, StringVar # , Job
from nautobot_ssot.contrib import NautobotModel, NautobotAdapter
from nautobot_ssot.jobs import DataTarget
# from diffsync.enum import DiffSyncFlags

from nautobot.apps.jobs import register_jobs #, Job

import requests
import json

name = "Custom Syncing"


# Step 1 - Data Modeling
class VLANModel(NautobotModel):
    """DiffSync model for VLANs."""

    _model = VLAN
    _modelname = "vlan"
    _identifiers = ("vid", "name", "vlan_group__name")
    _attributes = ("description", "status__name")

    vid: int
    name: str
    status__name: str
    vlan_group__name: Optional[str] = None
    description: Optional[str] = None


# Step 2 - The Nautobot Adapter
class MySSoTNautobotAdapter(NautobotAdapter):
    """DiffSync adapter for Nautobot."""

    vlan = VLANModel
    top_level = ("vlan",)


# Step 3.1 - The Remote CRUD operations
class VLANRemoteModel(VLANModel):
    """Implementation of VLAN create/update/delete methods for updating the remote Netbox data."""

    @classmethod
    def create(cls, diffsync, ids, attrs):
        """Create a VLAN record in the remote system."""
        diffsync.post(
            "/api/ipam/vlans/",
            {
                "vid": ids["vid"],
                "name": ids["name"],
                "status": attrs["status__name"].lower(), # "active",
                "group__name": attrs.get("vlan_group__name", None),
                "description": attrs["description"],
            },
        )
        return super().create(diffsync, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update an existing VLAN record in the remote system."""
        data = {}
        if "description" in attrs:
            data["description"] = attrs["description"]
        if "status__name" in attrs:
            data["status"] = attrs["status__name"]
        self.diffsync.patch(f"/api/ipam/vlans/{self.pk}/", data)
        return super().update(attrs)

    def delete(self):
        """Delete an existing VLAN record from the remote system."""
        self.diffsync.delete(f"/api/ipam/vlans/{self.pk}/")
        return super().delete()


# Step 3.2 - The Remote Adapter
class MySSoTRemoteAdapter(DiffSync):
    """DiffSync adapter for remote system."""

    vlan = VLANRemoteModel
    top_level = ("vlan",)

    def __init__(self, *args, url, token, job, **kwargs):
        super().__init__(*args, **kwargs)
        self.url = url
        self.token = token
        self.job = job
        self.headers = {
            "Authorization": f"Token {self.token}",
            "Accept": "application/json",
        }

    def _get_api_data(self):
        requests.packages.urllib3.disable_warnings()
        data = requests.get(
            self.url + "/api/ipam/vlans/", 
            headers=self.headers, 
            verify=False).json()
        result_data = data["results"]
        print(f"Response: {result_data}")
        return result_data

    def load(self):
        for item in self._get_api_data():
            loaded_vlan = self.vlan(
                vid=item["vid"],
                name=item["name"],
                status__name="active", # item["status"],
                vlan_group__name=item["group"]["name"] if item.get("group") else None,
                description=item["description"],
            )
            self.add(loaded_vlan)

    def post(self, path, data):
        """Send an appropriately constructed HTTP POST request."""
        response = requests.post(f"{self.url}{path}", headers=self.headers, json=data, timeout=60, verify=False)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print(f"HTTPError: {e}")
            print(f"Response content: {response.content}")
            raise
        return response

    def patch(self, path, data):
        """Send an appropriately constructed HTTP PATCH request."""
        response = requests.patch(f"{self.url}{path}", headers=self.headers, json=data, timeout=60, verify=False)
        response.raise_for_status()
        return response

    def delete(self, path):
        """Send an appropriately constructed HTTP DELETE request."""
        response = requests.delete(f"{self.url}{path}", headers=self.headers, timeout=60, verify=False)
        response.raise_for_status()
        return response


# Step 4 - The Job
class ExampleDataTarget(DataTarget):
    """SSoT Job class."""

    target_url = StringVar(
    	description="URL for remote Netbox", 
    	default="https://10.1.1.1"
    )
    target_token = StringVar(
    	description="REST API authentication token for remote Netbox", 
    	default="a" * 40
    )

    def __init__(self):
        super().__init__()
        # self.diffsync_flags = (self.diffsync_flags | DiffSyncFlags.SKIP_UNMATCHED_DST)

    class Meta:
        name = "Sync VLANs from Nautobot to Netbox"
        description = "SSoT Example Data Target"
        data_target = "Netbox (remote)"

    def run(self, target_url, target_token, dryrun, memory_profiling, *args, **kwargs):
        self.target_url = target_url
        self.target_token = target_token
        self.dryrun = dryrun
        self.memory_profiling = memory_profiling
        super().run(dryrun, memory_profiling, *args, **kwargs)

    def load_source_adapter(self):
        self.source_adapter = MySSoTNautobotAdapter(job=self, sync=self.sync)
        self.source_adapter.load()

    def load_target_adapter(self):
        self.target_adapter = MySSoTRemoteAdapter(url=self.target_url, token=self.target_token, job=self)
        self.target_adapter.load()


register_jobs(ExampleDataTarget)
