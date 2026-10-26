# Qt hook 接续记录（2026-10-26）

用户明确允许通过 Qt hook 点击选项。此记录不是已实现或已验证声明。

## 已确认

- CE 在上一轮调用期间崩溃，待决工具调用最终均返回无法连接 CE bridge。
  无法确认远程调用是否曾开始，不自动重放、不推断崩溃根因。
- 本轮只读进程检查：CS2 历史 PID22936 仍存在且 Responding=True；后续必须重新核对身份。
- 现有 injected_dll/hammer_bridge.cpp 使用 WH_GETMESSAGE 在选定窗口线程派发。
  GetMainThreadId 选择首个可见无 owner 窗口；其回退枚举也没有验证 Qt 线程。
- 主线程调用将栈上 MainThreadCall 发布给全局裸指针，超时后立即关闭 event 并返回。
  若回调已经取走指针但尚未完成，存在访问失效栈对象/已关闭句柄的竞态风险。
  这是源码审查发现，尚无证据说明它造成了此次 CE 崩溃。
- 历史 qt.py 使用静态 RVA、菜单地址缓存和多次派发；不能直接视为当前版本兼容。

## 实施顺序

1. 修复派发请求生命周期：队列拥有请求，明确 queued/running/completed/cancelled 状态；
   超时仅在未执行时取消，执行中返回 outcome unknown，并保留请求与参数直至完成。
   旧请求不能被新请求覆盖，event 在最后持有者释放后关闭。
2. 通过当前 Qt 导出与实际 Qt 窗口线程绑定主线程派发；不对进程任意首窗假定 Qt 身份。
3. 在 Qt 线程枚举控件/QAction，读取 objectName、文本、类型、父链、enabled/visible。
   对象销毁后失效；禁止跨进程或窗口重建后复用旧地址。
4. 精确选择唯一目标，再在 Qt 线程触发 QAction::trigger 或 QAbstractButton::click。
   查询与动作分开；重名返回候选，不猜测，不自动重试结果未知的动作。
5. 先验证桥接无害派发及枚举，再打开独立 Hammer 测试文档；记录读回。
   隔离文档的属性修改、Undo/Redo、保存和磁盘 hash 验证仍需完成。

Qt hook 是 UI 控制通道，不构成批准旧 Hammer/粒子/模型偏移的依据。
当前没有新增可用点击工具，也没有修改、关闭编辑文档或重启 CS2/CE。

## 已实施：派发请求生命周期（2026-10-26）

上述栈请求问题已在源码修复：共享请求持有 event、参数及RPC字符串分配；
回调进入/取消/完成由同一互斥量协调。排队超时取消，运行中超时保留请求；
旧调用未结束时拒绝新派发。状态1=未执行已取消、5=先前仍在执行、
6=执行结果未知不可自动重试、7=等待失败且未执行。状态改为线程局部。
本修复不保证调用者传入的任意裸指针对象存活；后续Qt专用操作必须管理对象和返回缓冲区。

独立Windows原生测试 injected_dll/tests/dispatch_test.cpp 使用实际WH_GETMESSAGE派发：
- 无消息泵时排队超时，恢复消息泵后未执行；
- 目标执行中超时后字符串/请求owner未提前释放；
- 在途时第二次调用拒绝，原调用仅执行一次；
- 回调完成后owner释放一次，后续无害自检返回正确值。
实际结果 failure=0 entered=1 finished=1 released=1。88项Python测试通过。
CMake/CTest已登记dispatch_lifetime测试（15秒上限）。

VS18 Release编译成功，产物位于 injected_dll/build_vs18/Release/cs2_tool.dll。
build.ps1最后复制根目录DLL因运行中旧DLL文件锁失败；未替换/注入新产物，
没有重启或关闭CS2，也未声称游戏内已验证。Qt线程识别和专用控件点击仍待实施。

## 已实施：Qt窗口线程选择（2026-10-26）

