"""Hammer offsets operations."""
from __future__ import annotations

RVA_CDATAMODEL_GLOBAL = 0x24BBE00   # CDataModel 全局单例（CE 实测：该处 RTTI == CDataModel）

RVA_CDATAMODEL_PTR_GLOBAL = 0x21B6958  # qword 指针，值 = base+0x24BBE00

RVA_CDATAMODEL_VTABLE = 0x16C45D8   # 用于运行前校验（CE 实测：该单例的 vptr）

UNDO_MANAGER_OFFSET = 240           # CUndoManager 内嵌在 CDataModel + 240（不变）

RVA_CDATAMODEL_UNDO = 0x5C34E0      # 带 UI 通知(vfn+1040)的包装

RVA_CDATAMODEL_REDO = 0x5C1560

RVA_UNDO_MANAGER_UNDO = 0x60FC50    # CUndoManager::Undo 本体（带 profile）

RVA_UNDO_MANAGER_REDO = 0x60F7C0    # CUndoManager::Redo 本体

UNDO_MGR_OFF_UNDO_COUNT = 0

UNDO_MGR_OFF_REDO_COUNT = 16

APP_OFF_SESSION_VEC_COUNT = 0x58

APP_OFF_SESSION_VEC_MEM = 0x60

SESSION_OFF_ACTIVE_WRAPPER = 0x138

WRAPPER_DOC_EMBED_OFFSET = 0x10

CMAPDOC_ROOT_OFFSET = 0x80           # CMapDoc -> CMapRootElement*

RVA_CMAPROOT_VTABLE = 0x1765FA8      # CE 实测：全进程仅 1 个对象持此 vptr（即 root）

RVA_MAP_HISTORY_VTABLE = 0x1765E00   # CMapDocHistory vtable（CE 实测 RTTI）

ROOT_OFF_UNDO_HISTORY = 0x240

ROOT_OFF_REDO_HISTORY = 0x248

HISTORY_OFF_COUNT = 0x08

HISTORY_OFF_ARRAY = 0x10

HISTORY_OFF_PAIR = 0x80

RVA_MAP_HISTORY_POP = 0x152B910

RVA_MAP_HISTORY_GATE = 0x221A418

RVA_MAP_HISTORY_PUSH_STEP = 0x152AD20   # sub_181529290(hist, name, 0, 0) 压入具名步（并清空重做栈）

RVA_MAP_HISTORY_REC_ADDED = 0x152AB40   # sub_1815290B0(hist, node) 记录「对象被新增」(kind=2)

RVA_MAP_HISTORY_REC_REMOVED = 0x152A950  # sub_181528EC0(hist, node) 记录「对象被移除」(kind=1)

RVA_MAP_HISTORY_NOTIFY = 0x152B190      # sub_181529700(hist, 2) 通知监听者（刷新 Undo 菜单/工具态）

RVA_HIST_RECORD_NODE = 0x86DD30

NODE_IFACE_OFFSET = 0xC8                # CDmElement -> 内嵌的 CMapNode 接口子对象

MAIN_THREAD_STATUS_NAMES = {
    0: "成功",
    1: "等待超时（目标函数未返回，可能卡住）",
    2: "未找到主线程",
    3: "SetWindowsHookEx 失败",
    4: "调用中触发异常（已由 SEH 捕获，宿主进程未受影响）",
}

MAX_READ_CHUNK = 8192  # DLL 侧 read_memory 单次上限（injected_dll/ipc_pipe.cpp kMaxReadSize）

MAP_DOC_PATH_OFFSET = 0x6A0   # CMapDoc -> 地图全路径（CUtlString，+0 即 char*）

RVA_QT_ALL_WIDGETS = 0xE270        # QApplication::allWidgets()   @ Qt5Widgets

RVA_QT_TOPLEVEL_WIDGETS = 0x17A80  # QApplication::topLevelWidgets() @ Qt5Widgets

RVA_QT_MENUBAR = 0x135220          # QMainWindow::menuBar()       @ Qt5Widgets

RVA_QT_ACTION_TEXT = 0xB340        # QAction::text()              @ Qt5Widgets

RVA_QT_ACTION_TRIGGER = 0xBBC0     # QAction::trigger()           @ Qt5Widgets

RVA_QT_ACTION_MENU = 0x8010        # QAction::menu()              @ Qt5Widgets

RVA_QT_WIDGET_ACTIONS = 0x32E70    # QWidget::actions()           @ Qt5Widgets

