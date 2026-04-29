"""
PokeMacro — native AppKit (PyObjC) UI
"""
from __future__ import annotations

import os
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
    NSBezierPath,
    NSBezelStyleRounded,
    NSButton, NSButtonTypeMomentaryPushIn, NSButtonTypeSwitch,
    NSCenterTextAlignment, NSRightTextAlignment,
    NSColor, NSCommandKeyMask, NSShiftKeyMask,
    NSEdgeInsets, NSFont,
    NSFocusRingTypeNone,
    NSFontAttributeName, NSForegroundColorAttributeName,
    NSImage, NSImageSymbolConfiguration, NSImageView,
    NSLayoutAttributeCenterX, NSLayoutAttributeCenterY, NSLayoutAttributeLeading,
    NSLayoutPriorityDefaultHigh,
    NSLayoutPriorityDefaultLow,
    NSLineBreakByTruncatingMiddle,
    NSLineBreakByTruncatingTail,
    NSMenu, NSMenuItem,
    NSNoTabsNoBorder, NSOffState, NSOnState,
    NSFilenamesPboardType,
    NSOpenPanel,
    NSPasteboard, NSStringPboardType,
    NSSavePanel,
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
    NSEvent,
    NSScreen,
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

from src import __version__ as APP_VERSION
from src.git_update import start_background_update
from src.macro_config import get_config_path

# ── Project paths ──────────────────────────────────────────────────────
# Same path the macro subprocess uses (important when frozen / bundled).
CONFIG_PATH = get_config_path()
PROJECT_ROOT = CONFIG_PATH.parent
_venv = PROJECT_ROOT / "ENV" / "bin" / "python"
VENV_PYTHON = _venv if _venv.exists() else Path(sys.executable)

# ── Layout constants ───────────────────────────────────────────────────
SIDEBAR_W  = 200.0
UI_PAD     = 20.0
LABEL_W    = 155.0
FIELD_W    = 80.0
PICK_BTN_W = 26.0
# Inner padding for _CardView contents — keep in sync with _UI.box.
_CARD_INNER_PAD_H = 12.0
_CARD_INNER_PAD_V = 10.0

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
    ("Dex",       "list.number"),
    ("Logs",      "doc.text"),
    ("Debug",     "ladybug"),
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


class _ClickThroughView(NSView):
    @objc.python_method
    def set_click_through(self, enabled: bool) -> None:
        self._click_through = bool(enabled)

    def hitTest_(self, point):
        if getattr(self, '_click_through', False):
            return None
        return objc.super(_ClickThroughView, self).hitTest_(point)


# ── Spinning ring view (update animation) ─────────────────────────────
class _SpinRingView(NSView):
    @objc.python_method
    def _setup(self) -> None:
        self._angle: float = 90.0
        self._spin_timer = None

    def drawRect_(self, rect) -> None:
        import warnings
        b = self.bounds()
        cx = b.size.width / 2.0
        cy = b.size.height / 2.0
        lw = 5.0
        r = min(cx, cy) - lw - 1.0

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            NSColor.colorWithWhite_alpha_(1.0, 0.18).set()
        track = NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(cx - r, cy - r, r * 2, r * 2)
        )
        track.setLineWidth_(lw)
        track.stroke()

        arc = NSBezierPath.bezierPath()
        arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
            (cx, cy), r, self._angle, self._angle - 240.0, True
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            NSColor.colorWithWhite_alpha_(1.0, 0.92).set()
        arc.setLineWidth_(lw)
        arc.setLineCapStyle_(1)  # NSRoundLineCapStyle
        arc.stroke()

    @objc.python_method
    def start_spin(self) -> None:
        if self._spin_timer is not None:
            return

        def _tick(_t: NSTimer) -> None:
            self._angle = (self._angle + 6.0) % 360.0
            self.setNeedsDisplay_(True)

        self._spin_timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            1.0 / 60.0, True, _tick
        )

    @objc.python_method
    def stop_spin(self) -> None:
        if self._spin_timer is not None:
            self._spin_timer.invalidate()
            self._spin_timer = None