当前CS2只读EnumWindows结果：Qt5152QWindowIcon及五个Qt5152QWindowPopupDropShadowSaveBits
均属于线程24296；SDL_app也在24296，WatchdogThreadWndClass在18912。
这些线程号是本次观察，不能跨进程复用。

GetMainThreadId已枚举当前进程全部原生顶层窗口，识别Qt+版本数字+QWindow类名前缀；
包括隐藏/owned popup；全部Qt候选须同线程。有歧义返回0。
Qt5Widgets已加载而无支持的Qt窗口时返回0，不再选择任意首窗或枚举到的首线程。
无Qt模块的独立宿主仅在可见无owner窗口全部属于同一线程时允许回退。
这验证窗口线程候选，不等于已取得QApplication/QObject身份或可安全调用任何Qt API。

原生测试新增Qt5/Qt5152类名识别、SDL类排除、两个线程各有Qt类窗口时拒绝、
另一个线程窗口销毁后恢复唯一候选。使用模拟类名的真实Win32窗口，未链接真实Qt。
结合实际CS2类名只读观察，不能冒称已在游戏运行新桥接或完成控件点击。
测试及Release构建通过，磁盘DLL按既有原子部署更新；运行模块仍未热更新。

## 新桥接游戏内自检（2026-10-26）

重启前再次核对历史PID22936的路径、创建时间、-tools/-addon test命令行，
完整模块枚举确认无hammer/pet/met/modeldoc_editor，随后重启该隔离实例。
新历史PID25944通过现有普通LoadLibrary注入器加载桥接；不依赖CE。
自检确认桥接磁盘SHA24249496a12a5b9bf981b829ef2defd3543e84edd89ac62b0260b7b89eceb025，
加载PE头与磁盘一致，initialized=false，addon=test，写入拒绝验证通过。

main_thread_selftest现在归纯诊断白名单：它只能调用桥接内部固定无害函数，
忽略任意目标地址，不开放call_function/initialize或编辑器偏移操作。
新增白名单回归测试；完整89项Python测试通过。
scripts/check_session_mcp.py新增--verify-dispatch，校验与stdio报告相同PID、
status=0、跨线程、固定返回值，并保存完整结果。

实机两次成功：Qt窗口线程25532、管道线程20924/13912，返回0x43533254434f4445。
期间一次调用返回main_thread_id=0/status=2，未执行目标；外部只读枚举仍见唯一Qt线程，
具体原因尚未确定。随后只重试固定无害自检成功，未重试未知结果的编辑动作。
这说明主线程派发已在游戏执行，但候选发现存在一次暂时失败，不能宣称绝对可靠。
最终报告C:\CS2_Temp\mcp_qt_dispatch_live.json。
Qt控件枚举/安全点击、未保存状态/Undo/Redo仍待实现验证。

## 已实施：只读Qt控件快照（2026-10-26）

新增bridge工具cs2_qt_widgets(offset=0,limit=128)，IPC为qt_widgets_snapshot。
仅由内部固定适配器在Qt窗口线程调用导出；无调用者指定函数/对象地址。
支持Qt5Core/Qt5Widgets当前加载PE timestamp/SizeOfImage及必要修饰导出检查，
不支持时拒绝。这不是密码学模块鉴定，也不是任何编辑器偏移的可写profile。
Qt数据布局核对Qt 5.15.2官方源码：
https://github.com/qt/qtbase/blob/v5.15.2/src/corelib/tools/qlist.h
https://github.com/qt/qtbase/blob/v5.15.2/src/corelib/tools/qarraydata.h
https://github.com/qt/qtbase/blob/v5.15.2/src/corelib/tools/qrefcount.h

读回当前QApplication::allWidgets，返回地址、QWidget/QAbstractButton分类、objectName、
按钮text、PID/线程/总数。分类不是完整具体类名；不读取密码编辑框等文本值。
字符串截取256 UTF16单元，分页最多128；顺序不稳定、跨页非一致快照。
地址仅本次观察可用，未作为操作句柄缓存。无enabled/visible/父链及点击能力。
QString调用Qt析构，QList按共享引用计数释放；请求运行中超时仍保有结果上下文。
独立原生测试补充Unicode、非法字符串异常清理和静态/共享/最后引用列表释放路径。

