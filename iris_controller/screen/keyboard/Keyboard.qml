import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// On-screen keyboard for iris-controller (L1 held). The controller owns the
// layout, the highlight and the typing; this draws them and reports the
// pointer over the keys back on keyboard.sock ("hover R C", "leave",
// "down R C", "up"). It never takes keyboard focus, so keys land in the
// window underneath.
//   summon payload: { "rows": [[{ "label": "q", "shift": "Q", "w": 1 }, ...], ...],
//                     "row": 2, "col": 1, "mods": ["shift"] }
//   update(json):   { "row": 2, "col": 3, "mods": [] }
// With "style": "wheel" it draws the petal wheel instead (wheel.py):
//   summon adds  { "layers": [{ "name": "abc", "petals": [[{ "label", "shift" } x4] x8] }, ...] }
//   state adds   { "layer": 0, "petal": -1 (center) | 0-7 clockwise from up, "locked": ["ctrl"] }
Item {
  id: root

  property bool opened: false
  property var rows: []
  property int row: 0
  property int col: 0
  property var mods: []
  property string style: "grid"
  property var layers: []
  property int level: 0
  property int petal: -1
  property var locked: []
  readonly property bool wheeling: style === "wheel" && layers.length > 0

  readonly property int unit: 44      // one key width, before scaling
  readonly property int gap: 5
  readonly property int pad: 14
  readonly property int rowUnits: 15
  readonly property int boardW: rowUnits * unit
  readonly property int boardH: rows.length * unit + (rows.length - 1) * gap
  // The wheel: petals of petalD around a ring of ringR.
  readonly property int petalD: 108
  readonly property int ringR: 156
  readonly property int dialD: 2 * ringR + petalD

  readonly property color ink: Color.popups.text
  readonly property color hud: Color.accent
  readonly property bool shifted: mods.indexOf("shift") >= 0

  readonly property var targetScreen: {
    var name = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : ""
    var screens = Quickshell.screens
    for (var i = 0; i < screens.length; i++)
      if (screens[i].name === name) return screens[i]
    return screens.length > 0 ? screens[0] : null
  }

  function applyState(p) {
    if (p.row !== undefined) root.row = p.row
    if (p.col !== undefined) root.col = p.col
    if (p.mods !== undefined) root.mods = p.mods
    if (p.style !== undefined) root.style = p.style
    if (p.layer !== undefined) root.level = p.layer
    if (p.petal !== undefined) root.petal = p.petal
    if (p.locked !== undefined) root.locked = p.locked
  }

  function open(payloadJson) {
    try {
      var p = JSON.parse(payloadJson || "{}")
      if (p.rows) root.rows = p.rows
      if (p.layers) root.layers = p.layers
      applyState(p)
    } catch (e) {}
    root.opened = true
  }

  function update(stateJson) {
    try { applyState(JSON.parse(stateJson || "{}")) } catch (e) {}
  }

  function close() { root.opened = false }

  function report(msg) {
    if (link.connected) {
      link.write(msg + "\n")
      link.flush()
    }
  }

  Socket {
    id: link
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/iris-controller/keyboard.sock"
    connected: root.opened
    // The controller restarted while the keyboard shows: keep knocking.
    onConnectedChanged: if (!connected && root.opened) reconnect.start()
  }

  Timer {
    id: reconnect
    interval: 1000
    onTriggered: link.connected = root.opened
  }

  PanelWindow {
    id: panel
    visible: root.opened
    screen: root.targetScreen
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "iris-controller-keyboard"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    // The panel covers the screen so the board can go anywhere, but only
    // the board takes the pointer; the rest stays click-through.
    mask: Region { item: board }

    // The board: a handle tab on its top left, and the keys under it. It
    // starts at the bottom middle and stays where it was dragged.
    Item {
      id: board
      width: card.width
      height: grip.height + card.height
      x: (panel.width - width) / 2
      y: panel.height - height - 24

      Rectangle {
        id: grip
        x: card.cut
        width: 72
        height: 22
        radius: 6
        color: gripArea.containsMouse || gripArea.drag.active ? Qt.lighter(root.hud, 1.25) : root.hud

        Text {
          anchors.centerIn: parent
          text: "\uDB80\uDDBE"   // nf-md-cursor_move: four arrows, "move me"
          font.family: "JetBrainsMono Nerd Font"
          font.pixelSize: 16
          color: Color.background
        }

        MouseArea {
          id: gripArea
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.SizeAllCursor
          // Not a key: ✕ clicks here, so it drags.
          onEntered: root.report("leave")
          drag.target: board
          drag.threshold: 0
          drag.minimumX: 0
          drag.maximumX: panel.width - board.width
          drag.minimumY: 0
          drag.maximumY: panel.height - board.height
        }
      }

      Item {
        id: card
        y: grip.height
        // The pointer leaving the keys: ✕ goes back to clicking.
        HoverHandler {
          onHoveredChanged: if (!hovered) root.report("leave")
        }
        width: (root.wheeling ? wheel.width : root.boardW) + 2 * root.pad
        height: (root.wheeling ? wheel.height : root.boardH) + 2 * root.pad

        readonly property int cut: 14   // chamfered corners, like the cheat sheet

        Shape {
          anchors.fill: parent
          preferredRendererType: Shape.CurveRenderer
          ShapePath {
            strokeColor: Util.alpha(root.hud, 0.55); strokeWidth: 1.5
            fillColor: Color.background
            PathSvg {
              path: "M " + card.cut + " 0 L " + card.width + " 0 L " + card.width + " " + (card.height - card.cut)
                  + " L " + (card.width - card.cut) + " " + card.height + " L 0 " + card.height
                  + " L 0 " + card.cut + " Z"
            }
          }
          ShapePath {
            strokeColor: root.hud; strokeWidth: 4; fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            PathSvg {
              path: "M " + (card.width - 60) + " 2 L " + (card.width - 2) + " 2 L " + (card.width - 2) + " 60 "
                  + "M 2 " + (card.height - 60) + " L 2 " + (card.height - 2) + " L 60 " + (card.height - 2)
            }
          }
        }

        Column {
          x: root.pad
          y: root.pad
          spacing: root.gap
          visible: !root.wheeling

          Repeater {
            model: root.rows
            Row {
              id: keyRow
              required property var modelData
              required property int index
              readonly property int rowIndex: index
              // Keys share the row's gaps so every row ends at the same edge.
              readonly property real unitW: (root.boardW - (modelData.length - 1) * root.gap) / root.rowUnits
              spacing: root.gap

              Repeater {
                model: keyRow.modelData
                Rectangle {
                  required property var modelData
                  required property int index
                  readonly property bool selected: keyRow.rowIndex === root.row && index === root.col
                  width: modelData.w * keyRow.unitW
                  height: root.unit
                  radius: 3
                  color: selected ? Util.alpha(root.hud, 0.32) : Util.alpha(root.ink, 0.06)
                  border.width: selected ? 2 : 1
                  border.color: selected ? root.hud : Util.alpha(root.hud, 0.25)

                  MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    onEntered: root.report("hover " + keyRow.rowIndex + " " + index)
                    onPressed: root.report("down " + keyRow.rowIndex + " " + index)
                    onReleased: root.report("up")
                    onCanceled: root.report("up")
                  }

                  Text {
                    anchors.centerIn: parent
                    textFormat: Text.PlainText
                    text: root.shifted ? modelData.shift : modelData.label
                    font.family: Style.font.family
                    font.bold: parent.selected
                    font.pixelSize: text.length > 1 ? 13 : 18
                    color: parent.selected ? root.ink : Util.alpha(root.ink, 0.8)
                  }
                }
              }
            }
          }
        }

        // The petal wheel: layer tabs on top, the dial, the modifiers under it.
        Column {
          id: wheel
          visible: root.wheeling
          x: root.pad
          y: root.pad
          width: root.dialD
          spacing: 10

          readonly property var petals: root.wheeling ? root.layers[Math.min(root.level, root.layers.length - 1)].petals : []

          // L2 ‹ abc 123 keys › R2
          Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8
            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "L2 ‹"
              font.family: Style.font.family; font.pixelSize: 13
              color: Util.alpha(root.ink, 0.55)
            }
            Repeater {
              model: root.layers
              Rectangle {
                required property var modelData
                required property int index
                readonly property bool current: index === root.level
                width: tabText.implicitWidth + 20
                height: 26
                radius: 3
                color: current ? root.hud : Util.alpha(root.ink, 0.06)
                border.width: 1
                border.color: Util.alpha(root.hud, current ? 1 : 0.3)
                Text {
                  id: tabText
                  anchors.centerIn: parent
                  text: modelData.name
                  font.family: Style.font.family; font.pixelSize: 14; font.bold: parent.current
                  color: parent.current ? Color.background : Util.alpha(root.ink, 0.8)
                }
              }
            }
            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "› R2"
              font.family: Style.font.family; font.pixelSize: 13
              color: Util.alpha(root.ink, 0.55)
            }
          }

          Item {
            id: dial
            width: root.dialD
            height: root.dialD

            // The ring the petals sit on.
            Rectangle {
              anchors.centerIn: parent
              width: 2 * root.ringR; height: width; radius: width / 2
              color: "transparent"
              border.width: 1
              border.color: Util.alpha(root.hud, 0.2)
            }
            Repeater {
              model: 8
              Rectangle {
                id: petalBox
                required property int index
                readonly property bool picked: index === root.petal
                readonly property var slots: wheel.petals[index] || []
                readonly property real a: index * Math.PI / 4
                width: root.petalD; height: root.petalD; radius: root.petalD / 2
                x: dial.width / 2 + root.ringR * Math.sin(a) - width / 2
                y: dial.height / 2 - root.ringR * Math.cos(a) - height / 2
                scale: picked ? 1.12 : 1
                Behavior on scale { NumberAnimation { duration: 90 } }
                color: picked ? Util.alpha(root.hud, 0.3) : Util.alpha(root.ink, 0.05)
                border.width: picked ? 2 : 1
                border.color: picked ? root.hud : Util.alpha(root.hud, 0.3)

                // △ top, ○ right, ✕ bottom, □ left, like the face buttons.
                Repeater {
                  model: petalBox.slots
                  Text {
                    required property var modelData
                    required property int index
                    readonly property var spot: [[0.5, 0.2], [0.8, 0.5], [0.5, 0.8], [0.2, 0.5]][index]
                    x: petalBox.width * spot[0] - width / 2
                    y: petalBox.height * spot[1] - height / 2
                    textFormat: Text.PlainText
                    text: root.shifted ? modelData.shift : modelData.label
                    font.family: Style.font.family
                    font.bold: petalBox.picked
                    font.pixelSize: text.length > 1 ? 11 : (petalBox.picked ? 22 : 19)
                    color: petalBox.picked ? root.ink : Util.alpha(root.ink, 0.8)
                  }
                }
              }
            }

            // The center: the picked petal big, with its buttons, or (stick
            // at rest) what the face buttons do there.
            Rectangle {
              id: hub
              anchors.centerIn: parent
              width: 150; height: 150; radius: 75
              color: Util.alpha(root.ink, 0.04)
              border.width: 1
              border.color: Util.alpha(root.hud, 0.35)

              readonly property var glyphs: ["△", "○", "✕", "□"]
              readonly property var idle: ["⌫", "close", "space", "⏎"]
              readonly property var slots: root.petal >= 0 ? (wheel.petals[root.petal] || []) : []

              Repeater {
                model: 4
                Column {
                  required property int index
                  readonly property var spot: [[0.5, 0.2], [0.79, 0.5], [0.5, 0.8], [0.21, 0.5]][index]
                  x: hub.width * spot[0] - width / 2
                  y: hub.height * spot[1] - height / 2
                  spacing: -2
                  Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    textFormat: Text.PlainText
                    text: {
                      if (root.petal < 0) return hub.idle[index]
                      var s = hub.slots[index]
                      return s ? (root.shifted ? s.shift : s.label) : ""
                    }
                    font.family: Style.font.family
                    font.bold: root.petal >= 0
                    font.pixelSize: root.petal < 0 ? 12 : (text.length > 1 ? 13 : 24)
                    color: root.petal >= 0 ? root.ink : Util.alpha(root.ink, 0.7)
                  }
                  Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: hub.glyphs[index]
                    font.pixelSize: 10
                    color: root.hud
                  }
                }
              }
            }
          }

          // Modifiers: lit for the next key, filled when locked (tap again).
          Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8
            Repeater {
              model: [["shift", "⇧ R1"], ["ctrl", "Ctrl ↑"], ["alt", "Alt ←"], ["super", "Super →"], ["", "Tab ↓"]]
              Rectangle {
                required property var modelData
                readonly property bool on: modelData[0] !== "" && root.mods.indexOf(modelData[0]) >= 0
                readonly property bool lock: root.locked.indexOf(modelData[0]) >= 0
                width: modText.implicitWidth + 18
                height: 24
                radius: 3
                color: lock ? root.hud : on ? Util.alpha(root.hud, 0.3) : "transparent"
                border.width: 1
                border.color: on ? root.hud : Util.alpha(root.hud, 0.3)
                Text {
                  id: modText
                  anchors.centerIn: parent
                  text: modelData[1]
                  font.family: Style.font.family; font.pixelSize: 12; font.bold: parent.on
                  color: parent.lock ? Color.background : Util.alpha(root.ink, parent.on ? 1 : 0.6)
                }
              }
            }
          }
        }
      }
    }
  }
}
