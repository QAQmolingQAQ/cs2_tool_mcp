import sys

sys.path.insert(0, r"C:\cs2_tool_mcp\mcp_server")
import cs2_mcp_server as m  # noqa: E402

ENT = "0x26366f9d400"
VPCF = "particles/environment/glow01.vpcf"

print("=== 2) cs2_entity_set_classname -> info_particle_system ===")
print(m.cs2_entity_set_classname(ENT, "info_particle_system"))
print()
print("=== 3) cs2_particle_set_definition ===")
print(m.cs2_particle_set_definition(ENT, VPCF))
print()
print("=== 4) 读回 ===")
print(m.cs2_entity_get_attr(ENT, "classname"))
print(m.cs2_entity_get_attr(ENT, "effect_name"))
print()
print("=== 5) 列表 ===")
print(m.cs2_entity_list())
