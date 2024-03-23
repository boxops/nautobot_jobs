"""
Purpose:
- Provide a job form that will allow you to select a device from Nautobot
- Connect to the device
- Execute a show version on the device
- Parse the output of the show version
- Store the parsed output in a Nautobot model
- Create a relationship between the device and the software version
"""
from django.conf import settings
from django.contrib.contenttypes.models import ContentType

# Import Netmiko to connect to the device and execute commands
from netmiko import ConnectHandler

# Import Nautobot DCIM device models
from nautobot.dcim.models import Device
from nautobot.apps.jobs import register_jobs, Job, ObjectVar, MultiObjectVar
from nautobot.extras.models.secrets import Secret, SecretsGroup
from nautobot.extras.models import Tag, Relationship, RelationshipAssociation
from nautobot_device_lifecycle_mgmt.models import SoftwareLCM

import re
import os

# Setting the name here gives a category for these jobs to be categorized into
name = "Demo Jobs"

class GetShowVersion(Job):
    devices = MultiObjectVar(
        model=Device,
        query_params={
            "has_primary_ip": True, 
            "status": "Active",
            }
        )

    # Describe the class Meta as what information about the Job to pass into Nautobot to help describe the Job
    class Meta:
        name = "Get show version"
        description = "Get the version information from a device"
        # Define task queues that this can run in.
        task_queues = [
            settings.CELERY_TASK_DEFAULT_QUEUE,
            "priority",
            "bulk",
            ]

    # The code execution, all things for the job are here.
    def run(self, devices):

        def print_status(status, message):
            if status == 'info':
                self.logger.info(message)
            elif status == 'success':
                self.logger.success(message)
            elif status == 'warning':
                self.logger.warning(message)
            elif status == 'failure':
                self.logger.failure(message)

        class OnboardVersion:
            def __init__(self, device):
                self.device = device
                self.supported_drivers = ["keymile_nos", "cisco_xr", "cisco_ios"]
                print_status("info", f"Currently supported platforms: {self.supported_drivers}")

                self.platform = self.device.platform.network_driver

                if self.platform not in self.supported_drivers:
                    raise Exception(f"Device {self.device} with platform {self.platform} is not supported")

                self.device_info = {
                    "device_type": self.platform,
                    "ip": self.device.primary_ip.host,
                    "username": Secret.objects.get(name="SSH_USERNAME").get_value(),
                    "password": Secret.objects.get(name="SSH_PASSWORD").get_value(),
                    "secret": Secret.objects.get(name="SSH_SECRET").get_value(),
                }
                self.show_version_commands = {
                    "arista_eos": "show version",
                    "keymile_nos": "show version",
                    "cisco_xr": "show version",
                    "cisco_ios": "show version | inc Cisco IOS Software"
                }
                self.patterns = {
                    "arista_eos": r"Software image version: (\S+)",
                    "keymile_nos": r"NOS version (\S+)",
                    "cisco_xr": r"Cisco IOS XR Software, Version (\S+)",
                    "cisco_ios": r"Version (\S+)"
                }

                self.raw_version = None
                self.parsed_version = None
                self.nautobot_software = None

            def get_version(self):
                print_status("info", f"Device name: {self.device}")
                print_status("info", f"Device IP: {self.device_info['ip']}")
                print_status("info", f"Device platform: {self.device_info['device_type']}")

                # Ping the device before connecting
                if os.system(f"ping -c 1 {self.device_info['ip']}") != 0:
                    raise Exception(f"Device with IP {self.device_info['ip']} is unreachable")

                with ConnectHandler(**self.device_info) as session:
                    session.enable()
                    self.raw_version = session.send_command(self.show_version_commands.get(self.platform))
                    # print_status("info", self.raw_version)

            def parse_version(self):
                match = re.search(self.patterns.get(self.platform), self.raw_version)
                if match:
                    self.parsed_version = (match.group(1)).strip(',')
                    print_status("info", f"Device software version: {self.parsed_version}")
                else:
                    raise Exception(f"Could not parse, pattern not found in the input string: {self.patterns.get(self.platform)}")

            def import_to_nautobot(self):
                # Check if software exists in nautobot database. If not, create it.
                if SoftwareLCM.objects.filter(version=self.parsed_version).exists():
                    self.nautobot_software = SoftwareLCM.objects.get(version=self.parsed_version)
                    print_status(
                        "info",
                        f"Software version {self.nautobot_software} exists in the database."
                    )
                else:
                    self.nautobot_software = SoftwareLCM(version=self.parsed_version, device_platform=self.device.platform)
                    self.nautobot_software.validated_save()
                    print_status(
                        "info",
                        f"Created software version {self.nautobot_software} in the database."
                    )

            def assign_to_device(self):
                # Check if software to dev relationship already exists. If not, create it.
                software_rel = Relationship.objects.get(label="Software on Device")
                if RelationshipAssociation.objects.filter(
                    relationship=software_rel.id,
                    source_id=self.nautobot_software.id,
                    destination_id=self.device.id,
                ).exists():
                    print_status(
                        "info",
                        f"Relationship {self.device} <-> {self.nautobot_software} exists."
                    )
                else:
                    source_ct = ContentType.objects.get(model="softwarelcm")
                    dest_ct = ContentType.objects.get(model="device")
                    created_rel = RelationshipAssociation(
                        relationship=software_rel,
                        source_type=source_ct,
                        source=self.nautobot_software,
                        destination_type=dest_ct,
                        destination=self.device,
                    )
                    created_rel.validated_save()
                    print_status(
                        "info",
                        f"Created {self.device} <-> {self.nautobot_software} relationship."
                    )

            def execute(self):
                self.get_version()
                self.parse_version()
                self.import_to_nautobot()
                self.assign_to_device()

        for device in devices:
            task = OnboardVersion(device)
            task.execute()

register_jobs(GetShowVersion)
