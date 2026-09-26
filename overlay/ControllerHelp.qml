import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// DualSense cheat sheet. iris-controller summons and hides it each time the
// mic button is pressed. Every word comes from the payload (the script's
// live keymap); this file only knows where each part sits on the pad:
//   { "parts":  { "cross": { "name": "✕", "actions": ["Enter"] }, ... },
//     "combos": [ { "keys": ["L2", "R2"], "action": "Fullscreen" }, ... ],
//     "menu":   [ { "keys": ["✕"], "action": "Open" }, ... ] }
Item {
  id: root

  property bool opened: false
  property var parts: ({})
  property var combos: []
  property var menu: []

  // The sheet is laid out at this size and scaled down to fit the monitor.
  readonly property int sheetW: 1700
  readonly property int sheetH: 900
  readonly property int pad: 36

  // Controller drawing: authored in a 1000 x 640 box, placed mid-sheet.
  readonly property real padScale: 0.7
  readonly property real padX: (sheetW - 1000 * padScale) / 2
  readonly property real padY: 96

  // Label columns either side of the drawing, and the band they may use.
  readonly property int colW: 430
  readonly property int leftColRight: 450
  readonly property int rightColLeft: sheetW - 450
  readonly property int bandTop: 70
  readonly property int bandBottom: 550
  readonly property int lineH: 28
  readonly property int labelGap: 12

  readonly property color ink: Color.popups.text
  readonly property color faint: Util.alpha(Color.popups.text, 0.55)
  readonly property color face: Util.alpha(Color.popups.text, 0.07)

  // PlayStation symbol colors.
  readonly property var symbolColor: ({
    "triangle": "#3fc8a8", "circle": "#e8616b", "cross": "#7b9fe8", "square": "#d58ad8"
  })

  // Hardware layout: where the leader line touches each part (drawing units),
  // and which side of the sheet its label goes.
  readonly property var anchorsLeft: ({
    "l2": [215, 20], "l1": [205, 62], "create": [300, 112], "touchpad": [400, 150],
    "dpad": [168, 230], "lstick": [340, 362], "mic": [490, 440]
  })
  readonly property var anchorsRight: ({
    "r2": [785, 20], "r1": [795, 62], "options": [700, 112], "triangle": [800, 158],
    "circle": [884, 230], "square": [740, 238], "cross": [800, 314],
    "rstick": [660, 362], "ps": [512, 396]
  })

  function sheetPoint(a) { return [padX + a[0] * padScale, padY + a[1] * padScale] }

  // Stack one column's labels in anchor order, each as close to its anchor's
  // height as the ones above it allow, then pull the stack back inside the band.
  function layoutSide(anchorMap) {
    var items = []
    for (var id in anchorMap) {
      var part = root.parts[id]
      if (!part || !part.actions || part.actions.length === 0) continue
      var p = sheetPoint(anchorMap[id])
      items.push({ id: id, ax: p[0], ay: p[1], h: part.actions.length * lineH })
    }
    items.sort(function(a, b) { return a.ay - b.ay || a.ax - b.ax })
    var y = bandTop
    for (var i = 0; i < items.length; i++) {
      items[i].y = Math.max(items[i].ay - lineH / 2, y)
      y = items[i].y + items[i].h + labelGap
    }
    var over = y - labelGap - bandBottom
    for (var j = items.length - 1; j >= 0 && over > 0; j--) {
      var limit = j === 0 ? bandTop : items[j - 1].y + items[j - 1].h + labelGap
      var shift = Math.min(over, items[j].y - limit)
      for (var k = j; k < items.length; k++) items[k].y -= shift
      over -= shift
    }
    return items
  }

  readonly property var leftLabels: layoutSide(anchorsLeft)
  readonly property var rightLabels: layoutSide(anchorsRight)

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
      root.parts = p.parts || {}
      root.combos = p.combos || []
      root.menu = p.menu || []
    } catch (e) {}
    root.opened = true
  }

  function close() { root.opened = false }

  // --- pieces ---------------------------------------------------------------

  // A button name as it reads on the pad: colored symbol for face buttons.
  component PartName: Text {
    property string partId: ""
    textFormat: Text.PlainText
    font.family: Style.font.family
    font.bold: true
    font.pixelSize: root.symbolColor[partId] ? 24 : 19
    color: root.symbolColor[partId] || root.ink
  }

  // One callout: name and actions, aligned toward the drawing.
  component Callout: Item {
    property var entry
    property bool leftSide: false
    readonly property var part: root.parts[entry.id] || { name: "", actions: [] }
    x: leftSide ? root.leftColRight - root.colW : root.rightColLeft
    y: entry.y
    width: root.colW
    height: entry.h

    Row {
      anchors.fill: parent
      layoutDirection: leftSide ? Qt.RightToLeft : Qt.LeftToRight
      spacing: 14

      PartName {
        id: nameText
        partId: entry.id
        text: part.name
        height: root.lineH
        verticalAlignment: Text.AlignVCenter
      }

      Column {
        width: parent.width - nameText.width - parent.spacing
        Repeater {
          model: part.actions
          Text {
            required property string modelData
            width: parent.width
            textFormat: Text.PlainText
            text: modelData
            height: root.lineH
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: leftSide ? Text.AlignRight : Text.AlignLeft
            font.family: Style.font.family
            font.pixelSize: 18
            color: Util.alpha(root.ink, 0.82)
          }
        }
      }
    }
  }

  // A key chip for the combo lists.
  component Key: Rectangle {
    property string label: ""
    readonly property string symbolId: {
      for (var id in root.symbolColor) {
        var p = root.parts[id]
        if (p && p.name === label) return id
      }
      return ""
    }
    implicitWidth: keyText.implicitWidth + 20
    implicitHeight: 34
    radius: 6
    color: Util.alpha(root.ink, 0.08)
    border.width: 1
    border.color: Util.alpha(root.ink, 0.25)
    Text {
      id: keyText
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: parent.label
      font.family: Style.font.family
      font.bold: true
      font.pixelSize: parent.symbolId ? 20 : 17
      color: root.symbolColor[parent.symbolId] || root.ink
    }
  }

  component ComboList: Column {
    property string title: ""
    property var rows: []
    spacing: 10

    Text {
      textFormat: Text.PlainText
      text: parent.title
      font.family: Style.font.family
      font.bold: true
      font.pixelSize: 20
      color: Color.accent
    }

    Repeater {
      model: parent.rows
      Row {
        required property var modelData
        spacing: 10

        Repeater {
          model: modelData.keys
          Row {
            required property string modelData
            required property int index
            spacing: 10
            Text {
              visible: index > 0
              text: "+"
              anchors.verticalCenter: parent.verticalCenter
              font.family: Style.font.family
              font.pixelSize: 18
              color: root.faint
            }
            Key { label: modelData }
          }
        }

        Text {
          text: "→"
          anchors.verticalCenter: parent.verticalCenter
          font.family: Style.font.family
          font.pixelSize: 18
          color: root.faint
        }

        Text {
          textFormat: Text.PlainText
          text: modelData.action
          anchors.verticalCenter: parent.verticalCenter
          font.family: Style.font.family
          font.pixelSize: 18
          color: root.ink
        }
      }
    }
  }

  // --- window -----------------------------------------------------------------

  PanelWindow {
    id: panel
    visible: root.opened
    screen: root.targetScreen
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "iris-controller-help"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    // Look-only: an empty input region so it never eats clicks.
    mask: Region {}

    readonly property real fit: Math.min(1,
      (panel.width * 0.94) / (root.sheetW + 2 * root.pad),
      (panel.height * 0.92) / (root.sheetH + 2 * root.pad))

    // Dim the desktop a little so the see-through card stays readable.
    Rectangle {
      anchors.fill: parent
      color: Util.alpha(Color.background, 0.4)
    }

    BorderSurface {
      id: card
      anchors.centerIn: parent
      width: root.sheetW + 2 * root.pad
      height: root.sheetH + 2 * root.pad
      scale: panel.fit
      color: Util.alpha(Color.background, 0.85)
      borderSpec: Border.surfaceSpec("popups", "border", Color.popups.border, Math.max(1, Style.space(2)))
      radius: Style.cornerRadius

      Item {
        id: sheet
        x: root.pad
        y: root.pad
        width: root.sheetW
        height: root.sheetH

        // Header
        Text {
          id: title
          textFormat: Text.PlainText
          text: "DualSense"
          font.family: Style.font.family
          font.bold: true
          font.pixelSize: 30
          color: root.ink
        }
        Text {
          anchors.baseline: title.baseline
          anchors.right: parent.right
          textFormat: Text.PlainText
          text: "press Mic again to close"
          font.family: Style.font.family
          font.pixelSize: 16
          color: root.faint
        }

        // Leader lines: anchor dot, diagonal to the column, short run into the label.
        Canvas {
          id: leaders
          anchors.fill: parent
          antialiasing: true
          readonly property var labels: root.leftLabels.concat(root.rightLabels)
          onLabelsChanged: requestPaint()
          onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = Util.alpha(root.ink, 0.35)
            ctx.lineWidth = 1.5
            for (var i = 0; i < labels.length; i++) {
              var l = labels[i]
              var left = l.ax < root.sheetW / 2
              var ly = l.y + root.lineH / 2
              var edge = left ? root.leftColRight + 12 : root.rightColLeft - 12
              ctx.beginPath()
              ctx.moveTo(l.ax, l.ay)
              ctx.lineTo(edge + (left ? 30 : -30), ly)
              ctx.lineTo(edge, ly)
              ctx.stroke()
            }
          }
        }

        Repeater {
          model: root.leftLabels.concat(root.rightLabels)
          Rectangle {
            required property var modelData
            x: modelData.ax - 4
            y: modelData.ay - 4
            width: 8
            height: 8
            radius: 4
            color: Color.accent
            z: 2
          }
        }

        Repeater {
          model: root.leftLabels
          Callout { required property var modelData; entry: modelData; leftSide: true }
        }
        Repeater {
          model: root.rightLabels
          Callout { required property var modelData; entry: modelData; leftSide: false }
        }

        // The controller, drawn in its own 1000 x 640 box.
        Item {
          x: root.padX
          y: root.padY
          width: 1000
          height: 640
          scale: root.padScale
          transformOrigin: Item.TopLeft

          Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer

            // L2 / R2 triggers (behind), L1 / R1 bumpers.
            ShapePath {
              strokeColor: root.faint; strokeWidth: 3; fillColor: root.face
              PathSvg { path: "M 150 44 C 160 8, 280 6, 292 40 L 286 50 C 250 34, 180 36, 158 56 Z" }
            }
            ShapePath {
              strokeColor: root.faint; strokeWidth: 3; fillColor: root.face
              PathSvg { path: "M 850 44 C 840 8, 720 6, 708 40 L 714 50 C 750 34, 820 36, 842 56 Z" }
            }
            ShapePath {
              strokeColor: root.faint; strokeWidth: 3; fillColor: root.face
              PathSvg { path: "M 110 84 C 150 52, 270 48, 318 70 L 312 82 C 260 64, 160 70, 126 94 Z" }
            }
            ShapePath {
              strokeColor: root.faint; strokeWidth: 3; fillColor: root.face
              PathSvg { path: "M 890 84 C 850 52, 730 48, 682 70 L 688 82 C 740 64, 840 70, 874 94 Z" }
            }

            // Body.
            ShapePath {
              strokeColor: Util.alpha(root.ink, 0.7); strokeWidth: 3.5; fillColor: root.face
              PathSvg {
                path: "M 150 88 C 250 66, 320 74, 334 86 L 666 86 C 680 74, 750 66, 850 88 "
                    + "C 940 104, 975 176, 985 286 C 1000 426, 990 562, 930 612 "
                    + "C 880 652, 792 642, 752 592 C 712 542, 682 472, 600 462 L 400 462 "
                    + "C 318 472, 288 542, 248 592 C 208 642, 120 652, 70 612 "
                    + "C 10 562, 0 426, 15 286 C 25 176, 60 104, 150 88 Z"
              }
            }

            // Touchpad.
            ShapePath {
              strokeColor: Util.alpha(root.ink, 0.5); strokeWidth: 3; fillColor: Util.alpha(root.ink, 0.05)
              PathSvg { path: "M 342 92 L 658 92 L 648 256 Q 646 274 628 274 L 372 274 Q 354 274 352 256 Z" }
            }

            // Create and Options.
            ShapePath {
              strokeColor: root.faint; strokeWidth: 3; fillColor: root.face
              PathSvg { path: "M 296 98 Q 304 94 308 102 L 312 128 Q 312 136 304 136 Q 298 136 296 128 Z" }
            }
            ShapePath {
              strokeColor: root.faint; strokeWidth: 3; fillColor: root.face
              PathSvg { path: "M 704 98 Q 696 94 692 102 L 688 128 Q 688 136 696 136 Q 702 136 704 128 Z" }
            }

            // D-pad: four arrow-tipped pads.
            ShapePath {
              strokeColor: root.faint; strokeWidth: 3; fillColor: root.face
              PathSvg {
                path: "M 180 170 L 210 170 L 210 205 L 195 220 L 180 205 Z "
                    + "M 180 290 L 210 290 L 210 255 L 195 240 L 180 255 Z "
                    + "M 135 215 L 135 245 L 170 245 L 185 230 L 170 215 Z "
                    + "M 255 215 L 255 245 L 220 245 L 205 230 L 220 215 Z"
              }
            }

            // Sticks: well and cap.
            ShapePath {
              strokeColor: root.faint; strokeWidth: 3; fillColor: "transparent"
              PathSvg {
                path: "M 300 362 A 60 60 0 1 0 420 362 A 60 60 0 1 0 300 362 Z "
                    + "M 580 362 A 60 60 0 1 0 700 362 A 60 60 0 1 0 580 362 Z"
              }
            }
            ShapePath {
              strokeColor: Util.alpha(root.ink, 0.7); strokeWidth: 3; fillColor: Util.alpha(root.ink, 0.1)
              PathSvg {
                path: "M 318 362 A 42 42 0 1 0 402 362 A 42 42 0 1 0 318 362 Z "
                    + "M 598 362 A 42 42 0 1 0 682 362 A 42 42 0 1 0 598 362 Z"
              }
            }

            // PS button and mic button.
            ShapePath {
              strokeColor: Util.alpha(root.ink, 0.7); strokeWidth: 3; fillColor: root.face
              PathSvg { path: "M 482 400 A 18 18 0 1 0 518 400 A 18 18 0 1 0 482 400 Z" }
            }
            ShapePath {
              strokeColor: root.faint; strokeWidth: 3; fillColor: root.face
              PathSvg { path: "M 480 434 L 520 434 Q 526 434 526 440 Q 526 446 520 446 L 480 446 Q 474 446 474 440 Q 474 434 480 434 Z" }
            }

            // Face button rings.
            ShapePath {
              strokeColor: root.faint; strokeWidth: 3; fillColor: root.face
              PathSvg {
                path: "M 770 170 A 30 30 0 1 0 830 170 A 30 30 0 1 0 770 170 Z "
                    + "M 830 230 A 30 30 0 1 0 890 230 A 30 30 0 1 0 830 230 Z "
                    + "M 770 290 A 30 30 0 1 0 830 290 A 30 30 0 1 0 770 290 Z "
                    + "M 710 230 A 30 30 0 1 0 770 230 A 30 30 0 1 0 710 230 Z"
              }
            }

            // Face symbols, in PlayStation colors.
            ShapePath {  // triangle
              strokeColor: root.symbolColor.triangle; strokeWidth: 4; fillColor: "transparent"
              joinStyle: ShapePath.RoundJoin
              PathSvg { path: "M 800 156 L 813 180 L 787 180 Z" }
            }
            ShapePath {  // circle
              strokeColor: root.symbolColor.circle; strokeWidth: 4; fillColor: "transparent"
              PathSvg { path: "M 846 230 A 14 14 0 1 0 874 230 A 14 14 0 1 0 846 230 Z" }
            }
            ShapePath {  // cross
              strokeColor: root.symbolColor.cross; strokeWidth: 4; fillColor: "transparent"
              capStyle: ShapePath.RoundCap
              PathSvg { path: "M 789 279 L 811 301 M 811 279 L 789 301" }
            }
            ShapePath {  // square
              strokeColor: root.symbolColor.square; strokeWidth: 4; fillColor: "transparent"
              joinStyle: ShapePath.RoundJoin
              PathSvg { path: "M 729 219 L 751 219 L 751 241 L 729 241 Z" }
            }
          }
        }

        // Combos and menu keys, under the drawing.
        Rectangle {
          x: 0
          y: 590
          width: root.sheetW
          height: 1
          color: Util.alpha(root.ink, 0.15)
        }
        ComboList {
          x: 0
          y: 620
          title: "Combos"
          rows: root.combos
        }
        ComboList {
          x: root.sheetW / 2 + 60
          y: 620
          title: "In the Omarchy menu"
          rows: root.menu
        }
      }
    }
  }
}