RVA_QT_INHERITS = 0x290560         # QObject::inherits(const char*) @ Qt5Core

RVA_HAMMER_SAVE_DOC = 0x1639F0

RVA_CMAPENTITY_VTABLE = 0x175AD00   # ??_7CMapEntity@@6B@（CE 实测 RTTI + 67 个对象持有）

RVA_CMAPWORLD_VTABLE = 0x1774920    # CMapWorld（CE 实测 RTTI + 1 个对象持有）

RVA_CMAPGROUP_VTABLE = 0x178D4A8    # CE 实测 RTTI

CMAPDOC_WORLD_OFFSET = 0x88         # CMapDoc -> CMapWorld*（136，旧版同偏移）

RVA_BIND_TARGET_LIST = 0x2731E98    # 链表头（qword_18272D898）

BIND_VFN_NAME = 0                   # vtable[0]  = 取工具名 (char*)

BIND_VFN_CMD_COUNT = 24             # vtable[24] = 命令数 (int)

BIND_VFN_CMD_AT = 32                # vtable[32] = 取第 i 个命令 (命令对象*)

BIND_OFF_CLASS = 0x18               # 类名 char*（KV 里的 "ClassName"）

BIND_OFF_FILE = 0x20                # 注册处源文件（CBufferString）

BIND_OFF_LINE = 0x28                # 注册处行号 (u32)

BIND_OFF_NEXT = 0x38                # next

BIND_CMD_OFF_NAME = 0x08            # 命令对象：命令名 char*

BIND_CMD_OFF_DESC = 0x18            # 命令对象：描述 char*

NODE_OFF_CHILD_COUNT = 0x1F8

NODE_OFF_CHILD_HANDLES = 0x200

ELEMENT_OFF_ATTR_HEAD = 0x48        # CDmAttribute 侵入式链表头（沿 attr+0 串起）

ATTR_OFF_NEXT = 0x00                # 40 字节一个属性

ATTR_OFF_VALUE = 0x08               # 值存储指针

ATTR_OFF_OWNER = 0x10               # 所属 element 回指

ATTR_OFF_TYPE = 0x1C                # 低 6 位为类型（字符串 type=5 时此字节=0x5）

ATTR_OFF_NAME = 0x20                # CUtlSymbolLarge 即裸 char*

DM_ATTR_TYPE_STRING = 5             # AT_STRING

DM_ATTR_TYPE_BOOL = 4               # AT_BOOL —— **值存储只占 1 字节**

DM_ATTR_TYPE_ID = 15                # referenceID 之类的 8 字节对象 ID

DM_ATTR_TYPE_ARRAY_UNK = 34         # CUtlVector 数组，但元素类型尚未确定

DM_ATTR_TYPE_NAMES = {
    DM_ATTR_TYPE_STRING: "string",
    1: "element_handle",
    2: "int", 3: "int", 7: "int",
    DM_ATTR_TYPE_BOOL: "bool",
    8: "color",
    10: "vec3",
    DM_ATTR_TYPE_ID: "id",
    33: "element_array",
    DM_ATTR_TYPE_ARRAY_UNK: "array",
    37: "string_array",
}

RVA_ELEMENT_MARK_DIRTY = 0x5C8540

DATAMODEL_VFN_RESOLVE_HANDLE = 168

ENTITY_PROPS_ATTR_NAME = "entity_properties"

ENTITY_TARGETNAME_ATTR = "name"      # 实体自身链上的 'name' 属性即 targetname

RVA_DATAMODEL = RVA_CDATAMODEL_GLOBAL

VFN_OFF_INTERN_STRING = 424

RVA_ATTR_SET_SYMBOL = 0x5CF3A0

RVA_PROPS_SET_STRING_ATTR = 0x62CD20

RVA_PROPS_FIND_ATTR = 0x5C74F0

RVA_ENTITY_SET_KEYVALUE = 0x83E450

RVA_ENTITY_SET_NODE_ATTR = 0x86B8D0

ENTITY_OFF_PROPS_HANDLE = 1336

ENTITY_VFN_SET_CLASSNAME = 2144

RVA_NODE_POST_CLASS = 0x8670F0     # sub_180866D70(node, flag)

RVA_NODE_ADD_CHILD = 0x8794F0      # sub_180879170(doc, child, siblingOr0)

RVA_NODE_GET_PARENT = 0x865220     # sub_180864EA0(node) -> 父节点（实测：func_brush 的父就是 CMapWorld）