加载该构建前核对上一隔离PID25944身份、创建时间及无四类编辑器模块后重启，
新历史PID20952，桥接SHA14dac0d5298476adda8f4c4bcaf21fe6e6bd2eef6ef4c67801880c078af681eb。
启动早期仅SDL/watchdog窗口时返回status2；后续Qt窗口出现后成功。
实际stdio MCP读回337个控件，线程25760；page0含Particle Editor、ModelDoc Editor、
Material Editor，page128含Hammer (Map Editor)。只查询，没有触发按钮。
报告C:\CS2_Temp\qt_widgets_mcp_page0.json、qt_widgets_mcp_page128.json；
版本/写入拒绝/主线程自检报告mcp_qt_snapshot_live.json，同目录。

87工具（bridge37，其余scope未增加），91项Python测试通过，原生测试及Release构建通过。
复现：python scripts/qt_widgets_mcp.py --offset 128 --report <本地报告路径>。
下一步专用Qt动作需在同一Qt线程重新定位唯一目标、校验启用/可见、观察动作结果；
不能直接使用本次返回地址跨请求点击，不能据只读成功放开旧Hammer写入。

## 已实施：Qt编辑器启动（2026-10-26）

新增cs2_qt_open_editor(editor,confirm=false)，仅hammer/pet/met/modeldoc_editor四种。
默认预览；同一个Qt线程任务重新枚举全部控件，以固定完整按钮文字唯一匹配，
校验QWidget::isVisible/isEnabled，再调用QAbstractButton::click。
禁止传入对象/函数地址，不复用快照缓存。目标模块已加载返回already_loaded_no_click，
不再点击；这不保证窗口仍打开或可见。click_returned只表示调用返回，editor_ready_verified=false。
超时拒绝自动重试；运行中请求仍由既有派发机制持有。

该操作属于独立STABLE_UI_METHODS，而非只读诊断；使用固定Qt ABI/导出检查，
允许在编辑器偏移尚未核准时打开工具窗口，不放开任意call_function/initialize/文档写入。
本工具只启动编辑器窗口，不打开或保存文档。Python限制editor和bool；原生再次限制。
未对其余三个编辑器做点击实测，不能据Hammer成功声称全部验证。

核对前一隔离实例身份/无编辑器模块后重启并注入；当前历史PID22360、
Qt线程5688、桥接SHA9a224e38a4b08f53e680cfb225d5a51df5506c1a094b32158ba4f70d56ee0536。
启动早期无Qt窗口时预览返回status2，后续预览成功。
真实stdio执行Hammer一次点击→click_returned；独立模块枚举确认hammer.dll加载，
Qt控件由337变1844且出现Block Tool、Insert logic_relay等Hammer控件。
再次confirm返回already_loaded_no_click，未重复点击。未打开地图或编辑文档。
版本自检、原生写入拒绝、无害跨线程自检复测通过。
报告C:\CS2_Temp\qt_hammer_preview.json、qt_hammer_click.json、qt_hammer_loaded_no_click.json、
qt_after_hammer_click.json、mcp_hammer_launch_live.json。

复现预览：python scripts/qt_widgets_mcp.py --editor hammer --report <路径>；
执行添加--confirm。88工具/bridge38、93项Python测试通过，原生测试/Release构建通过。
后续不再因为部署需要重启这个已加载Hammer的进程；先确认文档状态，保留可能的未保存编辑。

## 2026-10-26 Qt菜单查询（实际148项）

新增只读bridge工具cs2_qt_menu_actions(window_object_name='CQBaseEditorWnd')。
Qt线程中按QMainWindow/objectName唯一匹配→menuBar→顶层QAction→子菜单QAction；
返回原始菜单/文字、Qt enabled/visible，不返回地址，不触发动作、不递归展开子菜单。
缺失/多匹配返回候选QMainWindow名字，最多384项以限制IPC消息大小。
所有临时QString/QList继续使用已有清理及超时上下文管理。

