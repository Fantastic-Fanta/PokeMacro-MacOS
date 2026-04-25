"""
PokeMacro — native AppKit (PyObjC) UI.
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from src.git_update import start_background_update

import objc
import yaml
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSBezelStyleRounded,
    NSBezelStyleTexturedRounded,
    NSButton,
    NSButtonTypeMomentaryPushIn,
    NSButtonTypeRadio,
    NSButtonTypeSwitch,
    NSColor,
    NSCommandKeyMask,
    NSEdgeInsets,
    NSFont,
    NSLayoutAttributeCenterY,
    NSLineBreakByTruncatingTail,
    NSMenu,
    NSMenuItem,
    NSNoTabsNoBorder,
    NSPasteboard,
    NSPopUpButton,
    NSStringPboardType,
    NSStackView,
    NSStackViewDistributionFill,
    NSStackViewGravityTop,
    NSTabView,
    NSTabViewItem,
    NSTerminateCancel,
    NSTerminateNow,
    NSTextField,
    NSTextView,
    NSUserInterfaceLayoutOrientationHorizontal,
    NSUserInterfaceLayoutOrientationVertical,
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialSidebar,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
    NSLayoutAttributeLeading,
    NSLayoutPriorityDefaultHigh,
    NSLayoutPriorityDefaultLow,
    NSOnState,
    NSOffState,
    NSSecureTextField,
    NSScrollView,
)

from Foundation import (
    NSMakeRect,
    NSOperationQueue,
    NSObject,
    NSMutableAttributedString,
    NSTimer,
)

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "configs.yaml"
_venv_python = PROJECT_ROOT / "ENV" / "bin" / "python"
VENV_PYTHON = _venv_python if _venv_python.exists() else Path(sys.executable)

SIDEBAR_W = 208.0
TOPBAR_H = 50.0
UI_PAD = 20.0
LABEL_W = 128.0

POSITION_KEYS = [
    ("EggManPosition", "Egg Man Position"),
    ("EventButton", "Event Button"),
    ("DialogueYES", "Dialogue YES"),
    ("QuickRejoinSprite", "Quick Rejoin Sprite"),
    ("QuickRejoinButton", "Quick Rejoin Button"),
    ("MenuButton", "Menu Button"),
    ("SaveButton", "Save Button"),
    ("LoadingScreenYellow", "Loading Screen Yellow"),
    ("SaveFileCard", "Save File Card"),
    ("RunButton", "Run Button"),
    ("Pokeball", "Pokeball"),
]

_IDLE = None
_RUN = None
_STOP = None
_MUTED = None


def _apple_colors() -> None:
    global _IDLE, _RUN, _STOP, _MUTED
    if _MUTED is not None:
        return
    _IDLE = NSColor.colorWithRed_green_blue_alpha_(0.71, 0.71, 0.73, 1.0)
    _RUN = NSColor.systemGreenColor()
    _STOP = NSColor.systemRedColor()
    _MUTED = NSColor.secondaryLabelColor()


def _h_stack() -> NSStackView:
    s = NSStackView.stackViewWithViews_([])
    s.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
    s.setSpacing_(8.0)
    s.setAlignment_(NSLayoutAttributeCenterY)
    return s


def _v_stack() -> NSStackView:
    s = NSStackView.stackViewWithViews_([])
    s.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
    s.setSpacing_(6.0)
    s.setAlignment_(NSLayoutAttributeLeading)
    return s


def _label_small(s: str) -> NSTextField:
    t = NSTextField.labelWithString_(s)
    t.setTextColor_(_MUTED or NSColor.secondaryLabelColor())
    t.setFont_(NSFont.systemFontOfSize_(11.0))
    t.setLineBreakMode_(NSLineBreakByTruncatingTail)
    return t


def _section_title(s: str) -> NSTextField:
    t = NSTextField.labelWithString_(s)
    t.setFont_(NSFont.boldSystemFontOfSize_(13.0))
    t.setTextColor_(NSColor.labelColor())
    return t


def _int_field(f: NSTextField) -> int:
    st = f.stringValue() or ""
    st = st.strip() or "0"
    if st.lstrip("-").isdigit() or (st[0:1] in "-" and st[1:].isdigit()):
        try:
            return int(st)
        except ValueError:
            return 0
    return 0


def _push_button(target: object, action: bytes, title: str) -> NSButton:
    b = NSButton.alloc().init()
    b.setButtonType_(NSButtonTypeMomentaryPushIn)
    b.setBezelStyle_(NSBezelStyleRounded)
    b.setTitle_(title)
    b.setTarget_(target)
    b.setAction_(action)
    return b


def _ac_save(target: object) -> NSButton:
    b = _push_button(target, b"saveConfig:", "Save")
    b.setKeyEquivalent_("s")
    b.setKeyEquivalentModifierMask_(NSCommandKeyMask)
    return b


def _ac_prefs(target: object) -> NSMenuItem:
    m = (
        NSMenuItem.alloc()
        .initWithTitle_action_keyEquivalent_("Preferences…", b"openPreferences:", ",")
    )
    m.setKeyEquivalentModifierMask_(NSCommandKeyMask)
    m.setTarget_(target)
    return m


def _ac_hide() -> NSMenuItem:
    m = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Hide PokeMacro", b"hide:", "h")
    m.setKeyEquivalentModifierMask_(NSCommandKeyMask)
    return m


def _ac_about(target: object) -> NSMenuItem:
    m = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("About PokeMacro", b"showAbout:", "")
    m.setTarget_(target)
    return m


def _set_layer_bg(v: NSView, color: NSColor) -> None:
    v.setWantsLayer_(True)
    layer = v.layer()
    if layer is None or not hasattr(color, "CGColor"):
        return
    cg = color.CGColor()
    if cg is not None:
        layer.setBackgroundColor_(cg)  # type: ignore[union-attr]


def _pin_edges(inner: NSView, outer: NSView) -> None:
    inner.setTranslatesAutoresizingMaskIntoConstraints_(False)
    if inner.leadingAnchor() and outer.leadingAnchor():
        inner.leadingAnchor().constraintEqualToAnchor_(outer.leadingAnchor()).setActive_(True)
        inner.trailingAnchor().constraintEqualToAnchor_(outer.trailingAnchor()).setActive_(
            True
        )
        inner.topAnchor().constraintEqualToAnchor_(outer.topAnchor()).setActive_(True)
        inner.bottomAnchor().constraintEqualToAnchor_(outer.bottomAnchor()).setActive_(True)


class _StatusDotView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(_StatusDotView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._fill: NSColor = _IDLE or NSColor.tertiaryLabelColor()
        return self

    def isOpaque(self) -> bool:
        return False

    def setFillColor_(self, c: NSColor) -> None:
        self._fill = c
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        b = self.bounds()
        p = NSBezierPath.bezierPathWithOvalInRect_(b)
        self._fill.setFill()
        p.fill()


class _AdaptiveLogTextView(NSTextView):
    def viewDidChangeEffectiveAppearance(self) -> None:
        objc.super(_AdaptiveLogTextView, self).viewDidChangeEffectiveAppearance()
        self._pm_apply_appearance()

    @objc.python_method
    def _pm_apply_appearance(self) -> None:
        self.setDrawsBackground_(True)
        self.setBackgroundColor_(NSColor.textBackgroundColor())
        self.setTextColor_(NSColor.textColor())

    def awakeFromNib(self) -> None:
        if hasattr(self, "_pm_apply_appearance"):
            self._pm_apply_appearance()


class ConfigManager:
    def load(self) -> dict:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return self._default_config()

    def save(self, data: dict) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _default_config(self) -> dict:
        return {
            "HuntingMode": "egg",
            "Username": "",
            "Mode": "Default",
            "IsReskin": False,
            "IsShiny": False,
            "IsGradient": False,
            "IsAny": True,
            "IsGood": False,
            "Wishlist": {"Reskins": [], "Gradients": [], "Roamings": [], "Special": []},
            "Positions": {k: [0, 0] for k, _ in POSITION_KEYS},
            "ChatWindow": {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
            "EncounterNameRegion": {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
            "SpriteRegion": {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
            "DiscordBotToken": "",
            "ServerID": 0,
        }


class SubprocessManager:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._log_thread: threading.Thread | None = None

    def start(self, log_queue: queue.Queue, on_exit: Callable[[int], None]) -> None:
        self._proc = subprocess.Popen(
            [str(VENV_PYTHON), "-m", "src.main"],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._log_thread = threading.Thread(
            target=self._stream_logs,
            args=(log_queue, on_exit),
            daemon=True,
        )
        self._log_thread.start()

    def _stream_logs(
        self, log_queue: queue.Queue, on_exit: Callable[[int], None]
    ) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            log_queue.put(line.rstrip("\n"))
        self._proc.wait()
        code = int(self._proc.returncode or 0)
        NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: on_exit(code))

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

            def _wait_kill() -> None:
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()

            threading.Thread(target=_wait_kill, daemon=True).start()

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


class PokeMacroController(NSObject):
    def init(self):
        self = objc.super(PokeMacroController, self).init()
        if self is None:
            return None
        _apple_colors()
        self._config_manager = ConfigManager()
        self._subprocess_manager = SubprocessManager()
        self._config: dict = self._config_manager.load()
        self._is_running = False
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._all_config_controls: list = []
        self._token_shown = False
        self._log_timer: NSTimer | None = None
        self._status_reset_timer: NSTimer | None = None
        self._sidebar_radios: list[NSButton] = []
        self._side_split: NSView | None = None

        self._build_panels()
        self._build_window()
        self._load_all_fields()
        self._arm_log_polling()
        return self

    @objc.python_method
    def _form_pair(self, a: str, field: NSView) -> NSView:
        r = _h_stack()
        r.setSpacing_(12.0)
        lab = NSTextField.labelWithString_(a)
        lab.setFont_(NSFont.systemFontOfSize_(13.0))
        if hasattr(lab, "setContentHuggingPriority_forOrientation_"):
            lab.setContentHuggingPriority_forOrientation_(
                NSLayoutPriorityDefaultHigh, NSUserInterfaceLayoutOrientationHorizontal
            )
        if lab.widthAnchor():
            lab.widthAnchor().constraintEqualToConstant_(LABEL_W).setActive_(True)
        r.addView_inGravity_(lab, NSStackViewGravityTop)
        r.addView_inGravity_(field, NSStackViewGravityTop)
        if hasattr(field, "setContentHuggingPriority_forOrientation_"):
            field.setContentHuggingPriority_forOrientation_(
                250, NSUserInterfaceLayoutOrientationHorizontal
            )
        r.setDistribution_(NSStackViewDistributionFill)
        return r

    @objc.python_method
    def _build_panels(self) -> None:
        self._tab = NSTabView.alloc().init()
        self._tab.setTabViewType_(NSNoTabsNoBorder)
        for label, build in [
            ("General", self._tab_general),
            ("Wishlist", self._tab_wishlist),
            ("Positions", self._tab_positions),
            ("Logs", self._tab_logs),
        ]:
            view = build()
            item = NSTabViewItem.alloc().initWithIdentifier_(label)
            item.setLabel_(label)
            item.setView_(view)
            self._tab.addTabViewItem_(item)
        if hasattr(self._tab, "setTranslatesAutoresizingMaskIntoConstraints_"):
            self._tab.setTranslatesAutoresizingMaskIntoConstraints_(False)

    @objc.python_method
    def _build_window(self) -> None:
        rect = NSMakeRect(120, 120, 960, 680)
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable
        )
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        self._window.setTitle_("PokeMacro")
        self._window.setMinSize_((900, 620))
        self._window.setDelegate_(self)
        self._window.setReleasedWhenClosed_(False)

        top = self._make_topbar()
        self._side_split = self._make_main_split()
        sp = _v_stack()
        sp.setSpacing_(0.0)
        if hasattr(self._side_split, "setContentHuggingPriority_forOrientation_"):
            self._side_split.setContentHuggingPriority_forOrientation_(
                1, NSUserInterfaceLayoutOrientationVertical
            )
        sp.addView_inGravity_(top, NSStackViewGravityTop)
        sp.addView_inGravity_(self._h_separator(), NSStackViewGravityTop)
        sp.addView_inGravity_(self._side_split, NSStackViewGravityTop)
        sp.setTranslatesAutoresizingMaskIntoConstraints_(False)
        if self._side_split and self._side_split.heightAnchor():
            self._side_split.heightAnchor().constraintGreaterThanOrEqualToConstant_(
                500.0
            ).setActive_(True)
        self._root = sp
        self._window.setContentView_(sp)
        self._window.makeKeyAndOrderFront_(None)

    @objc.python_method
    def _h_separator(self) -> NSView:
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 1))
        _set_layer_bg(v, NSColor.separatorColor())
        v.setTranslatesAutoresizingMaskIntoConstraints_(False)
        if v.heightAnchor():
            v.heightAnchor().constraintEqualToConstant_(1.0).setActive_(True)
        return v

    @objc.python_method
    def _make_topbar(self) -> NSView:
        bar = _h_stack()
        bar.setEdgeInsets_(NSEdgeInsets(6, 16, 6, 16))
        bar.setAlignment_(NSLayoutAttributeCenterY)
        bar.setDistribution_(NSStackViewDistributionFill)
        if bar.heightAnchor():
            bar.heightAnchor().constraintEqualToConstant_(TOPBAR_H).setActive_(True)
        # Status
        self._status_dot = _StatusDotView.alloc().initWithFrame_(NSMakeRect(0, 0, 8, 8))
        self._status_dot.setFillColor_(_IDLE)
        if self._status_dot.widthAnchor() and self._status_dot.heightAnchor():
            self._status_dot.widthAnchor().constraintEqualToConstant_(8.0).setActive_(True)
            self._status_dot.heightAnchor().constraintEqualToConstant_(8.0).setActive_(True)
        self._status = NSTextField.labelWithString_("Idle")
        self._status.setTextColor_(_MUTED)
        self._status.setFont_(NSFont.systemFontOfSize_(12.0))
        st_row = _h_stack()
        st_row.setSpacing_(6.0)
        st_row.addView_inGravity_(self._status_dot, NSStackViewGravityTop)
        st_row.addView_inGravity_(self._status, NSStackViewGravityTop)
        # Flex
        flex = NSView.alloc().init()
        if hasattr(flex, "setContentHuggingPriority_forOrientation_"):
            flex.setContentHuggingPriority_forOrientation_(
                1, NSUserInterfaceLayoutOrientationHorizontal
            )
        # Actions
        self._save = _ac_save(self)
        self._go = _push_button(self, b"toggleRun:", "Start")
        if hasattr(self._go, "setKeyEquivalent_"):
            self._go.setKeyEquivalent_("r")
        bar.addView_inGravity_(st_row, NSStackViewGravityTop)
        bar.addView_inGravity_(flex, NSStackViewGravityTop)
        bar.addView_inGravity_(self._save, NSStackViewGravityTop)
        bar.addView_inGravity_(self._go, NSStackViewGravityTop)
        _set_layer_bg(bar, NSColor.controlBackgroundColor())
        bar.setTranslatesAutoresizingMaskIntoConstraints_(False)
        return bar

    @objc.python_method
    def _make_main_split(self) -> NSView:
        eff = NSVisualEffectView.alloc().init()
        eff.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        eff.setMaterial_(NSVisualEffectMaterialSidebar)
        eff.setState_(NSVisualEffectStateActive)
        eff.setWantsLayer_(True)
        eff.setTranslatesAutoresizingMaskIntoConstraints_(False)
        vs = _v_stack()
        vs.setEdgeInsets_(NSEdgeInsets(12, 8, 12, 8))
        vs.setSpacing_(4.0)
        for i, title in enumerate(["General", "Wishlist", "Positions", "Logs"]):
            b = NSButton.alloc().init()
            b.setButtonType_(NSButtonTypeRadio)
            b.setBezelStyle_(NSBezelStyleTexturedRounded)
            b.setTitle_(title)
            b.setTarget_(self)
            b.setAction_(b"selectSection:")
            b.setTag_(i)
            self._sidebar_radios.append(b)
            vs.addView_inGravity_(b, NSStackViewGravityTop)
        fsp = NSView.alloc().init()
        if hasattr(fsp, "setContentHuggingPriority_forOrientation_"):
            fsp.setContentHuggingPriority_forOrientation_(
                1, NSUserInterfaceLayoutOrientationVertical
            )
        vs.addView_inGravity_(fsp, NSStackViewGravityTop)
        if self._sidebar_radios:
            self._sidebar_radios[0].setState_(NSOnState)
        eff.addSubview_(vs)
        _pin_edges(vs, eff)
        if eff.widthAnchor():
            eff.widthAnchor().constraintEqualToConstant_(SIDEBAR_W).setActive_(True)
        vline = NSView.alloc().init()
        vline.setTranslatesAutoresizingMaskIntoConstraints_(False)
        _set_layer_bg(vline, NSColor.separatorColor())
        if vline.widthAnchor():
            vline.widthAnchor().constraintEqualToConstant_(1.0).setActive_(True)
        main = NSView.alloc().init()
        main.setTranslatesAutoresizingMaskIntoConstraints_(False)
        _set_layer_bg(main, NSColor.textBackgroundColor())
        main.addSubview_(self._tab)
        _pin_edges(self._tab, main)
        h = _h_stack()
        h.setSpacing_(0.0)
        h.setDistribution_(NSStackViewDistributionFill)
        h.addView_inGravity_(eff, NSStackViewGravityTop)
        h.addView_inGravity_(vline, NSStackViewGravityTop)
        h.addView_inGravity_(main, NSStackViewGravityTop)
        if hasattr(vline, "setContentHuggingPriority_forOrientation_"):
            vline.setContentHuggingPriority_forOrientation_(
                NSLayoutPriorityDefaultHigh, NSUserInterfaceLayoutOrientationHorizontal
            )
        h.setTranslatesAutoresizingMaskIntoConstraints_(False)
        if hasattr(eff, "setContentHuggingPriority_forOrientation_"):
            eff.setContentHuggingPriority_forOrientation_(
                NSLayoutPriorityDefaultHigh, NSUserInterfaceLayoutOrientationHorizontal
            )
        if hasattr(main, "setContentHuggingPriority_forOrientation_"):
            main.setContentHuggingPriority_forOrientation_(
                1, NSUserInterfaceLayoutOrientationHorizontal
            )
        if hasattr(h, "setClipsToBounds_"):
            h.setClipsToBounds_(True)
        return h

    @objc.python_method
    def _wrap_sc(self, doc: NSView, min_h: float) -> NSScrollView:
        sc = NSScrollView.alloc().init()
        sc.setDocumentView_(doc)
        sc.setHasVerticalScroller_(True)
        sc.setAutohidesScrollers_(True)
        sc.setBorderType_(0)
        sc.setDrawsBackground_(True)
        if hasattr(sc, "setTranslatesAutoresizingMaskIntoConstraints_"):
            sc.setTranslatesAutoresizingMaskIntoConstraints_(False)
        h = sc.heightAnchor().constraintEqualToConstant_(min_h)
        h.setActive_(True)
        return sc

    @objc.python_method
    def _tab_general(self) -> NSView:
        v = _v_stack()
        v.setEdgeInsets_(NSEdgeInsets(UI_PAD, UI_PAD, UI_PAD, UI_PAD))
        v.setSpacing_(14.0)
        v.addView_inGravity_(_section_title("Hunt"), NSStackViewGravityTop)
        self._hunt = NSPopUpButton.alloc().init()
        self._hunt.addItemsWithTitles_(["egg", "roam"])
        self._all_config_controls.append(self._hunt)
        v.addView_inGravity_(
            self._form_pair("Hunting mode", self._hunt), NSStackViewGravityTop
        )
        self._user = NSTextField.alloc().init()
        self._user.setStringValue_("")
        self._all_config_controls.append(self._user)
        v.addView_inGravity_(self._form_pair("Username", self._user), NSStackViewGravityTop)
        self._fast = NSPopUpButton.alloc().init()
        self._fast.addItemsWithTitles_(["Default", "Fast"])
        self._all_config_controls.append(self._fast)
        v.addView_inGravity_(self._form_pair("Speed", self._fast), NSStackViewGravityTop)
        v.addView_inGravity_(_section_title("Filters"), NSStackViewGravityTop)
        self._bools: dict[str, NSButton] = {}
        for key, t in [
            ("IsReskin", "Reskin"),
            ("IsShiny", "Shiny"),
            ("IsGradient", "Gradient"),
            ("IsAny", "Any"),
            ("IsGood", "Good"),
        ]:
            b = NSButton.alloc().init()
            b.setButtonType_(NSButtonTypeSwitch)
            b.setTitle_(t)
            self._bools[key] = b
            self._all_config_controls.append(b)
            v.addView_inGravity_(b, NSStackViewGravityTop)
        w = NSView.alloc().init()
        w.setTranslatesAutoresizingMaskIntoConstraints_(False)
        w.addSubview_(v)
        _pin_edges(v, w)
        return w

    @objc.python_method
    def _tab_wishlist(self) -> NSView:
        o = _v_stack()
        o.setEdgeInsets_(NSEdgeInsets(UI_PAD, UI_PAD, UI_PAD, UI_PAD))
        o.setSpacing_(10.0)
        o.addView_inGravity_(
            _label_small("One item per line, or comma-separated values."),
            NSStackViewGravityTop,
        )
        self._wish: dict[str, NSTextView] = {}
        heights = [("Reskins", 100), ("Gradients", 100), ("Roamings", 160), ("Special", 160)]
        for name, h in heights:
            o.addView_inGravity_(_label_small(name), NSStackViewGravityTop)
            tv = NSTextView.alloc().init()
            tv.setMinSize_((0, 0))
            tv.setMaxSize_((1e7, 1e7))
            tv.setVerticallyResizable_(True)
            tv.setHorizontallyResizable_(False)
            tv.setTextContainerInset_((5, 5))
            tv.setFont_(self._mono_font())
            sc = self._wrap_sc(tv, h)
            self._wish[name] = tv
            self._all_config_controls.append(tv)
            o.addView_inGravity_(sc, NSStackViewGravityTop)
        return self._v_scroll_page(o)

    @objc.python_method
    def _mono_font(self) -> NSFont:
        if hasattr(NSFont, "monospacedSystemFontOfSize_weight_"):
            return NSFont.monospacedSystemFontOfSize_weight_(12, 0)
        return NSFont.userFixedPitchFontOfSize_(12)

    @objc.python_method
    def _v_scroll_page(self, doc: NSView) -> NSView:
        sc = NSScrollView.alloc().init()
        doc.setTranslatesAutoresizingMaskIntoConstraints_(False)
        sc.setDocumentView_(doc)
        sc.setDrawsBackground_(True)
        sc.setHasVerticalScroller_(True)
        sc.setAutohidesScrollers_(True)
        sc.setBorderType_(0)
        sc.setTranslatesAutoresizingMaskIntoConstraints_(False)
        if sc.contentView() is not None and doc.leadingAnchor():
            cv = sc.contentView()
            doc.leadingAnchor().constraintEqualToAnchor_(cv.leadingAnchor()).setActive_(
                True
            )
            doc.trailingAnchor().constraintEqualToAnchor_(cv.trailingAnchor()).setActive_(
                True
            )
            doc.topAnchor().constraintEqualToAnchor_(cv.topAnchor()).setActive_(True)
            doc.widthAnchor().constraintEqualToAnchor_(cv.widthAnchor()).setActive_(
                True
            )
        return sc

    @objc.python_method
    def _coord_row(self, parent: NSView, label: str, d: dict, k: str) -> None:
        assert isinstance(parent, NSStackView)
        row = _h_stack()
        row.setSpacing_(8.0)
        la = NSTextField.labelWithString_(label)
        la.setFont_(NSFont.systemFontOfSize_(13.0))
        if la.widthAnchor():
            la.widthAnchor().constraintEqualToConstant_(LABEL_W + 4).setActive_(True)
        xb = NSTextField.labelWithString_("X")
        yb = NSTextField.labelWithString_("Y")
        xb.setTextColor_(_MUTED)
        yb.setTextColor_(_MUTED)
        x = NSTextField.alloc().init()
        y = NSTextField.alloc().init()
        for f in (x, y):
            f.setBezeled_(True)
            f.setStringValue_("0")
        if x.widthAnchor() and y.widthAnchor():
            x.widthAnchor().constraintEqualToConstant_(76.0).setActive_(True)
            y.widthAnchor().constraintEqualToConstant_(76.0).setActive_(True)
        d[k] = (x, y)
        self._all_config_controls.extend([x, y])
        for w in (la, xb, x, yb, y):
            row.addView_inGravity_(w, NSStackViewGravityTop)
        parent.addView_inGravity_(row, NSStackViewGravityTop)

    @objc.python_method
    def _tab_positions(self) -> NSView:
        col = _v_stack()
        col.setEdgeInsets_(NSEdgeInsets(UI_PAD, UI_PAD, UI_PAD, UI_PAD))
        col.setSpacing_(10.0)
        col.addView_inGravity_(_section_title("Clicks and markers"), NSStackViewGravityTop)
        pv = _v_stack()
        self._pos: dict[str, tuple[NSTextField, NSTextField]] = {}
        for key, label in POSITION_KEYS:
            self._coord_row(pv, label, self._pos, key)
        col.addView_inGravity_(pv, NSStackViewGravityTop)
        col.addView_inGravity_(_section_title("Screen regions"), NSStackViewGravityTop)
        self._regions: dict[str, dict[str, tuple[NSTextField, NSTextField]]] = {}
        for t, rkey in [
            ("Chat", "ChatWindow"),
            ("Encounter name", "EncounterNameRegion"),
            ("Sprite", "SpriteRegion"),
        ]:
            col.addView_inGravity_(_label_small(t), NSStackViewGravityTop)
            s = _v_stack()
            s.setSpacing_(4.0)
            d: dict[str, tuple] = {}
            self._coord_row(s, "Left corner", d, "LeftCorner")
            self._coord_row(s, "Right corner", d, "RightCorner")
            self._regions[rkey] = d
            col.addView_inGravity_(s, NSStackViewGravityTop)
        return self._wrap_sc(col, 500)

    @objc.python_method
    def _tab_logs(self) -> NSView:
        v = _v_stack()
        v.setEdgeInsets_(NSEdgeInsets(UI_PAD, UI_PAD, UI_PAD, UI_PAD))
        v.setSpacing_(12.0)
        v.addView_inGravity_(_section_title("Discord"), NSStackViewGravityTop)
        dcol = _v_stack()
        dcol.setSpacing_(8.0)
        self._ptok = NSTextField.alloc().init()
        self._stok = NSSecureTextField.alloc().init()
        for t in (self._ptok, self._stok):
            t.setStringValue_("")
        self._stok.setBezeled_(True)
        self._ptok.setBezeled_(True)
        self._ptok.setHidden_(True)
        self._all_config_controls.append(self._stok)
        self._all_config_controls.append(self._ptok)
        toks = _v_stack()
        toks.setSpacing_(0.0)
        toks.addView_inGravity_(self._stok, NSStackViewGravityTop)
        toks.addView_inGravity_(self._ptok, NSStackViewGravityTop)
        trow = _h_stack()
        trow.addView_inGravity_(
            NSTextField.labelWithString_("Bot token"), NSStackViewGravityTop
        )
        trow.addView_inGravity_(toks, NSStackViewGravityTop)
        self._tokbtn = _push_button(self, b"toggleToken:", "Show")
        trow.addView_inGravity_(self._tokbtn, NSStackViewGravityTop)
        dcol.addView_inGravity_(trow, NSStackViewGravityTop)
        self._server = NSTextField.alloc().init()
        self._server.setStringValue_("0")
        self._all_config_controls.append(self._server)
        dcol.addView_inGravity_(
            self._form_pair("Server ID (numeric)", self._server), NSStackViewGravityTop
        )
        v.addView_inGravity_(dcol, NSStackViewGravityTop)
        v.addView_inGravity_(_section_title("Output"), NSStackViewGravityTop)
        hrow = _h_stack()
        gfill = NSView.alloc().init()
        if hasattr(gfill, "setContentHuggingPriority_forOrientation_"):
            gfill.setContentHuggingPriority_forOrientation_(
                1, NSUserInterfaceLayoutOrientationHorizontal
            )
        hrow.addView_inGravity_(gfill, NSStackViewGravityTop)
        cpy = _push_button(self, b"copyLogs:", "Copy")
        clr = _push_button(self, b"clearLogs:", "Clear")
        hrow.addView_inGravity_(cpy, NSStackViewGravityTop)
        hrow.addView_inGravity_(clr, NSStackViewGravityTop)
        v.addView_inGravity_(hrow, NSStackViewGravityTop)
        self._log = _AdaptiveLogTextView.alloc().init()
        self._log.setEditable_(False)
        self._log.setSelectable_(True)
        self._log.setFont_(self._mono_font())
        self._log.setTextContainerInset_((6, 6))
        self._log._pm_apply_appearance()
        lg = self._wrap_sc(self._log, 300)
        v.addView_inGravity_(lg, NSStackViewGravityTop)
        return v

    def selectSection_(self, sender) -> None:
        for b in self._sidebar_radios:
            b.setState_(int(NSOnState) if b is sender else int(NSOffState))
        tag = 0
        if sender is not None and hasattr(sender, "tag"):
            tag = int(sender.tag() if sender.tag() is not None else 0)
        self._tab.selectTabViewItemAtIndex_(tag)

    def openPreferences_(self, sender) -> None:
        for b in self._sidebar_radios:
            b.setState_(int(NSOnState) if b.tag() == 0 else int(NSOffState))
        self._tab.selectTabViewItemAtIndex_(0)
        self._window.makeKeyAndOrderFront_(None)

    def showAbout_(self, sender) -> None:
        a = NSAlert.alloc().init()
        a.setMessageText_("PokeMacro")
        a.setInformativeText_("Pokémon automation helper for macOS.")
        a.runModal()

    @objc.python_method
    def _read_wish(self, tv: NSTextView) -> list[str]:
        s = (tv.textStorage().string() or "") if tv.textStorage() is not None else ""
        raw = str(s).strip()
        out: list[str] = []
        for line in raw.splitlines():
            for part in line.split(","):
                p = part.strip()
                if p:
                    out.append(p)
        return out

    @objc.python_method
    def _xy_from_entries(self, p: tuple[NSTextField, NSTextField]) -> list[int]:
        return [_int_field(p[0]), _int_field(p[1])]

    @objc.python_method
    def _gather(self) -> dict:
        return {
            "HuntingMode": str(self._hunt.titleOfSelectedItem() or "egg"),
            "Username": str(self._user.stringValue() or ""),
            "Mode": str(self._fast.titleOfSelectedItem() or "Default"),
            "Wishlist": {n: self._read_wish(t) for n, t in self._wish.items()},
            "Positions": {k: self._xy_from_entries(t) for k, t in self._pos.items()},
            "ChatWindow": {c: self._xy_from_entries(p) for c, p in self._regions["ChatWindow"].items()},
            "EncounterNameRegion": {
                c: self._xy_from_entries(p) for c, p in self._regions["EncounterNameRegion"].items()
            },
            "SpriteRegion": {c: self._xy_from_entries(p) for c, p in self._regions["SpriteRegion"].items()},
            "IsReskin": self._bools["IsReskin"].state() == int(NSOnState),
            "IsShiny": self._bools["IsShiny"].state() == int(NSOnState),
            "IsGradient": self._bools["IsGradient"].state() == int(NSOnState),
            "IsAny": self._bools["IsAny"].state() == int(NSOnState),
            "IsGood": self._bools["IsGood"].state() == int(NSOnState),
            "DiscordBotToken": (
                (self._ptok.stringValue() or "")
                if self._token_shown
                else (self._stok.stringValue() or "")
            ),
            "ServerID": int(self._server.stringValue() or "0"),
        }

    @objc.python_method
    def _load_all_fields(self) -> None:
        c = self._config
        self._hunt.selectItemWithTitle_(c.get("HuntingMode", "egg") or "egg")
        self._user.setStringValue_(c.get("Username", "") or "")
        self._fast.selectItemWithTitle_(c.get("Mode", "Default") or "Default")
        for k, b in self._bools.items():
            b.setState_(int(NSOnState) if c.get(k, False) else int(NSOffState))
        w = c.get("Wishlist", {}) or {}
        for n, tv in self._wish.items():
            items = w.get(n, []) or []
            s = "\n".join(str(x) for x in items)
            if tv.textStorage() is not None:
                tv.textStorage().setAttributedString_(
                    NSMutableAttributedString.alloc().initWithString_(s)
                )
        p = c.get("Positions", {}) or {}
        for k, (xf, yf) in self._pos.items():
            t = p.get(k, [0, 0])
            xf.setStringValue_(str(int(t[0] if len(t) > 0 else 0)))
            yf.setStringValue_(str(int(t[1] if len(t) > 1 else 0)))
        for rk, block in self._regions.items():
            region = c.get(rk, {}) or {}
            for corner, (xf, yf) in block.items():
                t = region.get(corner, [0, 0])
                xf.setStringValue_(str(int(t[0] if len(t) > 0 else 0)))
                yf.setStringValue_(str(int(t[1] if len(t) > 1 else 0)))
        tok = c.get("DiscordBotToken", "") or ""
        self._stok.setStringValue_(tok)
        self._ptok.setStringValue_(tok)
        self._server.setStringValue_(str(int(c.get("ServerID", 0) or 0)))
        if hasattr(self, "_log") and self._log is not None:
            self._log._pm_apply_appearance()

    def saveConfig_(self, sender) -> None:
        self._config = self._gather()
        self._config_manager.save(self._config)
        self._status.setStringValue_("Saved")
        self._status.setTextColor_(_RUN)
        if self._status_reset_timer is not None:
            self._status_reset_timer.invalidate()
        me = self

        def one_shot(t: NSTimer) -> None:
            if me._is_running:
                me._status.setStringValue_("Running")
                me._status.setTextColor_(_RUN)
            else:
                me._status.setStringValue_("Idle")
                me._status.setTextColor_(_MUTED)

        self._status_reset_timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            2.0, False, one_shot
        )

    def toggleRun_(self, sender) -> None:
        if not self._is_running:
            self._start_run()
        else:
            self._stop_run()

    @objc.python_method
    def _start_run(self) -> None:
        self._config = self._gather()
        self._config_manager.save(self._config)
        self._is_running = True
        self._go.setTitle_("Stop")
        self._status.setStringValue_("Running")
        self._status.setTextColor_(_RUN)
        self._status_dot.setFillColor_(_RUN)
        self._set_en(False)
        self._subprocess_manager.start(self._log_queue, self._on_exit)

    @objc.python_method
    def _on_exit(self, code: int) -> None:
        self._is_running = False
        self._set_en(True)
        self._go.setTitle_("Start")
        self._go.setEnabled_(True)
        self._status_dot.setFillColor_(_IDLE)
        self._status.setStringValue_(
            "Idle" if int(code) == 0 else f"Stopped (exit {int(code)})"
        )
        self._status.setTextColor_(_MUTED)

    @objc.python_method
    def _stop_run(self) -> None:
        self._go.setTitle_("Stopping…")
        self._go.setEnabled_(False)
        self._status.setStringValue_("Stopping…")
        self._status.setTextColor_(_STOP)
        self._status_dot.setFillColor_(_STOP)
        self._subprocess_manager.stop()

    @objc.python_method
    def _set_en(self, on: bool) -> None:
        for c in self._all_config_controls:
            if isinstance(c, NSTextView):
                c.setEditable_(on)
            elif isinstance(c, NSPopUpButton):
                c.setEnabled_(on)
            else:
                c.setEnabled_(on)
        for b in self._bools.values():
            b.setEnabled_(on)

    @objc.python_method
    def _arm_log_polling(self) -> None:
        def tick(_t: NSTimer) -> None:
            while True:
                try:
                    line = self._log_queue.get_nowait()
                except queue.Empty:
                    break
                self._line(line)

        self._log_timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            0.1, True, tick
        )

    @objc.python_method
    def _line(self, s: str) -> None:
        ts = self._log.textStorage()
        if ts is None:
            return
        at_bottom = self._near_bottom()
        L = len(ts.string() or "")
        ns = str(s) + "\n"
        ts.replaceCharactersInRange_withString_((L, 0), ns)
        if at_bottom:
            self._log.scrollToEndOfDocument_(None)

    @objc.python_method
    def _near_bottom(self) -> bool:
        v = self._log.enclosingScrollView()
        if v is None:
            return True
        doc = v.documentView()
        if doc is None:
            return True
        vr = v.contentView().bounds()
        h = doc.bounds().size.height
        if h <= vr.size.height + 2.0:
            return True
        y = v.contentView().bounds().origin.y
        return y + vr.size.height >= h - 4.0

    def clearLogs_(self, sender) -> None:
        ts = self._log.textStorage()
        if ts is not None and ts.length():
            ts.deleteCharactersInRange_((0, int(ts.length())))

    def copyLogs_(self, sender) -> None:
        ts = self._log.textStorage()
        t = (ts.string() or "") if ts else ""
        p = NSPasteboard.generalPasteboard()
        p.clearContents()
        p.setString_forType_(t, NSStringPboardType)

    def toggleToken_(self, sender) -> None:
        self._token_shown = not self._token_shown
        if self._token_shown:
            s = str(self._stok.stringValue() or "")
            self._ptok.setStringValue_(s)
            self._stok.setHidden_(True)
            self._ptok.setHidden_(False)
            self._tokbtn.setTitle_("Hide")
        else:
            s = str(self._ptok.stringValue() or "")
            self._stok.setStringValue_(s)
            self._ptok.setHidden_(True)
            self._stok.setHidden_(False)
            self._tokbtn.setTitle_("Show")

    @objc.python_method
    def _should_stop(self) -> bool:
        a = NSAlert.alloc().init()
        a.setMessageText_("Quit")
        a.setInformativeText_("Macro is running. Stop it and quit?")
        a.addButtonWithTitle_("Quit")
        a.addButtonWithTitle_("Cancel")
        return int(a.runModal()) == int(NSAlertFirstButtonReturn)

    @objc.python_method
    def _menu(self) -> None:
        app = NSApplication.sharedApplication()
        bar = NSMenu.alloc().init()
        app_sub = NSMenuItem.alloc().init()
        sm = NSMenu.alloc().init()
        sm.addItem_(_ac_about(self))
        sm.addItem_(NSMenuItem.separatorItem())
        sm.addItem_(_ac_prefs(self))
        sm.addItem_(NSMenuItem.separatorItem())
        sm.addItem_(_ac_hide())
        sm.addItem_(NSMenuItem.separatorItem())
        q = (
            NSMenuItem.alloc()
            .initWithTitle_action_keyEquivalent_("Quit PokeMacro", b"terminate:", "q")
        )
        q.setKeyEquivalentModifierMask_(NSCommandKeyMask)
        sm.addItem_(q)
        app_sub.setSubmenu_(sm)
        app_sub.setTitle_("PokeMacro")
        bar.addItem_(app_sub)
        app.setMainMenu_(bar)

    @objc.python_method
    def run(self) -> None:
        start_background_update(log_queue=self._log_queue)
        app = NSApplication.sharedApplication()
        app.setDelegate_(self)
        self._menu()
        app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        self._window.setIsVisible_(True)
        app.activateIgnoringOtherApps_(True)
        app.run()

    def applicationShouldTerminate_(self, app) -> int:
        if not self._is_running:
            return int(NSTerminateNow)
        if self._should_stop():
            self._subprocess_manager.stop()
            return int(NSTerminateNow)
        return int(NSTerminateCancel)

    def windowShouldClose_(self, sender) -> bool:
        if not self._is_running:
            return True
        if self._should_stop():
            self._subprocess_manager.stop()
            return True
        return False


def main() -> None:
    c = PokeMacroController.alloc().init()
    if c is None:
        return
    c.run()


if __name__ == "__main__":
    main()
