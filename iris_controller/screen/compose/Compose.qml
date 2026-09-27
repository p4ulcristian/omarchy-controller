import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// The compose panel for iris-controller (Create), near the top of the
// screen: your last prompt on top, the draft (what the box holds) under it. The controller owns all the state and
// sends all of it on every change, so a call the shell drops for a newer one
// loses nothing. Look-only: it never takes focus, so the box you're writing
// into keeps it.
//   summon / update(json): { "state": "listening" | "thinking" | "ready" | "error",
//                            "prompt": "...", "draft": "...", "error": "...", "undo": true }
Item {
  id: root

  // Injected by omarchy-shell. Not keepLoaded: loaded at each summon.
  property var shell: null

  property bool opened: false
  property string phase: "ready"
  property string draft: ""
  property string prompt: ""
  property string error: ""
  property bool canUndo: false

  readonly property color ink: Color.popups.text
  readonly property color accent: Color.accent
  readonly property color live: "#e8616b"     // ○ red: the mic is open
  readonly property var symbolColor: ({ "△": "#3fc8a8", "○": "#e8616b", "✕": "#7b9fe8", "□": "#d58ad8" })

  readonly property var targetScreen: {
    var name = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : ""
    var screens = Quickshell.screens
    for (var i = 0; i < screens.length; i++)
      if (screens[i].name === name) return screens[i]
    return screens.length > 0 ? screens[0] : null
  }

  function apply(json) {
    try {
      var p = JSON.parse(json || "{}")
      root.phase = p.state || "ready"
      root.draft = p.draft || ""
      root.prompt = p.prompt || ""
      root.error = p.error || ""
      root.canUndo = !!p.undo
    } catch (e) {}
  }

  function open(payloadJson) {
    apply(payloadJson)
    root.opened = true
  }

  function close() { root.opened = false }

  function update(json) {
    var was = root.draft
    apply(json)
    if (root.draft !== was) landed.restart()
  }

  PanelWindow {
    id: panel
    visible: root.opened
    screen: root.targetScreen
    anchors { top: true; left: true; right: true }
    implicitHeight: card.height + 120
    color: "transparent"
    WlrLayershell.namespace: "iris-controller-compose"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    mask: Region {}

    Item {
      id: card
      width: Math.min(980, panel.width - 64)
      height: body.implicitHeight + 56
      anchors.horizontalCenter: parent.horizontalCenter
      y: 72

      readonly property int cut: 18
      readonly property color edge: root.phase === "listening" ? root.live : root.accent

      // Chamfered plate with bracket corners, like the flash and cheat sheet.
      Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
          strokeColor: Util.alpha(card.edge, 0.6); strokeWidth: 1.5
          fillColor: Color.background
          PathSvg {
            path: "M " + card.cut + " 0 L " + card.width + " 0 L " + card.width + " " + (card.height - card.cut)
                + " L " + (card.width - card.cut) + " " + card.height + " L 0 " + card.height
                + " L 0 " + card.cut + " Z"
          }
        }
        ShapePath {
          strokeColor: card.edge; strokeWidth: 4; fillColor: "transparent"
          capStyle: ShapePath.FlatCap
          PathSvg {
            path: "M " + (card.width - 44) + " 2 L " + (card.width - 2) + " 2 L " + (card.width - 2) + " 44 "
                + "M 2 " + (card.height - 44) + " L 2 " + (card.height - 2) + " L 44 " + (card.height - 2)
          }
        }
      }

      Column {
        id: body
        x: 32
        y: 28
        width: card.width - 64
        spacing: 16

        // Header: what it is, and what it's doing.
        Row {
          spacing: 12
          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "COMPOSE"
            font.family: Style.font.family
            font.bold: true
            font.pixelSize: 15
            font.letterSpacing: 3
            color: Util.alpha(root.ink, 0.55)
          }
          Rectangle {
            id: dot
            anchors.verticalCenter: parent.verticalCenter
            width: 10; height: 10; radius: 5
            color: root.phase === "listening" ? root.live
                 : root.phase === "error" ? root.live
                 : root.accent
            SequentialAnimation on opacity {
              running: root.phase === "listening" || root.phase === "thinking"
              loops: Animation.Infinite
              NumberAnimation { to: 0.25; duration: root.phase === "listening" ? 450 : 250 }
              NumberAnimation { to: 1; duration: root.phase === "listening" ? 450 : 250 }
              onStopped: dot.opacity = 1
            }
          }
          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.phase === "listening" ? "Listening…"
                : root.phase === "thinking" ? "Working it out…"
                : root.phase === "error" ? root.error
                : "Ready"
            font.family: Style.font.family
            font.pixelSize: 15
            color: root.phase === "error" ? root.live : root.ink
          }
        }

        // Your last prompt: what you asked for.
        Text {
          width: parent.width
          textFormat: Text.PlainText
          wrapMode: Text.Wrap
          maximumLineCount: 3
          elide: Text.ElideRight
          text: root.prompt ? "“" + root.prompt + "”" : "Hold Create and say what to write."
          font.family: Style.font.family
          font.pixelSize: 20
          color: root.prompt ? root.accent : Util.alpha(root.ink, 0.45)
        }

        // The draft: what the box holds now.
        Rectangle {
          width: parent.width
          height: draftText.implicitHeight + 32
          radius: 3
          color: Util.alpha(root.ink, 0.05)
          border.width: 1
          border.color: Util.alpha(root.ink, 0.12)
          Text {
            id: draftText
            x: 18; y: 16
            width: parent.width - 36
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            maximumLineCount: 12
            elide: Text.ElideRight
            text: root.draft || "The box is empty."
            font.family: Style.font.family
            font.pixelSize: 26
            color: root.draft ? root.ink : Util.alpha(root.ink, 0.4)
            SequentialAnimation {
              id: landed
              NumberAnimation { target: draftText; property: "opacity"; from: 0.2; to: 1; duration: 220; easing.type: Easing.OutCubic }
            }
          }
        }

        Rectangle { width: parent.width; height: 1; color: Util.alpha(root.ink, 0.12) }

        // What the buttons do right now.
        Row {
          spacing: 26
          Repeater {
            model: [
              { key: "Create", label: "Talk", on: root.phase !== "thinking" },
              { key: "✕", label: "Done", on: root.phase !== "listening" && root.phase !== "thinking" },
              { key: "△", label: "Undo", on: root.canUndo },
              { key: "○", label: "Put back", on: true }
            ]
            Row {
              required property var modelData
              spacing: 8
              opacity: modelData.on ? 1 : 0.35
              Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                readonly property color tint: root.symbolColor[modelData.key] || root.accent
                implicitWidth: keyText.implicitWidth + 16
                implicitHeight: 28
                radius: 3
                color: Util.alpha(tint, 0.14)
                border.width: 1.5
                border.color: tint
                Text {
                  id: keyText
                  anchors.centerIn: parent
                  text: modelData.key
                  font.family: Style.font.family
                  font.bold: true
                  font.pixelSize: root.symbolColor[modelData.key] ? 18 : 13
                  color: root.symbolColor[modelData.key] || root.ink
                }
              }
              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.label
                font.family: Style.font.family
                font.pixelSize: 15
                color: root.ink
              }
            }
          }
        }
      }
    }
  }
}