本轮核对历史PID22360的空会话/空dirty分组重复读一致及进程身份，且无其它编辑器模块后，
重启隔离实例加载菜单查询版桥接。新历史PID27972、Qt线程27932。
实际stdio重新通过Qt按钮打开Hammer后，菜单查询读回10个菜单中的148个动作。
File/Open原文是“&Open\tCtrl+O”，Save为“&Save\tCtrl+S”。
发现快捷键后缀是文字的一部分，MenuLabel新增先截断tab后缀，再处理助记符/省略号；
新归一化构建/原生回归测试已通过。

注意：空窗口中Undo/Save等QAction也报告enabled=true，不能将Qt属性当作命令或地图就绪证明。
只读菜单报告C:\CS2_Temp\qt_hammer_menu_actions.json。
复现：python scripts/qt_widgets_mcp.py --menu-window CQBaseEditorWnd --report <新报告路径>。
90工具（Hammer51/bridge39），100项Python、原生测试及Release构建通过。

桥接另有固定qt_hammer_open_dialog实验IPC（默认预览），使用QTimer::singleShot向唯一
File/Open动作排队trigger()，以免阻塞桥接等待模态窗口；尚未实际执行/验证，不是已发布MCP工具。
不允许将任意菜单文字/对象地址作为动作参数，也不开放文档编辑调用。
当前运行桥接SHA1b258ecb7451c8998a1b9a2e94ece93215a2d04adcd75c691c86214a9428a207，
磁盘最新构建SHAf2417863e26f440d60918bcb0f2ea8522c38e16f9d843b217bb58c92fedb78da
包含tab归一化修正，尚未加载。下一步先核对文档状态再部署/验证排队Open与真实对话框，
然后只打开隔离地图副本。未宣称已打开地图或已通过写入往返验证。

## 2026-10-26 排队Open实机验证与隔离副本

再次核对前一隔离实例空会话/空dirty分组和进程身份后，加载含tab归一化的新桥接。
当前历史PID26192、Qt窗口线程30736，桥接SHA
f2417863e26f440d60918bcb0f2ea8522c38e16f9d843b217bb58c92fedb78da。
Qt启动Hammer后，qt_hammer_open_dialog(confirm=false)预览通过，
confirm=true返回open_dialog_queued。随后computer-use在Hammer辅助功能树中
实际观察到原生“Open”对话框及文件名输入框/打开按钮，证明队列动作确实执行。
list_windows未单列该模态对话框，但get_window_state(Hammer,include_text=true)含其子树；
不能仅按顶层窗口列表缺失判断对话框没出现。
模态窗口打开时，管道仍响应，主线程固定自检/版本检查/写入拒绝复测通过。
该实验IPC尚未新增公开MCP工具（仍90工具），也未宣称可自动填路径。
报告C:\CS2_Temp\qt_open_dialog_preview.json、qt_open_dialog_queued.json、mcp_open_dialog_live.json。

新增scripts/prepare_edit_probe.py：从当前工程配置读取地图，生成唯一
maps/__mcp_edit_tests/<UUID>/<原地图名>.vmap，复制前后校验原文件与副本SHA。
同时在工程state_root/editor_probes/<UUID>创建独立project.json/manifest.json，
便于后续构建直接使用同一隔离地图配置。仅新建，不覆盖原地图或已有副本。
本轮实际生成UUID f61a8859b90241378cb9120ea21675fe。
清单C:\CS2_Temp\mcp_build_jobs\editor_probes\f61a8859b90241378cb9120ea21675fe\manifest.json。
原图和副本SHA均保持f489c4112a3380b898b1267929c32c5a7241af64ef9b06c6ada013381ab80b9e。
manifest中的editor_opened仍false，地图没有打开。

