"""Fixed read-only Qt diagnostics shared by editor DLL services."""
from .runtime import _call


def cs2_qt_widgets(offset: int = 0, limit: int = 128) -> str:
    """在Qt窗口线程读取控件类型、对象名、父级路径、可见状态及有界显示文本。

    仅支持已校验的Qt ABI，offset 0..20000，limit 1..128；文字最多256个UTF16单元。
    返回的地址仅为本次观察，不可跨窗口重建复用；列表顺序不稳定，分页不是一致快照。
    新桥接返回最多32级父控件路径；可见标签/普通文本框可读，密码式文本框隐去。
    父路径不保证唯一；locator_unique_verified=false，不能将观察当作点击授权。
    缺少唯一Qt窗口线程、未支持ABI或超时返回错误；不会重启进程或自动重试。
    """
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 20000:
        raise ValueError('offset must be an integer in 0..20000')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 128:
        raise ValueError('limit must be an integer in 1..128')
    return _call('qt_widgets_snapshot', {'offset': offset, 'limit': limit})


def cs2_qt_open_editor(editor: str, confirm: bool = False) -> str:
    """通过Qt原生按钮打开指定编辑器窗口；默认仅预览，不打开文档。

    editor仅允许hammer/pet/met/modeldoc_editor。在同一Qt线程重新定位唯一、可见、
    启用的按钮后点击，不接收对象地址。模块已加载时不点击，也不保证现有窗口可见。
    click_returned仅证明点击调用返回，需另查模块/会话确认就绪；超时不自动重试。
    此固定Qt操作不开放任意函数或编辑器偏移写入。
    """
    if editor not in ('hammer', 'pet', 'met', 'modeldoc_editor'):
        raise ValueError('unsupported editor')
    if not isinstance(confirm, bool):
        raise ValueError('confirm must be bool')
    return _call('qt_open_editor', {'editor': editor, 'confirm': confirm})


def cs2_qt_menu_actions(window_object_name: str = 'CQBaseEditorWnd') -> str:
    """只读查询唯一Qt主窗口的菜单与一层QAction文字、enabled/visible。

    按objectName精确匹配；缺失/重名会返回候选窗口名，不猜测窗口。
    不递归展开子菜单，不触发动作，不返回可复用QAction地址。
    """
    if not isinstance(window_object_name, str) or not 1 <= len(window_object_name.encode('utf-8')) <= 128:
        raise ValueError('window objectName must be 1..128 UTF8 bytes')
    return _call('qt_menu_actions', {'window_object_name': window_object_name})