# ── Update overlay (dims window and shows the ring while updating) ─────
class _UpdateOverlayView(NSView):
    @objc.python_method
    def _setup(self) -> None:
        self.setWantsLayer_(True)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bg = NSColor.colorWithRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.55).CGColor()
        layer = self.layer()
        if layer and bg:
            layer.setBackgroundColor_(bg)

        ring_size = 72.0
        self._ring: _SpinRingView = _SpinRingView.alloc().init()
        self._ring._setup()
        self._ring.setTranslatesAutoresizingMaskIntoConstraints_(False)

        lbl = _UI.label("Updating…", size=14.0, color=NSColor.whiteColor())
        lbl.setTranslatesAutoresizingMaskIntoConstraints_(False)
        lbl.setAlignment_(NSCenterTextAlignment)

        stack = NSStackView.stackViewWithViews_([])
        stack.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        stack.setSpacing_(14.0)
        stack.setAlignment_(NSLayoutAttributeCenterX)
        stack.setTranslatesAutoresizingMaskIntoConstraints_(False)
        stack.addView_inGravity_(self._ring, NSStackViewGravityTop)
        stack.addView_inGravity_(lbl, NSStackViewGravityTop)

        self.addSubview_(stack)
        self._ring.widthAnchor().constraintEqualToConstant_(ring_size).setActive_(True)
        self._ring.heightAnchor().constraintEqualToConstant_(ring_size).setActive_(True)
        stack.centerXAnchor().constraintEqualToAnchor_(self.centerXAnchor()).setActive_(True)
        stack.centerYAnchor().constraintEqualToAnchor_(self.centerYAnchor()).setActive_(True)

    @objc.python_method
    def start(self) -> None:
        self._ring.start_spin()

    @objc.python_method
    def stop(self) -> None:
        self._ring.stop_spin()


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
        sc.setDrawsBackground_(False)
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
        H, V = _CARD_INNER_PAD_H, _CARD_INNER_PAD_V
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
            "HuntingMode": "Egg Resetter",
            "Username": "",
            "Mode": "URL Open",
            "IsReskin": False, "IsShiny": False, "IsGradient": False,
            "IsAny": True, "IsGood": False,
            "Wishlist": {"Reskins": [], "Gradients": [], "Roamings": [], "Special": []},
            "Positions": {k: [0, 0] for k, _ in POSITION_KEYS},
            "ChatWindow":          {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
            "EncounterNameRegion": {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
            "SpriteRegion":        {"LeftCorner": [0, 0], "RightCorner": [0, 0]},
            "DiscordBotToken": "",
            "ServerID": 0,
            "DexScanner": {
                "Rows": 23,
                "Cols": 33,
                "SampleOffset": [10, 10],
                "OutputFile": "missing-poopimons.txt",
            },
        }


class SubprocessManager:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._log_thread: threading.Thread | None = None

    def start(self, log_queue: queue.Queue, on_exit: Callable[[int], None]) -> None:
        self._proc = subprocess.Popen(
            [str(VENV_PYTHON), "-u", "-m", "src.main"],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
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

    def stop_blocking(self, timeout: float = 20.0) -> None:
        """Wait for the macro subprocess to exit (used before process replace on update)."""
        if not self._proc or self._proc.poll() is not None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            try:
                self._proc.wait(timeout=5)
            except OSError:
                pass

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
        self.setTextColor_(NSColor.secondaryLabelColor())


class _AdaptiveWishTextView(NSTextView):
    def viewDidChangeEffectiveAppearance(self) -> None:
        objc.super(_AdaptiveWishTextView, self).viewDidChangeEffectiveAppearance()
        self._apply()

    @objc.python_method
    def _apply(self) -> None:
        self.setDrawsBackground_(True)
        self.setBackgroundColor_(NSColor.textBackgroundColor())
        self.setTextColor_(NSColor.textColor())


# ── Drag-and-drop zone ────────────────────────────────────────────────
class _DropZoneView(NSView):
    """Spacious, friendly drop target for image files.
    Exposes stringValue / setStringValue_ so existing callers need no changes."""

    @objc.python_method
    def _setup(self, title: str, default_path: str) -> None:
        self._path = default_path
        self._dragging = False

        self.setWantsLayer_(True)
        self.registerForDraggedTypes_([NSFilenamesPboardType])
        self._refresh_layer()

        # Hero icon (drop affordance)
        self._iv = NSImageView.alloc().init()
        self._iv.setTranslatesAutoresizingMaskIntoConstraints_(False)
        img = _UI.sf("arrow.down.circle.fill", "drop image here", size=32.0, weight=-0.25)
        if img is None:
            img = _UI.sf("photo.on.rectangle.angled", "drop image here", size=32.0)
        if img is None:
            img = _UI.sf("photo.on.rectangle", "drop image here", size=32.0)
        if img is not None:
            self._iv.setImage_(img)
        self._sync_icon_tint()
        ICON = 48.0
        self._iv.widthAnchor().constraintEqualToConstant_(ICON).setActive_(True)
        self._iv.heightAnchor().constraintEqualToConstant_(ICON).setActive_(True)

        # Title
        title_lbl = _UI.label(title, size=14.5, bold=True)
        title_lbl.setAlignment_(NSCenterTextAlignment)
        title_lbl.setTranslatesAutoresizingMaskIntoConstraints_(False)

        # Hint — short enough for two columns; truncates if the pane is very narrow
        hint_lbl = _UI.label(
            "Drop a screenshot, or tap Choose.",
            size=11.25,
            color=NSColor.secondaryLabelColor(),
        )
        hint_lbl.setAlignment_(NSCenterTextAlignment)
        hint_lbl.setTranslatesAutoresizingMaskIntoConstraints_(False)

        # Current filename (muted monospaced)
        self._path_lbl = NSTextField.labelWithString_(Path(self._path).name)
        self._path_lbl.setFont_(_UI.mono_font(10.0))
        self._path_lbl.setTextColor_(NSColor.tertiaryLabelColor())
        self._path_lbl.setLineBreakMode_(NSLineBreakByTruncatingMiddle)
        self._path_lbl.setAlignment_(NSCenterTextAlignment)
        self._path_lbl.setTranslatesAutoresizingMaskIntoConstraints_(False)

        # Browse — caller must set target/action via self.browse_button
        self._browse_btn = NSButton.alloc().init()
        self._browse_btn.setButtonType_(NSButtonTypeMomentaryPushIn)
        self._browse_btn.setBezelStyle_(NSBezelStyleRounded)
        self._browse_btn.setTitle_("Choose file…")
        self._browse_btn.setFont_(NSFont.systemFontOfSize_(11.5))
        self._browse_btn.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self.browse_button = self._browse_btn

        vstack = NSStackView.stackViewWithViews_([])
        vstack.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        vstack.setSpacing_(9.0)
        vstack.setAlignment_(NSLayoutAttributeCenterX)
        vstack.setTranslatesAutoresizingMaskIntoConstraints_(False)
        vstack.addView_inGravity_(self._iv, NSStackViewGravityTop)
        vstack.addView_inGravity_(title_lbl, NSStackViewGravityTop)
        vstack.addView_inGravity_(hint_lbl, NSStackViewGravityTop)
        vstack.addView_inGravity_(self._path_lbl, NSStackViewGravityTop)
        vstack.addView_inGravity_(self._browse_btn, NSStackViewGravityTop)

        self.addSubview_(vstack)
        # Inset inside the drop well; card already uses _CARD_INNER_PAD_H from ss_card.
        EDGE_H = 10.0
        vstack.leadingAnchor().constraintEqualToAnchor_constant_(
            self.leadingAnchor(), EDGE_H
        ).setActive_(True)
        vstack.trailingAnchor().constraintEqualToAnchor_constant_(
            self.trailingAnchor(), -EDGE_H
        ).setActive_(True)
        vstack.centerYAnchor().constraintEqualToAnchor_(self.centerYAnchor()).setActive_(True)

        self._path_lbl.widthAnchor().constraintEqualToAnchor_(vstack.widthAnchor()).setActive_(True)

        _prio = NSLayoutPriorityDefaultLow
        _ori = NSUserInterfaceLayoutOrientationHorizontal
        for v in (title_lbl, hint_lbl, self._path_lbl, self._browse_btn, self._iv, vstack):
            v.setContentCompressionResistancePriority_forOrientation_(_prio, _ori)
        self.setContentCompressionResistancePriority_forOrientation_(_prio, _ori)

    @objc.python_method
    def _sync_icon_tint(self) -> None:
        if not hasattr(self, "_iv") or self._iv is None:
            return
        if getattr(self, "_dragging", False):
            self._iv.setContentTintColor_(NSColor.controlAccentColor())
        else:
            self._iv.setContentTintColor_(NSColor.secondaryLabelColor())

    @objc.python_method
    def _refresh_layer(self) -> None:
        lyr = self.layer()
        if lyr is None:
            return
        dragging = getattr(self, '_dragging', False)
        self._sync_icon_tint()
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if dragging:
                bg = NSColor.controlAccentColor().colorWithAlphaComponent_(0.14).CGColor()
                bd = NSColor.controlAccentColor().CGColor()
            else:
                bg = NSColor.quaternarySystemFillColor().CGColor()
                if bg is None:
                    bg = NSColor.labelColor().colorWithAlphaComponent_(0.05).CGColor()
                bd = NSColor.separatorColor().colorWithAlphaComponent_(0.85).CGColor()
        lyr.setCornerRadius_(14.0)
        lyr.setBorderWidth_(1.0 if not dragging else 2.0)
        if bg:
            lyr.setBackgroundColor_(bg)
        if bd:
            lyr.setBorderColor_(bd)

    def viewDidChangeEffectiveAppearance(self) -> None:
        objc.super(_DropZoneView, self).viewDidChangeEffectiveAppearance()
        self._refresh_layer()

    # ── NSTextField-compatible interface ───────────────────────────────
    def stringValue(self):
        return getattr(self, '_path', '')

    def setStringValue_(self, path):
        self._path = str(path) if path else ''
        if hasattr(self, '_path_lbl') and self._path_lbl is not None:
            self._path_lbl.setStringValue_(Path(self._path).name)

    # ── Drag protocol ──────────────────────────────────────────────────
    def draggingEntered_(self, sender):
        self._dragging = True
        self._refresh_layer()
        return 1  # NSDragOperationCopy

    def draggingUpdated_(self, sender):
        return 1

    def draggingExited_(self, sender):
        self._dragging = False
        self._refresh_layer()

    def prepareForDragOperation_(self, sender):
        return True

    def performDragOperation_(self, sender):
        files = sender.draggingPasteboard().propertyListForType_(NSFilenamesPboardType)
        self._dragging = False
        self._refresh_layer()
        if files:
            self.setStringValue_(str(files[0]))
            return True
        return False


# ── Sidebar table data source / delegate ───────────────────────────────
class SidebarSource(NSObject):
    def initWithController_(self, controller):
        self = objc.super(SidebarSource, self).init()
        if self is None:
            return None
        self._ctrl = controller
        return self

    @objc.python_method
    def attach(self, table: NSTableView) -> None:
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
        self._pick_map: dict   = {}
        self._pick_monitor     = None
        self._pick_timer       = None
        self._pick_fields      = None
        self._pick_btn         = None
        self._debug_timer      = None
        self._debug_iv         = None
        self._debug_ocr        = None
        self._debug_ss_mtime   = 0.0
        self._debug_ocr_mtime  = 0.0
        self._dex_p1_field     = None
        self._dex_p2_field     = None
        self._dex_tv           = None
        self._update_overlay: _UpdateOverlayView | None = None

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
            ("Dex",       self._tab_dex),
            ("Logs",      self._tab_logs),
            ("Debug",     self._tab_debug),
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
        self._window.setTitle_("Stingray - PokeMacro")
        self._window.setTitleVisibility_(NSWindowTitleHidden)
        self._window.setTitlebarAppearsTransparent_(True)
        self._window.setMinSize_(NSMakeSize(628, 500))
        self._window.setDelegate_(self)
        self._window.setReleasedWhenClosed_(False)
        self._window.setLevel_(3)  # NSFloatingWindowLevel — always on top
        self._build_toolbar()
        self._window.setToolbar_(self._toolbar)
        split = self._build_split_view()
        self._ct_view = _ClickThroughView.alloc().init()
        self._ct_view.addSubview_(split)
        _UI.pin_edges(split, self._ct_view)

        ver_lbl = _UI.label(f"v{APP_VERSION}", size=10.0, color=NSColor.whiteColor())
        ver_lbl.setFont_(NSFont.systemFontOfSize_weight_(10.0, -0.2))
        ver_lbl.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self._ct_view.addSubview_(ver_lbl)
        ver_lbl.leadingAnchor().constraintEqualToAnchor_constant_(
            self._ct_view.leadingAnchor(), 10.0
        ).setActive_(True)
        ver_lbl.bottomAnchor().constraintEqualToAnchor_constant_(
            self._ct_view.bottomAnchor(), -8.0
        ).setActive_(True)

        self._window.setContentView_(self._ct_view)
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
        self._user = _UI.field()
        self._all_config_controls.append(self._user)
        hunt.addView_inGravity_(self._form_row("Username", self._user), NSStackViewGravityTop)

        self._hunt = _UI.popup(["Egg Resetter", "Roaming Hunter"])
        self._all_config_controls.append(self._hunt)
        hunt.addView_inGravity_(self._form_row("Hunting mode", self._hunt), NSStackViewGravityTop)


        self._fast = _UI.popup(["URL Open", "Quick rejoin"])
        self._all_config_controls.append(self._fast)
        hunt.addView_inGravity_(self._form_row("Rejoin method", self._fast), NSStackViewGravityTop)
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
            ("IsGood",     "Good"),
            ("IsAny",      "Reskin Gradient"),
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
    ) -> tuple[NSStackView, dict[str, tuple[NSTextField, NSTextField]]]:
        outer = _UI.v_stack(spacing=6.0)
        result: dict[str, tuple[NSTextField, NSTextField]] = {}
        for key, label_text in rows:
            la = _UI.label(label_text)
            la.setTranslatesAutoresizingMaskIntoConstraints_(False)
            la.widthAnchor().constraintEqualToConstant_(LABEL_W).setActive_(True)
            la.setContentHuggingPriority_forOrientation_(
                NSLayoutPriorityDefaultHigh, NSUserInterfaceLayoutOrientationHorizontal
            )

            xb = _UI.label("X", size=11.0, color=NSColor.secondaryLabelColor())
            yb = _UI.label("Y", size=11.0, color=NSColor.secondaryLabelColor())
            xf = _UI.field(width=FIELD_W)
            xf.setAlignment_(NSRightTextAlignment)
            xf.setStringValue_("0")
            yf = _UI.field(width=FIELD_W)
            yf.setAlignment_(NSRightTextAlignment)
            yf.setStringValue_("0")
            pb = _UI.button("", self, b'pickCoord:')
            scope_img = _UI.sf("scope", "Pick coordinate", size=13.0)
            if scope_img:
                pb.setImage_(scope_img)
            pb.setTranslatesAutoresizingMaskIntoConstraints_(False)
            pb.widthAnchor().constraintEqualToConstant_(PICK_BTN_W).setActive_(True)
            self._pick_map[id(pb)] = (xf, yf)
            result[key] = (xf, yf)

            coords = _UI.h_stack(spacing=4.0)
            coords.addView_inGravity_(xb, NSStackViewGravityTop)
            coords.addView_inGravity_(xf, NSStackViewGravityTop)
            coords.addView_inGravity_(yb, NSStackViewGravityTop)
            coords.addView_inGravity_(yf, NSStackViewGravityTop)
            coords.addView_inGravity_(pb, NSStackViewGravityTop)
            coords.setContentHuggingPriority_forOrientation_(
                NSLayoutPriorityDefaultHigh, NSUserInterfaceLayoutOrientationHorizontal
            )

            spacer = _UI.spacer_h()
            row = _UI.h_stack(spacing=12.0)
            row.addView_inGravity_(la, NSStackViewGravityTop)
            row.addView_inGravity_(spacer, NSStackViewGravityTop)
            row.addView_inGravity_(coords, NSStackViewGravityTop)
            row.setDistribution_(NSStackViewDistributionFill)

            outer.addView_inGravity_(row, NSStackViewGravityTop)

        return outer, result

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

    # ── Dex tab ────────────────────────────────────────────────────
    @objc.python_method
    def _tab_dex(self) -> NSView:
        CH, CV = _CARD_INNER_PAD_H, _CARD_INNER_PAD_V
        GAP  = 11.0
        DROP_H = 168.0
        # Keeps the output panel readable; still grows with the window above this.
        DEX_OUTPUT_MIN_H = 188.0

        # ── Two spacious drop zones ───────────────────────────────
        self._dex_p1_field = _DropZoneView.alloc().initWithFrame_(NSMakeRect(0, 0, 200, DROP_H))
        self._dex_p1_field._setup("Page 1", str(PROJECT_ROOT / "dex_screenshot.png"))
        self._dex_p1_field.browse_button.setTarget_(self)
        self._dex_p1_field.browse_button.setAction_(b"dexBrowsePage1:")
        self._dex_p1_field.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self._dex_p1_field.heightAnchor().constraintEqualToConstant_(DROP_H).setActive_(True)

        self._dex_p2_field = _DropZoneView.alloc().initWithFrame_(NSMakeRect(0, 0, 200, DROP_H))
        self._dex_p2_field._setup("Page 2", str(PROJECT_ROOT / "dex_screenshot2.png"))
        self._dex_p2_field.browse_button.setTarget_(self)
        self._dex_p2_field.browse_button.setAction_(b"dexBrowsePage2:")
        self._dex_p2_field.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self._dex_p2_field.heightAnchor().constraintEqualToConstant_(DROP_H).setActive_(True)

        # ── Screenshots card (manual layout for full-width zones) ─
        hdr_title = _UI.label("Dex screenshots", size=13.0, bold=True)
        hdr_title.setTranslatesAutoresizingMaskIntoConstraints_(False)
        hdr_sub = _UI.label(
            "Add both pages, then run Scan.",
            size=11.0,
            color=NSColor.secondaryLabelColor(),
        )
        hdr_sub.setTranslatesAutoresizingMaskIntoConstraints_(False)
        ss_hdr = NSStackView.stackViewWithViews_([hdr_title, hdr_sub])
        ss_hdr.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        ss_hdr.setSpacing_(4.0)
        ss_hdr.setAlignment_(NSLayoutAttributeLeading)
        ss_hdr.setTranslatesAutoresizingMaskIntoConstraints_(False)

        scan_btn = _UI.button("Scan", self, b"dexRunScan:")
        scan_btn.setTranslatesAutoresizingMaskIntoConstraints_(False)

        _prio = NSLayoutPriorityDefaultLow
        _horiz = NSUserInterfaceLayoutOrientationHorizontal
        for v in (hdr_title, hdr_sub, ss_hdr, scan_btn):
            v.setContentCompressionResistancePriority_forOrientation_(_prio, _horiz)

        ss_card = _CardView.alloc().init()
        ss_card.setWantsLayer_(True)
        ss_card.setTranslatesAutoresizingMaskIntoConstraints_(False)
        ss_card._refresh()
        if ss_card.layer() is not None:
            ss_card.layer().setCornerRadius_(8.0)
            ss_card.layer().setBorderWidth_(1.0)

        for sub in (ss_hdr, self._dex_p1_field, self._dex_p2_field):
            ss_card.addSubview_(sub)
        ss_card.addSubview_(scan_btn)

        # Header row: titles left, Scan right
        ss_hdr.topAnchor().constraintEqualToAnchor_constant_(
            ss_card.topAnchor(), CV).setActive_(True)
        ss_hdr.leadingAnchor().constraintEqualToAnchor_constant_(
            ss_card.leadingAnchor(), CH).setActive_(True)
        scan_btn.trailingAnchor().constraintEqualToAnchor_constant_(
            ss_card.trailingAnchor(), -CH).setActive_(True)
        scan_btn.centerYAnchor().constraintEqualToAnchor_(
            ss_hdr.centerYAnchor()).setActive_(True)
        ss_hdr.trailingAnchor().constraintLessThanOrEqualToAnchor_constant_(
            scan_btn.leadingAnchor(), -GAP).setActive_(True)

        # Drop zones side-by-side below header, equal width
        self._dex_p1_field.topAnchor().constraintEqualToAnchor_constant_(
            ss_hdr.bottomAnchor(), GAP).setActive_(True)
        self._dex_p1_field.leadingAnchor().constraintEqualToAnchor_constant_(
            ss_card.leadingAnchor(), CH).setActive_(True)

        self._dex_p2_field.topAnchor().constraintEqualToAnchor_(
            self._dex_p1_field.topAnchor()).setActive_(True)
        self._dex_p2_field.leadingAnchor().constraintEqualToAnchor_constant_(
            self._dex_p1_field.trailingAnchor(), GAP).setActive_(True)
        self._dex_p2_field.trailingAnchor().constraintEqualToAnchor_constant_(
            ss_card.trailingAnchor(), -CH).setActive_(True)
        self._dex_p1_field.widthAnchor().constraintEqualToAnchor_(
            self._dex_p2_field.widthAnchor()).setActive_(True)

        self._dex_p1_field.bottomAnchor().constraintEqualToAnchor_constant_(
            ss_card.bottomAnchor(), -CV).setActive_(True)

        # ── Output card ───────────────────────────────────────────
        out_hdr = _UI.h_stack(spacing=6.0)
        out_hdr.addView_inGravity_(
            _UI.label("Output", size=11.0, color=NSColor.secondaryLabelColor()),
            NSStackViewGravityTop,
        )
        out_hdr.addView_inGravity_(_UI.spacer_h(), NSStackViewGravityTop)
        out_hdr.addView_inGravity_(_UI.button("Export", self, b"dexExport:"),      NSStackViewGravityTop)
        out_hdr.addView_inGravity_(_UI.button("Copy",   self, b"dexCopyOutput:"),  NSStackViewGravityTop)
        out_hdr.addView_inGravity_(_UI.button("Clear",  self, b"dexClearOutput:"), NSStackViewGravityTop)
        out_hdr.setTranslatesAutoresizingMaskIntoConstraints_(False)

        self._dex_tv = _AdaptiveLogTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, 320, DEX_OUTPUT_MIN_H)
        )
        self._dex_tv.setEditable_(False)
        self._dex_tv.setSelectable_(True)
        self._dex_tv.setFont_(_UI.mono_font(11.0))
        self._dex_tv.setTextContainerInset_((6, 6))
        self._dex_tv.setMinSize_(NSMakeSize(0.0, 0.0))
        self._dex_tv.setMaxSize_(NSMakeSize(1e7, 1e7))
        self._dex_tv.setVerticallyResizable_(True)
        self._dex_tv.setHorizontallyResizable_(False)
        # NSViewWidthSizable (2): track clip view width (same pattern as Wishlist tab).
        self._dex_tv.setAutoresizingMask_(2)
        self._dex_tv.textContainer().setWidthTracksTextView_(True)
        self._dex_tv._apply()

        dex_sc = NSScrollView.alloc().init()
        dex_sc.setDocumentView_(self._dex_tv)
        dex_sc.setHasVerticalScroller_(True)
        dex_sc.setAutohidesScrollers_(True)
        dex_sc.setBorderType_(0)
        dex_sc.setDrawsBackground_(True)
        dex_sc.setWantsLayer_(True)
        dex_sc.layer().setCornerRadius_(6.0)
        dex_sc.layer().setMasksToBounds_(True)
        dex_sc.layer().setBorderWidth_(1.0)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            dex_sc.layer().setBorderColor_(NSColor.separatorColor().CGColor())
        dex_sc.setTranslatesAutoresizingMaskIntoConstraints_(False)
        dex_sc.heightAnchor().constraintGreaterThanOrEqualToConstant_(DEX_OUTPUT_MIN_H).setActive_(True)
        dex_sc.setContentHuggingPriority_forOrientation_(
            NSLayoutPriorityDefaultLow,
            NSUserInterfaceLayoutOrientationVertical,
        )

        out_card = _CardView.alloc().init()
        out_card.setWantsLayer_(True)
        out_card.setTranslatesAutoresizingMaskIntoConstraints_(False)
        out_card._refresh()
        if out_card.layer() is not None:
            out_card.layer().setCornerRadius_(8.0)
            out_card.layer().setBorderWidth_(1.0)
        out_card.addSubview_(out_hdr)
        out_card.addSubview_(dex_sc)
        out_hdr.topAnchor().constraintEqualToAnchor_constant_(out_card.topAnchor(), CV).setActive_(True)
        out_hdr.leadingAnchor().constraintEqualToAnchor_constant_(out_card.leadingAnchor(), CH).setActive_(True)
        out_hdr.trailingAnchor().constraintEqualToAnchor_constant_(out_card.trailingAnchor(), -CH).setActive_(True)
        dex_sc.topAnchor().constraintEqualToAnchor_constant_(out_hdr.bottomAnchor(), 8.0).setActive_(True)
        dex_sc.leadingAnchor().constraintEqualToAnchor_constant_(out_card.leadingAnchor(), CH).setActive_(True)
        dex_sc.trailingAnchor().constraintEqualToAnchor_constant_(out_card.trailingAnchor(), -CH).setActive_(True)
        dex_sc.bottomAnchor().constraintEqualToAnchor_constant_(out_card.bottomAnchor(), -CV).setActive_(True)

        # Fill the tab vertically (no outer scroll); output text scrolls inside dex_sc only.
        # Root uses default TAMIC (YES) like _tab_logs / _tab_general so NSTabView can
        # set the item view's frame to fill the tab; explicit False caused undersized
        # item_bounds until the window was resized (see debug logs: item w < tab w).
        w = NSView.alloc().init()
        pad = UI_PAD
        w.addSubview_(ss_card)
        w.addSubview_(out_card)
        ss_card.topAnchor().constraintEqualToAnchor_constant_(w.topAnchor(), pad).setActive_(True)
        ss_card.leadingAnchor().constraintEqualToAnchor_constant_(w.leadingAnchor(), pad).setActive_(True)
        ss_card.trailingAnchor().constraintEqualToAnchor_constant_(w.trailingAnchor(), -pad).setActive_(True)

        out_card.topAnchor().constraintEqualToAnchor_constant_(ss_card.bottomAnchor(), 14.0).setActive_(True)
        out_card.leadingAnchor().constraintEqualToAnchor_constant_(w.leadingAnchor(), pad).setActive_(True)
        out_card.trailingAnchor().constraintEqualToAnchor_constant_(w.trailingAnchor(), -pad).setActive_(True)
        out_card.bottomAnchor().constraintEqualToAnchor_constant_(w.bottomAnchor(), -pad).setActive_(True)

        for v in (ss_card, out_card):
            v.setContentCompressionResistancePriority_forOrientation_(_prio, _horiz)
        ss_card.setContentHuggingPriority_forOrientation_(
            NSLayoutPriorityDefaultHigh,
            NSUserInterfaceLayoutOrientationVertical,
        )
        out_card.setContentHuggingPriority_forOrientation_(
            NSLayoutPriorityDefaultLow,
            NSUserInterfaceLayoutOrientationVertical,
        )

        self._dex_reload_output()
        return w

    @objc.python_method
    def _dex_sync_text_view(self) -> None:
        """Force layout/display after programmatic text storage edits (otherwise the view
        can stay stale until something triggers a relayout, e.g. resizing the window)."""
        tv = self._dex_tv
        if tv is None:
            return
        lm = tv.layoutManager()
        tc = tv.textContainer()
        if lm is not None and tc is not None:
            lm.ensureLayoutForTextContainer_(tc)
        tv.setNeedsDisplay_(True)
        sc = tv.enclosingScrollView()
        if sc is not None:
            sc.reflectScrolledClipView_(sc.contentView())
        tv.scrollToBeginningOfDocument_(None)

    @objc.python_method
    def _dex_set_output(self, text: str) -> None:
        tv = self._dex_tv
        if tv is None:
            return
        ts = tv.textStorage()
        if ts is None:
            return
        attr = NSMutableAttributedString.alloc().initWithString_attributes_(
            text,
            {
                NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
                NSFontAttributeName: _UI.mono_font(11.0),
            },
        )
        ts.beginEditing()
        try:
            ts.replaceCharactersInRange_withAttributedString_(
                (0, int(ts.length())),
                attr,
            )
        finally:
            ts.endEditing()
        self._dex_sync_text_view()

    @objc.python_method
    def _dex_output_file(self) -> str:
        return self._config.get("DexScanner", {}).get("OutputFile", "missing-poopimons.txt")

    @objc.python_method
    def _dex_reload_output(self) -> None:
        out_path = PROJECT_ROOT / self._dex_output_file()
        if out_path.exists():
            try:
                text = out_path.read_text(encoding="utf-8")
            except Exception:
                text = "(error reading output file)"
            self._dex_set_output(text)

    def dexBrowsePage1_(self, sender) -> None:
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(["png", "jpg", "jpeg"])
        if int(panel.runModal()) == 1 and panel.URL():
            self._dex_p1_field.setStringValue_(panel.URL().path())

    def dexBrowsePage2_(self, sender) -> None:
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(["png", "jpg", "jpeg"])
        if int(panel.runModal()) == 1 and panel.URL():
            self._dex_p2_field.setStringValue_(panel.URL().path())

    def dexRunScan_(self, sender) -> None:
        p1 = str(self._dex_p1_field.stringValue() or "")
        p2 = str(self._dex_p2_field.stringValue() or "")
        self._config = self._gather()
        out_file = self._dex_output_file()
        self._config_manager.save(self._config)
        self._dex_set_output("Scanning…\n")
        me = self

        def _run() -> None:
            try:
                proc = subprocess.Popen(
                    [str(VENV_PYTHON), "-m", "dex.main", p1, p2, str(CONFIG_PATH)],
                    cwd=str(PROJECT_ROOT),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                )
                lines: list[str] = []
                assert proc.stdout
                for line in proc.stdout:
                    stripped = line.rstrip("\n")
                    lines.append(stripped)
                    print(stripped, flush=True)
                proc.wait()
                code = int(proc.returncode or 0)
                out_path = PROJECT_ROOT / out_file

                def _apply() -> None:
                    if code == 0 and out_path.exists():
                        try:
                            text = out_path.read_text(encoding="utf-8")
                        except Exception as e:
                            text = f"(error reading output: {e})"
                        me._dex_set_output(text)
                    else:
                        me._dex_set_output("\n".join(lines) or f"Scan failed (exit {code})")

                NSOperationQueue.mainQueue().addOperationWithBlock_(_apply)
            except Exception as exc:
                def _err() -> None:
                    me._dex_set_output(f"Error: {exc}")
                NSOperationQueue.mainQueue().addOperationWithBlock_(_err)

        threading.Thread(target=_run, daemon=True).start()

    def dexCopyOutput_(self, sender) -> None:
        if self._dex_tv is None:
            return
        ts = self._dex_tv.textStorage()
        t = (ts.string() or "") if ts else ""
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(t, NSStringPboardType)

    def dexClearOutput_(self, sender) -> None:
        if self._dex_tv is None:
            return
        ts = self._dex_tv.textStorage()
        if ts is not None and ts.length():
            ts.beginEditing()
            try:
                ts.deleteCharactersInRange_((0, int(ts.length())))
            finally:
                ts.endEditing()
            self._dex_sync_text_view()

    def dexExport_(self, sender) -> None:
        if self._dex_tv is None:
            return
        ts = self._dex_tv.textStorage()
        text = str((ts.string() or "") if ts else "")
        panel = NSSavePanel.savePanel()
        panel.setNameFieldStringValue_("missing.txt")
        panel.setAllowedFileTypes_(["txt"])
        if int(panel.runModal()) == 1 and panel.URL():
            try:
                Path(panel.URL().path()).write_text(text, encoding="utf-8")
            except Exception as exc:
                a = NSAlert.alloc().init()
                a.setMessageText_("Export failed")
                a.setInformativeText_(str(exc))
                a.runModal()

    # ── Coordinate pick ────────────────────────────────────────────
    def pickCoord_(self, sender) -> None:
        # Cancel any in-progress pick first
        if self._pick_timer is not None:
            self._pick_timer.invalidate()
            self._pick_timer = None
        if self._pick_monitor is not None:
            NSEvent.removeMonitor_(self._pick_monitor)
            self._pick_monitor = None
        if self._pick_btn is not None:
            self._pick_btn.setImage_(_UI.sf("scope", "Pick coordinate", size=13.0))
            self._pick_btn.setTitle_("")
            self._pick_btn.setEnabled_(True)
        self._pick_fields = None
        self._pick_btn = None

        fields = self._pick_map.get(id(sender))
        if fields is None:
            return

        self._pick_fields = fields
        self._pick_btn = sender
        sender.setImage_(_UI.sf("scope.fill", "Waiting", size=13.0) or sender.image())
        sender.setEnabled_(False)

        self._pick_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.05, self, b'_pickPollTick:', None, True
        )

        def _click_handler(event):
            NSOperationQueue.mainQueue().addOperationWithBlock_(
                lambda: self._applyPick()
            )

        self._pick_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            1 << 1,  # NSEventMaskLeftMouseDown
            _click_handler,
        )

    def _pickPollTick_(self, timer) -> None:
        if self._pick_fields is None:
            return
        pt = NSEvent.mouseLocation()
        h = NSScreen.mainScreen().frame().size.height
        self._pick_fields[0].setStringValue_(str(int(round(pt.x))))
        self._pick_fields[1].setStringValue_(str(int(round(h - pt.y))))

    @objc.python_method
    def _applyPick(self) -> None:
        self._pick_fields = None
        if self._pick_timer is not None:
            self._pick_timer.invalidate()
            self._pick_timer = None
        if self._pick_monitor is not None:
            NSEvent.removeMonitor_(self._pick_monitor)
            self._pick_monitor = None
        if self._pick_btn is not None:
            self._pick_btn.setImage_(_UI.sf("scope", "Pick coordinate", size=13.0))
            self._pick_btn.setTitle_("")
            self._pick_btn.setEnabled_(True)
            self._pick_btn = None

    # ── Logs tab ───────────────────────────────────────────────────
    @objc.python_method
    def _tab_logs(self) -> NSView:
        w   = NSView.alloc().init()
        pad = UI_PAD

        # ── Discord card ──────────────────────────────────────────
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
        tok_row.addView_inGravity_(tok_stack,    NSStackViewGravityTop)
        tok_row.addView_inGravity_(self._tokbtn, NSStackViewGravityTop)
        discord.addView_inGravity_(tok_row, NSStackViewGravityTop)

        self._server = NSTextField.alloc().init()
        self._server.setStringValue_("0")
        self._server.setBezeled_(True)
        self._server.cell().setScrollable_(False)
        self._all_config_controls.append(self._server)
        discord.addView_inGravity_(
            self._form_row("Server ID (numeric)", self._server), NSStackViewGravityTop
        )
        discord_card = _UI.box(discord)
        discord_card.setTranslatesAutoresizingMaskIntoConstraints_(False)

        # ── Output card (stretches to fill remaining height) ──────
        hdr = _UI.h_stack(spacing=6.0)
        hdr.addView_inGravity_(
            _UI.label("Output", size=11.0, color=NSColor.secondaryLabelColor()),
            NSStackViewGravityTop,
        )
        hdr.addView_inGravity_(_UI.spacer_h(),                              NSStackViewGravityTop)
        hdr.addView_inGravity_(_UI.button("Copy",  self, b"copyLogs:"),     NSStackViewGravityTop)
        hdr.addView_inGravity_(_UI.button("Clear", self, b"clearLogs:"),    NSStackViewGravityTop)
        hdr.setTranslatesAutoresizingMaskIntoConstraints_(False)

        self._log = _AdaptiveLogTextView.alloc().init()
        self._log.setEditable_(False)
        self._log.setSelectable_(True)
        self._log.setFont_(_UI.mono_font())
        self._log.setTextContainerInset_((6, 6))
        self._log._apply()

        sc = NSScrollView.alloc().init()
        sc.setDocumentView_(self._log)
        sc.setHasVerticalScroller_(True)
        sc.setAutohidesScrollers_(True)
        sc.setBorderType_(0)
        sc.setDrawsBackground_(True)
        sc.setWantsLayer_(True)
        sc.layer().setCornerRadius_(6.0)
        sc.layer().setMasksToBounds_(True)
        sc.layer().setBorderWidth_(1.0)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sc.layer().setBorderColor_(NSColor.separatorColor().CGColor())
        sc.setTranslatesAutoresizingMaskIntoConstraints_(False)

        H, V = 12.0, 10.0
        output_card = _CardView.alloc().init()
        output_card.setWantsLayer_(True)
        output_card.setTranslatesAutoresizingMaskIntoConstraints_(False)
        output_card._refresh()
        layer = output_card.layer()
        if layer is not None:
            layer.setCornerRadius_(8.0)
            layer.setBorderWidth_(1.0)
        output_card.addSubview_(hdr)
        output_card.addSubview_(sc)
        hdr.topAnchor().constraintEqualToAnchor_constant_(output_card.topAnchor(), V).setActive_(True)
        hdr.leadingAnchor().constraintEqualToAnchor_constant_(output_card.leadingAnchor(), H).setActive_(True)
        hdr.trailingAnchor().constraintEqualToAnchor_constant_(output_card.trailingAnchor(), -H).setActive_(True)
        sc.topAnchor().constraintEqualToAnchor_constant_(hdr.bottomAnchor(), 8.0).setActive_(True)
        sc.leadingAnchor().constraintEqualToAnchor_constant_(output_card.leadingAnchor(), H).setActive_(True)
        sc.trailingAnchor().constraintEqualToAnchor_constant_(output_card.trailingAnchor(), -H).setActive_(True)
        sc.bottomAnchor().constraintEqualToAnchor_constant_(output_card.bottomAnchor(), -V).setActive_(True)

        # ── Place both cards in wrapper ───────────────────────────
        w.addSubview_(discord_card)
        w.addSubview_(output_card)

        discord_card.topAnchor().constraintEqualToAnchor_constant_(w.topAnchor(), pad).setActive_(True)
        discord_card.leadingAnchor().constraintEqualToAnchor_constant_(w.leadingAnchor(), pad).setActive_(True)
        discord_card.trailingAnchor().constraintEqualToAnchor_constant_(w.trailingAnchor(), -pad).setActive_(True)

        output_card.topAnchor().constraintEqualToAnchor_constant_(discord_card.bottomAnchor(), 14.0).setActive_(True)
        output_card.leadingAnchor().constraintEqualToAnchor_constant_(w.leadingAnchor(), pad).setActive_(True)
        output_card.trailingAnchor().constraintEqualToAnchor_constant_(w.trailingAnchor(), -pad).setActive_(True)
        output_card.bottomAnchor().constraintEqualToAnchor_constant_(w.bottomAnchor(), -pad).setActive_(True)

        return w

    # ── Debug tab ──────────────────────────────────────────────────
    @objc.python_method
    def _tab_debug(self) -> NSView:
        w   = NSView.alloc().init()
        pad = UI_PAD
        H, V = 12.0, 10.0

        # ── Screenshot card ───────────────────────────────────────
        ss_hdr = _UI.h_stack(spacing=6.0)
        ss_hdr.addView_inGravity_(
            _UI.label("Screenshot", size=11.0, color=NSColor.secondaryLabelColor()),
            NSStackViewGravityTop,
        )
        ss_hdr.addView_inGravity_(_UI.spacer_h(), NSStackViewGravityTop)
        ss_hdr.setTranslatesAutoresizingMaskIntoConstraints_(False)

        self._debug_iv = NSImageView.alloc().init()
        self._debug_iv.setImageScaling_(3)  # NSImageScaleProportionallyUpOrDown
        self._debug_iv.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self._debug_iv.heightAnchor().constraintEqualToConstant_(220.0).setActive_(True)

        ss_card = _CardView.alloc().init()
        ss_card.setWantsLayer_(True)
        ss_card.setTranslatesAutoresizingMaskIntoConstraints_(False)
        ss_card._refresh()
        lyr = ss_card.layer()
        if lyr is not None:
            lyr.setCornerRadius_(8.0)
            lyr.setBorderWidth_(1.0)
        ss_card.addSubview_(ss_hdr)
        ss_card.addSubview_(self._debug_iv)
        ss_hdr.topAnchor().constraintEqualToAnchor_constant_(ss_card.topAnchor(), V).setActive_(True)
        ss_hdr.leadingAnchor().constraintEqualToAnchor_constant_(ss_card.leadingAnchor(), H).setActive_(True)
        ss_hdr.trailingAnchor().constraintEqualToAnchor_constant_(ss_card.trailingAnchor(), -H).setActive_(True)
        self._debug_iv.topAnchor().constraintEqualToAnchor_constant_(ss_hdr.bottomAnchor(), 8.0).setActive_(True)
        self._debug_iv.leadingAnchor().constraintEqualToAnchor_constant_(ss_card.leadingAnchor(), H).setActive_(True)
        self._debug_iv.trailingAnchor().constraintEqualToAnchor_constant_(ss_card.trailingAnchor(), -H).setActive_(True)
        self._debug_iv.bottomAnchor().constraintEqualToAnchor_constant_(ss_card.bottomAnchor(), -V).setActive_(True)

        # ── OCR text card ─────────────────────────────────────────
        ocr_hdr = _UI.h_stack(spacing=6.0)
        ocr_hdr.addView_inGravity_(
            _UI.label("OCR Text", size=11.0, color=NSColor.secondaryLabelColor()),
            NSStackViewGravityTop,
        )
        ocr_hdr.addView_inGravity_(_UI.spacer_h(), NSStackViewGravityTop)
        ocr_hdr.setTranslatesAutoresizingMaskIntoConstraints_(False)

        self._debug_ocr = _AdaptiveLogTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
        self._debug_ocr.setEditable_(False)
        self._debug_ocr.setSelectable_(True)
        self._debug_ocr.setFont_(_UI.mono_font(11.0))
        self._debug_ocr.setTextContainerInset_((6, 6))
        self._debug_ocr.setVerticallyResizable_(True)
        self._debug_ocr.setHorizontallyResizable_(False)
        self._debug_ocr.textContainer().setWidthTracksTextView_(True)
        self._debug_ocr.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self._debug_ocr._apply()

        ocr_sc = NSScrollView.alloc().init()
        ocr_sc.setDocumentView_(self._debug_ocr)
        ocr_sc.setHasVerticalScroller_(True)
        ocr_sc.setHasHorizontalScroller_(False)
        cv = ocr_sc.contentView()
        self._debug_ocr.leadingAnchor().constraintEqualToAnchor_(cv.leadingAnchor()).setActive_(True)
        self._debug_ocr.trailingAnchor().constraintEqualToAnchor_(cv.trailingAnchor()).setActive_(True)
        self._debug_ocr.topAnchor().constraintEqualToAnchor_(cv.topAnchor()).setActive_(True)
        self._debug_ocr.widthAnchor().constraintEqualToAnchor_(cv.widthAnchor()).setActive_(True)
        ocr_sc.setAutohidesScrollers_(True)
        ocr_sc.setBorderType_(0)
        ocr_sc.setDrawsBackground_(True)
        ocr_sc.setWantsLayer_(True)
        ocr_sc.layer().setCornerRadius_(6.0)
        ocr_sc.layer().setMasksToBounds_(True)
        ocr_sc.layer().setBorderWidth_(1.0)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ocr_sc.layer().setBorderColor_(NSColor.separatorColor().CGColor())
        ocr_sc.setTranslatesAutoresizingMaskIntoConstraints_(False)

        ocr_card = _CardView.alloc().init()
        ocr_card.setWantsLayer_(True)
        ocr_card.setTranslatesAutoresizingMaskIntoConstraints_(False)
        ocr_card._refresh()
        lyr = ocr_card.layer()
        if lyr is not None:
            lyr.setCornerRadius_(8.0)
            lyr.setBorderWidth_(1.0)
        ocr_card.addSubview_(ocr_hdr)
        ocr_card.addSubview_(ocr_sc)
        ocr_hdr.topAnchor().constraintEqualToAnchor_constant_(ocr_card.topAnchor(), V).setActive_(True)
        ocr_hdr.leadingAnchor().constraintEqualToAnchor_constant_(ocr_card.leadingAnchor(), H).setActive_(True)
        ocr_hdr.trailingAnchor().constraintEqualToAnchor_constant_(ocr_card.trailingAnchor(), -H).setActive_(True)
        ocr_sc.topAnchor().constraintEqualToAnchor_constant_(ocr_hdr.bottomAnchor(), 8.0).setActive_(True)
        ocr_sc.leadingAnchor().constraintEqualToAnchor_constant_(ocr_card.leadingAnchor(), H).setActive_(True)
        ocr_sc.trailingAnchor().constraintEqualToAnchor_constant_(ocr_card.trailingAnchor(), -H).setActive_(True)
        ocr_sc.bottomAnchor().constraintEqualToAnchor_constant_(ocr_card.bottomAnchor(), -V).setActive_(True)

        # ── Place both cards in wrapper ───────────────────────────
        w.addSubview_(ss_card)
        w.addSubview_(ocr_card)

        ss_card.topAnchor().constraintEqualToAnchor_constant_(w.topAnchor(), pad).setActive_(True)
        ss_card.leadingAnchor().constraintEqualToAnchor_constant_(w.leadingAnchor(), pad).setActive_(True)
        ss_card.trailingAnchor().constraintEqualToAnchor_constant_(w.trailingAnchor(), -pad).setActive_(True)

        ocr_card.topAnchor().constraintEqualToAnchor_constant_(ss_card.bottomAnchor(), 14.0).setActive_(True)
        ocr_card.leadingAnchor().constraintEqualToAnchor_constant_(w.leadingAnchor(), pad).setActive_(True)
        ocr_card.trailingAnchor().constraintEqualToAnchor_constant_(w.trailingAnchor(), -pad).setActive_(True)
        ocr_card.bottomAnchor().constraintEqualToAnchor_constant_(w.bottomAnchor(), -pad).setActive_(True)

        # ── Initial load + polling ────────────────────────────────
        self._refresh_debug()
        me = self

        def _debug_tick(t: NSTimer) -> None:
            ss_p  = PROJECT_ROOT / "screenshot.png"
            ocr_p = PROJECT_ROOT / "ocr_text.txt"
            changed = False
            if ss_p.exists():
                mt = ss_p.stat().st_mtime
                if mt != me._debug_ss_mtime:
                    me._debug_ss_mtime = mt
                    changed = True
            if ocr_p.exists():
                mt = ocr_p.stat().st_mtime
                if mt != me._debug_ocr_mtime:
                    me._debug_ocr_mtime = mt
                    changed = True
            if changed:
                me._refresh_debug()

        self._debug_timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            0.5, True, _debug_tick
        )
        return w

    @objc.python_method
    def _refresh_debug(self) -> None:
        ss_p  = PROJECT_ROOT / "screenshot.png"
        ocr_p = PROJECT_ROOT / "ocr_text.txt"
        debug_iv  = self._debug_iv
        debug_ocr = self._debug_ocr

        def _load() -> None:
            img = NSImage.alloc().initWithContentsOfFile_(str(ss_p)) if ss_p.exists() else None
            if ocr_p.exists():
                try:
                    text = ocr_p.read_text(encoding="utf-8")
                except Exception:
                    text = "(error reading file)"
            else:
                text = "(no OCR output yet — run the macro to populate)"

            def _apply() -> None:
                if debug_iv is not None and img is not None:
                    debug_iv.setImage_(img)
                if debug_ocr is not None:
                    ts = debug_ocr.textStorage()
                    if ts is not None:
                        ts.replaceCharactersInRange_withAttributedString_(
                            (0, int(ts.length())),
                            NSMutableAttributedString.alloc().initWithString_attributes_(
                                text,
                                {
                                    NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
                                    NSFontAttributeName: _UI.mono_font(11.0),
                                },
                            ),
                        )

            NSOperationQueue.mainQueue().addOperationWithBlock_(_apply)

        threading.Thread(target=_load, daemon=True).start()

    # ── Selector actions ────────────────────────────────────────────
    def switchToTab_(self, index) -> None:
        self._tab.selectTabViewItemAtIndex_(int(index))
        win = self._window
        if win is not None:
            cv = win.contentView()
            if cv is not None:
                cv.layoutSubtreeIfNeeded()

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
        self._ct_view.set_click_through(True)
        if self._run_item is not None:
            img = _UI.sf("stop.fill", "Stop", size=16.0)
            self._run_item.setImage_(img)
            self._run_item.setLabel_("Stop")
            self._run_item.setEnabled_(False)
        self._set_status("Checking for updates…", _Colors.MUTED, _Colors.IDLE)
        self._set_en(False)

        def _launch():
            if self._run_item is not None:
                self._run_item.setEnabled_(True)
            self._set_status("Running", _Colors.RUN, _Colors.RUN)
            self._subprocess_mgr.start(self._log_queue, self._on_exit)

        start_background_update(
            log_queue=self._log_queue,
            restart_callback=lambda: NSOperationQueue.mainQueue().addOperationWithBlock_(
                self._restart_after_update,
            ),
            done_callback=lambda: NSOperationQueue.mainQueue().addOperationWithBlock_(_launch),
        )

    @objc.python_method
    def _on_exit(self, code: int) -> None:
        self._is_running = False
        self._ct_view.set_click_through(False)
        self._set_en(True)
        if self._run_item is not None:
            img = _UI.sf("play.fill", "Start", size=16.0)
            self._run_item.setImage_(img)
            self._run_item.setLabel_("Start")
            self._run_item.setEnabled_(True)
        self._set_status(
            "Idle" if int(code) == 0 else f"Stopped",
            _Colors.MUTED, _Colors.IDLE,
        )

    @objc.python_method
    def _restart_after_update(self) -> None:
        if self._is_running:
            self._subprocess_mgr.stop_blocking()
        try:
            subprocess.Popen(
                [str(VENV_PYTHON), str(PROJECT_ROOT / "ui.py")],
                cwd=str(PROJECT_ROOT),
                start_new_session=True,
            )
        except OSError as e:
            self._line(f"[update] Could not restart ({e}). Quit and reopen the app.")
            return
        NSApplication.sharedApplication().terminate_(None)

    @objc.python_method
    def _show_update_overlay(self) -> None:
        if self._update_overlay is not None:
            return
        overlay = _UpdateOverlayView.alloc().init()
        overlay.setTranslatesAutoresizingMaskIntoConstraints_(False)
        overlay._setup()
        self._ct_view.addSubview_(overlay)
        _UI.pin_edges(overlay, self._ct_view)
        overlay.start()
        self._update_overlay = overlay

    @objc.python_method
    def _hide_update_overlay(self) -> None:
        if self._update_overlay is None:
            return
        self._update_overlay.stop()
        self._update_overlay.removeFromSuperview()
        self._update_overlay = None

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
            "HuntingMode": str(self._hunt.titleOfSelectedItem() or "Egg Resetter"),
            "Username":    str(self._user.stringValue() or ""),
            "Mode":        str(self._fast.titleOfSelectedItem() or "URL Open"),
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
            "DexScanner": self._config.get("DexScanner", {
                "Rows": 23, "Cols": 33,
                "SampleOffset": [10, 10],
                "OutputFile": "missing-poopimons.txt",
            }),
        }

    @objc.python_method
    def _load_all_fields(self) -> None:
        c = self._config
        self._hunt.selectItemWithTitle_(c.get("HuntingMode", "Egg Resetter") or "Egg Resetter")
        self._user.setStringValue_(c.get("Username", "") or "")
        self._fast.selectItemWithTitle_(c.get("Mode", "URL Open") or "URL Open")
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
        print(s, flush=True)
        if "[update] Downloading" in s:
            self._show_update_overlay()
        elif self._update_overlay is not None:
            sl = s.lower()
            if "failed" in sl or "error" in sl or "could not" in sl or "skipping" in sl:
                self._hide_update_overlay()
        ts = self._log.textStorage()
        if ts is None:
            return
        at_bottom = self._near_bottom()
        L = len(ts.string() or "")
        astr = NSMutableAttributedString.alloc().initWithString_attributes_(
            str(s) + "\n",
            {
                NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
                NSFontAttributeName: _UI.mono_font(),
            },
        )
        ts.replaceCharactersInRange_withAttributedString_((L, 0), astr)
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

    def windowWillClose_(self, notification) -> None:
        NSApplication.sharedApplication().terminate_(None)

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

        # Standard Edit menu (Cut/Copy/Paste/Select All). Cmd+V routes through the Paste
        # item — without these, Cocoa often does not deliver paste to embedded text fields.
        edit = NSMenu.alloc().initWithTitle_("Edit")

        def _resp_item(title: str, action: bytes, key: str, mod: int = NSCommandKeyMask) -> None:
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
            mi.setKeyEquivalentModifierMask_(mod)
            edit.addItem_(mi)

        _resp_item("Undo", b"undo:", "z")
        _resp_item("Redo", b"redo:", "Z", NSCommandKeyMask | NSShiftKeyMask)
        edit.addItem_(NSMenuItem.separatorItem())
        _resp_item("Cut", b"cut:", "x")
        _resp_item("Copy", b"copy:", "c")
        _resp_item("Paste", b"paste:", "v")
        _resp_item(
            "Paste and Match Style",
            b"pasteAsPlainText:",
            "v",
            NSCommandKeyMask | NSShiftKeyMask,
        )
        edit.addItem_(NSMenuItem.separatorItem())
        _resp_item("Select All", b"selectAll:", "a")

        edit_top = NSMenuItem.alloc().init()
        edit_top.setSubmenu_(edit)
        edit_top.setTitle_("Edit")
        bar.addItem_(edit_top)

        app.setMainMenu_(bar)

    # ── Entry point ────────────────────────────────────────────────
    @objc.python_method
    def run(self) -> None:
        start_background_update(
            log_queue=self._log_queue,
            restart_callback=lambda: NSOperationQueue.mainQueue().addOperationWithBlock_(
                self._restart_after_update,
            ),
        )
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
