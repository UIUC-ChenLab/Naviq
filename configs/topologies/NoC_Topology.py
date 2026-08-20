import json

from common import FileSystemConfig
from topologies.BaseTopology import SimpleTopology

from m5.objects import *
from m5.params import *


class NoC_Topology(SimpleTopology):
    description = "NoC_Topology"

    def __init__(self, controllers):
        self.nodes = controllers
        self.use_names = 0
        self.router_latency = 1
        self.link_latency = 1
        self.Router = None
        self.node_dict = {}
        self.file_path = "configs/topologies/basic_setup.ncr"
        self.record_nps = 0
        self.record_nps_gap_cycles = 200

    def set_node_dict(self, node_dict):
        self.node_dict = node_dict

    def set_record_nps(self, record_nps):
        """Propagate to each NocGarnetRouter as SimObject param record_nps (0 = off)."""
        self.record_nps = int(record_nps)

    def set_record_nps_gap_cycles(self, record_nps_gap_cycles):
        """NoC clock cycles between NPS occupancy CSV samples when record_nps is on."""
        self.record_nps_gap_cycles = int(record_nps_gap_cycles)

    @staticmethod
    def _has_simobject_param(simobject_class, param_name):
        return param_name in getattr(simobject_class, "_params", {})

    def _router_kwargs(self):
        kwargs = {}
        if self._has_simobject_param(self.Router, "record_nps"):
            kwargs["record_nps"] = self.record_nps
            kwargs["record_nps_gap_cycles"] = self.record_nps_gap_cycles
        return kwargs

    def set_file_path(self, file_path):
        self.file_path = file_path

    def resolve_node_name(self, full_path, port=None):
        """
        Resolve NCR path to node_dict key name.

        For HBM: uses last 2 path segments (hbm_stX/I_hbm_chnlY) + port
                 e.g., ".../hbm_st0/I_hbm_chnl2" + "PORT0" -> "hbm_st0/I_hbm_chnl2_PORT0"
        For DDR: uses last 2 path segments (inst/MC0_ddrc) + port
                 e.g., ".../inst/MC0_ddrc" + "PORT0" -> "inst/MC0_ddrc_PORT0"
        For Standard: uses last path segment
                 e.g., ".../S00_AXI_nmu" -> "S00_AXI_nmu"
        """
        if "hbm_chnl" in full_path:
            # HBM: use last 2 path segments (stack + channel) + port
            channel_name = "/".join(full_path.split("/")[-2:])
            if port:
                return f"{channel_name}_{port}"
            return channel_name
        elif "ddrc" in full_path.lower() or "MC" in full_path:
            # DDR: use last 2 path segments (inst + controller) + port
            channel_name = "/".join(full_path.split("/")[-2:])
            if port:
                return f"{channel_name}_{port}"
            return channel_name
        else:
            # Standard NMU/NSU: use last path segment
            return full_path.split("/")[-1]

    def check_and_add_router(self, routers, router_string, router_dict):
        # Check if a router with the given id 'n' already exists
        if router_string not in router_dict:
            # print(router_string)
            router_id = len(routers)
            router_dict[router_string] = router_id
            if self.use_names:
                nps_type = 0  # default type
                if "VNOC" in router_string:
                    nps_type = 0
                elif "RPTR" in router_string:
                    nps_type = 2
                elif "NCRB" in router_string:
                    nps_type = 3
                elif "NIDB" in router_string:
                    nps_type = 4
                else:
                    nps_type = 1
                # print("creating nps type", nps_type)
                routers.append(
                    self.Router(
                        router_id=router_id,
                        latency=self.router_latency,
                        nocname=router_string,
                        nps_type=nps_type,
                        **self._router_kwargs(),
                    )
                )
            else:
                routers.append(
                    self.Router(
                        router_id=router_id,
                        latency=self.router_latency,
                        **self._router_kwargs(),
                    )
                )
        return routers, router_dict

    def makeTopology(self, options, network, IntLink, ExtLink, Router):
        nodes = self.nodes
        # print(nodes) # Debug

        link_latency = options.link_latency
        self.router_latency = options.router_latency
        self.use_names = options.noc_names
        self.Router = Router

        routers = []
        ext_links = []
        int_links = []
        links = (
            []
        )  # Tracks (src, dst, src_port, dst_port) tuples to get link_id
        router_dict = {}  # Maps router name -> router index in routers list
        # node_dict maps node name -> index in nodes list (passed in earlier)
        print(f"Node dictionary: {self.node_dict}")  # Debug

        # This list will be populated: routing_list[link_id] = [(src_node_id, dst_node_id, vc_str), ...]
        routing_list_by_linkid = []
        per_net_vc_map_info = []

        with open(self.file_path) as file:
            data = json.load(file)
        paths = data.get("Paths", [])

        for path in paths:
            path_from = path.get("From", "")
            path_to = path.get("To", "")
            path_port = path.get("Port", "")  # HBM paths have Port field

            # Resolve names using helper (handles HBM port-specific naming)
            nmu = self.resolve_node_name(path_from)
            nsu = self.resolve_node_name(path_to, path_port)

            for nets in path.get("Nets", []):
                CommType = nets.get("CommType", "")
                vc_str = nets.get("VC", "")  # Get VC as string first
                req_type = -1
                match CommType:
                    case "READ_REQ":
                        (src_name, dst_name) = (nmu, nsu)
                        req_type = 0  # Assign 0 for READ_REQ
                    case "WRITE":
                        (src_name, dst_name) = (nmu, nsu)
                        req_type = 1  # Assign 1 for WRITE
                    case "READ":
                        (src_name, dst_name) = (nsu, nmu)
                        req_type = 2  # Assign 2 for READ
                    case "WRITE_RESP":
                        (src_name, dst_name) = (nsu, nmu)
                        req_type = 3  # Assign 3 for WRITE_RESP
                    case _:
                        print(
                            f"Warning: Unknown CommType '{CommType}'. Using default direction ({nmu} -> {nsu}) and req_type=-1."
                        )
                        (src_name, dst_name) = (
                            nmu,
                            nsu,
                        )  # Keep default direction assignment
                        # req_type remains -1 (the initialized default)

                connections = nets.get("Connections", [])
                # Ensure src/dst nodes are in the dictionary (mapping name to controller index)
                if (
                    src_name not in self.node_dict
                    or dst_name not in self.node_dict
                ):
                    print(
                        f"Error: Cannot find node IDs for {src_name} or {dst_name}. Skipping net."
                    )
                    continue

                src_node_id = self.node_dict[src_name]
                dst_node_id = self.node_dict[dst_name]

                vc_int = int(vc_str)
                per_net_vc_map_info.append(
                    [src_node_id, dst_node_id, req_type, vc_int]
                )

                for i in range(0, len(connections), 4):
                    src_conn = connections[
                        i
                    ]  # Can be node name or router name
                    src_port = connections[i + 1]  # Outport string
                    dst_conn = connections[
                        i + 2
                    ]  # Can be node name or router name
                    dst_port = connections[i + 3]  # Inport string

                    link_identifier = None
                    current_link_id = -1

                    if i == 0:
                        # External Link: Controller -> Router
                        routers, router_dict = self.check_and_add_router(
                            routers, dst_conn, router_dict
                        )
                        link_identifier = (
                            src_name,
                            dst_conn,
                            "",
                            "",
                        )  # Key by logical endpoint so shared physical HBM ports stay distinct
                        if link_identifier not in links:
                            current_link_id = len(links)
                            el = ExtLink(
                                link_id=current_link_id,
                                ext_node=nodes[
                                    src_node_id
                                ],  # Use controller object
                                int_node=routers[
                                    router_dict[dst_conn]
                                ],  # Use router object
                                latency=link_latency,
                            )
                            ext_links.append(el)
                            links.append(link_identifier)
                            routing_list_by_linkid.append(
                                []
                            )  # Add empty list for this new link
                            # print("adding external link", current_link_id, src_node_id, router_dict[dst_conn]) # Debug
                            # print(nodes[src_node_id])
                        else:
                            current_link_id = links.index(link_identifier)

                    elif i + 5 > len(connections):
                        # External Link: Router -> Controller
                        routers, router_dict = self.check_and_add_router(
                            routers, src_conn, router_dict
                        )
                        link_identifier = (
                            dst_name,
                            src_conn,
                            "",
                            "",
                        )  # Key by logical endpoint so shared physical HBM ports stay distinct
                        if link_identifier not in links:
                            current_link_id = len(links)
                            el = ExtLink(
                                link_id=current_link_id,
                                ext_node=nodes[
                                    dst_node_id
                                ],  # Use controller object
                                int_node=routers[
                                    router_dict[src_conn]
                                ],  # Use router object
                                latency=link_latency,
                            )
                            ext_links.append(el)
                            links.append(link_identifier)
                            routing_list_by_linkid.append(
                                []
                            )  # Add empty list for this new link
                        #  print("adding external link", current_link_id, dst_node_id, router_dict[src_conn]) # Debug
                        #  print(nodes[dst_node_id])
                        else:
                            current_link_id = links.index(link_identifier)

                    else:
                        # Internal Link: Router -> Router
                        routers, router_dict = self.check_and_add_router(
                            routers, src_conn, router_dict
                        )
                        routers, router_dict = self.check_and_add_router(
                            routers, dst_conn, router_dict
                        )
                        link_identifier = (
                            src_conn,
                            dst_conn,
                            src_port,
                            dst_port,
                        )
                        if link_identifier not in links:
                            current_link_id = len(links)
                            il = IntLink(
                                link_id=current_link_id,
                                src_node=routers[router_dict[src_conn]],
                                dst_node=routers[router_dict[dst_conn]],
                                src_outport=src_port,
                                dst_inport=dst_port,
                                latency=link_latency,
                                weight=1,  # Default weight
                            )
                            int_links.append(il)
                            links.append(link_identifier)
                            routing_list_by_linkid.append(
                                []
                            )  # Add empty list for this new link
                            # print("adding internal link", current_link_id, router_dict[src_conn], router_dict[dst_conn]) # Debug
                        else:
                            current_link_id = links.index(link_identifier)

                    # --- Append routing info for this link ---
                    if current_link_id != -1:
                        if i != 0:
                            route_tuple = (src_node_id, dst_node_id, vc_str)
                            # Avoid adding duplicate routes for the same link/src/dst/vc combo
                            if (
                                route_tuple
                                not in routing_list_by_linkid[current_link_id]
                            ):
                                routing_list_by_linkid[current_link_id].append(
                                    route_tuple
                                )
                    else:
                        print(
                            f"Warning: Could not determine link_id for connection {src_conn}->{dst_conn}"
                        )

        # --- Assign components to the network object ---
        network.routers = routers
        network.ext_links = ext_links
        network.int_links = int_links

        # --- Convert routing_list_by_linkid to the flat format ---
        converted_routing_list = []
        for link_id, routes_on_link in enumerate(routing_list_by_linkid):
            for route_tuple in routes_on_link:
                src_node_id, dst_node_id, vc_str = route_tuple
                try:
                    # --- Convert VC string to integer ---
                    # This logic depends on your VC format. If it's complex,
                    # you might need a mapping dictionary or more elaborate parsing.
                    # Assuming simple integer strings like "0", "1", ...
                    vc_int = int(vc_str)
                except ValueError:
                    print(
                        f"Warning: Invalid VC format '{vc_str}' for route {src_node_id}->{dst_node_id} on link {link_id}. Using VC=0."
                    )
                    vc_int = 0  # Default or error VC

                converted_routing_list.append(
                    [link_id, src_node_id, dst_node_id, vc_int]
                )

        # --- Assign the converted list to the network's parameter ---\\
        routing_table_json_string = json.dumps(converted_routing_list)
        print(
            f"Assigning {len(converted_routing_list)} rules to network.custom_routing_table"
        )  # Debug
        print(
            f"Routing table JSON (link_id, src_node_id, dst_node_id, vc_int): \n {routing_table_json_string}"
        )
        network.custom_routing_table_json = routing_table_json_string
        vc_map_info_json_string = json.dumps(per_net_vc_map_info)
        network.route_to_vc_json = vc_map_info_json_string