电脑操控对文件名框set_value返回Cannot set a value for an element that is not settable；
重新读取确认仍为空。Alt+n后焦点仍为SearchEditBox，未输入路径。
随后按新观察的文件名框click返回coordinate input geometry is unavailable。
没有继续盲打/回车，没有重复排队Open；当前模态Open仍保留。
下一步通过经过ABI核对的QFileDialog::selectFile/accept机制操作原生对话框，
必须验证AcceptOpen/ExistingFile模式、唯一对话框、工程内现有vmap和源hash，
再观察非空文档与保存/Undo/Redo。不得把本轮Open对话框成功写成地图打开成功。

## 2026-10-26 原生文件选择适配器：源码/测试，尚未部署实测

实现实验QtFileDialogMap：已有vmap、唯一可见QFileDialog、AcceptOpen/ExistingFile模式；
QString::fromUtf8→selectFile→selectedFiles精确读回，匹配才排队accept()。
新增QStringList内容析构和容器释放，原生mock清理测试通过，Release构建成功。
源码参考Qt官方5.15.2 QFileDialog对native helper分支的实现：
https://github.com/qt/qtbase/blob/v5.15.2/src/widgets/dialogs/qfiledialog.cpp
这不是该接口已成功控制本机Windows原生选择器的证据。

部署前发现当前已有cs_script_demo.vmap文档，已保留进程，不重启；因此没有执行该接口。
运行桥接仍为f2417863e26f440d60918bcb0f2ea8522c38e16f9d843b217bb58c92fedb78da；
磁盘构建1ff592a3efeba420204bfea7cc51921afe4c81e54cdaea1c39198c6a5dc3d883尚未加载。
qt_file_dialog_map仅实验IPC，不是已验证/已公开的MCP地图打开功能。
当前窗口标题Hammer - [cs_script_demo.vmap]，不再假定Open模态仍在。
本轮只读核对非空会话/文档/路径，详见HAMMER_DIRTY_ANALYSIS.md。

## 2026-10-26 v0.2.1实机及原生文件选择失败复现

新一轮CIM确认没有CS2进程后启动test addon，参数包含-insecure、-tools、
-allow_third_party_software和-condebug。PID10764实际加载v0.2.1，主线程自检与
版本失配写入拒绝通过，报告C:\CS2_Temp\mcp_bridge_021_live.json。
早期启动尚无唯一Qt线程时status2，待Asset Browser出现后自检通过；没有重放未知调用。

空Hammer会话确认后排队Open，再调用实验qt_file_dialog_map。
selectFile实际已把路径写入原生对话框文件名框，但selectedFiles读回不是一个文件，
所以适配器没有排队accept。computer-use辅助功能树确认该路径；Alt+O提交后，
原生窗口明确提示该C:/完整路径“文件名无效”。提示已用Return关闭。

源码新增QFileDialog::setDirectory(QString)导出调用，再selectFile(basename)。
确认本轮创建的PID10764始终零文档后终止该测试进程，构建并启动新的PID10268。
新DLL SHA2f2cb2a0c20f7bf7cbc19607c82e8ba376e194f560efa77105b9e6544233d24c。
派发生命周期与真实管道bootstrap原生测试通过；108项Python测试通过。
新适配器已实机运行：目录确实切到隔离测试UUID目录，但Qt/native helper仍把完整
C:/路径放进文件名框，selectedFiles仍不为单个文件。**此改动仅解决目录导航，
没有解决打开地图，不得发布成已验证地图打开MCP。**

Computer-use截图仍FrameArrived timed out；重新选择窗口后只读辅助功能可用。
click报coordinate input geometry is unavailable；set_value报element not available in
cached app state；Alt+n后焦点仍搜索框。没有盲输路径，没有再次提交无效文件名。
最终PID10268、v0.2.1管道在线，Hammer会话0，原图/隔离副本哈希不变，Open模态保留。
最终报告C:\CS2_Temp\qt_dirfix_session_final.json；调用结果qt_file_dialog_dirfix_live.json。

