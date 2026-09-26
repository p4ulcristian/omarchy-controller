import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// What can follow a held trigger, at that trigger's side of the screen:
// L2 on the left, R2 on the right. Appears at once, stays while the trigger
// is held, fades when iris-controller hides it.
//   payload: { "side": "left", "trigger": "L2",
//              "rows": [ { "keys": ["□"], "action": "Copy" }, ... ] }
Item {
  id: root

  property bool opened: false
  property string side: "left"
  property string trigger: ""
  property var rows: []

  readonly property color ink: Color.popups.text
  readonly property color accent: Color.accent
  readonly property int edge: 36         // gap between the card and the screen edge

  // PlayStation symbol colors.
  readonly property var symbolColor: ({ "△": "#3fc8a8", "○": "#e8616b", "✕": "#7b9fe8", "□": "#d58ad8" })

  readonly property var targetScreen: {
    var name = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : ""
    var screens = Quickshell.screens
    for (var i = 0; i < screens.length; i++)
      if (screens[i].name === name) return screens[i]
    return screens.length > 0 ? screens[0] : null
  }

  function open(payloadJson) {
    try {
      var p = JSON.parse(payloadJson || "{}")
      root.side = p.side === "right" ? "right" : "left"
      root.trigger = p.trigger || ""
      root.rows = p.rows || []
    } catch (e) {}
    out.stop()
    card.opacity = 1
    root.opened = true
  }

  function close() {
    if (root.opened) out.restart()
  }

  SequentialAnimation {
    id: out
    NumberAnimation { target: card; property: "opacity"; to: 0; duration: 120; easing.type: Easing.InQuad }
    ScriptAction { script: root.opened = false }
  }

  PanelWindow {
    visible: root.opened
    screen: root.targetScreen
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "iris-controller-guide"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    // Look-only: an empty input region so it never eats clicks.
    mask: Region {}

    Item {
      id: card
      opacity: 0
      readonly property bool rightSide: root.side === "right"
      readonly property int cut: 18
      width: list.width + 56
      height: list.height + 48
      x: rightSide ? parent.width - width - root.edge : root.edge
      anchors.verticalCenter: parent.verticalCenter

      // Chamfered plate with bracket corners, like the flash. The brackets sit
      // on the side facing the screen edge.
      Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
          strokeColor: Util.alpha(root.accent, 0.6); strokeWidth: 1.5
          fillColor: Util.alpha(Color.background, 0.75)
          PathSvg {
            path: "M " + card.cut + " 0 L " + card.width + " 0 L " + card.width + " " + (card.height - card.cut)
                + " L " + (card.width - card.cut) + " " + card.height + " L 0 " + card.height
                + " L 0 " + card.cut + " Z"
          }
        }
        ShapePath {
          strokeColor: root.accent; strokeWidth: 4; fillColor: "transparent"
          capStyle: ShapePath.FlatCap
          PathSvg {
            path: card.rightSide
              ? "M " + (card.width - 44) + " 2 L " + (card.width - 2) + " 2 L " + (card.width - 2) + " 44"
              : "M 2 " + (card.height - 44) + " L 2 " + (card.height - 2) + " L 44 " + (card.height - 2)
          }
        }
      }

      Column {
        id: list
        x: 28
        y: 24
        spacing: 12

        // Header: the held trigger, at the screen-edge side.
        Row {
          x: card.rightSide ? list.width - width : 0
          layoutDirection: card.rightSide ? Qt.RightToLeft : Qt.LeftToRight
          spacing: 12
          Rectangle {
            implicitWidth: triggerText.implicitWidth + 24
            implicitHeight: 40
            radius: 3
            color: Util.alpha(root.accent, 0.16)
            border.width: 2
            border.color: root.accent
            Text {
              id: triggerText
              anchors.centerIn: parent
              text: root.trigger
              font.family: Style.font.family
              font.bold: true
              font.pixelSize: 20
              color: root.ink
            }
          }
          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "HELD"
            font.family: Style.font.family
            font.pixelSize: 14
            font.letterSpacing: 3
            color: Util.alpha(root.ink, 0.55)
          }
        }

        Rectangle { width: grid.width; height: 1; color: Util.alpha(root.accent, 0.35) }

        // What it does first, then the inputs. Text is left-aligned on the
        // left panel and right-aligned on the right one. Filled column by
        // column, so each is as wide as its widest entry.
        Grid {
          id: grid
          flow: Grid.TopToBottom
          rows: root.rows.length
          columnSpacing: 18
          rowSpacing: 10
          verticalItemAlignment: Grid.AlignVCenter
          horizontalItemAlignment: card.rightSide ? Grid.AlignRight : Grid.AlignLeft

          Repeater {
            model: root.rows
            Text {
              required property var modelData
              textFormat: Text.PlainText
              text: modelData.action
              font.family: Style.font.family
              font.pixelSize: 19
              color: root.ink
            }
          }
          Repeater {
            model: root.rows
            Row {
              required property var modelData
              spacing: 6
              Repeater {
                model: modelData.keys
                Rectangle {
                  required property string modelData
                  readonly property color tint: root.symbolColor[modelData] || Util.alpha(root.ink, 0.5)
                  implicitWidth: keyText.implicitWidth + 18
                  implicitHeight: 34
                  radius: 3
                  color: Util.alpha(tint, 0.14)
                  border.width: 1.5
                  border.color: tint
                  Text {
                    id: keyText
                    anchors.centerIn: parent
                    textFormat: Text.PlainText
                    text: modelData
                    font.family: Style.font.family
                    font.bold: true
                    font.pixelSize: root.symbolColor[modelData] ? 22 : 16
                    color: root.symbolColor[modelData] || root.ink
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
