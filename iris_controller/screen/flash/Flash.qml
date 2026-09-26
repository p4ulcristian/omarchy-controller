import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// Mid-screen flash of what iris-controller just did. The buttons pop in one
// after another, then what they did slides in, then it all fades. Summoned
// again while showing, it starts over. No keys = a message on its own.
//   payload: { "keys": ["L2", "□"], "action": "Copy" }
Item {
  id: root

  property bool opened: false
  property var keys: []
  property string action: ""
  property int gen: 0          // bumps on every combo, restarting the animation

  readonly property color ink: Color.popups.text
  readonly property color accent: Color.accent
  readonly property int stagger: 70     // ms between one key popping in and the next

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
      root.keys = p.keys || []
      root.action = p.action || ""
    } catch (e) {}
    root.opened = true
    root.gen++
    show.restart()
  }

  function close() { root.opened = false }

  // In, hold, out. The keys and the action run their own entrances off `gen`.
  SequentialAnimation {
    id: show
    NumberAnimation { target: card; property: "opacity"; to: 1; duration: 90 }
    PauseAnimation { duration: 550 + root.keys.length * root.stagger }
    ParallelAnimation {
      NumberAnimation { target: card; property: "opacity"; to: 0; duration: 200; easing.type: Easing.InQuad }
      NumberAnimation { target: card; property: "scale"; from: 1; to: 0.94; duration: 200; easing.type: Easing.InQuad }
    }
    ScriptAction { script: { root.opened = false; card.scale = 1 } }
  }

  PanelWindow {
    id: panel
    visible: root.opened
    screen: root.targetScreen
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "iris-controller-flash"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    // Look-only: an empty input region so it never eats clicks.
    mask: Region {}

    Item {
      id: card
      opacity: 0
      width: content.width + 64
      height: 112
      anchors.horizontalCenter: parent.horizontalCenter
      y: parent.height * 0.42 - height / 2

      readonly property int cut: 18

      // Chamfered plate with bracket corners, like the cheat sheet.
      Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
          strokeColor: Util.alpha(root.accent, 0.6); strokeWidth: 1.5
          fillColor: Color.background
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
            path: "M " + (card.width - 44) + " 2 L " + (card.width - 2) + " 2 L " + (card.width - 2) + " 44 "
                + "M 2 " + (card.height - 44) + " L 2 " + (card.height - 2) + " L 44 " + (card.height - 2)
          }
        }
      }

      // A scan line sweeping across once per combo.
      Rectangle {
        id: sweep
        width: 90
        height: card.height - 4
        y: 2
        opacity: 0
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0; color: Util.alpha(root.accent, 0) }
          GradientStop { position: 0.8; color: Util.alpha(root.accent, 0.22) }
          GradientStop { position: 1; color: Util.alpha(root.accent, 0) }
        }
        Connections {
          target: root
          function onGenChanged() { sweepAnim.restart() }
        }
        SequentialAnimation {
          id: sweepAnim
          PropertyAction { target: sweep; property: "opacity"; value: 1 }
          NumberAnimation { target: sweep; property: "x"; from: 0; to: card.width - sweep.width; duration: 520; easing.type: Easing.OutCubic }
          NumberAnimation { target: sweep; property: "opacity"; to: 0; duration: 180 }
        }
      }

      Row {
        id: content
        anchors.centerIn: parent
        spacing: 14

        Repeater {
          model: root.keys
          Row {
            required property string modelData
            required property int index
            spacing: 14

            Text {
              visible: index > 0
              anchors.verticalCenter: parent.verticalCenter
              text: "+"
              font.family: Style.font.family
              font.pixelSize: 26
              color: Util.alpha(root.ink, 0.5)
            }

            // One pressed button: pops in, flashes, settles.
            Rectangle {
              id: chip
              readonly property color tint: root.symbolColor[modelData] || root.accent
              implicitWidth: chipText.implicitWidth + 32
              implicitHeight: 58
              radius: 3
              color: Util.alpha(tint, 0.14)
              border.width: 2
              border.color: tint
              scale: 0
              Text {
                id: chipText
                anchors.centerIn: parent
                textFormat: Text.PlainText
                text: modelData
                font.family: Style.font.family
                font.bold: true
                font.pixelSize: root.symbolColor[modelData] ? 32 : 26
                color: root.symbolColor[modelData] || root.ink
              }
              Rectangle {        // flash as it lands
                id: flash
                anchors.fill: parent
                anchors.margins: -6
                radius: 6
                color: "transparent"
                border.width: 3
                border.color: chip.tint
                opacity: 0
              }
              function play() { pop.restart() }
              Component.onCompleted: play()
              Connections {
                target: root
                function onGenChanged() { chip.play() }
              }
              SequentialAnimation {
                id: pop
                PropertyAction { target: chip; property: "scale"; value: 0 }
                PauseAnimation { duration: index * root.stagger }
                ParallelAnimation {
                  NumberAnimation { target: chip; property: "scale"; to: 1; duration: 260; easing.type: Easing.OutBack; easing.overshoot: 2.2 }
                  SequentialAnimation {
                    PropertyAction { target: flash; property: "opacity"; value: 0.9 }
                    NumberAnimation { target: flash; property: "anchors.margins"; from: -2; to: -14; duration: 380; easing.type: Easing.OutCubic }
                  }
                  NumberAnimation { target: flash; property: "opacity"; to: 0; duration: 380 }
                }
              }
            }
          }
        }

        Text {
          id: arrow
          visible: root.keys.length > 0
          anchors.verticalCenter: parent.verticalCenter
          text: "▸"
          font.family: Style.font.family
          font.pixelSize: 28
          color: root.accent
        }

        // What it did: slides in after the last key, letters spreading out.
        Text {
          id: actionText
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: root.action
          font.family: Style.font.family
          font.bold: true
          font.pixelSize: 30
          font.capitalization: Font.AllUppercase
          color: root.ink
          Connections {
            target: root
            function onGenChanged() { slide.restart() }
          }
          SequentialAnimation {
            id: slide
            PropertyAction { targets: [actionText, arrow]; property: "opacity"; value: 0 }
            PropertyAction { target: actionText; property: "font.letterSpacing"; value: 0 }
            PauseAnimation { duration: root.keys.length * root.stagger + 120 }
            NumberAnimation { target: arrow; property: "opacity"; to: 1; duration: 120 }
            ParallelAnimation {
              NumberAnimation { target: actionText; property: "opacity"; to: 1; duration: 220 }
              NumberAnimation { target: actionText; property: "font.letterSpacing"; to: 3; duration: 360; easing.type: Easing.OutCubic }
            }
          }
        }
      }
    }
  }
}