下一步需修正Windows native helper的文件名设置/读回，或实现有严格所属进程、
线程、对话框模式和文件范围检查的原生文件选择适配器；不能跳过读回直接accept。
dirty修改/Undo/Redo/保存验证尚未开始。公开工具仍92个。

## 2026-10-26 Windows原生打开成功

新增固定原生文件选择适配器，仍在已校验Qt主线程、唯一可见QFileDialog、
AcceptOpen/ExistingFile模式下运行。只枚举本线程/本进程的可见#32770窗口，
要求同线程同进程Qt5 QWindow owner和文件名1148、类型1136、Open/Cancel固定控件。
多个候选拒绝。原生文件名控件实际为ComboBoxEx32→ComboBox→Edit，
首轮只找直接Edit失败；现限定1148后代中的唯一Edit，禁用或歧义拒绝。
用反斜杠绝对路径设置文件名，长度和完整字符串精确读回后才PostMessage Open。
不直接调用未经验证的Hammer RVA，也不跳过文件名读回。

原生独立窗口测试覆盖嵌套Edit、精确路径读回、额外Edit歧义拒绝和Open禁用拒绝，
dispatch_lifetime及diagnostic_bootstrap通过。最新桥接SHA：
e00f79e6fbe7df47b10200cc219674d2802697a05300419fb5b8c6d5e01bfe9a。
只在即时确认本轮自建测试进程零文档后重启换版，未热卸载。

实机PID2064一次提交返回native_map_open_queued，随后实际stdio自检确认唯一文档：
content/csgo_addons/test/maps/__mcp_edit_tests/f61a8859b90241378cb9120ea21675fe/untitled_2.vmap。
文档主虚表/RTTI与模块SHA均验证，主线程自检和原生写入拒绝再次通过。
报告C:\CS2_Temp\qt_native_leaf_map_result.json、mcp_isolated_map_open_verified.json。
此前的文件选择失败已被本轮实机证据解决；公开MCP地图打开包装尚未新增，
成功调用的是固定实验IPC，不能将其宣称为通用任意文件打开能力。

隔离工程cs2_edit_preflight首次记录da5b149299b0433f96b507a5cac739a5，
第二次09946eb8d02a4966b4335a694c93dd1f返回matched；配置地图唯一打开/addon匹配，
原图和副本SHA均未变。saved_generation_candidate=1、generation_candidate=1，
仍不推断clean。safe_to_write=false，dirty语义、批量执行/回滚和原生写入profile仍未完成。
报告C:\CS2_Temp\isolated_map_preflight_verified.json；本地探针manifest仅在路径校验后更新editor_opened=true。
后续保留此隔离文档用于修改、Undo/Redo和保存验证，不能因其当前无已知修改直接重启。

## 2026-10-26：Qt控件父级与文本只读查询

cs2_qt_widgets现增加kind（已识别的Qt基类）、visible/enabled、display_text、text_redacted、
ancestors及ancestry_complete；祖先按根到父排列，最多32级，循环/坏指针拒绝。
已支持QLineEdit、QLabel、QTreeView、QTableView、QComboBox、QAbstractButton、QDockWidget、QMainWindow分类。
只读取可见标签、按钮和普通文本框的有界文本，非Normal echoMode文本框不读值。
未新增任意对象地址调用或点击；locator_unique_verified始终false，空对象名与同名控件仍可能歧义。
分页顺序仍不稳定，父级链是定位证据，不能据此宣称跨分页原子快照或稳定唯一定位已完成。

原生测试覆盖父链32级截断、短链完成和循环拒绝；147项Python测试（146通过/1权限跳过）、
dispatch_test及bootstrap_test通过，Release构建通过。未用真实密码控件验证redaction，不冒称该分支实机覆盖。
桥接产物SHA 1c37e62bafc83eecf2aed86e10023123aa3480740e9b6f8c015b18f8f1581e62。