RVA_NODE_GET_ROOT = 0x865230       # sub_180864EB0(node) -> 根/世界（实测全部实体都指向 CMapWorld）

NODE_VFN_REMOVE_CHILD = 0x1D0

RVA_PARTICLE_SET_DEFINITION = 0x7F56D0

RVA_CPARTICLE_HELPER_VTABLE = 0x17520B8   # CE 实测 RTTI（primary，coloff=0）

CMAPENTITY_SIZE = 6232              # CMapEntity 对象大小（工厂 sub_180898D10 分配）

OFF_HELPER_ENTITY_HANDLE = 152      # helper+0x98 = 所属实体句柄(u32)

OFF_HELPER_EFFECT_NAME = 176        # helper+0xB0 = effect_name (CUtlString)

OFF_HELPER_DEFINITION = 184          # helper+0xB8 = 解析出的粒子定义指针

ENTITY_OFF_ORIGIN = 0xA0             # Vec3D 世界坐标

ENTITY_OFF_ANGLES = 0xAC             # Vec3D 欧拉角（度）

ENTITY_OFF_SCALES = 0xB8             # Vec3D 缩放（新建时为 1,1,1）

TRANSFORM_ATTR_OFFSETS = {
    "origin": ENTITY_OFF_ORIGIN,
    "angles": ENTITY_OFF_ANGLES,
    "scales": ENTITY_OFF_SCALES,
}

ARR_OFF_SIZE = 0x00

ARR_OFF_DATA = 0x08

ARR_OFF_ALLOC = 0x10

ENTITY_OFF_CONN_COUNT = 0x4A0   # CUtlVector<Conn> m_nSize

ENTITY_OFF_CONN_DATA = 0x4A8    # Conn* m_pMemory

ENTITY_OFF_CONN_ALLOC = 0x4B0   # m_nAllocation

CONN_STRIDE = 0x50              # sizeof(Conn) = 80

CONN_OFF_SOURCE = 0x00          # CUtlString sourceEntity（触发者名字，通常空）

CONN_OFF_OUTPUT = 0x08          # CUtlString output（输出名，如 OnStartTouch）

CONN_OFF_TARGET = 0x10          # CUtlString targetEntity（如 !self）

CONN_OFF_INPUT = 0x18           # CUtlString input（如 Kill）

CONN_OFF_PARAM = 0x20           # CUtlString param（覆盖参数）

CONN_OFF_TYPE = 0x28            # int ioTargetType（新建默认 7）

CONN_OFF_PARAMMAP = 0x30        # KV3 值 m_paramMap（16 字节，Hammer 用 sub_1813E79E0 初始化）

CONN_OFF_DELAY = 0x40           # float delay

CONN_OFF_TIMES = 0x44           # int timesToFire（-1 = 无限）

CONN_OFF_RELAY = 0x48           # bool relayConnection

CONN_OFF_GLOBAL = 0x49          # bool fromGlobalRelay

CONN_OFF_UNIQUE = 0x4C          # int 唯一 id（Hammer 分配，仅 UI 用）

IO_TARGET_TYPE_NAMES = {
    -1: "ENTITY_IO_TARGET_INVALID",
    2: "ENTITY_IO_TARGET_ENTITYNAME",
    6: "ENTITY_IO_TARGET_EHANDLE",
    7: "ENTITY_IO_TARGET_ENTITYNAME_OR_CLASSNAME",
}

RVA_ENTITY_ADD_CONN = 0x987220

RVA_ENTITY_REMOVE_CONN = 0x987E70

RVA_CONN_VALUE_INIT = 0x13E9470

ENTITY_ATTR_CONNECTIONS = "connectionsData"   # 元素句柄数组 -> DmeConnectionData

ENTITY_ATTR_RELAY_PLUGS = "relayPlugData"     # -> DmePlugList

IO_CONN_FIELDS = ("outputName", "targetType", "targetName", "inputName",
                  "overrideParam", "delay", "timesToFire")

IO_PLUG_FIELDS = ("names", "dataTypes", "plugTypes", "descriptions")

RVA_CMAPMESH_VTABLE = 0x176D8E0     # CE 实测 RTTI + 21 个对象持有

RVA_CDMEPOLYGONMESH_VTABLE = 0x1D73360   # CE 实测 RTTI == CDmePolygonMesh（无需改）

RVA_MESH_SET_VERTEX_POSITIONS = 0x9B8C00

RVA_POLY_SET_VERTEX_POSITIONS = 0xCDCC10

