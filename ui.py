"""
PokeMacro — native AppKit (PyObjC) UI
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

import objc
import yaml

from AppKit import (
    NSAlert, NSAlertFirstButtonReturn,
    NSApplication, NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton, NSButtonTypeMomentaryPushIn, NSButtonTypeSwitch,
    NSColor, NSCommandKeyMask,
    NSEdgeInsets, NSFont,
    NSFocusRingTypeNone,
    NSGridView, NSGridRowAlignmentFirstBaseline,
    NSImage, NSImageSymbolConfiguration, NSImageView,
    NSLayoutAttributeCenterY, NSLayoutAttributeLeading,
    NSLayoutPriorityDefaultHigh,
    NSLineBreakByTruncatingTail,
    NSMenu, NSMenuItem,
    NSNoTabsNoBorder, NSOffState, NSOnState,
    NSPasteboard, NSStringPboardType,
    NSPopUpButton, NSScrollView, NSSecureTextField,
    NSStackView, NSStackViewDistributionFill, NSStackViewGravityTop,
    NSTableCellView, NSTableColumn, NSTableColumnNoResizing,
    NSTableView, NSTableViewGridNone,
    NSTableViewSelectionHighlightStyleSourceList,
    NSTableViewStyleSourceList,
    NSTabView, NSTabViewItem,
    NSTerminateCancel, NSTerminateNow,
    NSTextField, NSTextView,
    NSToolbar, NSToolbarDisplayModeIconOnly, NSToolbarItem,
    NSUserInterfaceLayoutOrientationHorizontal,
    NSUserInterfaceLayoutOrientationVertical,
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialSidebar,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
    NSWindowTitleHidden,
)
from Foundation import (
    NSIndexSet, NSMakeRect, NSMakeSize,
    NSMutableAttributedString, NSObject,
    NSOperationQueue, NSTimer,
)

from src.git_update import start_background_update

# ── Project paths ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "configs.yaml"
_venv = PROJECT_ROOT / "ENV" / "bin" / "python"
VENV_PYTHON = _venv if _venv.exists() else Path(sys.executable)

# ── Layout constants ───────────────────────────────────────────────────
SIDEBAR_W = 200.0
UI_PAD    = 20.0
LABEL_W   = 155.0
FIELD_W   = 80.0
BADGE_W   = 16.0

# ── Data ───────────────────────────────────────────────────────────────
POSITION_KEYS = [
    ("EggManPosition",     "Egg Man Position"),
    ("EventButton",        "Event Button"),
    ("DialogueYES",        "Dialogue YES"),
    ("QuickRejoinSprite",  "Quick Rejoin Sprite"),
    ("QuickRejoinButton",  "Quick Rejoin Button"),
    ("MenuButton",         "Menu Button"),
    ("SaveButton",         "Save Button"),
    ("LoadingScreenYellow","Loading Screen Yellow"),
    ("SaveFileCard",       "Save File Card"),
    ("RunButton",          "Run Button"),
    ("Pokeball",           "Pokeball"),
]

SIDEBAR_ITEMS = [
    ("General",   "gearshape"),
    ("Wishlist",  "star.fill"),
    ("Positions", "mappin.and.ellipse"),
    ("Logs",      "doc.text"),
]

_TB_STATUS  = "PM.status"
_TB_FLEX    = "NSToolbarFlexibleSpaceItem"
_TB_SAVE    = "PM.save"
_TB_RUN     = "PM.run"
_TB_DEFAULT = [_TB_STATUS, _TB_FLEX, _TB_SAVE, _TB_RUN]


# ── Color namespace ────────────────────────────────────────────────────
class _Colors:
    IDLE  = None
    RUN   = None
    STOP  = None
    MUTED = None


def _init_colors() -> None:
    if _Colors.IDLE is not None:
        return
    _Colors.IDLE  = NSColor.colorWithRed_green_blue_alpha_(0.71, 0.71, 0.73, 1.0)
    _Colors.RUN   = NSColor.systemGreenColor()
    _Colors.STOP  = NSColor.systemRedColor()
    _Colors.MUTED = NSColor.secondaryLabelColor()


# ── Flipped view (y=0 at top) for scroll view document views ──────────
class _FlippedView(NSView):
    def isFlipped(self) -> bool:
        return True


# ── Card view (dark-mode adaptive bordered box) ────────────────────────
class _CardView(NSView):
    def viewDidChangeEffectiveAppearance(self) -> None:
        objc.super(_CardView, self).viewDidChangeEffectiveAppearance()
        self._refresh()

    @objc.python_method
    def _refresh(self) -> None:
        layer = self.layer()
        if layer is None:
            return
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bg = NSColor.controlBackgroundColor().CGColor()
            bd = NSColor.separatorColor().CGColor()
        if bg:
            layer.setBackgroundColor_(bg)
        if bd:
            layer.setBorderColor_(bd)


# ── Integer field parser ───────────────────────────────────────────────
def _int_val(f: NSTextField) -> int:
    s = (f.stringValue() or "").strip() or "0"
    try:
        return int(s)
    except ValueError:
        return 0


# ── UI factory helpers ─────────────────────────────────────────────────
class _UI:
    @staticmethod
    def label(text: str, size: float = 13.0,
              color: NSColor | None = None, bold: bool = False) -> NSTextField:
        t = NSTextField.labelWithString_(text)
        t.setFont_(
            NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
        )
        if color is not None:
            t.setTextColor_(color)
        t.setLineBreakMode_(NSLineBreakByTruncatingTail)
        return t

    @staticmethod
    def mono_font(size: float = 12.0) -> NSFont:
        return NSFont.monospacedSystemFontOfSize_weight_(size, 0)

    @staticmethod
    def field(placeholder: str = "", width: float | None = None) -> NSTextField:
        f = NSTextField.alloc().init()
        f.setBezeled_(True)
        f.setStringValue_("")
        f.cell().setScrollable_(False)
        f.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
        if placeholder:
            f.setPlaceholderString_(placeholder)
        if width is not None:
            f.setTranslatesAutoresizingMaskIntoConstraints_(False)
            f.widthAnchor().constraintEqualToConstant_(width).setActive_(True)
        return f

    @staticmethod
    def button(title: str, target: object, action: bytes,
               key: str = "", mod: int = 0) -> NSButton:
        b = NSButton.alloc().init()
        b.setButtonType_(NSButtonTypeMomentaryPushIn)
        b.setBezelStyle_(NSBezelStyleRounded)
        b.setTitle_(title)
        b.setTarget_(target)
        b.setAction_(action)
        if key:
            b.setKeyEquivalent_(key)
            if mod:
                b.setKeyEquivalentModifierMask_(mod)
        return b

    @staticmethod
    def popup(items: list[str]) -> NSPopUpButton:
        p = NSPopUpButton.alloc().init()
        p.addItemsWithTitles_(items)
        return p

    @staticmethod
    def checkbox(title: str) -> NSButton:
        b = NSButton.alloc().init()
        b.setButtonType_(NSButtonTypeSwitch)
        b.setTitle_(title)
        return b

    @staticmethod
    def h_stack(spacing: float = 8.0) -> NSStackView:
        s = NSStackView.stackViewWithViews_([])
        s.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
        s.setSpacing_(spacing)
        s.setAlignment_(NSLayoutAttributeCenterY)
        return s

    @staticmethod
    def v_stack(spacing: float = 8.0) -> NSStackView:
        s = NSStackView.stackViewWithViews_([])
        s.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        s.setSpacing_(spacing)
        s.setAlignment_(NSLayoutAttributeLeading)
        return s

    @staticmethod
    def pin_edges(inner: NSView, outer: NSView) -> None:
        inner.setTranslatesAutoresizingMaskIntoConstraints_(False)
        inner.leadingAnchor().constraintEqualToAnchor_(outer.leadingAnchor()).setActive_(True)
        inner.trailingAnchor().constraintEqualToAnchor_(outer.trailingAnchor()).setActive_(True)
        inner.topAnchor().constraintEqualToAnchor_(outer.topAnchor()).setActive_(True)
        inner.bottomAnchor().constraintEqualToAnchor_(outer.bottomAnchor()).setActive_(True)

    @staticmethod
    def set_bg(view: NSView, color: NSColor) -> None:
        view.setWantsLayer_(True)
        layer = view.layer()
        if layer is not None:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cg = color.CGColor()
            if cg is not None:
                layer.setBackgroundColor_(cg)

    @staticmethod
    def spacer_h() -> NSView:
        v = NSView.alloc().init()
        v.setTranslatesAutoresizingMaskIntoConstraints_(False)
        v.setContentHuggingPriority_forOrientation_(
            1, NSUserInterfaceLayoutOrientationHorizontal
        )
        return v

    @staticmethod
    def spacer_v() -> NSView:
        v = NSView.alloc().init()
        v.setTranslatesAutoresizingMaskIntoConstraints_(False)
        v.setContentHuggingPriority_forOrientation_(
            1, NSUserInterfaceLayoutOrientationVertical
        )
        return v

    @staticmethod
    def scroll(doc: NSView, min_height: float) -> NSScrollView:
        sc = NSScrollView.alloc().init()
        sc.setDocumentView_(doc)
        sc.setHasVerticalScroller_(True)
        sc.setAutohidesScrollers_(True)
        sc.setBorderType_(0)
        sc.setDrawsBackground_(True)
        sc.setTranslatesAutoresizingMaskIntoConstraints_(False)
        sc.heightAnchor().constraintEqualToConstant_(min_height).setActive_(True)
        return sc

    @staticmethod
    def full_scroll(doc: NSView) -> NSScrollView:
        doc.setTranslatesAutoresizingMaskIntoConstraints_(False)
        sc = NSScrollView.alloc().init()
        sc.setDocumentView_(doc)
        sc.setDrawsBackground_(True)
        sc.setHasVerticalScroller_(True)
        sc.setAutohidesScrollers_(True)
        sc.setBorderType_(0)
        sc.setTranslatesAutoresizingMaskIntoConstraints_(False)
        cv = sc.contentView()
        doc.leadingAnchor().constraintEqualToAnchor_(cv.leadingAnchor()).setActive_(True)
        doc.trailingAnchor().constraintEqualToAnchor_(cv.trailingAnchor()).setActive_(True)
        doc.topAnchor().constraintEqualToAnchor_(cv.topAnchor()).setActive_(True)
        doc.widthAnchor().constraintEqualToAnchor_(cv.widthAnchor()).setActive_(True)
        return sc

    @staticmethod
    def add_card(stack: NSStackView, content: NSView, pad: float = UI_PAD) -> NSView:
        """Wrap `content` in a card and append to `stack`, constraining the card
        to span the stack's full width (minus `pad` on each side) so all cards
        in a column line up."""
        box = _UI.box(content)
        stack.addView_inGravity_(box, NSStackViewGravityTop)
        box.widthAnchor().constraintEqualToAnchor_constant_(
            stack.widthAnchor(), -2 * pad
        ).setActive_(True)
        return box

    @staticmethod
    def tab_scroll(doc: NSView) -> NSView:
        """Scrollable tab content view. Uses a flipped document container so
        content anchors to the top, wrapped in a plain NSView so NSTabView
        can resize it via setFrame:."""
        fv = _FlippedView.alloc().init()
        fv.setTranslatesAutoresizingMaskIntoConstraints_(False)
        doc.setTranslatesAutoresizingMaskIntoConstraints_(False)
        fv.addSubview_(doc)
        doc.leadingAnchor().constraintEqualToAnchor_(fv.leadingAnchor()).setActive_(True)
        doc.trailingAnchor().constraintEqualToAnchor_(fv.trailingAnchor()).setActive_(True)
        doc.topAnchor().constraintEqualToAnchor_(fv.topAnchor()).setActive_(True)
        doc.bottomAnchor().constraintEqualToAnchor_(fv.bottomAnchor()).setActive_(True)

        sc = NSScrollView.alloc().init()
        sc.setDocumentView_(fv)
        sc.setDrawsBackground_(True)
        sc.setHasVerticalScroller_(True)
        sc.setAutohidesScrollers_(True)
        sc.setBorderType_(0)

        cv = sc.contentView()
        fv.leadingAnchor().constraintEqualToAnchor_(cv.leadingAnchor()).setActive_(True)
        fv.topAnchor().constraintEqualToAnchor_(cv.topAnchor()).setActive_(True)
        fv.widthAnchor().constraintEqualToAnchor_(cv.widthAnchor()).setActive_(True)

        w = NSView.alloc().init()
        sc.setTranslatesAutoresizingMaskIntoConstraints_(False)
        w.addSubview_(sc)
        _UI.pin_edges(sc, w)
        return w

    @staticmethod
    def box(inner: NSView) -> NSView:
        card = _CardView.alloc().init()
        card.setWantsLayer_(True)
        card.setTranslatesAutoresizingMaskIntoConstraints_(False)
        card._refresh()
        layer = card.layer()
        if layer is not None:
            layer.setCornerRadius_(8.0)
            layer.setBorderWidth_(1.0)
        inner.setTranslatesAutoresizingMaskIntoConstraints_(False)
        card.addSubview_(inner)
        H, V = 12.0, 10.0
        inner.topAnchor().constraintEqualToAnchor_constant_(card.topAnchor(), V).setActive_(True)
        inner.bottomAnchor().constraintEqualToAnchor_constant_(card.bottomAnchor(), -V).setActive_(True)
        inner.leadingAnchor().constraintEqualToAnchor_constant_(card.leadingAnchor(), H).setActive_(True)
        inner.trailingAnchor().constraintEqualToAnchor_constant_(card.trailingAnchor(), -H).setActive_(True)
        return card

    @staticmethod
    def sf(name: str, description: str, size: float = 15.0,
           weight: float = 0.0) -> NSImage | None:
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, description)
        if img is None:
            return None
        cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(size, weight)
        return img.imageWithSymbolConfiguration_(cfg)

    @staticmethod
    def _make_sidebar_cell(identifier: str) -> NSTableCellView:
        cell = NSTableCellView.alloc().initWithFrame_(NSMakeRect(0, 0, SIDEBAR_W, 28))
        cell.setIdentifier_(identifier)

        iv = NSImageView.alloc().init()
        iv.setTranslatesAutoresizingMaskIntoConstraints_(False)
        iv.setContentTintColor_(NSColor.secondaryLabelColor())
        iv.widthAnchor().constraintEqualToConstant_(16.0).setActive_(True)
        iv.heightAnchor().constraintEqualToConstant_(16.0).setActive_(True)
        cell.setImageView_(iv)

        tf = NSTextField.labelWithString_("")
        tf.setFont_(NSFont.systemFontOfSize_(13.0))
        tf.setLineBreakMode_(NSLineBreakByTruncatingTail)
        cell.setTextField_(tf)

        row = NSStackView.stackViewWithViews_([])
        row.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
        row.setSpacing_(7.0)
        row.setAlignment_(NSLayoutAttributeCenterY)
        row.setEdgeInsets_(NSEdgeInsets(0, 10, 0, 8))
        row.addView_inGravity_(iv, NSStackViewGravityTop)
        row.addView_inGravity_(tf, NSStackViewGravityTop)
        row.setTranslatesAutoresizingMaskIntoConstraints_(False)

        cell.addSubview_(row)
        row.leadingAnchor().constraintEqualToAnchor_(cell.leadingAnchor()).setActive_(True)
        row.trailingAnchor().constraintEqualToAnchor_(cell.trailingAnchor()).setActive_(True)
        row.topAnchor().constraintEqualToAnchor_(cell.topAnchor()).setActive_(True)
        row.bottomAnchor().constraintEqualToAnchor_(cell.bottomAnchor()).setActive_(True)

        return cell


# ── Config + subprocess (unchanged logic) ─────────────────────────────
class ConfigManager:
    def load(self) -> dict:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return self._default()

    def save(self, data: dict) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _default(self) -> dict:
        return {
            "HuntingMode": "egg",
            "Username": "",
            "Mode": "Default",
            "IsReskin": False, "IsShiny": False, "IsGradient": False,
            "IsAny": True, "IsGood": False,
            "Wishlist": {"Reskins": [], "Gradients": [], "Roamings": [], "Special": []},
            "Positions": {k: [0, 0] for k, _ in POSITION_KEYS},
            "ChatWindow":          {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
            "EncounterNameRegion": {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
            "SpriteRegion":        {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
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
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        self._log_thread = threading.Thread(
            target=self._stream, args=(log_queue, on_exit), daemon=True
        )
        self._log_thread.start()

    def _stream(self, log_queue: queue.Queue, on_exit: Callable[[int], None]) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            log_queue.put(line.rstrip("\n"))
        self._proc.wait()
        code = int(self._proc.returncode or 0)
        NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: on_exit(code))

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

            def _wait() -> None:
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()

            threading.Thread(target=_wait, daemon=True).start()

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


# ── Adaptive text views ────────────────────────────────────────────────
class _AdaptiveLogTextView(NSTextView):
    def viewDidChangeEffectiveAppearance(self) -> None:
        objc.super(_AdaptiveLogTextView, self).viewDidChangeEffectiveAppearance()
        self._apply()

    @objc.python_method
    def _apply(self) -> None:
        self.setDrawsBackground_(True)
        self.setBackgroundColor_(NSColor.textBackgroundColor())
        self.setTextColor_(NSColor.textColor())


class _AdaptiveWishTextView(NSTextView):
    def viewDidChangeEffectiveAppearance(self) -> None:
        objc.super(_AdaptiveWishTextView, self).viewDidChangeEffectiveAppearance()
        self._apply()

    @objc.python_method
    def _apply(self) -> None:
        self.setDrawsBackground_(True)
        self.setBackgroundColor_(NSColor.textBackgroundColor())
        self.setTextColor_(NSColor.textColor())


# ── Sidebar table data source / delegate ───────────────────────────────
class SidebarSource(NSObject):
    def initWithController_(self, controller):
        self = objc.super(SidebarSource, self).init()
        if self is None:
            return None
        self._ctrl = controller
        self._table = None
        return self

    @objc.python_method
    def attach(self, table: NSTableView) -> None:
        self._table = table
        table.setDataSource_(self)
        table.setDelegate_(self)
        table.reloadData()
        table.selectRowIndexes_byExtendingSelection_(
            NSIndexSet.indexSetWithIndex_(0), False
        )

    def numberOfRowsInTableView_(self, table) -> int:
        return len(SIDEBAR_ITEMS)

    def tableView_viewForTableColumn_row_(self, table, column, row) -> NSView:
        ident = "SidebarCell"
        cell = table.makeViewWithIdentifier_owner_(ident, self)
        if cell is None:
            cell = _UI._make_sidebar_cell(ident)
        label, symbol = SIDEBAR_ITEMS[int(row)]
        cell.textField().setStringValue_(label)
        img = _UI.sf(symbol, label, size=14.0)
        if img is not None:
            cell.imageView().setImage_(img)
        return cell

    def tableViewSelectionDidChange_(self, notification) -> None:
        table = notification.object()
        idx = int(table.selectedRow())
        if 0 <= idx < len(SIDEBAR_ITEMS):
            self._ctrl.switchToTab_(idx)


# ── Main controller ────────────────────────────────────────────────────
class PokeMacroController(NSObject):

    def init(self):
        self = objc.super(PokeMacroController, self).init()
        if self is None:
            return None
        _init_colors()
        self._config_manager   = ConfigManager()
        self._subprocess_mgr   = SubprocessManager()
        self._config: dict     = self._config_manager.load()
        self._is_running       = False
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._all_config_controls: list   = []
        self._token_shown      = False
        self._log_timer        = None
        self._status_reset_timer = None
        self._sidebar_source   = None
        self._sidebar_tv       = None
        self._run_item         = None
        self._status_iv        = None
        self._status_label     = None

        self._build_content_panels()
        self._build_window()
        self._load_all_fields()
        self._arm_log_polling()
        return self

    # ── Content panels ─────────────────────────────────────────────
    @objc.python_method
    def _build_content_panels(self) -> None:
        self._tab = NSTabView.alloc().init()
        self._tab.setTabViewType_(NSNoTabsNoBorder)
        for label, builder in [
            ("General",   self._tab_general),
            ("Wishlist",  self._tab_wishlist),
            ("Positions", self._tab_positions),
            ("Logs",      self._tab_logs),
        ]:
            view = builder()
            item = NSTabViewItem.alloc().initWithIdentifier_(label)
            item.setLabel_(label)
            item.setView_(view)
            self._tab.addTabViewItem_(item)
        self._tab.selectTabViewItemAtIndex_(0)
        self._tab.setTranslatesAutoresizingMaskIntoConstraints_(False)

    # ── Window ─────────────────────────────────────────────────────
    @objc.python_method
    def _build_window(self) -> None:
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable
            | NSWindowStyleMaskFullSizeContentView
        )
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(120, 120, 630, 580), style, NSBackingStoreBuffered, False
        )
        self._window.setTitle_("PokeMacro")
        self._window.setTitleVisibility_(NSWindowTitleHidden)
        self._window.setTitlebarAppearsTransparent_(True)
        self._window.setMinSize_(NSMakeSize(628, 500))
        self._window.setDelegate_(self)
        self._window.setReleasedWhenClosed_(False)
        self._build_toolbar()
        self._window.setToolbar_(self._toolbar)
        self._window.setContentView_(self._build_split_view())
        guide = self._window.contentLayoutGuide()
        self._sidebar_sv.topAnchor().constraintEqualToAnchor_(guide.topAnchor()).setActive_(True)
        self._tab.topAnchor().constraintEqualToAnchor_(guide.topAnchor()).setActive_(True)
        self._window.makeKeyAndOrderFront_(None)

    # ── Toolbar ────────────────────────────────────────────────────
    @objc.python_method
    def _build_toolbar(self) -> None:
        self._toolbar = NSToolbar.alloc().initWithIdentifier_("PokeMacroToolbar")
        self._toolbar.setDelegate_(self)
        self._toolbar.setDisplayMode_(NSToolbarDisplayModeIconOnly)
        self._toolbar.setAllowsUserCustomization_(False)
        self._toolbar.setShowsBaselineSeparator_(False)

    def toolbarDefaultItemIdentifiers_(self, toolbar) -> list:
        return _TB_DEFAULT

    def toolbarAllowedItemIdentifiers_(self, toolbar) -> list:
        return _TB_DEFAULT

    def toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(
            self, toolbar, identifier: str, flag: bool):
        item = NSToolbarItem.alloc().initWithItemIdentifier_(identifier)

        if identifier == _TB_STATUS:
            self._status_iv = NSImageView.alloc().init()
            self._status_iv.setTranslatesAutoresizingMaskIntoConstraints_(False)
            self._status_iv.setContentTintColor_(NSColor.tertiaryLabelColor())
            dot = _UI.sf("circle.fill", "Status", size=9.0)
            if dot:
                self._status_iv.setImage_(dot)
            self._status_iv.widthAnchor().constraintEqualToConstant_(11.0).setActive_(True)
            self._status_iv.heightAnchor().constraintEqualToConstant_(11.0).setActive_(True)

            self._status_label = NSTextField.labelWithString_("Idle")
            self._status_label.setFont_(NSFont.systemFontOfSize_(12.0))
            self._status_label.setTextColor_(NSColor.secondaryLabelColor())

            row = _UI.h_stack(spacing=5.0)
            row.addView_inGravity_(self._status_iv,    NSStackViewGravityTop)
            row.addView_inGravity_(self._status_label, NSStackViewGravityTop)
            row.setTranslatesAutoresizingMaskIntoConstraints_(False)
            item.setView_(row)
            item.setMinSize_(NSMakeSize(60, 28))
            item.setMaxSize_(NSMakeSize(220, 28))

        elif identifier == _TB_SAVE:
            img = _UI.sf("square.and.arrow.down", "Save", size=16.0)
            item.setImage_(img)
            item.setLabel_("Save")
            item.setPaletteLabel_("Save")
            item.setBordered_(True)
            item.setTarget_(self)
            item.setAction_(b"saveConfig:")

        elif identifier == _TB_RUN:
            self._run_item = item
            img = _UI.sf("play.fill", "Start", size=16.0)
            item.setImage_(img)
            item.setLabel_("Start")
            item.setPaletteLabel_("Start/Stop")
            item.setBordered_(True)
            item.setTarget_(self)
            item.setAction_(b"toggleRun:")

        return item

    # ── Split view (sidebar + content) ─────────────────────────────
    @objc.python_method
    def _build_split_view(self) -> NSView:
        eff = NSVisualEffectView.alloc().init()
        eff.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        eff.setMaterial_(NSVisualEffectMaterialSidebar)
        eff.setState_(NSVisualEffectStateActive)
        eff.setWantsLayer_(True)
        # Round only the two left corners to match the window corner radius.
        # CACornerMask: kCALayerMinXMinYCorner=1 (bottom-left),
        #               kCALayerMinXMaxYCorner=4 (top-left) in CA coords (Y-up).
        # masksToBounds is intentionally NOT set — it hard-clips the blur
        # material along straight edges and creates a visible seam.
        eff.layer().setCornerRadius_(10.0)
        eff.layer().setMaskedCorners_(1 | 4)
        eff.setTranslatesAutoresizingMaskIntoConstraints_(False)
        eff.widthAnchor().constraintEqualToConstant_(SIDEBAR_W).setActive_(True)
        eff.setContentHuggingPriority_forOrientation_(
            NSLayoutPriorityDefaultHigh, NSUserInterfaceLayoutOrientationHorizontal
        )

        sidebar_scroll = self._build_sidebar()
        eff.addSubview_(sidebar_scroll)
        sidebar_scroll.setTranslatesAutoresizingMaskIntoConstraints_(False)
        sidebar_scroll.leadingAnchor().constraintEqualToAnchor_(eff.leadingAnchor()).setActive_(True)
        sidebar_scroll.trailingAnchor().constraintEqualToAnchor_(eff.trailingAnchor()).setActive_(True)
        sidebar_scroll.bottomAnchor().constraintEqualToAnchor_(eff.bottomAnchor()).setActive_(True)

        sep = NSView.alloc().init()
        sep.setTranslatesAutoresizingMaskIntoConstraints_(False)
        _UI.set_bg(sep, NSColor.separatorColor())
        sep.widthAnchor().constraintEqualToConstant_(1.0).setActive_(True)
        sep.setContentHuggingPriority_forOrientation_(
            NSLayoutPriorityDefaultHigh, NSUserInterfaceLayoutOrientationHorizontal
        )

        content = NSView.alloc().init()
        content.setTranslatesAutoresizingMaskIntoConstraints_(False)
        content.setContentHuggingPriority_forOrientation_(
            1, NSUserInterfaceLayoutOrientationHorizontal
        )
        content.addSubview_(self._tab)
        self._tab.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self._tab.leadingAnchor().constraintEqualToAnchor_(content.leadingAnchor()).setActive_(True)
        self._tab.trailingAnchor().constraintEqualToAnchor_(content.trailingAnchor()).setActive_(True)
        self._tab.bottomAnchor().constraintEqualToAnchor_(content.bottomAnchor()).setActive_(True)

        h = _UI.h_stack(spacing=0.0)
        h.setDistribution_(NSStackViewDistributionFill)
        h.addView_inGravity_(eff,     NSStackViewGravityTop)
        h.addView_inGravity_(sep,     NSStackViewGravityTop)
        h.addView_inGravity_(content, NSStackViewGravityTop)
        h.setTranslatesAutoresizingMaskIntoConstraints_(False)
        return h

    @objc.python_method
    def _build_sidebar(self) -> NSScrollView:
        tv = NSTableView.alloc().init()
        tv.setStyle_(NSTableViewStyleSourceList)
        tv.setSelectionHighlightStyle_(NSTableViewSelectionHighlightStyleSourceList)
        tv.setHeaderView_(None)
        tv.setFocusRingType_(NSFocusRingTypeNone)
        tv.setRowHeight_(28.0)
        tv.setGridStyleMask_(NSTableViewGridNone)
        tv.setIntercellSpacing_(NSMakeSize(0.0, 0.0))
        tv.setAllowsEmptySelection_(False)
        tv.setAllowsMultipleSelection_(False)
        tv.setBackgroundColor_(NSColor.clearColor())

        col = NSTableColumn.alloc().initWithIdentifier_("sidebar")
        col.setResizingMask_(NSTableColumnNoResizing)
        col.setWidth_(SIDEBAR_W - 2)
        tv.addTableColumn_(col)

        self._sidebar_source = SidebarSource.alloc().initWithController_(self)
        self._sidebar_source.attach(tv)
        self._sidebar_tv = tv

        sv = NSScrollView.alloc().init()
        sv.setDocumentView_(tv)
        sv.setHasVerticalScroller_(False)
        sv.setAutohidesScrollers_(True)
        sv.setBorderType_(0)
        sv.setDrawsBackground_(False)
        sv.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self._sidebar_sv = sv
        return sv

    # ── General tab ────────────────────────────────────────────────
    @objc.python_method
    def _form_row(self, label_text: str, field: NSView) -> NSStackView:
        row = _UI.h_stack(spacing=12.0)
        la = _UI.label(label_text)
        la.setTranslatesAutoresizingMaskIntoConstraints_(False)
        la.widthAnchor().constraintEqualToConstant_(LABEL_W).setActive_(True)
        la.setContentHuggingPriority_forOrientation_(
            NSLayoutPriorityDefaultHigh, NSUserInterfaceLayoutOrientationHorizontal
        )
        row.addView_inGravity_(la,    NSStackViewGravityTop)
        row.addView_inGravity_(field, NSStackViewGravityTop)
        row.setDistribution_(NSStackViewDistributionFill)
        return row

    @objc.python_method
    def _tab_general(self) -> NSView:
        outer = _UI.v_stack(spacing=14.0)
        outer.setEdgeInsets_(NSEdgeInsets(UI_PAD, UI_PAD, UI_PAD, UI_PAD))

        hunt = _UI.v_stack(spacing=10.0)
        hunt.addView_inGravity_(
            _UI.label("Hunt", size=11.0, color=NSColor.secondaryLabelColor()),
            NSStackViewGravityTop,
        )
        self._hunt = _UI.popup(["egg", "roam"])
        self._all_config_controls.append(self._hunt)
        hunt.addView_inGravity_(self._form_row("Hunting mode", self._hunt), NSStackViewGravityTop)

        self._user = _UI.field()
        self._all_config_controls.append(self._user)
        hunt.addView_inGravity_(self._form_row("Username", self._user), NSStackViewGravityTop)

        self._fast = _UI.popup(["Default", "Fast"])
        self._all_config_controls.append(self._fast)
        hunt.addView_inGravity_(self._form_row("Speed", self._fast), NSStackViewGravityTop)
        _UI.add_card(outer, hunt)

        filters = _UI.v_stack(spacing=8.0)
        filters.addView_inGravity_(
            _UI.label("Filters", size=11.0, color=NSColor.secondaryLabelColor()),
            NSStackViewGravityTop,
        )
        self._bools: dict[str, NSButton] = {}
        for key, title in [
            ("IsReskin",   "Reskin"),
            ("IsShiny",    "Shiny"),
            ("IsGradient", "Gradient"),
            ("IsAny",      "Any"),
            ("IsGood",     "Good"),
        ]:
            cb = _UI.checkbox(title)
            self._bools[key] = cb
            self._all_config_controls.append(cb)
            filters.addView_inGravity_(cb, NSStackViewGravityTop)
        _UI.add_card(outer, filters)
        outer.addView_inGravity_(_UI.spacer_v(), NSStackViewGravityTop)

        w = NSView.alloc().init()
        w.addSubview_(outer)
        _UI.pin_edges(outer, w)
        return w

    # ── Wishlist tab ───────────────────────────────────────────────
    @objc.python_method
    def _tab_wishlist(self) -> NSView:
        outer = _UI.v_stack(spacing=12.0)
        outer.setEdgeInsets_(NSEdgeInsets(UI_PAD, UI_PAD, UI_PAD, UI_PAD))
        outer.addView_inGravity_(
            _UI.label(
                "One item per line, or comma-separated values.",
                size=11.0, color=NSColor.secondaryLabelColor(),
            ),
            NSStackViewGravityTop,
        )
        self._wish: dict[str, NSTextView] = {}
        for name, h in [("Reskins", 80), ("Gradients", 80), ("Roamings", 140), ("Special", 140)]:
            inner = _UI.v_stack(spacing=6.0)
            inner.addView_inGravity_(
                _UI.label(name, size=12.0, bold=True),
                NSStackViewGravityTop,
            )

            sc = NSScrollView.alloc().init()
            sc.setHasVerticalScroller_(True)
            sc.setHasHorizontalScroller_(False)
            sc.setAutohidesScrollers_(True)
            sc.setBorderType_(0)  # no AppKit bezel — border drawn via layer
            sc.setDrawsBackground_(True)
            sc.setWantsLayer_(True)
            sc.layer().setCornerRadius_(5.0)
            sc.layer().setMasksToBounds_(True)
            sc.layer().setBorderWidth_(1.0)
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sc.layer().setBorderColor_(NSColor.separatorColor().CGColor())
            sc.setTranslatesAutoresizingMaskIntoConstraints_(False)
            sc.heightAnchor().constraintEqualToConstant_(h).setActive_(True)

            tv = _AdaptiveWishTextView.alloc().initWithFrame_(
                NSMakeRect(0, 0, 200, h)
            )
            tv.setMinSize_(NSMakeSize(0, h))
            tv.setMaxSize_(NSMakeSize(1e7, 1e7))
            tv.setVerticallyResizable_(True)
            tv.setHorizontallyResizable_(False)
            # NSViewWidthSizable (2) makes the text view track its superview
            # (the NSClipView) width — NSScrollView manages this via its own
            # internal mechanism and must NOT be replaced with Auto Layout
            # constraints (which break editing and scrolling).
            tv.setAutoresizingMask_(2)
            tv.textContainer().setWidthTracksTextView_(True)
            tv.setTextContainerInset_((5, 5))
            tv.setFont_(_UI.mono_font(12.0))
            tv._apply()
            sc.setDocumentView_(tv)

            inner.addView_inGravity_(sc, NSStackViewGravityTop)
            self._wish[name] = tv
            self._all_config_controls.append(tv)
            _UI.add_card(outer, inner)

        return _UI.tab_scroll(outer)

    # ── Positions tab ──────────────────────────────────────────────
    @objc.python_method
    def _make_coord_grid(
        self, rows: list[tuple[str, str]]
    ) -> tuple[NSGridView, dict[str, tuple[NSTextField, NSTextField]]]:
        gv = NSGridView.alloc().init()
        gv.setColumnSpacing_(4.0)
        gv.setRowSpacing_(6.0)
        result: dict[str, tuple[NSTextField, NSTextField]] = {}
        for key, label_text in rows:
            la = _UI.label(label_text)
            xb = _UI.label("X", size=11.0, color=NSColor.secondaryLabelColor())
            yb = _UI.label("Y", size=11.0, color=NSColor.secondaryLabelColor())
            xf = _UI.field(width=FIELD_W)
            xf.setStringValue_("0")
            yf = _UI.field(width=FIELD_W)
            yf.setStringValue_("0")
            result[key] = (xf, yf)
            row = gv.addRowWithViews_([la, xb, xf, yb, yf])
            row.setRowAlignment_(NSGridRowAlignmentFirstBaseline)
        gv.columnAtIndex_(0).setWidth_(LABEL_W)
        gv.columnAtIndex_(1).setWidth_(BADGE_W)
        gv.columnAtIndex_(2).setWidth_(FIELD_W)
        gv.columnAtIndex_(3).setWidth_(BADGE_W)
        gv.columnAtIndex_(4).setWidth_(FIELD_W)
        return gv, result

    @objc.python_method
    def _tab_positions(self) -> NSView:
        outer = _UI.v_stack(spacing=14.0)
        outer.setEdgeInsets_(NSEdgeInsets(UI_PAD, UI_PAD, UI_PAD, UI_PAD))

        markers = _UI.v_stack(spacing=8.0)
        markers.addView_inGravity_(
            _UI.label("Clicks and markers", size=11.0, color=NSColor.secondaryLabelColor()),
            NSStackViewGravityTop,
        )
        grid, self._pos = self._make_coord_grid(POSITION_KEYS)
        grid.setTranslatesAutoresizingMaskIntoConstraints_(False)
        for xf, yf in self._pos.values():
            self._all_config_controls.extend([xf, yf])
        markers.addView_inGravity_(grid, NSStackViewGravityTop)
        _UI.add_card(outer, markers)

        self._regions: dict[str, dict[str, tuple[NSTextField, NSTextField]]] = {}
        for title, rkey in [
            ("Chat",           "ChatWindow"),
            ("Encounter name", "EncounterNameRegion"),
            ("Sprite",         "SpriteRegion"),
        ]:
            reg = _UI.v_stack(spacing=8.0)
            reg.addView_inGravity_(
                _UI.label(title, size=11.0, color=NSColor.secondaryLabelColor()),
                NSStackViewGravityTop,
            )
            grid_r, d = self._make_coord_grid([
                ("LeftCorner",  "Left corner"),
                ("RightCorner", "Right corner"),
            ])
            self._regions[rkey] = d
            for xf, yf in d.values():
                self._all_config_controls.extend([xf, yf])
            grid_r.setTranslatesAutoresizingMaskIntoConstraints_(False)
            reg.addView_inGravity_(grid_r, NSStackViewGravityTop)
            _UI.add_card(outer, reg)

        return _UI.tab_scroll(outer)

    # ── Logs tab ───────────────────────────────────────────────────
    @objc.python_method
    def _tab_logs(self) -> NSView:
        outer = _UI.v_stack(spacing=14.0)
        outer.setEdgeInsets_(NSEdgeInsets(UI_PAD, UI_PAD, UI_PAD, UI_PAD))

        discord = _UI.v_stack(spacing=10.0)
        discord.addView_inGravity_(
            _UI.label("Discord", size=11.0, color=NSColor.secondaryLabelColor()),
            NSStackViewGravityTop,
        )
        self._stok = NSSecureTextField.alloc().init()
        self._stok.setStringValue_("")
        self._stok.setBezeled_(True)
        self._stok.cell().setScrollable_(False)
        self._ptok = NSTextField.alloc().init()
        self._ptok.setStringValue_("")
        self._ptok.setBezeled_(True)
        self._ptok.cell().setScrollable_(False)
        self._ptok.setHidden_(True)
        self._all_config_controls.extend([self._stok, self._ptok])

        tok_stack = _UI.v_stack(spacing=0.0)
        tok_stack.addView_inGravity_(self._stok, NSStackViewGravityTop)
        tok_stack.addView_inGravity_(self._ptok, NSStackViewGravityTop)

        self._tokbtn = _UI.button("Show", self, b"toggleToken:")
        tok_row = _UI.h_stack(spacing=8.0)
        tok_row.setDistribution_(NSStackViewDistributionFill)
        tok_row.addView_inGravity_(_UI.label("Bot token"), NSStackViewGravityTop)
        tok_row.addView_inGravity_(tok_stack,       NSStackViewGravityTop)
        tok_row.addView_inGravity_(self._tokbtn,    NSStackViewGravityTop)
        discord.addView_inGravity_(tok_row, NSStackViewGravityTop)

        self._server = NSTextField.alloc().init()
        self._server.setStringValue_("0")
        self._server.setBezeled_(True)
        self._server.cell().setScrollable_(False)
        self._all_config_controls.append(self._server)
        discord.addView_inGravity_(
            self._form_row("Server ID (numeric)", self._server), NSStackViewGravityTop
        )
        _UI.add_card(outer, discord)

        output = _UI.v_stack(spacing=8.0)
        output.addView_inGravity_(
            _UI.label("Output", size=11.0, color=NSColor.secondaryLabelColor()),
            NSStackViewGravityTop,
        )
        btn_row = _UI.h_stack(spacing=6.0)
        btn_row.addView_inGravity_(_UI.spacer_h(),                               NSStackViewGravityTop)
        btn_row.addView_inGravity_(_UI.button("Copy",  self, b"copyLogs:"),      NSStackViewGravityTop)
        btn_row.addView_inGravity_(_UI.button("Clear", self, b"clearLogs:"),     NSStackViewGravityTop)
        output.addView_inGravity_(btn_row, NSStackViewGravityTop)

        self._log = _AdaptiveLogTextView.alloc().init()
        self._log.setEditable_(False)
        self._log.setSelectable_(True)
        self._log.setFont_(_UI.mono_font())
        self._log.setTextContainerInset_((6, 6))
        self._log._apply()
        output.addView_inGravity_(_UI.scroll(self._log, 300), NSStackViewGravityTop)
        _UI.add_card(outer, output)
        outer.addView_inGravity_(_UI.spacer_v(), NSStackViewGravityTop)

        w = NSView.alloc().init()
        w.addSubview_(outer)
        _UI.pin_edges(outer, w)
        return w

    # ── Selector actions ────────────────────────────────────────────
    def switchToTab_(self, index) -> None:
        self._tab.selectTabViewItemAtIndex_(int(index))

    def openPreferences_(self, sender) -> None:
        if self._sidebar_tv is not None:
            self._sidebar_tv.selectRowIndexes_byExtendingSelection_(
                NSIndexSet.indexSetWithIndex_(0), False
            )
        self._tab.selectTabViewItemAtIndex_(0)
        self._window.makeKeyAndOrderFront_(None)

    def showAbout_(self, sender) -> None:
        a = NSAlert.alloc().init()
        a.setMessageText_("PokeMacro")
        a.setInformativeText_("Pokémon automation helper for macOS.")
        a.runModal()

    def saveConfig_(self, sender) -> None:
        self._config = self._gather()
        self._config_manager.save(self._config)
        self._set_status("Saved", _Colors.RUN, _Colors.RUN)
        if self._status_reset_timer is not None:
            self._status_reset_timer.invalidate()
        me = self

        def _reset(t: NSTimer) -> None:
            if me._is_running:
                me._set_status("Running", _Colors.RUN, _Colors.RUN)
            else:
                me._set_status("Idle", _Colors.MUTED, _Colors.IDLE)

        self._status_reset_timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            2.0, False, _reset
        )

    def toggleRun_(self, sender) -> None:
        if not self._is_running:
            self._start_run()
        else:
            self._stop_run()

    def toggleToken_(self, sender) -> None:
        self._token_shown = not self._token_shown
        if self._token_shown:
            self._ptok.setStringValue_(str(self._stok.stringValue() or ""))
            self._stok.setHidden_(True)
            self._ptok.setHidden_(False)
            self._tokbtn.setTitle_("Hide")
        else:
            self._stok.setStringValue_(str(self._ptok.stringValue() or ""))
            self._ptok.setHidden_(True)
            self._stok.setHidden_(False)
            self._tokbtn.setTitle_("Show")

    def copyLogs_(self, sender) -> None:
        ts = self._log.textStorage()
        t = (ts.string() or "") if ts else ""
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(t, NSStringPboardType)

    def clearLogs_(self, sender) -> None:
        ts = self._log.textStorage()
        if ts is not None and ts.length():
            ts.deleteCharactersInRange_((0, int(ts.length())))

    # ── Run lifecycle ──────────────────────────────────────────────
    @objc.python_method
    def _start_run(self) -> None:
        self._config = self._gather()
        self._config_manager.save(self._config)
        self._is_running = True
        if self._run_item is not None:
            img = _UI.sf("stop.fill", "Stop", size=16.0)
            self._run_item.setImage_(img)
            self._run_item.setLabel_("Stop")
        self._set_status("Running", _Colors.RUN, _Colors.RUN)
        self._set_en(False)
        self._subprocess_mgr.start(self._log_queue, self._on_exit)

    @objc.python_method
    def _on_exit(self, code: int) -> None:
        self._is_running = False
        self._set_en(True)
        if self._run_item is not None:
            img = _UI.sf("play.fill", "Start", size=16.0)
            self._run_item.setImage_(img)
            self._run_item.setLabel_("Start")
            self._run_item.setEnabled_(True)
        self._set_status(
            "Idle" if int(code) == 0 else f"Stopped (exit {int(code)})",
            _Colors.MUTED, _Colors.IDLE,
        )

    @objc.python_method
    def _stop_run(self) -> None:
        if self._run_item is not None:
            self._run_item.setEnabled_(False)
        self._set_status("Stopping…", _Colors.STOP, _Colors.STOP)
        self._subprocess_mgr.stop()

    @objc.python_method
    def _set_en(self, on: bool) -> None:
        for ctrl in self._all_config_controls:
            if isinstance(ctrl, NSTextView):
                ctrl.setEditable_(on)
            else:
                ctrl.setEnabled_(on)

    # ── Status helper ──────────────────────────────────────────────
    @objc.python_method
    def _set_status(self, text: str, color: NSColor, dot: NSColor) -> None:
        if self._status_label is not None:
            self._status_label.setStringValue_(text)
            self._status_label.setTextColor_(color)
        if self._status_iv is not None:
            self._status_iv.setContentTintColor_(dot)

    # ── Config gather / load ───────────────────────────────────────
    @objc.python_method
    def _read_wish(self, tv: NSTextView) -> list[str]:
        ts = tv.textStorage()
        raw = str((ts.string() or "") if ts is not None else "").strip()
        out: list[str] = []
        for line in raw.splitlines():
            for part in line.split(","):
                p = part.strip()
                if p:
                    out.append(p)
        return out

    @objc.python_method
    def _xy(self, pair: tuple[NSTextField, NSTextField]) -> list[int]:
        return [_int_val(pair[0]), _int_val(pair[1])]

    @objc.python_method
    def _gather(self) -> dict:
        return {
            "HuntingMode": str(self._hunt.titleOfSelectedItem() or "egg"),
            "Username":    str(self._user.stringValue() or ""),
            "Mode":        str(self._fast.titleOfSelectedItem() or "Default"),
            "Wishlist":    {n: self._read_wish(t) for n, t in self._wish.items()},
            "Positions":   {k: self._xy(t) for k, t in self._pos.items()},
            "ChatWindow":          {c: self._xy(p) for c, p in self._regions["ChatWindow"].items()},
            "EncounterNameRegion": {c: self._xy(p) for c, p in self._regions["EncounterNameRegion"].items()},
            "SpriteRegion":        {c: self._xy(p) for c, p in self._regions["SpriteRegion"].items()},
            "IsReskin":   self._bools["IsReskin"].state()   == int(NSOnState),
            "IsShiny":    self._bools["IsShiny"].state()    == int(NSOnState),
            "IsGradient": self._bools["IsGradient"].state() == int(NSOnState),
            "IsAny":      self._bools["IsAny"].state()      == int(NSOnState),
            "IsGood":     self._bools["IsGood"].state()     == int(NSOnState),
            "DiscordBotToken": (
                str(self._ptok.stringValue() or "") if self._token_shown
                else str(self._stok.stringValue() or "")
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
            tv._apply()
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
        self._log._apply()

    # ── Log polling ────────────────────────────────────────────────
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
        ts.replaceCharactersInRange_withString_((L, 0), str(s) + "\n")
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
        vr  = v.contentView().bounds()
        h   = doc.bounds().size.height
        if h <= vr.size.height + 2.0:
            return True
        y = v.contentView().bounds().origin.y
        return y + vr.size.height >= h - 4.0

    # ── Quit guard ─────────────────────────────────────────────────
    @objc.python_method
    def _should_stop(self) -> bool:
        a = NSAlert.alloc().init()
        a.setMessageText_("Quit")
        a.setInformativeText_("Macro is running. Stop it and quit?")
        a.addButtonWithTitle_("Quit")
        a.addButtonWithTitle_("Cancel")
        return int(a.runModal()) == int(NSAlertFirstButtonReturn)

    def applicationShouldTerminate_(self, app) -> int:
        if not self._is_running:
            return int(NSTerminateNow)
        if self._should_stop():
            self._subprocess_mgr.stop()
            return int(NSTerminateNow)
        return int(NSTerminateCancel)

    def windowShouldClose_(self, sender) -> bool:
        if not self._is_running:
            return True
        if self._should_stop():
            self._subprocess_mgr.stop()
            return True
        return False

    # ── Menu bar ───────────────────────────────────────────────────
    @objc.python_method
    def _mi(self, title: str, action: bytes, key: str, mod: int = 0) -> NSMenuItem:
        m = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        if mod:
            m.setKeyEquivalentModifierMask_(mod)
        m.setTarget_(self)
        return m

    @objc.python_method
    def _menu(self) -> None:
        app = NSApplication.sharedApplication()
        bar = NSMenu.alloc().init()
        app_item = NSMenuItem.alloc().init()
        sm = NSMenu.alloc().init()
        sm.addItem_(self._mi("About PokeMacro",  b"showAbout:",      ""))
        sm.addItem_(NSMenuItem.separatorItem())
        sm.addItem_(self._mi("Preferences…",     b"openPreferences:", ",", NSCommandKeyMask))
        sm.addItem_(NSMenuItem.separatorItem())
        sm.addItem_(self._mi("Hide PokeMacro",   b"hide:",           "h", NSCommandKeyMask))
        sm.addItem_(NSMenuItem.separatorItem())
        sm.addItem_(self._mi("Save",             b"saveConfig:",     "s", NSCommandKeyMask))
        sm.addItem_(self._mi("Start / Stop",     b"toggleRun:",      "r", NSCommandKeyMask))
        sm.addItem_(NSMenuItem.separatorItem())
        sm.addItem_(self._mi("Quit PokeMacro",   b"terminate:",      "q", NSCommandKeyMask))
        app_item.setSubmenu_(sm)
        app_item.setTitle_("PokeMacro")
        bar.addItem_(app_item)
        app.setMainMenu_(bar)

    # ── Entry point ────────────────────────────────────────────────
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


def main() -> None:
    c = PokeMacroController.alloc().init()
    if c is None:
        return
    c.run()


if __name__ == "__main__":
    main()
