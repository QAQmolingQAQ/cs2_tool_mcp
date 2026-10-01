# -*- coding: utf-8 -*-
"""安全版 Qt 按钮定位/点击：**按 vtable 缓存类名**，绝不逐 widget 调 inherits。

背景：`vm_pipe.py qt-buttons` 会对 `allWidgets()` 的**每个** widget 调一次
`QObject::inherits`（几百次主线程派发）。2026-09-26 实测有一次把 cs2 卡死
（主线程 + 管道都无响应）—— 推断为列表里存在已失效的 widget 指针，
`inherits` 会解 metaobject 链，等于对垃圾指针做虚调用。

本脚本改为：
  1) 对 `allWidgets()` 只**读 vtable**（读内存零风险）
  2) 每种 vtable 只调一次 `metaObject()` 拿类名（Qt 里 distinct vtable 只有几十个）
  3) 只对「类名像按钮」的 widget 取 toolTip

用法：
    python qt_button.py find [needle]
    python qt_button.py click <addr>
"""
import os
import sys

REPO = r"c:\cs2_tool_mcp"
sys.path.insert(0, os.path.join(REPO, "mcp_server"))
import cs2_mcp_server as S  # noqa: E402

RVA_ALL_WIDGETS = 0xE270     # QApplication::allWidgets()
RVA_TOOLTIP = 0xE0900        # QWidget::toolTip()
RVA_CLICK = 0xDE8C0          # QAbstractButton::click()（见 REVERSE_NOTES §2.14）
RVA_CLASSNAME = 0x1D6140     # QMetaObject::className() @ Qt5Core（const char* 返回）

BUTTON_CLASSES = ("QAbstractButton", "QToolButton", "QPushButton", "QCheckBox",
                  "QRadioButton", "QCommandLinkButton")


class Qt:
    def __init__(self):
        self.wb, self.cb = S._qt_bases()
        self.retbuf = S._qt_alloc(256)
        self.vt_class: dict[int, str] = {}

    def qstring(self, fn_rva, this):
        S._qt_call(self.wb + fn_rva, [this, self.retbuf], 8000)
        p = int.from_bytes(S._read_bytes(self.retbuf, 8), "little")
        return S._qt_read_qstring(p)

    def qlist(self, fn_rva):
        S._qt_call(self.wb + fn_rva, [self.retbuf], 15000)
        p = int.from_bytes(S._read_bytes(self.retbuf, 8), "little")
        return S._read_qlist(p)

    def class_name(self, obj):
        """vtable → 类名。取 vtable[0] = QObject::metaObject()，再调
        QMetaObject::className()（返回 const char*，无隐藏缓冲区坑）。

        ⚠️ 必须调 **[vtable] 里的函数指针**（`*(vt)`），不是 vtable 地址本身 ——
        直接调 vt 会跳到 assetbrowser.dll 之类的随机位置并卡死宿主（实测踩过）。
        """
        vt = int.from_bytes(S._read_bytes(obj, 8), "little")
        if vt in self.vt_class:
            return self.vt_class[vt]
        name = ""
        try:
            meta_fn = int.from_bytes(S._read_bytes(vt, 8), "little")
            mo = S._qt_call(meta_fn, [obj], 8000)
            p = S._qt_call(self.cb + RVA_CLASSNAME, [mo], 8000)
            if 0x10000 < p < 0x7FFFFFFFFFFF:
                name = S._read_string(p, 64)
        except Exception:  # noqa: BLE001
            name = ""
        self.vt_class[vt] = name
        return name


def find_buttons(qt, needle=""):
    res = []
    widgets = qt.qlist(RVA_ALL_WIDGETS)
    for w in widgets:
        if not (0x10000 < w < 0x7FFFFFFFFFFF):
            continue
        try:
            cn = qt.class_name(w)
        except Exception:  # noqa: BLE001
            continue
        if not cn or not any(cn == c for c in BUTTON_CLASSES):
            continue
        try:
            tip = qt.qstring(RVA_TOOLTIP, w)
        except Exception:  # noqa: BLE001
            continue
        if needle and needle.lower() not in tip.lower():
            continue
        res.append((w, cn, tip))
    return res, len(widgets), len(qt.vt_class)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "find"
    qt = Qt()
    if cmd == "find":
        needle = sys.argv[2] if len(sys.argv) > 2 else ""
        hits, nw, nvt = find_buttons(qt, needle)
        for w, cn, tip in hits:
            print(f"  {w:#014x}  {cn:<16} tip={tip!r}")
        print(f"命中 {len(hits)} 个（widget 总数 {nw}，distinct vtable={nvt}）")
        return 0
    if cmd == "click":
        addr = int(sys.argv[2], 16)
        if not S._qt_call(qt.cb + S.RVA_QT_INHERITS, [addr, "str:QAbstractButton"], 8000):
            print("不是 QAbstractButton，拒绝点击")
            return 2
        print("click ret =", S._qt_call(qt.wb + RVA_CLICK, [addr], 15000))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