RVA_MESH_BUILD_FACE = 0x9022C0       # sub_180901F40(el, 点数组, 默认贴图轴, 点数, 材质名)

RVA_POLY_MERGE_VERTICES = 0xCD2710

RVA_POLY_REMOVE_ISOLATED = 0xCD88F0

RVA_CHAMMERPOLYMESH_VTABLE = 0x1768ED8   # CE 实测 RTTI == CHammerPolyMesh（21 个对象持有）

RVA_CPOLYGONMESH_VTABLE = 0x18163D0      # CE 实测 RTTI == CPolygonMesh

MESH_OFF_POLYMESH = 0x498            # CMapMesh 内嵌 CHammerPolyMesh 的偏移

MESH_OFF_POLYMESH_BACKPTR = 0x560    # 指回内嵌 CHammerPolyMesh 的指针

MESH_OFF_AABB = 0x118                # CMapMesh 缓存的 AABB（空 mesh = ±FLT_MAX）

POLY_OFF_VPOOL_CNT = 0x18            # 顶点记录池(32B/条)：活顶点数

POLY_OFF_VPOOL_PTR = 0x20

POLY_OFF_VPOOL_CAP = 0x28            # 顶点池槽位容量（槽位数，不是字节数）

POLY_OFF_VMAP_CNT = 0x30             # 顶点 handle -> 池槽位（24B/条，句柄在 +8）

POLY_OFF_VMAP_PTR = 0x38

POLY_OFF_HEPOOL_PTR = 0x58           # 半边记录池(80B/条)

POLY_OFF_HEMAP_CNT = 0x68

POLY_OFF_HEMAP_PTR = 0x70

POLY_OFF_FPOOL_CNT = 0x88            # 面记录池(32B/条)

POLY_OFF_FPOOL_PTR = 0x90

POLY_OFF_FMAP_CNT = 0xA0

POLY_OFF_FMAP_PTR = 0xA8

POLY_OFF_CH_CTL = 0x688              # 通道集控制字：低字节==2，次字节==位置通道序号

POLY_OFF_CH_FLAGS = 0x8CC            # 逐通道 present 标志（0x8CC + 通道号）

POLY_OFF_CH0 = 0x8D8                 # 通道描述符数组（24B/项）

POLY_CH_STRIDE = 24

VREC_OFF_POS_INDEX = 0x10            # 顶点记录 +0x10 = 位置通道数据下标

HEC_OFF_ORIGIN_VERTEX = 0x00         # 半边记录 +0 = 起点顶点 handle（低 22 位为索引）

HEC_OFF_NEXT = 0x20                  # 半边记录 +0x20 = 下一条半边 handle

FACE_OFF_FIRST_HE = 0x00             # 面记录 +0 = 首条半边 handle

POLY_HANDLE_MASK = 0x3FFFFF          # handle 低 22 位 = 索引

POLY_HANDLE_INVALID = 0x3FFFFF

POLY_HANDLE_SERIAL_MASK = 0xFFC00000

POLY_OFF_HE_DENSE = 0x1110           # 「密集序 -> 半边 handle 索引」映射表（16B/条）

POLY_OFF_HE_TEXCOORD = 0x1240        # 每半边 texcoord（Vec2，按密集序）

POLY_OFF_HE_NORMAL = 0x1328          # 每半边 normal（Vec3）

POLY_OFF_HE_TANGENT = 0x1428         # 每半边 tangent（Vec4，w=手性）

POLY_OFF_FACE_SCALE = 0x3118         # 每面 textureScale（Vec2，Hammer 默认 0.125）

POLY_OFF_FACE_AXIS_U = 0x3300        # 每面 textureAxisU（Vec4）

POLY_OFF_FACE_AXIS_V = 0x3318        # 每面 textureAxisV（Vec4）

POLY_OFF_FACE_MATINDEX = 0x33B8      # 每面 materialindex（int，索引进材料名表；-1 = 无）

POLY_OFF_MATERIALS = 0x3448          # 材料名表 CUtlVector<CUtlString>：count@+0 / data@+8

POLY_CUTLSTRING_SIZE = 16            # CUtlString 记录步长，条首 qword = 名字指针

MESH_ATTR_DATA = "meshData"          # CMapMesh -> CDmePolygonMesh

MESH_ATTR_MATERIALS = "materials"    # CDmePolygonMesh -> 材质名数组

