import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// App grid for iris-controller (tap PS): the same apps as the Omarchy
// launcher, from the shell's app library, as tiles. The controller only
// counts: every D-pad step and ✕ press adds to running totals, and each call
// carries all of them, so a call the controller drops for a newer one loses
// nothing. This applies whatever changed since the last call.
//   summon payload: { "dx": 0, "dy": 0, "picks": 0 }   totals so far: the baseline
//   steer(json):    { "dx": 3, "dy": -1, "picks": 0 }  a pick launches and closes
Item {
  id: root

  // Injected by omarchy-shell. Not keepLoaded: loaded at each summon, since
  // the shell can revoke a kept plugin's API while it starts up.
  property var shell: null
  readonly property var appLibrary: root.shell ? root.shell.appLibrary : null

  property bool opened: false
  property var apps: []           // [{ id, name, icon }], launcher order
  property int current: 0
  property var seen: ({ dx: 0, dy: 0, picks: 0 })

  readonly property int cols: 6
  readonly property int tile: 150
  readonly property int gap: 12
  readonly property int pad: 24
  readonly property int visibleRows: 4

  readonly property color ink: Color.popups.text
  readonly property color hud: Color.accent

  readonly property var targetScreen: {
    var name = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : ""
    var screens = Quickshell.screens
    for (var i = 0; i < screens.length; i++)
      if (screens[i].name === name) return screens[i]
    return screens.length > 0 ? screens[0] : null
  }

  function totals(json) {
    try {
      var p = JSON.parse(json || "{}")
      return { dx: p.dx || 0, dy: p.dy || 0, picks: p.picks || 0 }
    } catch (e) {
      return null
    }
  }

  function loadApps() {
    var out = []
    if (root.appLibrary) {
      root.appLibrary.refreshIcons()
      var rows = root.appLibrary.sortedEntries("")
      for (var i = 0; i < rows.length; i++) {
        var entry = rows[i].entry
        var id = String(entry.id || "")
        if (id) out.push({ id: id, name: root.appLibrary.entryName(entry), icon: String(entry.icon || "") })
      }
    }
    root.apps = out
    console.warn("LAUNCHERDBG shell=" + root.shell + " lib=" + root.appLibrary + " n=" + out.length)
  }

  function open(payloadJson) {
    root.seen = totals(payloadJson) || { dx: 0, dy: 0, picks: 0 }
    loadApps()
    root.current = 0
    grid.positionViewAtBeginning()
    root.opened = true
  }

  function close() { root.opened = false }

  function steer(json) {
    var t = totals(json)
    if (!t || !root.opened) return
    var n = root.apps.length
    var dx = t.dx - root.seen.dx, dy = t.dy - root.seen.dy, picks = t.picks - root.seen.picks
    root.seen = t
    if (n === 0) return
    // Sideways runs on through the rows; up/down stops at the edges.
    var i = Math.max(0, Math.min(n - 1, root.current + dx))
    var down = i + dy * root.cols
    if (down >= 0 && down < n) i = down
    else if (dy > 0 && Math.floor(i / root.cols) < Math.floor((n - 1) / root.cols)) i = n - 1
    root.current = i
    grid.positionViewAtIndex(i, GridView.Contain)
    if (picks > 0) {
      var app = root.apps[i]
      root.opened = false
      root.appLibrary.launch(app.id, app.name)
      root.shell.hide("p4ulcristian.iris-controller-launcher")   // unload until the next summon
    }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    screen: root.targetScreen
    anchors { top: true; bottom: true; left: true; right: true }
    color: Util.alpha(Color.background, 0.55)
    WlrLayershell.namespace: "iris-controller-launcher"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      id: card
      anchors.centerIn: parent
      width: root.cols * (root.tile + root.gap) + 2 * root.pad - root.gap
      height: Math.min(root.visibleRows, Math.max(1, Math.ceil(root.apps.length / root.cols)))
              * (root.tile + root.gap) + 2 * root.pad - root.gap
      radius: 6
      color: Color.background
      border.width: 1.5
      border.color: Util.alpha(root.hud, 0.55)

      Text {
        visible: root.apps.length === 0
        anchors.centerIn: parent
        text: "No apps"
        font.family: Style.font.family
        font.pixelSize: 18
        color: Util.alpha(root.ink, 0.6)
      }

      GridView {
        id: grid
        anchors.fill: parent
        anchors.margins: root.pad
        clip: true
        interactive: false
        cellWidth: root.tile + root.gap
        cellHeight: root.tile + root.gap
        model: root.apps

        delegate: Rectangle {
          required property var modelData
          required property int index
          readonly property bool selected: index === root.current
          width: root.tile
          height: root.tile
          radius: 6
          color: selected ? Util.alpha(root.hud, 0.32) : Util.alpha(root.ink, 0.06)
          border.width: selected ? 3 : 1
          border.color: selected ? root.hud : Util.alpha(root.hud, 0.25)

          Image {
            id: icon
            anchors.horizontalCenter: parent.horizontalCenter
            y: 22
            width: 64
            height: 64
            fillMode: Image.PreserveAspectFit
            sourceSize.width: width * Screen.devicePixelRatio
            sourceSize.height: height * Screen.devicePixelRatio
            source: root.appLibrary ? root.appLibrary.iconSource(modelData.icon) : ""
            asynchronous: true
          }

          Text {
            anchors { left: parent.left; right: parent.right; top: icon.bottom; topMargin: 12; margins: 8 }
            horizontalAlignment: Text.AlignHCenter
            textFormat: Text.PlainText
            text: modelData.name
            elide: Text.ElideRight
            font.family: Style.font.family
            font.bold: parent.selected
            font.pixelSize: 15
            color: parent.selected ? root.ink : Util.alpha(root.ink, 0.8)
          }
        }
      }
    }
  }
}
