from extras.scripts import *
from dcim.models import Device, Interface
from ipam.models import VLAN, VLANGroup
from dcim.choices import InterfaceModeChoices
from jinja2 import Template
from core.models import ObjectChange
from django.contrib.contenttypes.models import ContentType
import urllib.parse

class UpdateInterfaceScript(Script):
    class Meta:
        name = "Update Interface Descriptions, VLANs, and Mode"
        description = "Update interface descriptions, VLAN groups, VLANs, and mode for a device"
   
    site = ObjectVar(
        model=Site,
        label="Site",
        description="Select the site to filter devices and VLAN groups"
    )
     
    device = ObjectVar(
        model=Device,
        label="Device",
        query_params={
            "status": "active",
            "role_id": "1"
        },
        description="Select the device you want to update interfaces for"
    )
    interfaces = MultiObjectVar(
        model=Interface,
        label="Interfaces",
        query_params={"device_id":"$device"},
        description="Select the interfaces you want to update"
    )
    interface_description = StringVar(
        label="Description",
        required=False,
        description="Provide the new description for the interfaces (optional)"
    )
    mode = ChoiceVar(
        choices=InterfaceModeChoices,
        label="Interface Mode",
        required=False,
        description="Select the mode for the interfaces (optional)"
    )
    vlan_group = ObjectVar(
        model=VLANGroup,
        label="VLAN Group",
        query_params={"site_id": "$site"},
        required=False,
        description="Select the VLAN Group (optional)"
    )
    untagged_vlan = ObjectVar(
        model=VLAN,
        label="Untagged VLAN",
        query_params={"group_id": "$vlan_group"},
        required=False,
        description="Select the untagged VLAN (optional)"
    )
    tagged_vlans = MultiObjectVar(
        model=VLAN,
        label="Tagged VLANs",
        query_params={"group_id": "$vlan_group"},
        required=False,
        description="Select the tagged VLANs (optional)"
    )

    def run(self, data, commit):
        # Retrieve the selected interfaces
        interfaces = data['interfaces']

        # Capture the pre-change snapshot and process updates for each interface
        for interface in interfaces:
            if interface.pk and hasattr(interface, 'snapshot'):
                interface.snapshot()

            # Update interface description if provided
            if data['interface_description']:
                interface.description = data['interface_description']
                self.log_success(f"Updated description for interface '{interface}': {data['interface_description']}")
            else:
                self.log_info(f"Description field was left blank for interface '{interface}' and was not modified.")

            # Update interface mode if provided
            if data['mode']:
                interface.mode = data['mode']
                self.log_success(f"Updated mode for interface '{interface}' to: {data['mode']}")

            # Update VLAN assignments
            vlan_group = data.get('vlan_group')

            if data['untagged_vlan']:
                interface.untagged_vlan = data['untagged_vlan']
                self.log_success(f"Assigned untagged VLAN for interface '{interface}': {data['untagged_vlan']}")

            # Save the interface and create ObjectChange log entry
            if commit:
                interface.full_clean()
                interface.save()
                self.log_success(f"Interface '{interface}' updated successfully.")

            if data['tagged_vlans']:
                interface.tagged_vlans.set(data['tagged_vlans'])
                self.log_success(f"Assigned tagged VLANs for interface '{interface}': {', '.join([str(vlan) for vlan in data['tagged_vlans']])}")

        # Log the request ID and generate URLs for each interface
        request_id = self.request.id  # Reference the request ID
        
        for interface in interfaces:
            try:
                # Fetch the ObjectChange entry related to this interface and request ID
                change_log_entry = ObjectChange.objects.get(
                    request_id=request_id, 
                    changed_object_type=ContentType.objects.get_for_model(interface), 
                    changed_object_id=interface.pk
                )
                change_log_url = change_log_entry.get_absolute_url()  # Get URL for the change log entry
                
                # Log the request ID and change log URL for the interface
                self.log_info(f"Change Log for Interface '{interface}': Request ID [{request_id}]({change_log_url})")
            except ObjectChange.DoesNotExist:
                # Handle the case where no change log entry is found for this interface
                self.log_info(f"Change Log for Interface '{interface}': Request ID {request_id} (No change log entry found.)")
            except Exception as e:
                # Log any other unexpected exceptions
                self.log_info(f"An error occurred while retrieving the change log entry for interface '{interface}': {str(e)}")

        # Generate a base URL with the form data for rerun
        base_link = self.request.path + "?"

        # Append other form data parameters to the base link
        for d in data:
            if isinstance(data[d], (str, int)):  # Simple types (string, int)
                base_link += f"{d}={urllib.parse.quote_plus(str(data[d]))}&"
            elif hasattr(data[d], 'id'):  # Handle NetBox objects with an 'id' attribute (e.g., VLAN, VLAN group)
                base_link += f"{d}={data[d].id}&"
            elif hasattr(data[d], 'all'):  # Handle other multi-object vars (if needed in future)
                for item in data[d].all():  # Iterate over each item in the collection
                    base_link += f"{d}={item.id}&"  # Append each ID separately

        # Remove the last '&' if it exists
        link = base_link.rstrip('&')

        # Log the clickable link
        log_line = f"[CLICK HERE TO RUN AGAIN]({link})"
        self.log_info(log_line)  # Log the clickable link

        # Template for generated configuration
        template_str = """
        config
        {%- for interface in interfaces %}
        interface {{ interface.name }}
            {%- if interface.description %}
            description {{ interface.description }}
            {%- endif %}
            {%- if interface.mode == "access" %}
            vlan access {{ interface.untagged_vlan.vid }}
            {%- elif interface.mode == "tagged" %}
            vlan trunk native {{ interface.untagged_vlan.vid }}
            vlan trunk allowed {{ interface.tagged_vlans.all()|map(attribute='vid')|join(',') }}
            {%- elif "tagged-all" in interface.mode %}
            vlan trunk allowed all
            {%- endif %}
        {%- endfor %}
        """
        # Prepare the Jinja2 template
        template = Template(template_str)

        # Render the interface configuration for the selected interfaces
        rendered_output = template.render(interfaces=interfaces)

        # Output the rendered configuration inside a code block
        self.log_info(f"Generated Interface Configuration:\n{rendered_output}")