MESH_ATTR_STREAMS = "streams"        # CDmePolygonMeshDataArray -> [CDmePolygonMeshDataStream]

MESH_STREAM_ATTR_SEMANTIC = "semanticName"

MESH_STREAM_ATTR_DATA = "data"

MESH_STREAM_COMPONENTS = {
    "position": 3, "texcoord": 2, "normal": 3, "tangent": 4,
    "materialindex": 1, "flags": 1, "lightmapScaleBias": 1,
    "textureScale": 2, "textureAxisU": 4, "textureAxisV": 4,
}

MESH_ATTR_VERTEX_DATA = "vertexData"

MESH_ATTR_FACE_VERTEX_DATA = "faceVertexData"

MESH_ATTR_FACE_DATA = "faceData"

MESH_ATTR_FACE_DATA_INDICES = "faceDataIndices"

MESH_ATTR_FACE_EDGE_INDICES = "faceEdgeIndices"

MESH_ATTR_EDGE_NEXT_INDICES = "edgeNextIndices"

MESH_ATTR_EDGE_VERTEX_DATA_INDICES = "edgeVertexDataIndices"

RVA_DATAMODEL_CREATE_ELEMENT = 0x5BBF10

RVA_ELEMENT_CREATE_CORE = 0x5BBB70   # sub_1805BB7F0（内部，最终调工厂 Create）

RVA_CMAPENTITY_FACTORY = 0x21DF1F0     # CE 实测：该处首字段 == 工厂 vtable（+0x1767170）

RVA_CMAPENTITY_FACTORY_VTABLE = 0x1767170   # CE 实测 RTTI == CDmElementFactory<CMapEntity>

ENTITY_DMX_TYPE = "CMapEntity"       # 实体在 .vmap 里的元素类型名

ENTITY_CREATE_FLAGS = 1              # 与实体工具一致；!= -1 时登记 CUndoCreateElement 撤销步

INVALID_DMX_HANDLE = 0xFFFFFFFF

RVA_UNDO_SCOPE_BEGIN = 0x60F6F0     # CUndoManager::BeginUndoScope(um, name, desc, flags)

RVA_UNDO_SCOPE_END = 0x60F540       # CUndoManager::EndUndoScope(um, bool abort=0)

UNDO_MGR_OFF_SCOPE_DEPTH = 88       # +0x58（新版；旧版在 +84）

UNDO_MGR_OFF_FLAGS = 132            # +0x84 bit3 = undo 总开关（不变）

UNDO_MGR_FLAG_ENABLED = 0x08

PARTICLE_ENTITY_CLASS = "info_particle_system"

PARTICLE_EFFECT_ATTR = "effect_name"

TEX_DEFAULT_SCALE = 0.125

TEX_DEFAULT_SIZE = 512.0

CMD_OFF_NAME = 0x08

CMD_OFF_HASH = 0x10

CMD_OFF_DESC = 0x18

CMD_BLOCK_BASE = 0x40        # stage 0 的 std::function 块

CMD_BLOCK_STRIDE = 0x40

CMD_STAGE_COUNT = 8

CMD_STAGE_LABELS = {0: "press", 2: "drag", 3: "repeat", 5: "execute", 6: "release"}

CMD_STAGE_AUTO_ORDER = (5, 0, 2, 3, 6, 4, 7, 1)

FN_VT_OFF_DOCALL = 0x10      # functor vtable 槽 2 = _Do_call

FN_OFF_PMF = 0x08

FN_OFF_ADJ = 0x10

FN_OFF_ARG = 0x18

RVA_CHAMMERAPP = 0x677F440          # CE 实测：RTTI == CHammerApp，且 [+0x58] 会话数 == 1

APP_OFF_ACTIVE_SESSION = 0x50        # ModelDoc/Pet App 当前会话指针（RTTI 校验后使用）

APP_OFF_SESSION_COUNT = 0x58         # CHammerApp+0x58 = 编辑器会话 CUtlVector 计数

APP_OFF_SESSION_ARRAY = 0x60         # CHammerApp+0x60 = 会话数组

SESSION_OFF_TOOLMGR = 0x120          # 会话+0x120 = 工具管理器（CToolManager）

TOOLMGR_OFF_COUNT = 0x30             # 工具管理器+0x30 = 工具实例数

TOOLMGR_OFF_ARRAY = 0x38             # 工具管理器+0x38 = 工具实例数组

RTTI_COL_TO_TYPEDESC = 0xC           # MSVC COL+0xC = TypeDescriptor 的 RVA