为部署新桥接，先核对本轮自建隔离地图世代1/saved1、源码SHA不变；正常关闭Find Entities与Hammer，
再关闭Asset Browser。底层测试游戏进程仍运行，确认MCP打开文档列表为空并以原始FILETIME/路径绑定后
停止此自建测试进程，再启动新实例PID16492。首次按秒比较CIM时间因亚秒信息缺失而拒绝操作，
随后改用原始创建FILETIME精确核对；没有因此杀错或重复启动进程。未热卸载任何DLL。

新进程单次注入后，旧常驻MCP管道报错没有重发；新stdio会话验证成功。
第一次手动查询误用qt_widgets方法名被版本门禁在发送前拒绝，改用实际qt_widgets_snapshot后读回成功。
真实MCP返回128条控件及完整新增字段，快照当时总数1842，可见23；每条明确非唯一定位证明。
记录C:\CS2_Temp\qt_widget_ancestry_stdio.json、qt_widget_ancestry_live.json。
随后重新打开同一隔离UUID bc1d170dd26541cf80f946e324a3beca，独立实机自检确认唯一文档路径/RTTI、
写入拒绝与线程派发自测通过；快照3bbb7b125bd64733ac3ff24337a6e96f，原图/副本仍未修改。
当前实例身份以C:\CS2_Temp\qt_ancestry_session.json为准；旧PID15744已退出，勿复用地址。

此次只有只读控件能力实机完成，实体属性选择、写入与Undo/Redo仍需继续；保持本地，未推送。

## 2026-10-26：Outliner模型的实际行读取

新增Hammer工具cs2_qt_hammer_outliner()，唯一工具100个、Hammer55个。
读取当前可见、父级属于CQBaseEditorWnd/HammerMapOutlineDockWidget的QTreeView模型；
不选择、修改或保存，不接受对象/函数地址。每个树独立返回path和DisplayRole文本，
路径是当前观察的行号，不是持久nodeID/GUID。最多4树、每树256行/8层，截断显式报告。
原生QModelIndex大小24字节，index/rowCount/data虚表槽来自安装版Qt5Core的
sibling/hasIndex/itemData导出汇编核对；仍限已支持Qt ABI身份，没有批准Hammer原生写入profile。
QVariant/QString按Qt析构，模型索引必须属于同一模型且行列匹配。

当前Outliner两棵可见树父级路径相同；未任选第一棵。新查询在实际进程读出两份相同显示树：
每份24行，21实体、2网格、1地图根，遍历完整，selection_changed=false。
这不证明两视图底层model/selectionModel指针相同，也未验证改变名称后的未保存差分。
下一步应读取选择模型/当前索引并核对镜像视图，再设计带预期标签和文档身份的固定选择动作。
尚未实现实体属性写入或通用批量回滚，不把显示行数当作结构回滚证明。

原生测试覆盖正常行遍历、256行截断、8层截断、坏索引拒绝和异常行计数；
每次返回的QVariant均析构。Release构建、dispatch_test/bootstrap_test通过；
147项Python测试146通过、1项符号链接权限跳过。真实Hammer stdio工具列举55项并读取两棵24行树成功。
本地报告C:\CS2_Temp\qt_outliner_stdio.json、qt_outliner_live.json、qt_outliner_empty.json。

部署前再次确认隔离副本世代1/saved1与原图哈希；正常关闭该Hammer后独立读回零打开文档，
按FILETIME/路径绑定停止本轮测试进程16492，启动3280并单次注入新桥接。
启动早期打开Hammer因按钮0匹配明确拒绝；确认未点击后待启动就绪再调用成功。
没有因观察超时重发未知动作，未热卸载DLL。
桥接SHA c02ef5914b610763934e4aeb44b2926fb27e3d17a76220892dcd447113425318。
当前仍打开隔离UUID bc1d170dd26541cf80f946e324a3beca；快照8d601edebe0743d38365a4fb9bbc0cf2。
原图/副本SHA f489c4112a3380b898b1267929c32c5a7241af64ef9b06c6ada013381ab80b9e不变。
C:\CS2_Temp\qt_outliner_session.json记录实际文档RTTI、原生写入拒绝和派发自测通过。
保持本地，不自动推送。
